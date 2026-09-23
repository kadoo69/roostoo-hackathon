"""Positioning, implied-vol and flow data against the deployed book. config/positioning_edges.yaml.

The simulator steps hourly and reproduces the live cycle rather than an idealised
book: channel entries and the rank only at 4h closes, `min(want, held)` so a held
name is never topped up while booking is on, the 25% drift band on everything
except a deliberate skim, and the ladder checked at every hourly close because
the live bot checks it every cycle. A backtest that resets weights to target on
every bar is not the book the bots trade. DECISIONS.md#positioning-history.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import flow, macro, vision
from gates.compounding import block_p
from gates.competition_window import windows
from gates.concentration import context, rank_score
from signals.exit_clock import to_fast

warnings.filterwarnings("ignore")

H = pd.Timedelta(hours=1)
FEE = 0.0005
BAND = 0.25
STEP, FRAC = 0.03, 0.15
SEEDS = int(__import__('os').environ.get('POSITIONING_SEEDS', '20'))


def declaration() -> dict:
    with (ROOT / "config" / "positioning_edges.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def zscore(s: pd.Series | pd.DataFrame, window: int, min_periods: int):
    m = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - m) / sd.replace(0.0, np.nan)


def hourly_grid(frame: pd.DataFrame, grid: pd.DatetimeIndex, limit: int) -> pd.DataFrame:
    return frame.reindex(frame.index.union(grid)).ffill(limit=limit).reindex(grid)


def funding_per_8h(f: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Mean funding per 8h over a trailing clock window, so 4h-interval contracts compare with 8h ones."""
    out = {}
    for c in f.columns:
        s = f[c].dropna()
        out[c] = s.rolling(f"{hours}h").sum() / (hours / 8.0)
    return pd.DataFrame(out)


def features(names: list[str], grid: pd.DatetimeIndex, btc_1h: pd.Series) -> tuple[dict, dict, float]:
    pmap = json.loads((vision.CACHE / "perp_map.json").read_text())
    oi = hourly_grid(vision.panel("metrics", "oi_usd", names, pmap), grid, 2)
    topl = hourly_grid(vision.panel("metrics", "top_position_ls", names, pmap), grid, 2)
    glob = hourly_grid(vision.panel("metrics", "global_account_ls", names, pmap), grid, 2)
    tak = hourly_grid(vision.panel("metrics", "taker_ls", names, pmap), grid, 2)
    prem = hourly_grid(vision.panel("premium", "premium", names, pmap), grid, 2)
    fund = vision.panel("funding", "funding", names, pmap)
    f72 = hourly_grid(funding_per_8h(fund, 72), grid, 9)
    f168 = hourly_grid(funding_per_8h(fund[["BTCUSDT", "ETHUSDT"]], 168), grid, 9)

    lo = np.log(oi)
    coin = {
        "oi_chg_24h": lo.diff(24),
        "oi_chg_3d": lo.diff(72),
        "funding_3d": f72,
        "premium_24h": prem.rolling(24, min_periods=20).mean(),
        "top_vs_global_24h": np.log(topl).diff(24) - np.log(glob).diff(24),
        "taker_ls_24h": np.log(tak).rolling(24, min_periods=20).mean(),
    }
    agg_oi = oi[["BTCUSDT", "ETHUSDT"]].sum(axis=1, min_count=2)
    agg_chg = np.log(agg_oi).diff(168)
    agg_f = f168.mean(axis=1)
    crowd = zscore(agg_chg, 4320, 720) + zscore(agg_f, 4320, 720)
    dv = macro.load("dvol_btc").reindex(macro.load("dvol_btc").index.union(grid)).ffill(limit=2).reindex(grid)
    r = np.log(btc_1h.reindex(grid)).diff()
    rv = r.rolling(720, min_periods=600).std() * np.sqrt(8760) * 100
    cbp = macro.load("coinbase_premium")
    cbp = cbp.reindex(cbp.index.union(grid)).ffill(limit=2).reindex(grid)
    st = macro.load("stablecoin_supply")
    st_imp = np.log(st / st.shift(30))
    st_imp = st_imp.reindex(st_imp.index.union(grid)).ffill(limit=30).reindex(grid)
    market = {
        "agg_oi_chg_7d": agg_chg,
        "agg_funding_7d": agg_f,
        "crowding": crowd,
        "dvol_vrp": dv - rv,
        "dvol_chg_3d": dv.diff(72),
        "cb_premium_z": zscore(cbp.rolling(72, min_periods=60).mean(), 2160, 720),
        "stable_impulse_30d": st_imp,
    }
    covered = float(oi.notna().any().mean())
    return coin, market, covered


def at_close(hourly, labels: pd.DatetimeIndex, bar: pd.Timedelta):
    """Value known at each bar's CLOSE, indexed by the bar's LABEL."""
    closes = labels + bar
    out = hourly.reindex(closes)
    out.index = labels
    return out


def simulate(chosen4, close4_index, close1, gate4=None, btc_sleeve4=None,
             extra_skim1=None, rng=None, skim_hazard=None, skim_frac_extra=0.25,
             cooldown=6, booking=True, band=BAND):
    """Hourly weight state for the deployed book. Returns daily net returns and event counts."""
    cols = close1.columns
    idx1 = close1.index
    want = to_fast(chosen4.astype(float), close4_index, idx1).fillna(0.0).to_numpy() > 0.5
    g = (to_fast(gate4.to_frame("g"), close4_index, idx1)["g"].fillna(1.0).to_numpy()
         if gate4 is not None else np.ones(len(idx1)))
    sleeve = (to_fast(btc_sleeve4.to_frame("b"), close4_index, idx1)["b"].fillna(0.0).to_numpy()
              if btc_sleeve4 is not None else np.zeros(len(idx1)))
    extra = extra_skim1.reindex(index=idx1, columns=cols).fillna(False).to_numpy() \
        if extra_skim1 is not None else None
    is4 = np.asarray(((idx1 + H).hour % 4) == 0)
    ib = list(cols).index("BTCUSDT")
    px = close1.to_numpy(dtype=float)
    n = len(cols)
    w = np.zeros(n)
    ref = np.full(n, np.nan)
    last_extra = np.full(n, -10_000)
    net = np.zeros(len(px))
    skims = extras = 0
    eligible = 0
    for t in range(1, len(px)):
        prev, cur = px[t - 1], px[t]
        ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
        r = np.where(ok, np.divide(cur - prev, np.where(ok, prev, 1.0)), 0.0)
        mult = 1.0 + float(w @ r)
        if mult <= 0.0:
            break
        w = w * (1.0 + r) / mult
        tgt = w.copy()
        force = np.zeros(n, dtype=bool)
        if is4[t]:
            keep = want[t] & np.isfinite(cur)
            k = int(keep.sum())
            base = np.zeros(n)
            if k:
                base[keep] = g[t] / k
            fresh = keep & (w <= 1e-12)
            held = keep & (w > 1e-12)
            tgt = np.zeros(n)
            tgt[fresh] = base[fresh]
            tgt[held] = np.minimum(base[held], w[held]) if booking else base[held]
            btc_ref = ref[ib]
            ref[fresh] = cur[fresh]
            ref[~keep] = np.nan
            sl = sleeve[t]
            if sl > 0 and not keep[ib]:
                room = max(0.0, 1.0 - float(tgt.sum()))
                bt = min(sl, room)
                ref[ib] = cur[ib] if w[ib] <= 1e-12 else btc_ref
                tgt[ib] = min(bt, w[ib]) if w[ib] > 1e-12 else bt
            elif not keep[ib]:
                tgt[ib] = 0.0
        live = (tgt > 1e-12) & (w > 1e-12) & np.isfinite(ref) & booking
        hit = live & (cur >= ref * (1.0 + STEP))
        if hit.any():
            tgt[hit] = w[hit] * (1.0 - FRAC)
            ref[hit] = cur[hit]
            force |= hit
            skims += int(hit.sum())
        if extra is not None or skim_hazard is not None:
            above = live & ~hit & (cur > ref) & (t - last_extra >= cooldown)
            eligible += int(above.sum())
            if extra is not None:
                fire = above & extra[t]
            else:
                fire = above & (rng.random(n) < skim_hazard)
            if fire.any():
                tgt[fire] = w[fire] * (1.0 - skim_frac_extra)
                last_extra[fire] = t
                force |= fire
                extras += int(fire.sum())
        scale = np.maximum(np.abs(tgt), np.abs(w))
        inside = (~force) & (scale > 0) & (tgt > 1e-12) & (w > 1e-12) & (np.abs(tgt - w) <= band * scale)
        tgt = np.where(inside, w, tgt)
        gross = float(tgt.sum())
        if gross > 1.0:
            tgt = tgt / gross
        trade = float(np.abs(tgt - w).sum())
        net[t] = (mult - 1.0) - FEE * trade
        w = tgt
    s = pd.Series(net, index=idx1)
    daily = ((1.0 + s).resample("1D").prod() - 1.0).dropna()
    return daily, {"skims": skims, "extra_skims": extras, "extra_eligible": eligible}


def describe(d: pd.Series, lo, hi) -> dict:
    w = windows(d.loc[lo:hi])
    if w.empty:
        return {}
    return {"n_windows": int(len(w)),
            "median_pct": round(float(w["ret"].median()) * 100, 3),
            "mean_pct": round(float(w["ret"].mean()) * 100, 3),
            "p_gt5": round(float((w["ret"] > 0.05).mean()), 4),
            "p_gt10": round(float((w["ret"] > 0.10).mean()), 4),
            "p_gt20": round(float((w["ret"] > 0.20).mean()), 4),
            "worst_pct": round(float(w["ret"].min()) * 100, 2),
            "median_maxdd_pct": round(float(w["maxdd"].median()) * 100, 2),
            "median_screen3": round(float(w["screen3"].median()), 3)}


def paired(ctl: pd.Series, alt: pd.Series, lo, hi, rng) -> dict:
    a, b = windows(ctl.loc[lo:hi]), windows(alt.loc[lo:hi])
    j = a.join(b, rsuffix="_a", how="inner")
    d = (j["ret_a"] - j["ret"]).to_numpy()
    m, pm = block_p(d, np.median, rng)
    return {"median_delta_pp": round(m * 100, 3), "p_median": pm}


def xs_ic(feat: pd.DataFrame, close4: pd.DataFrame, sel: pd.DataFrame, horizon: int, windows_: dict) -> dict:
    fwd = close4.shift(-horizon) / close4 - 1.0
    f = feat.where(sel)
    rows = {}
    for tag, (lo, hi) in windows_.items():
        ics = []
        for t in f.loc[lo:hi].index[::horizon]:
            x, y = f.loc[t], fwd.loc[t]
            m = x.notna() & y.notna()
            if m.sum() >= 8:
                ics.append(x[m].rank().corr(y[m].rank()))
        ics = np.array([v for v in ics if np.isfinite(v)])
        rows[tag] = ({"ic": round(float(ics.mean()), 4),
                      "t": round(float(ics.mean() / ics.std(ddof=1) * np.sqrt(len(ics))), 2),
                      "n": int(len(ics))} if len(ics) > 10 else {"n": int(len(ics))})
    return rows


def ts_corr(x: pd.Series, y: pd.Series, step: int, windows_: dict) -> dict:
    rows = {}
    for tag, (lo, hi) in windows_.items():
        j = pd.concat([x.loc[lo:hi], y.loc[lo:hi]], axis=1).dropna().iloc[::step]
        if len(j) < 15:
            rows[tag] = {"n": int(len(j))}
            continue
        r = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
        q = pd.qcut(j.iloc[:, 0].rank(method="first"), 5, labels=False)
        spread = float(j.iloc[:, 1][q == 4].mean() - j.iloc[:, 1][q == 0].mean())
        rows[tag] = {"r": round(r, 4), "t": round(r * np.sqrt((len(j) - 2) / max(1e-12, 1 - r * r)), 2),
                     "n": int(len(j)), "q5_minus_q1_pct": round(spread * 100, 3)}
    return rows


def veto(live: pd.DataFrame, feat: pd.DataFrame, rule) -> pd.DataFrame:
    bad = rule(feat).fillna(False)
    return live & ~bad


def ranked(score: pd.DataFrame, live: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    return (score.where(live).rank(axis=1, ascending=False) <= n) & live


def shifted_gate(gate: pd.Series, rng) -> pd.Series:
    k = int(rng.integers(len(gate) // 10, len(gate) - len(gate) // 10))
    return pd.Series(np.roll(gate.to_numpy(), k), index=gate.index)


def main() -> int:
    cfg = declaration()
    win = {k: tuple(v) for k, v in cfg["meta"]["windows"].items()}
    close4, qv4, sel4, pos4 = context(30)
    start = pd.Timestamp("2021-10-01", tz="UTC")
    close4, qv4, sel4, pos4 = (x.loc[start:] for x in (close4, qv4, sel4, pos4))
    names = sorted(set(sel4.columns[sel4.any()]) | {"BTCUSDT", "ETHUSDT"})
    close4, sel4, pos4 = close4[names], sel4[names], pos4[names]
    close1 = flow.panel("1h")["close"][names].loc[start:]
    grid = close1.index + H
    coin_h, mkt_h, covered = features(names, grid, close1["BTCUSDT"].set_axis(grid))
    bar4 = pd.Timedelta(hours=4)
    coin = {k: at_close(v, close4.index, bar4) for k, v in coin_h.items()}
    mkt = {k: at_close(v, close4.index, bar4) for k, v in mkt_h.items()}

    score = rank_score("momentum", close4, qv4[names], pos4, 40)
    live = pos4.where(sel4, 0.0) > 0.5
    have = coin["oi_chg_24h"].notna()
    cov = {tag: round(float((have & live).loc[lo:hi].sum().sum() / max(1, live.loc[lo:hi].sum().sum())), 4)
           for tag, (lo, hi) in win.items()}
    out = {"declaration": "config/positioning_edges.yaml", "names": len(names),
           "names_with_any_oi_history": covered, "live_candidate_coverage_by_oi": cov}
    print("coverage of live candidates by positioning data:", cov, flush=True)

    out["xs_ic"] = {}
    for k, f in coin.items():
        out["xs_ic"][k] = {f"{h}b": xs_ic(f, close4, sel4, h, win) for h in (6, 18)}
        print("IC", k, json.dumps(out["xs_ic"][k]), flush=True)

    ew = close4.where(sel4).pct_change(fill_method=None).mean(axis=1)
    ew_lvl = (1 + ew.fillna(0)).cumprod()
    btc = close4["BTCUSDT"]
    out["ts_corr"] = {}
    for k, s in mkt.items():
        out["ts_corr"][k] = {
            "ew_3d": ts_corr(s, ew_lvl.shift(-18) / ew_lvl - 1, 18, win),
            "ew_14d": ts_corr(s, ew_lvl.shift(-84) / ew_lvl - 1, 84, win),
            "btc_3d": ts_corr(s, btc.shift(-18) / btc - 1, 18, win)}
        print("TS", k, json.dumps(out["ts_corr"][k]), flush=True)

    chosen = {"control": ranked(score, live)}
    chosen["X1_oi_confirmed_breakout"] = ranked(score, veto(live, coin["oi_chg_24h"], lambda f: f < 0))
    chosen["X2_funding_veto_asof"] = ranked(score, veto(live, coin["funding_3d"], lambda f: f > 0.0003))
    tilt = (score.where(live).rank(axis=1, pct=True)
            + coin["top_vs_global_24h"].where(live).rank(axis=1, pct=True).fillna(0.5))
    chosen["X3_smart_money_tilt"] = ranked(tilt, live)

    def rate_matched_inverse(feat, rule, remove_high):
        known = live & feat.notna()
        fired = (rule(feat) & known).fillna(False)
        frac = float(fired.sum().sum() / max(1, known.sum().sum()))
        vals = feat.where(known).stack()
        bad = feat > vals.quantile(1 - frac) if remove_high else feat < vals.quantile(frac)
        return ranked(score, live & ~bad.fillna(False)), frac

    ctl_x = {}
    ctl_x["X1_oi_confirmed_breakout"], f1 = rate_matched_inverse(
        coin["oi_chg_24h"], lambda f: f < 0, True)
    ctl_x["X2_funding_veto_asof"], f2 = rate_matched_inverse(
        coin["funding_3d"], lambda f: f > 0.0003, False)
    tvg = coin["top_vs_global_24h"].where(live).rank(axis=1, pct=True).fillna(0.5)
    tilt_inv = score.where(live).rank(axis=1, pct=True) - tvg
    ctl_x["X3_smart_money_tilt"] = ranked(tilt_inv, live)
    out["veto_fire_rate"] = {"X1": round(f1, 4), "X2": round(f2, 4)}

    idx4 = close4.index
    crowd = mkt["crowding"]
    gates = {
        "M1_crowding_gate": pd.Series(np.where(crowd > 2.0, 0.5, 1.0), index=idx4),
        "M3_vrp_gate": pd.Series(np.where(mkt["dvol_vrp"] < -15, 0.5, 1.0), index=idx4),
        "M4_cb_premium_gate": pd.Series(np.where(mkt["cb_premium_z"] < -2.0, 0.5, 1.0), index=idx4),
        "M5_stable_contraction_gate": pd.Series(np.where(mkt["stable_impulse_30d"] < 0, 0.5, 1.0), index=idx4),
    }
    wash = (crowd < -2.0).astype(float)
    trig = wash.to_numpy()
    active = np.zeros(len(trig))
    left = 0
    for i, v in enumerate(trig):
        left = 42 if v > 0 else max(0, left - 1)
        active[i] = 0.5 if left > 0 else 0.0
    sleeve = pd.Series(active, index=idx4)

    crowd_pos = ((coin["funding_3d"] > 0.0003) | (coin["oi_chg_3d"] > 0.25)).fillna(False)
    b1 = to_fast(crowd_pos.astype(float), idx4, close1.index).fillna(0.0) > 0.5
    cross = (crowd > 2.0) & ~(crowd.shift(1) > 2.0)
    fired = np.zeros(len(cross), dtype=bool)
    last = -10_000
    for i, v in enumerate(cross.to_numpy()):
        if v and i - last >= 42:
            fired[i] = True
            last = i
    b2_4 = pd.DataFrame(np.repeat(fired[:, None], len(names), axis=1), index=idx4, columns=names)
    b2 = to_fast(b2_4.astype(float), idx4, close1.index).fillna(0.0) > 0.5
    b2 = b2 & ~b2.shift(1).fillna(False)

    from gates.concentration import net_daily
    ch = chosen["control"].astype(float)
    vec = net_daily(ch.div(ch.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0), close4)
    raw, _ = simulate(chosen["control"], idx4, close1, booking=False, band=0.0)
    lo, hi = win["holdout"]
    rec = {"vectorised_4h_holdout_median_pct": describe(vec, lo, hi)["median_pct"],
           "simulator_no_ladder_no_band_holdout_median_pct": describe(raw, lo, hi)["median_pct"]}
    rec["gap_pp"] = round(abs(rec["vectorised_4h_holdout_median_pct"]
                              - rec["simulator_no_ladder_no_band_holdout_median_pct"]), 3)
    rec["passes"] = rec["gap_pp"] <= 0.3
    out["reconciliation"] = rec
    print("reconciliation", rec, flush=True)
    if not rec["passes"]:
        (RESULTS / "positioning_edges.json").write_text(json.dumps(out, indent=1, default=str))
        raise SystemExit("reconciliation_failed")

    rng = np.random.default_rng(0)
    runs, events = {}, {}
    runs["control"], events["control"] = simulate(chosen["control"], idx4, close1)
    for k in ("X1_oi_confirmed_breakout", "X2_funding_veto_asof", "X3_smart_money_tilt"):
        runs[k], events[k] = simulate(chosen[k], idx4, close1)
        runs[k + "__nonsense"], _ = simulate(ctl_x[k], idx4, close1)
    for k, gser in gates.items():
        runs[k], events[k] = simulate(chosen["control"], idx4, close1, gate4=gser)
        events[k]["gate_on_share"] = round(float((gser < 1).loc[win["pre"][0]:].mean()), 4)
    runs["M2_washout_btc"], events["M2_washout_btc"] = simulate(chosen["control"], idx4, close1,
                                                                btc_sleeve4=sleeve)
    events["M2_washout_btc"]["sleeve_on_share"] = round(float((sleeve > 0).loc[win["pre"][0]:].mean()), 4)
    runs["B1_crowded_position_booking"], events["B1_crowded_position_booking"] = simulate(
        chosen["control"], idx4, close1, extra_skim1=b1)
    runs["B2_market_crowding_booking"], events["B2_market_crowding_booking"] = simulate(
        chosen["control"], idx4, close1, extra_skim1=b2, cooldown=42)

    nonsense = {}
    for k, gser in list(gates.items()) + [("M2_washout_btc", sleeve)]:
        draws = []
        for s in range(SEEDS):
            r2 = np.random.default_rng(100 + s)
            sh = shifted_gate(gser, r2)
            d, _ = (simulate(chosen["control"], idx4, close1, btc_sleeve4=sh) if k == "M2_washout_btc"
                    else simulate(chosen["control"], idx4, close1, gate4=sh))
            draws.append(d)
        nonsense[k] = draws
        print("nonsense done", k, flush=True)
    for k in ("B1_crowded_position_booking", "B2_market_crowding_booking"):
        ev = events[k]
        hz = ev["extra_skims"] / max(1, ev["extra_eligible"])
        draws = []
        for s in range(SEEDS):
            d, _ = simulate(chosen["control"], idx4, close1, rng=np.random.default_rng(200 + s),
                            skim_hazard=hz, cooldown=42 if k.startswith("B2") else 6)
            draws.append(d)
        nonsense[k] = draws
        print("nonsense done", k, flush=True)

    out["arms"] = {}
    for k, d in runs.items():
        if k.endswith("__nonsense"):
            continue
        row = {"events": events.get(k, {})}
        for tag, (lo, hi) in win.items():
            row[tag] = describe(d, lo, hi)
            if k != "control":
                row[tag]["vs_control"] = paired(runs["control"], d, lo, hi, rng)
        if k.startswith("X"):
            nd = runs[k + "__nonsense"]
            row["nonsense_holdout"] = describe(nd, *win["holdout"])
            row["nonsense_holdout_vs_control"] = paired(runs["control"], nd, *win["holdout"], rng)
        elif k in nonsense:
            meds = [describe(nd, *win["holdout"])["median_pct"] for nd in nonsense[k]]
            p5 = [describe(nd, *win["holdout"])["p_gt5"] for nd in nonsense[k]]
            row["nonsense_holdout"] = {"median_pct_mean": round(float(np.mean(meds)), 3),
                                       "median_pct_p90": round(float(np.quantile(meds, 0.9)), 3),
                                       "p_gt5_mean": round(float(np.mean(p5)), 4), "seeds": SEEDS}
        out["arms"][k] = row

    c = out["arms"]["control"]
    verdict = {}
    for k, row in out["arms"].items():
        if k == "control":
            continue
        ok3 = all(row[t]["median_pct"] > c[t]["median_pct"] and row[t]["p_gt5"] > c[t]["p_gt5"]
                  for t in win)
        worst = row["holdout"]["worst_pct"] >= c["holdout"]["worst_pct"] - 5.0
        p_ok = row["holdout"]["vs_control"]["p_median"] < 0.10
        gain = row["holdout"]["median_pct"] - c["holdout"]["median_pct"]
        nh = row.get("nonsense_holdout", {})
        n_med = nh.get("median_pct", nh.get("median_pct_mean"))
        n_gain = (n_med - c["holdout"]["median_pct"]) if n_med is not None else None
        not_repro = n_gain is None or gain <= 0 or n_gain < 0.5 * gain
        verdict[k] = {"all_three_windows": ok3, "worst_ok": worst, "p_ok": p_ok,
                      "nonsense_not_reproducing": not_repro,
                      "candidate": bool(ok3 and worst and p_ok and not_repro)}
    out["verdict"] = verdict

    print("\narm                              " + "  ".join(f"{t:>28s}" for t in win))
    for k, row in out["arms"].items():
        cells = []
        for t in win:
            r_ = row[t]
            cells.append(f"med {r_['median_pct']:+6.2f} P5 {r_['p_gt5']:.3f} w {r_['worst_pct']:+6.1f}")
        tag = "" if k == "control" else ("  CANDIDATE" if verdict[k]["candidate"] else "")
        print(f"{k:32s} " + "  ".join(cells) + tag)
    (RESULTS / "positioning_edges.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
