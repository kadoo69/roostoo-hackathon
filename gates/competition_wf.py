"""Competition-shaped, out-of-sample and walk-forward evaluation. config/competition_wf.yaml.

Every arm is one declared rule, scored on every 14-day window in three periods,
on an hourly simulator that reproduces the live cycle: selection at 4h closes,
the 3% x 15% ladder, the 25% drift band, a held long never topped up, fee plus
each coin's own tick per side, 10 bps plus tick per side on shorts. The
simulator must reproduce gates.positioning_edges.simulate on the control before
any arm is read. DECISIONS.md#competition-wf-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import flow, universe as ru
from gates import positioning_edges as pe
from gates.concentration import context
from signals import donchian
from signals.exit_clock import to_fast

H = pd.Timedelta(hours=1)
FEE, SHORT_FEE, STEP, FRAC, BAND = 0.0005, 0.0010, 0.03, 0.15, 0.25
PERIODS = {"2022": ("2022-01-15", "2023-01-01"), "2023-24": ("2023-01-01", "2025-01-01"),
           "2025-26": ("2025-01-01", "2026-09-19")}
THRESH = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20)
SEEDS = int(os.environ.get("WF_SEEDS", "20"))


def declaration() -> dict:
    with (ROOT / "config" / "competition_wf.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def load():
    close4, qv4, sel4, pos4 = context(30)
    start = pd.Timestamp("2021-10-01", tz="UTC")
    close4, sel4 = close4.loc[start:], sel4.loc[start:]
    names = sorted(set(sel4.columns[sel4.any()]) | {"BTCUSDT", "ETHUSDT"})
    close4, sel4 = close4[names], sel4[names]
    close1 = flow.panel("1h")["close"][names].loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in names if s in specs}).reindex(names).fillna(0.0)
    return close4, sel4, close1, tick


def book_hourly(close1, idx4, long4=None, short4=None, long1=None, trigger1=None, mom1=None,
                n=3, divisor=None, ladder=True, band=BAND, tick=None, return_gross=False):
    """Hourly weight state. `long4`/`short4` are 4h boolean frames of SELECTED names (applied at 4h
    closes); `long1` (hourly live set) plus `trigger1` (hours allowed to add entries) and `mom1` (hourly
    rank score) switch on intrabar entries into free slots between 4h closes."""
    cols, idx1 = close1.columns, close1.index
    px = close1.to_numpy(dtype=float)
    nn = len(cols)
    is4 = np.asarray(((idx1 + H).hour % 4) == 0)
    L = (to_fast(long4.astype(float), idx4, idx1).fillna(0.0).to_numpy() > 0.5) if long4 is not None else np.zeros(px.shape, bool)
    S = (to_fast(short4.astype(float), idx4, idx1).fillna(0.0).to_numpy() > 0.5) if short4 is not None else np.zeros(px.shape, bool)
    LH = long1.reindex(index=idx1, columns=cols).fillna(False).to_numpy() if long1 is not None else None
    TR = trigger1.reindex(idx1).fillna(False).to_numpy() if trigger1 is not None else None
    MO = mom1.reindex(index=idx1, columns=cols).to_numpy() if mom1 is not None else None
    tk = (tick.reindex(cols).fillna(0.0).to_numpy() if tick is not None else np.zeros(nn))
    w = np.zeros(nn)
    ref = np.full(nn, np.nan)
    net = np.zeros(len(px))
    gross_path = np.zeros(len(px))
    for t in range(1, len(px)):
        prev, cur = px[t - 1], px[t]
        ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
        r = np.where(ok, np.divide(cur - prev, np.where(ok, prev, 1.0)), 0.0)
        mult = 1.0 + float(w @ r)
        if mult <= 0.0:
            break
        w = w * (1.0 + r) / mult
        tgt = w.copy()
        force = np.zeros(nn, dtype=bool)
        fin = np.isfinite(cur)
        if is4[t]:
            lk, sk = L[t] & fin, S[t] & fin & ~L[t]
            k = int(lk.sum()) + int(sk.sum())
            per = (1.0 / k if k else 0.0) if divisor is None else 1.0 / divisor
            tgt = np.zeros(nn)
            fresh_l, held_l = lk & (w <= 1e-12), lk & (w > 1e-12)
            tgt[fresh_l] = per
            tgt[held_l] = np.minimum(per, w[held_l]) if ladder else per
            fresh_s, held_s = sk & (w >= -1e-12), sk & (w < -1e-12)
            tgt[fresh_s] = -per
            tgt[held_s] = np.maximum(-per, w[held_s])
            ref[fresh_l] = cur[fresh_l]
            ref[~lk] = np.nan
        elif LH is not None and TR[t]:
            held = w > 1e-12
            free = n - int(held.sum()) - int((w < -1e-12).sum())
            cand = LH[t] & fin & ~held
            if free > 0 and cand.any():
                sc = np.where(cand, np.nan_to_num(MO[t], nan=-9.0), -np.inf)
                pick = np.argsort(-sc)[:free]
                pick = pick[cand[pick]]
                if len(pick):
                    kk = int(held.sum()) + len(pick)
                    per = 1.0 / kk
                    tgt = np.where(held, np.minimum(per, w), tgt)
                    tgt[pick] = per
                    ref[pick] = cur[pick]
                    force[pick] = True
        live = (tgt > 1e-12) & (w > 1e-12) & np.isfinite(ref) & ladder
        hit = live & (cur >= ref * (1.0 + STEP))
        if hit.any():
            tgt[hit] = w[hit] * (1.0 - FRAC)
            ref[hit] = cur[hit]
            force |= hit
        scale = np.maximum(np.abs(tgt), np.abs(w))
        inside = (~force) & (scale > 0) & (np.abs(tgt) > 1e-12) & (np.abs(w) > 1e-12) & \
                 (np.sign(tgt) == np.sign(w)) & (np.abs(tgt - w) <= band * scale)
        tgt = np.where(inside, w, tgt)
        g = float(np.abs(tgt).sum())
        if g > 1.0:
            tgt = tgt / g
        dw = np.abs(tgt - w)
        tb = np.where(np.isfinite(cur) & (cur > 0), tk / np.where(cur > 0, cur, 1.0), 0.0)
        short_leg = (tgt < -1e-12) | (w < -1e-12)
        cost = float((dw * (np.where(short_leg, SHORT_FEE, FEE) + tb)).sum())
        net[t] = (mult - 1.0) - cost
        w = tgt
        gross_path[t] = float(np.abs(w).sum())
    if return_gross:
        return pd.Series(net, index=idx1), pd.Series(gross_path, index=idx1)
    return pd.Series(net, index=idx1)


def ranked(score, live, n=3):
    return (score.where(live).rank(axis=1, ascending=False) <= n) & live


def windows_hourly(net1: pd.Series, gross1: pd.Series | None = None, lock: float | None = None,
                   entry_cost: float = 0.0) -> pd.DataFrame:
    """Every 14-day window starting at 00:00 UTC, from hourly net returns, as the competition scores it."""
    starts = net1.index[(net1.index.hour == 0)]
    vals = net1.to_numpy()
    pos = {t: i for i, t in enumerate(net1.index)}
    rows = []
    for s in starts:
        i = pos[s]
        seg = vals[i:i + 14 * 24]
        if len(seg) < 14 * 24:
            break
        seg = seg.copy()
        seg[0] -= entry_cost
        if lock is not None:
            eq = np.cumprod(1.0 + seg)
            hit = np.argmax(eq >= 1.0 + lock) if (eq >= 1.0 + lock).any() else None
            if hit is not None and hit + 1 < len(seg):
                seg[hit + 1:] *= 0.3
                seg[hit + 1] -= 0.7 * (FEE + 0.0004)
        eq = np.cumprod(1.0 + seg)
        daily = eq[23::24] / np.r_[1.0, eq[23::24][:-1]] - 1.0
        rows.append((s, eq[-1] - 1.0, float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1.0).min()), daily))
    w = pd.DataFrame([(s, r, dd) for s, r, dd, _ in rows], columns=["start", "ret", "maxdd"]).set_index("start")
    from gates.competition_window import window_stats
    ws = window_stats(np.stack([d for *_, d in rows]), [s for s, *_ in rows])
    w["screen3"] = ws["screen3"].to_numpy()
    return w


def describe(w: pd.DataFrame) -> dict:
    if w.empty:
        return {}
    out = {"n": int(len(w)), "median_pct": round(float(w.ret.median()) * 100, 2),
           "worst_pct": round(float(w.ret.min()) * 100, 1),
           "median_screen3": round(float(w.screen3.median()), 2)}
    for th in THRESH:
        out[f"p_gt{int(th * 100)}"] = round(float((w.ret > th).mean()), 3)
    return out


def by_period(w: pd.DataFrame) -> dict:
    return {k: describe(w.loc[a:b]) for k, (a, b) in PERIODS.items()}


def main() -> int:
    declaration()
    close4, sel4, close1, tick = load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = ranked(mom4, live4)
    out = {"declaration": "config/competition_wf.yaml", "arms": {}}

    ref = pe.simulate(c0, idx4, close1)[0]
    mine = book_hourly(close1, idx4, long4=c0)
    mine_d = ((1 + mine).resample("1D").prod() - 1).dropna()
    gap = abs(pe.describe(ref, *PERIODS["2025-26"])["median_pct"] - pe.describe(mine_d, *PERIODS["2025-26"])["median_pct"])
    out["reconciliation_fee_only_vs_positioning_sim_pp"] = round(gap, 4)
    print("reconciliation (fee only) gap pp:", round(gap, 4), flush=True)
    if gap > 0.02:
        (RESULTS / "competition_wf.json").write_text(json.dumps(out, indent=1, default=str))
        raise SystemExit("reconciliation_failed")

    nets = {}
    nets["C0"] = book_hourly(close1, idx4, long4=c0, tick=tick)
    nets["C1"] = book_hourly(close1, idx4, long4=live4, divisor=20, tick=tick)

    btc = close4["BTCUSDT"]
    bear = btc < btc.rolling(180).mean()
    lower = close4.rolling(20).min().shift(1)
    upper10 = close4.rolling(10).max().shift(1)
    state = np.zeros(len(close4.columns), bool)
    C, LO, UP = close4.to_numpy(), lower.to_numpy(), upper10.to_numpy()
    arr = np.zeros(C.shape, bool)
    for i in range(len(C)):
        valid = np.isfinite(C[i]) & np.isfinite(LO[i]) & np.isfinite(UP[i])
        state = np.where(state & valid & (C[i] > UP[i]), False, state)
        state = state | (valid & (C[i] < LO[i]))
        state &= np.isfinite(C[i])
        arr[i] = state
    brk = pd.DataFrame(arr, index=idx4, columns=close4.columns) & sel4

    def short_sleeve(regime):
        longs = c0
        free = 3 - longs.sum(axis=1)
        rg = regime.reindex(idx4).fillna(False).to_numpy()
        rgf = pd.DataFrame(np.repeat(rg[:, None], len(close4.columns), axis=1), index=idx4, columns=close4.columns)
        sc = (-mom4).where(brk & rgf & ~live4)
        rk = sc.rank(axis=1, ascending=False)
        shorts = rk.le(free, axis=0) & sc.notna()
        return shorts

    s1 = short_sleeve(bear)
    nets["S1"] = book_hourly(close1, idx4, long4=c0, short4=s1, tick=tick)
    out["S1_bear_share"] = round(float(bear.loc["2022":].mean()), 3)
    out["S1_short_bar_share"] = round(float(s1.any(axis=1).loc["2022":].mean()), 3)

    idx1 = close1.index
    up4 = close4.rolling(20).max().shift(1)
    up_h = to_fast(up4.shift(-1), idx4, idx1)
    sel_h = to_fast(sel4.astype(float).shift(-1), idx4, idx1).fillna(0.0) > 0.5
    c4_h = to_fast(close4.shift(40 - 1), idx4, idx1)
    is4 = pd.Series(((idx1 + H).hour % 4) == 0, index=idx1)

    def hourly_live(trig_mask):
        P, U = close1.to_numpy(), up_h.to_numpy()
        st = np.zeros(P.shape[1], bool)
        out_ = np.zeros(P.shape, bool)
        pos4_fast = to_fast(donchian.position(close4, 20, "lowchannel", 10), idx4, idx1).fillna(0.0).to_numpy() > 0.5
        m4 = is4.to_numpy()
        for t in range(len(P)):
            if m4[t]:
                st = pos4_fast[t].copy()
            elif trig_mask[t]:
                v = np.isfinite(P[t]) & np.isfinite(U[t])
                st = st | (v & (P[t] > U[t]))
            out_[t] = st
        return pd.DataFrame(out_, index=idx1, columns=close1.columns) & sel_h

    trig = np.ones(len(idx1), bool)
    lh = hourly_live(trig)
    mom_h = close1 / c4_h - 1.0
    nets["S2"] = book_hourly(close1, idx4, long4=c0, long1=lh, trigger1=pd.Series(trig, index=idx1), mom1=mom_h, tick=tick)
    leak = book_hourly(close1, idx4, long4=c0, long1=hourly_live(np.zeros(len(idx1), bool)),
                       trigger1=pd.Series(False, index=idx1), mom1=mom_h, tick=tick)
    out["S2_leak_check_max_abs_diff"] = float((leak - nets["C0"]).abs().max())
    print("S2 leak check (must be 0):", out["S2_leak_check_max_abs_diff"], flush=True)

    ens = sum((donchian.position(close4, e, "lowchannel", x) > 0.5).astype(int)
              for e, x in ((10, 5), (20, 10), (40, 20), (80, 40)))
    nets["S3"] = book_hourly(close1, idx4, long4=ranked(mom4, (ens >= 3) & sel4), tick=tick)
    nets["S5"] = 0.5 * nets["C0"] + 0.5 * nets["C1"]

    ec = FEE + float((tick / close1.median()).median())
    W = {k: windows_hourly(v, entry_cost=ec) for k, v in nets.items()}
    W["S4"] = windows_hourly(nets["C0"], lock=0.05, entry_cost=ec)

    rng = np.random.default_rng(7)
    nons = []
    blocks = bear.groupby((bear != bear.shift()).cumsum())
    runs = [g for _, g in blocks]
    for s in range(SEEDS):
        order = rng.permutation(len(runs))
        vals = np.concatenate([runs[i].to_numpy() for i in order])
        fake = pd.Series(vals[:len(bear)], index=bear.index)
        n1 = book_hourly(close1, idx4, long4=c0, short4=short_sleeve(fake), tick=tick)
        nons.append(windows_hourly(n1, entry_cost=ec))
        print("S1 nonsense seed", s, flush=True)

    starts = W["C0"].index
    months = pd.date_range(pd.Timestamp(starts[0].year, starts[0].month, 1, tz="UTC"), starts[-1], freq="MS")
    arms = ["C0", "C1", "S1", "S2", "S3", "S4", "S5"]
    pick = {}
    for m in months:
        lo = m - pd.Timedelta(days=180 + 14)
        scores = {}
        for a in arms:
            w = W[a]
            done = w.loc[lo: m - pd.Timedelta(days=14)]
            scores[a] = float((done.ret > 0.02).mean()) if len(done) >= 60 else -1.0
        best = max(arms, key=lambda a: (scores[a], a == "C0"))
        pick[m] = best
    sel_rows = []
    for s in starts:
        a = pick.get(pd.Timestamp(s.year, s.month, 1, tz="UTC"), "C0")
        sel_rows.append((s, a))
    wf = pd.concat([W[a].loc[[s]] for s, a in sel_rows])
    W["WF"] = wf
    out["WF_picks"] = pd.Series(pick).value_counts().to_dict()

    for k, w in W.items():
        out["arms"][k] = by_period(w)
    out["S1_nonsense"] = {p: {"median_pct_mean": round(float(np.mean([describe(n.loc[a:b])["median_pct"] for n in nons])), 2),
                              "p_gt2_mean": round(float(np.mean([describe(n.loc[a:b])["p_gt2"] for n in nons])), 3)}
                          for p, (a, b) in PERIODS.items()}
    ctl = out["arms"]["C0"]
    verdict = {}
    for k in ("S1", "S2", "S3", "S4", "S5", "WF"):
        a = out["arms"][k]
        ok3 = all(a[p]["p_gt2"] > ctl[p]["p_gt2"] and a[p]["median_pct"] > ctl[p]["median_pct"] for p in PERIODS)
        worst = all(a[p]["worst_pct"] >= ctl[p]["worst_pct"] - 5 for p in PERIODS)
        nons_ok = True
        if k == "S1":
            gain = a["2025-26"]["p_gt2"] - ctl["2025-26"]["p_gt2"]
            ng = out["S1_nonsense"]["2025-26"]["p_gt2_mean"] - ctl["2025-26"]["p_gt2"]
            nons_ok = gain > 0 and ng < 0.5 * gain
        verdict[k] = {"all_three_periods": ok3, "worst_ok": worst, "nonsense_ok": nons_ok,
                      "candidate": bool(ok3 and worst and nons_ok)}
    out["verdict"] = verdict
    hdr = "arm  " + "".join(f"| {p:^58s}" for p in PERIODS)
    print("\n" + hdr)
    for k in ["C0", "C1", "S1", "S2", "S3", "S4", "S5", "WF"]:
        a = out["arms"][k]
        cells = "".join(f"| med {a[p]['median_pct']:+6.2f} P>0 {a[p]['p_gt0']:.2f} P>2 {a[p]['p_gt2']:.2f} P>15 {a[p]['p_gt15']:.2f} w {a[p]['worst_pct']:+6.1f} " for p in PERIODS)
        tag = "" if k.startswith("C") else ("  CANDIDATE" if verdict[k]["candidate"] else "")
        print(f"{k:4s} {cells}{tag}")
    print("S1 nonsense:", out["S1_nonsense"])
    print("WF picks:", out["WF_picks"])
    (RESULTS / "competition_wf.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
