"""The S1 short sleeve on donchian_4h, on the competition_wf engine. config/short_paper_books.yaml.

Fails unless the shared `signals.donchian.breakdown_position` matches, cell by cell, the loop
gates/competition_wf.py carried inline, so the move is checked, not assumed. C0 and S1 are
re-scored beside C1 and D1 because the pool changed after #competition-wf-outcome was recorded
(#universe-completeness). DECISIONS.md#short-paper-books
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as wf
from signals import donchian


def declaration() -> dict:
    with (ROOT / "config" / "short_paper_books.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def sleeve(regime: pd.Series, brk: pd.DataFrame, live4: pd.DataFrame, longs: pd.DataFrame,
           mom4: pd.DataFrame, slots: int, own_slots: bool = False, negative_momentum: bool = False) -> pd.DataFrame:
    """Short picks per bar. `own_slots` gives shorts `slots` of their own instead of the slots the
    longs leave free, and `negative_momentum` admits only names with negative momentum.
    DECISIONS.md#lowtf-breadth-shorts-declaration"""
    idx4, cols = brk.index, brk.columns
    free = pd.Series(float(slots), index=idx4) if own_slots else slots - longs.sum(axis=1)
    rg = regime.reindex(idx4).fillna(False).to_numpy()
    rgf = pd.DataFrame(np.repeat(rg[:, None], len(cols), axis=1), index=idx4, columns=cols)
    cand = brk & rgf & ~live4
    if negative_momentum:
        cand &= mom4 < 0
    sc = (-mom4).where(cand)
    rk = sc.rank(axis=1, ascending=False)
    return rk.le(free, axis=0) & sc.notna()


def _inline_breakdown(close4: pd.DataFrame) -> pd.DataFrame:
    """The breakdown loop exactly as gates/competition_wf.py carried it before the move."""
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
    return pd.DataFrame(arr, index=close4.index, columns=close4.columns)


def main() -> int:
    declaration()
    close4, sel4, close1, tick = wf.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = wf.ranked(mom4, live4)
    bear = donchian.bear_regime(close4["BTCUSDT"], 180)
    brk = donchian.breakdown_position(close4, 20, 10) & sel4

    nets = {
        "C0": wf.book_hourly(close1, idx4, long4=c0, tick=tick),
        "C1": wf.book_hourly(close1, idx4, long4=live4, divisor=20, tick=tick),
        "S1": wf.book_hourly(close1, idx4, long4=c0,
                             short4=sleeve(bear, brk, live4, c0, mom4, 3), tick=tick),
        "D1": wf.book_hourly(close1, idx4, long4=live4, divisor=20,
                             short4=sleeve(bear, brk, live4, live4, mom4, 20), tick=tick),
    }
    ec = wf.FEE + float((tick / close1.median()).median())
    W = {k: wf.windows_hourly(v, entry_cost=ec) for k, v in nets.items()}
    out = {"declaration": "config/short_paper_books.yaml",
           "arms": {k: wf.by_period(w) for k, w in W.items()}}

    ref = _inline_breakdown(close4) & sel4
    mismatches = int((ref != brk).to_numpy().sum())
    out["refactor_breakdown_cell_mismatches"] = mismatches
    out["pool_note"] = ("C0 and S1 are re-scored on the complete pool of #universe-completeness; "
                        "the recorded #competition-wf-outcome rows predate it")
    print("breakdown refactor mismatches (must be 0):", mismatches, flush=True)
    if mismatches:
        (RESULTS / "short_paper_books.json").write_text(json.dumps(out, indent=1, default=str))
        raise SystemExit("refactor_reproduction_failed")

    rng = np.random.default_rng(7)
    runs = [g for _, g in bear.groupby((bear != bear.shift()).cumsum())]
    nons = []
    for s in range(wf.SEEDS):
        vals = np.concatenate([runs[i].to_numpy() for i in rng.permutation(len(runs))])
        fake = pd.Series(vals[:len(bear)], index=bear.index)
        n1 = wf.book_hourly(close1, idx4, long4=live4, divisor=20,
                            short4=sleeve(fake, brk, live4, live4, mom4, 20), tick=tick)
        nons.append(wf.windows_hourly(n1, entry_cost=ec))
        print("D1 nonsense seed", s, flush=True)
    out["D1_nonsense"] = {p: {"median_pct_mean": round(float(np.mean([wf.describe(n.loc[a:b])["median_pct"] for n in nons])), 2),
                              "p_gt2_mean": round(float(np.mean([wf.describe(n.loc[a:b])["p_gt2"] for n in nons])), 3)}
                          for p, (a, b) in wf.PERIODS.items()}

    a, ctl = out["arms"]["D1"], out["arms"]["C1"]
    ok3 = all(a[p]["p_gt2"] > ctl[p]["p_gt2"] and a[p]["median_pct"] > ctl[p]["median_pct"] for p in wf.PERIODS)
    worst = all(a[p]["worst_pct"] >= ctl[p]["worst_pct"] - 5 for p in wf.PERIODS)
    gain = a["2025-26"]["p_gt2"] - ctl["2025-26"]["p_gt2"]
    ng = out["D1_nonsense"]["2025-26"]["p_gt2_mean"] - ctl["2025-26"]["p_gt2"]
    out["verdict"] = {"D1": {"all_three_periods": ok3, "worst_ok": worst,
                             "nonsense_ok": bool(gain > 0 and ng < 0.5 * gain),
                             "candidate": bool(ok3 and worst and gain > 0 and ng < 0.5 * gain)}}
    for k in ("C0", "S1", "C1", "D1"):
        r = out["arms"][k]
        print(f"{k:3s} " + "".join(
            f"| {p} med {r[p]['median_pct']:+6.2f} P>2 {r[p]['p_gt2']:.2f} P>15 {r[p]['p_gt15']:.2f} w {r[p]['worst_pct']:+6.1f} "
            for p in wf.PERIODS))
    print("D1 nonsense:", out["D1_nonsense"])
    print("verdict:", out["verdict"])
    (RESULTS / "short_paper_books.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
