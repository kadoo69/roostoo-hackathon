"""Intraday structure against the deployed book. config/intraday_structure.yaml.

S1 intraday time-series momentum (idle-cash BTC sleeve), S2 cointegrated pairs on
hourly bars (standalone market-neutral sleeve), S3 a quiet-market gate on C0, and
the D1 alt hour-of-day diagnostic. Each arm carries its declared nonsense control.
DECISIONS.md#intraday-structure-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from gates import literature_edges as le
from gates.concentration import context
from signals import donchian
from signals.exit_clock import to_fast

SEEDS = int(os.environ.get("IS_SEEDS", "20"))
PERIODS = dict(cw.PERIODS)
LONG_FEE, SHORT_FEE = 0.0005, 0.0010
FIT, ENTRY_Z, EXIT_Z, STOP_Z, MAX_HOLD, DF_CRIT, PAIR_NAMES = 720, 2.5, 0.5, 5.0, 72, -3.37, 12


def declaration() -> dict:
    with (ROOT / "config" / "intraday_structure.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def period_of(t: pd.Timestamp) -> str | None:
    for k, (a, b) in PERIODS.items():
        if pd.Timestamp(a, tz="UTC") <= t < pd.Timestamp(b, tz="UTC"):
            return k
    return None


def tsmom_hold(r1: pd.Series, predictor_hour: int) -> pd.Series:
    """Hold the 23:00 bar of each UTC day whose `predictor_hour` bar closed up."""
    idx = r1.index
    day = idx.floor("1D")
    pred = r1[idx.hour == predictor_hour]
    up = pd.Series((pred > 0).to_numpy(), index=pred.index.floor("1D"))
    up = up[~up.index.duplicated()]
    sig = pd.Series(day.map(up).fillna(False).astype(bool).to_numpy(), index=idx)
    return sig & (idx.hour == 23)


def dickey_fuller_t(e: np.ndarray) -> float:
    de, lag = np.diff(e), e[:-1]
    lag = lag - lag.mean()
    b = float(lag @ (de - de.mean()) / (lag @ lag))
    resid = de - de.mean() - b * lag
    se = float(np.sqrt((resid @ resid) / (len(de) - 2) / (lag @ lag)))
    return b / se if se > 0 else 0.0


def pair_trades(la: np.ndarray, lb: np.ndarray, pa: np.ndarray, pb: np.ndarray,
                idx: pd.DatetimeIndex, eligible_days: dict, day_start: dict,
                cost_a: float, cost_b: float) -> list[dict]:
    """One pair's trades. `la`/`lb` are log prices for fitting, `pa`/`pb` the traded prices.
    Parameters refit at each eligible UTC day start on the trailing FIT bars only."""
    trades, open_t, params = [], None, None
    days = sorted(day_start)
    for d in days:
        i0 = day_start[d]
        if i0 >= FIT and eligible_days.get(d, False):
            ya, xb = la[i0 - FIT:i0], lb[i0 - FIT:i0]
            ok = np.isfinite(ya) & np.isfinite(xb)
            if ok.sum() >= FIT * 0.95:
                ya, xb = ya[ok], xb[ok]
                xm, ym = xb.mean(), ya.mean()
                beta = float(((xb - xm) @ (ya - ym)) / ((xb - xm) @ (xb - xm)))
                if beta > 0:
                    e = ya - beta * xb
                    if dickey_fuller_t(e) < DF_CRIT:
                        params = (beta, float(e.mean()), float(e.std(ddof=1)))
                    elif open_t is None:
                        params = None
                elif open_t is None:
                    params = None
        elif open_t is None:
            params = None
        if params is None and open_t is None:
            continue
        i1 = day_start.get(d + pd.Timedelta(days=1), len(idx))
        for i in range(i0, i1):
            if params is None or not (np.isfinite(la[i]) and np.isfinite(lb[i])):
                continue
            beta, mu, sd = params
            z = (la[i] - beta * lb[i] - mu) / sd
            if open_t is None:
                if abs(z) > ENTRY_Z and abs(z) < STOP_Z:
                    open_t = (i, -np.sign(z), beta)
                continue
            j, side, b0 = open_t
            if abs(z) < EXIT_Z or abs(z) > STOP_Z or i - j >= MAX_HOLD:
                wa, wb = 1.0 / (1.0 + b0), b0 / (1.0 + b0)
                ra, rb = pa[i] / pa[j] - 1.0, pb[i] / pb[j] - 1.0
                gross = side * (wa * ra - wb * rb)
                if side > 0:
                    cost = 2 * wa * (LONG_FEE + cost_a) + 2 * wb * (SHORT_FEE + cost_b)
                else:
                    cost = 2 * wa * (SHORT_FEE + cost_a) + 2 * wb * (LONG_FEE + cost_b)
                trades.append({"t": idx[j], "hours": i - j, "gross": gross, "net": gross - cost,
                               "exit": "revert" if abs(z) < EXIT_Z else ("stop" if abs(z) > STOP_Z else "time")})
                open_t = None
    return trades


def pairs_run(close1: pd.DataFrame, top12: pd.DataFrame, tick_bps: pd.Series, shift_b: int = 0) -> pd.DataFrame:
    idx = close1.index
    day_start = {}
    for i, t in enumerate(idx):
        if t.hour == 0:
            day_start.setdefault(t, i)
    names = [c for c in top12.columns if top12[c].any()]
    rows = []
    for ia, a in enumerate(names):
        for b in names[ia + 1:]:
            both = (top12[a] & top12[b])
            if not both.any():
                continue
            elig = {d: bool(v) for d, v in both.items()}
            pa = close1[a].to_numpy(dtype=float)
            pb_s = close1[b].shift(shift_b) if shift_b else close1[b]
            pb = pb_s.to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                la, lb = np.log(pa), np.log(pb)
            for tr in pair_trades(la, lb, pa, pb, idx, elig, day_start,
                                  float(tick_bps.get(a, 0.0)), float(tick_bps.get(b, 0.0))):
                tr["pair"] = f"{a}/{b}"
                rows.append(tr)
    return pd.DataFrame(rows)


def trade_stats(tr: pd.DataFrame) -> dict:
    out = {}
    if tr.empty:
        return {k: {"trades": 0} for k in PERIODS}
    tr = tr.assign(period=tr["t"].map(period_of))
    for k in PERIODS:
        s = tr[tr["period"] == k]
        if len(s) < 10:
            out[k] = {"trades": int(len(s))}
            continue
        out[k] = {"trades": int(len(s)), "pairs": int(s["pair"].nunique()),
                  "mean_gross_bps": round(float(s["gross"].mean()) * 1e4, 2),
                  "mean_net_bps": round(float(s["net"].mean()) * 1e4, 2),
                  "t_net": round(float(s["net"].mean() / s["net"].std(ddof=1) * np.sqrt(len(s))), 2),
                  "hit_net": round(float((s["net"] > 0).mean()), 3),
                  "median_hours": float(s["hours"].median()),
                  "exits": s["exit"].value_counts().to_dict()}
    return out


def random_gate(index: pd.DatetimeIndex, frac: float, mean_len: float, rng) -> pd.Series:
    p_off = 1.0 / max(mean_len, 1.0)
    p_on = min(1.0, frac * p_off / max(1e-9, 1.0 - frac))
    state, out = rng.random() < frac, np.zeros(len(index), dtype=bool)
    u = rng.random(len(index))
    for i in range(len(index)):
        state = (u[i] >= p_off) if state else (u[i] < p_on)
        out[i] = state
    return pd.Series(out, index=index)


def episode_mean_len(g: pd.Series) -> float:
    runs = (g != g.shift()).cumsum()[g]
    return float(runs.value_counts().mean()) if len(runs) else 0.0


def main() -> int:
    declaration()
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0_sel = cw.ranked(mom4, live4)
    c0, g0 = cw.book_hourly(close1, idx4, long4=c0_sel, tick=tick, return_gross=True)
    ec = cw.FEE + float((tick / close1.median()).median())
    out = {"declaration": "config/intraday_structure.yaml", "arms": {}, "sleeves": {}, "nonsense": {},
           "diagnostic": {}, "mean_idle_fraction": round(float((1 - g0).loc["2022":].mean()), 3)}
    out["arms"]["C0"] = le.score(c0, ec, PERIODS)
    print("C0", json.dumps(out["arms"]["C0"]), flush=True)

    btc1 = close1["BTCUSDT"]
    r_btc = btc1.pct_change(fill_method=None)
    btc_cost = cw.FEE + float(tick["BTCUSDT"] / btc1.median())
    s1_hold = tsmom_hold(r_btc, 0)
    s1 = le.btc_sleeve(btc1, s1_hold, btc_cost)
    out["sleeves"]["S1"] = le.sleeve_stats(s1, s1_hold, PERIODS)
    alt_h = {h: le.sleeve_stats(le.btc_sleeve(btc1, tsmom_hold(r_btc, h), btc_cost), tsmom_hold(r_btc, h), PERIODS)
             for h in range(0, 23)}
    out["nonsense"]["S1_rank_of_hour0_among_23"] = {
        p: int(sorted([alt_h[h][p]["mean_net_bps"] for h in alt_h], reverse=True).index(alt_h[0][p]["mean_net_bps"]) + 1)
        for p in PERIODS}
    gross_s1 = {}
    for p, (a, b) in PERIODS.items():
        m = s1_hold.loc[a:b]
        gross_s1[p] = round(float(r_btc.loc[a:b][m].mean()) * 1e4, 2)
    out["sleeves"]["S1_gross_bps_per_hold"] = gross_s1
    print("S1", json.dumps(out["sleeves"]["S1"]), gross_s1, out["nonsense"]["S1_rank_of_hour0_among_23"], flush=True)
    if all(out["sleeves"]["S1"][p].get("mean_net_bps", -1) > 0 for p in PERIODS):
        out["arms"]["S1"] = le.score(le.combine(c0, g0, s1), ec, PERIODS)

    _, qv4, _, _ = context(30)
    qv4 = qv4.reindex(index=idx4, columns=close4.columns)
    liq = qv4.rolling(180, min_periods=120).mean().shift(1)
    rank_liq = liq.where(sel4).rank(axis=1, ascending=False)
    top12_4 = (rank_liq <= PAIR_NAMES) & sel4
    top12_1 = to_fast(top12_4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    top12_d = top12_1[idx1.hour == 0]
    top12_d = top12_d[~top12_d.index.duplicated()]
    tick_bps = (tick / close1.median()).fillna(0.0)
    tr = pairs_run(close1, top12_d, tick_bps)
    out["sleeves"]["S2"] = trade_stats(tr)
    print("S2", json.dumps(out["sleeves"]["S2"], default=str), flush=True)
    tr_ctl = pairs_run(close1, top12_d, tick_bps, shift_b=FIT)
    out["nonsense"]["S2_shifted_partner"] = trade_stats(tr_ctl)
    print("S2 control", json.dumps(out["nonsense"]["S2_shifted_partner"], default=str), flush=True)
    if not tr.empty:
        tr.to_csv(RESULTS / "intraday_structure_pairs.csv", index=False)

    r24 = (close4 / close4.shift(6) - 1.0).where(sel4)
    disp = r24.std(axis=1)
    vol1 = r_btc.rolling(168, min_periods=150).std()
    vol4 = pd.Series(vol1.reindex(idx4 + pd.Timedelta(hours=3)).to_numpy(), index=idx4)
    q_d = disp.rolling(540, min_periods=360).quantile(0.33)
    q_v = vol4.rolling(540, min_periods=360).quantile(0.33)
    flat = (disp < q_d) & (vol4 < q_v)
    s3_sel = c0_sel & ~flat.to_numpy()[:, None]
    s3 = cw.book_hourly(close1, idx4, long4=s3_sel, tick=tick)
    out["arms"]["S3"] = le.score(s3, ec, PERIODS)
    frac = float(flat.loc["2022":].mean())
    mlen = episode_mean_len(flat.loc["2022":])
    out["diagnostic"]["S3_gate"] = {"flat_fraction": round(frac, 3), "mean_episode_4h_bars": round(mlen, 2),
                                   "flat_fraction_by_period": {p: round(float(flat.loc[a:b].mean()), 3) for p, (a, b) in PERIODS.items()}}
    print("S3", json.dumps(out["arms"]["S3"]), out["diagnostic"]["S3_gate"], flush=True)
    rng = np.random.default_rng(23)
    ctl = []
    for _ in range(SEEDS):
        g = random_gate(idx4, frac, mlen, rng)
        ctl.append(le.score(cw.book_hourly(close1, idx4, long4=c0_sel & ~g.to_numpy()[:, None], tick=tick), ec, PERIODS))
    out["nonsense"]["S3_random_gate"] = {p: {"p_gt2_mean": round(float(np.mean([c[p]["p_gt2"] for c in ctl])), 3),
                                             "median_mean": round(float(np.mean([c[p]["median_pct"] for c in ctl])), 2)}
                                         for p in PERIODS}
    print("S3 control", json.dumps(out["nonsense"]["S3_random_gate"]), flush=True)

    sel1 = to_fast(sel4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    ret1 = close1.pct_change(fill_method=None).where(sel1)
    ew = ret1.mean(axis=1)
    ex = ew - r_btc
    d1 = {}
    for name, s in (("pool", ew), ("pool_minus_btc", ex), ("btc", r_btc)):
        d1[name] = {}
        for p, (a, b) in PERIODS.items():
            x = s.loc[a:b].dropna()
            g = x.groupby(x.index.hour)
            d1[name][p] = {int(h): {"bps": round(float(v.mean()) * 1e4, 2),
                                    "t": round(float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))), 2)} for h, v in g}
    stable = []
    for name in ("pool", "pool_minus_btc"):
        for h in range(24):
            v = [d1[name][p][h]["bps"] for p in PERIODS]
            if (all(x > 10 for x in v) or all(x < -10 for x in v)):
                stable.append({"series": name, "hour": h, "bps": v})
    out["diagnostic"]["D1_hour_of_day"] = d1
    out["diagnostic"]["D1_stable_above_10bps"] = stable
    same_sign = {name: [h for h in range(24) if len({np.sign(d1[name][p][h]["bps"]) for p in PERIODS}) == 1]
                 for name in ("pool", "pool_minus_btc")}
    out["diagnostic"]["D1_same_sign_all_periods"] = same_sign
    print("D1 stable>10bps", stable, "same-sign hours", same_sign, flush=True)

    ctl0 = out["arms"]["C0"]
    verdict = {}
    for k in ("S1", "S3"):
        a = out["arms"].get(k)
        if a is None:
            verdict[k] = {"candidate": False, "reason": "sleeve net not positive in every period"}
            continue
        ok = all(a[p]["p_gt2"] > ctl0[p]["p_gt2"] and a[p]["median_pct"] > ctl0[p]["median_pct"] for p in PERIODS)
        worst = all(a[p]["worst_pct"] >= ctl0[p]["worst_pct"] - 5 for p in PERIODS)
        verdict[k] = {"all_periods": ok, "worst_ok": worst}
    if "all_periods" in verdict["S1"]:
        verdict["S1"]["nonsense_ok"] = all(v <= 5 for v in out["nonsense"]["S1_rank_of_hour0_among_23"].values())
    if "all_periods" in verdict["S3"]:
        gain = out["arms"]["S3"]["2025-26"]["p_gt2"] - ctl0["2025-26"]["p_gt2"]
        ng = out["nonsense"]["S3_random_gate"]["2025-26"]["p_gt2_mean"] - ctl0["2025-26"]["p_gt2"]
        verdict["S3"]["nonsense_ok"] = bool(gain > 0 and ng < 0.5 * gain)
    s2, s2c = out["sleeves"]["S2"], out["nonsense"]["S2_shifted_partner"]
    s2_net = all(s2[p].get("mean_net_bps", -1) > 0 for p in PERIODS)
    s2_ctl = all(s2[p].get("mean_gross_bps", 0) > 2 * max(s2c[p].get("mean_gross_bps", 0), 0) for p in PERIODS)
    verdict["S2"] = {"net_positive_all_periods": s2_net, "beats_control_2x_gross": s2_ctl,
                     "candidate": False, "reason": "sleeve gate" if not s2_net else "needs combined book run"}
    for k, v in verdict.items():
        if "all_periods" in v:
            v["candidate"] = bool(v["all_periods"] and v["worst_ok"] and v.get("nonsense_ok", False))
    out["verdict"] = verdict
    print("verdict", json.dumps(verdict), flush=True)
    (RESULTS / "intraday_structure.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
