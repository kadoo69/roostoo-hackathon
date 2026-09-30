"""Top-3 strongest contenders across both sides, sized by strength. DECISIONS.md#lowtf-contenders-declaration

Harness, universe and costs of gates/lowtf_paper_bots.py; compared with the long-only momentum
rule and the breadth-short rule (gates/lowtf_breadth_shorts.py) on the same clock.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates.concentration import context
from gates.lowtf_breadth_shorts import book, score
from gates.lowtf_paper_bots import W, fast_close
from signals import contenders, donchian

CFG = {"momentum_bars": 40, "breadth_max": 0.40, "n": 3, "max_weight": 0.50}
SEEDS = 5


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    rng = np.random.default_rng(7)
    rows = []
    for iv in ("1h", "30m", "15m"):
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        bar = close.index[1] - close.index[0]
        s4 = sel4[cols].copy()
        s4.index = s4.index + pd.Timedelta(hours=4)
        sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
        sel.index = close.index
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        base = score(book("momentum", close, sel, None), close, tick)
        ls = score(book("momentum", close, sel, flag), close, tick)
        w = contenders.targets(close, sel, CFG, short_on=flag)
        arm = score(w, close, tick)
        nons = []
        for _ in range(SEEDS):
            rnd = pd.DataFrame(rng.uniform(0.1, 1.0, w.shape), index=w.index, columns=w.columns).where(w.abs() > 0)
            rw = rnd.div(rnd.sum(axis=1), axis=0).fillna(0.0)
            rw = contenders.cap_weights(rw, CFG["max_weight"]) * np.sign(w)
            nons.append(score(rw, close, tick))
        row = {"interval": iv, "long_only": base, "breadth_shorts_own_slots": ls, "contenders": arm,
               "random_size_holdout_median_mean": round(float(np.mean([n["holdout"]["median_pct"] for n in nons])), 2),
               "mean_names": round(float((w.abs() > 0).sum(axis=1).loc["2023":].mean()), 2),
               "mean_gross": round(float(w.abs().sum(axis=1).loc["2023":].mean()), 2)}
        rows.append(row)
        print(f"{iv:4s} names {row['mean_names']} gross {row['mean_gross']} | " + " | ".join(
            f"{t}: L {base[t]['median_pct']:+6.2f} | LS {ls[t]['median_pct']:+6.2f} | TOP3 {arm[t]['median_pct']:+6.2f} (P5 {arm[t]['p_gt5']:.2f}, w {arm[t]['worst_pct']:+.1f}, drag {arm[t]['cost_drag_per_14d_pct']}%)"
            for t in W) + f" | random sizes {row['random_size_holdout_median_mean']:+.2f}", flush=True)
    (RESULTS / "lowtf_contenders.json").write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
