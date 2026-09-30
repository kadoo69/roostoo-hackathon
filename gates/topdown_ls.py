"""Top-down long/short book on the competition_wf engine. config/topdown_ls.yaml.

`book_weights` is gates.competition_wf.book_hourly generalised to signed target weights and a
ladder on both sides. With equal long-only weights and no short ladder it must reproduce
book_hourly on C0 exactly, which is checked before any arm is read.
DECISIONS.md#topdown-ls-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as wf
from signals import donchian, topdown

H = pd.Timedelta(hours=1)


def declaration() -> dict:
    with (ROOT / "config" / "topdown_ls.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def book_weights(close1: pd.DataFrame, idx4, w4: pd.DataFrame, tick: pd.Series, ladder: bool = True,
                 short_ladder: bool = True, band: float = wf.BAND) -> tuple[pd.Series, pd.Series]:
    """Hourly net returns and gross for signed 4h target weights, with book_hourly's rules: targets
    applied at 4h closes, held names never topped up, the 3% x 15% ladder, the drift band, fee plus
    tick per side and the short fee on short legs."""
    cols, idx1 = close1.columns, close1.index
    px = close1.to_numpy(dtype=float)
    nn = len(cols)
    is4 = np.asarray(((idx1 + H).hour % 4) == 0)
    T = wf.to_fast(w4.reindex(columns=cols).fillna(0.0), idx4, idx1).fillna(0.0).to_numpy()
    tk = tick.reindex(cols).fillna(0.0).to_numpy()
    w = np.zeros(nn)
    ref = np.full(nn, np.nan)
    net = np.zeros(len(px))
    gross = np.zeros(len(px))
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
            want = np.where(fin, T[t], 0.0)
            lk, sk = want > 1e-12, want < -1e-12
            tgt = np.zeros(nn)
            fresh_l, held_l = lk & (w <= 1e-12), lk & (w > 1e-12)
            fresh_s, held_s = sk & (w >= -1e-12), sk & (w < -1e-12)
            tgt[fresh_l] = want[fresh_l]
            tgt[held_l] = np.minimum(want[held_l], w[held_l]) if ladder else want[held_l]
            tgt[fresh_s] = want[fresh_s]
            tgt[held_s] = np.maximum(want[held_s], w[held_s])
            ref[fresh_l | fresh_s] = cur[fresh_l | fresh_s]
            ref[~(lk | sk)] = np.nan
        if ladder:
            live_l = (tgt > 1e-12) & (w > 1e-12) & np.isfinite(ref)
            hit = live_l & (cur >= ref * (1.0 + wf.STEP))
            if short_ladder:
                live_s = (tgt < -1e-12) & (w < -1e-12) & np.isfinite(ref)
                hit |= live_s & (cur <= ref * (1.0 - wf.STEP))
            if hit.any():
                tgt[hit] = w[hit] * (1.0 - wf.FRAC)
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
        net[t] = (mult - 1.0) - float((dw * (np.where(short_leg, wf.SHORT_FEE, wf.FEE) + tb)).sum())
        w = tgt
        gross[t] = float(np.abs(w).sum())
    return pd.Series(net, index=idx1), pd.Series(gross, index=idx1)


def main() -> int:
    cfg = declaration()
    td = cfg["topdown"]
    close4, sel4, close1, tick = wf.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = wf.ranked(mom4, live4)
    btc = close4["BTCUSDT"]

    ref = wf.book_hourly(close1, idx4, long4=c0, tick=tick)
    eq = c0.astype(float).div(c0.sum(axis=1).clip(lower=1), axis=0)
    mine, _ = book_weights(close1, idx4, eq, tick, short_ladder=False)
    gap = float((mine - ref).abs().max())
    out = {"declaration": "config/topdown_ls.yaml", "reconciliation_max_abs_hourly_diff": gap}
    print("reconciliation vs book_hourly (must be ~0):", gap, flush=True)
    if gap > 1e-9:
        (RESULTS / "topdown_ls.json").write_text(json.dumps(out, indent=1))
        raise SystemExit("reconciliation_failed")

    w_t1, reg = topdown.targets(close4, sel4, btc, td)
    no_short = {**td, "budgets": {s: {"long": b["long"], "short": 0.0} for s, b in td["budgets"].items()}}
    w_long, _ = topdown.targets(close4, sel4, btc, no_short, reg=reg)
    w_eq, _ = topdown.targets(close4, sel4, btc, {**td, "sizing": "equal"}, reg=reg)
    arms = {"C0": (eq, True), "T1": (w_t1, True), "T1_long": (w_long, True),
            "T1_equal": (w_eq, True), "T1_noTP": (w_t1, False)}
    ec = wf.FEE + float((tick / close1.median()).median())
    W, G = {}, {}
    for k, (wt, lad) in arms.items():
        n, g = book_weights(close1, idx4, wt, tick, ladder=lad)
        W[k], G[k] = wf.windows_hourly(n, entry_cost=ec), g
        print(k, "done", flush=True)
    out["arms"] = {k: wf.by_period(w) for k, w in W.items()}
    after = reg.loc["2022":]
    out["regime_share"] = after["state"].value_counts(normalize=True).round(3).to_dict()
    out["mean_gross"] = {k: {p: round(float(g.loc[a:b].mean()), 2) for p, (a, b) in wf.PERIODS.items()}
                         for k, g in G.items()}
    out["short_share"] = {p: round(float((w_t1.loc[a:b] < 0).any(axis=1).mean()), 3) for p, (a, b) in wf.PERIODS.items()}

    rng = np.random.default_rng(7)
    st = reg["state"]
    runs = [g for _, g in st.groupby((st != st.shift()).cumsum())]
    nons = []
    for s in range(wf.SEEDS):
        vals = np.concatenate([runs[i].to_numpy() for i in rng.permutation(len(runs))])
        fake = reg.copy()
        fake["state"] = vals[:len(st)]
        wn, _ = topdown.targets(close4, sel4, btc, td, reg=fake)
        n1, _ = book_weights(close1, idx4, wn, tick)
        nons.append(wf.windows_hourly(n1, entry_cost=ec))
        print("T1 nonsense seed", s, flush=True)
    out["T1_nonsense"] = {p: {"median_pct_mean": round(float(np.mean([wf.describe(n.loc[a:b])["median_pct"] for n in nons])), 2),
                              "p_gt2_mean": round(float(np.mean([wf.describe(n.loc[a:b])["p_gt2"] for n in nons])), 3)}
                          for p, (a, b) in wf.PERIODS.items()}
    a, ctl = out["arms"]["T1"], out["arms"]["C0"]
    ok3 = all(a[p]["p_gt2"] > ctl[p]["p_gt2"] and a[p]["median_pct"] > ctl[p]["median_pct"] for p in wf.PERIODS)
    worst = all(a[p]["worst_pct"] >= ctl[p]["worst_pct"] - 5 for p in wf.PERIODS)
    gain = a["2025-26"]["p_gt2"] - ctl["2025-26"]["p_gt2"]
    ng = out["T1_nonsense"]["2025-26"]["p_gt2_mean"] - ctl["2025-26"]["p_gt2"]
    out["verdict"] = {"T1": {"all_three_periods": ok3, "worst_ok": worst,
                             "nonsense_ok": bool(gain > 0 and ng < 0.5 * gain),
                             "candidate": bool(ok3 and worst and gain > 0 and ng < 0.5 * gain)}}
    for k in arms:
        r = out["arms"][k]
        print(f"{k:8s} " + "".join(
            f"| {p} med {r[p]['median_pct']:+6.2f} P>2 {r[p]['p_gt2']:.2f} P>15 {r[p]['p_gt15']:.2f} w {r[p]['worst_pct']:+6.1f} s3 {r[p]['median_screen3']:+.2f} "
            for p in wf.PERIODS))
    for k in ("regime_share", "mean_gross", "short_share", "T1_nonsense", "verdict"):
        print(k, out[k])
    (RESULTS / "topdown_ls.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
