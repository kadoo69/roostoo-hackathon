"""W1: laggard shorts in bull hours, in the ranked book's free slots. config/weak_short_bull.yaml.

Engine and windows are gates.competition_wf, unchanged. DECISIONS.md#weak-short-bull-outcome.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as wf
from gates.short_paper_books import sleeve
from signals import donchian


def declaration() -> dict:
    with (ROOT / "config" / "weak_short_bull.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def main() -> int:
    declaration()
    close4, sel4, close1, tick = wf.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    c0 = wf.ranked(mom4, live4)
    bull = ~donchian.bear_regime(close4["BTCUSDT"], 180)
    eligible = sel4 & mom4.notna()
    w1 = sleeve(bull, eligible, live4, c0, mom4, 3)
    nets = {"C0": wf.book_hourly(close1, idx4, long4=c0, tick=tick),
            "W1": wf.book_hourly(close1, idx4, long4=c0, short4=w1, tick=tick)}
    ec = wf.FEE + float((tick / close1.median()).median())
    W = {k: wf.windows_hourly(v, entry_cost=ec) for k, v in nets.items()}
    out = {"declaration": "config/weak_short_bull.yaml",
           "arms": {k: wf.by_period(w) for k, w in W.items()},
           "W1_short_bar_share": round(float(w1.any(axis=1).loc["2022":].mean()), 3)}
    rng = np.random.default_rng(7)
    nons = []
    for s in range(wf.SEEDS):
        rnd = pd.DataFrame(rng.uniform(-1, 0, mom4.shape), index=mom4.index, columns=mom4.columns)
        n1 = wf.book_hourly(close1, idx4, long4=c0, short4=sleeve(bull, eligible, live4, c0, rnd, 3), tick=tick)
        nons.append(wf.windows_hourly(n1, entry_cost=ec))
        print("W1 nonsense seed", s, flush=True)
    out["W1_nonsense"] = {p: {"median_pct_mean": round(float(np.mean([wf.describe(n.loc[a:b])["median_pct"] for n in nons])), 2),
                              "p_gt2_mean": round(float(np.mean([wf.describe(n.loc[a:b])["p_gt2"] for n in nons])), 3)}
                          for p, (a, b) in wf.PERIODS.items()}
    a, ctl = out["arms"]["W1"], out["arms"]["C0"]
    ok3 = all(a[p]["p_gt2"] > ctl[p]["p_gt2"] and a[p]["median_pct"] > ctl[p]["median_pct"] for p in wf.PERIODS)
    worst = all(a[p]["worst_pct"] >= ctl[p]["worst_pct"] - 5 for p in wf.PERIODS)
    gain = a["2025-26"]["p_gt2"] - ctl["2025-26"]["p_gt2"]
    ng = out["W1_nonsense"]["2025-26"]["p_gt2_mean"] - ctl["2025-26"]["p_gt2"]
    out["verdict"] = {"W1": {"all_three_periods": ok3, "worst_ok": worst,
                             "nonsense_ok": bool(gain > 0 and ng < 0.5 * gain),
                             "candidate": bool(ok3 and worst and gain > 0 and ng < 0.5 * gain)}}
    for k in ("C0", "W1"):
        r = out["arms"][k]
        print(f"{k:3s} " + "".join(
            f"| {p} med {r[p]['median_pct']:+6.2f} P>2 {r[p]['p_gt2']:.2f} P>15 {r[p]['p_gt15']:.2f} w {r[p]['worst_pct']:+6.1f} "
            for p in wf.PERIODS))
    print("W1 nonsense:", out["W1_nonsense"])
    print("verdict:", out["verdict"])
    (RESULTS / "weak_short_bull.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
