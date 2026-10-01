"""Sizing tilts toward residual strength and volatility on the competition rule. Declared in
config/strength_tilt.yaml before any number was computed. DECISIONS.md#strength-tilt-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS, record_trials
from gates import stress
from signals import contenders

SEEDS = 20


def retilt(w: pd.DataFrame, mult: pd.DataFrame) -> pd.DataFrame:
    held = w > 1e-12
    raw = (w * mult.reindex_like(w).fillna(1.0)).where(held, 0.0)
    gross = w.sum(axis=1)
    out = raw.div(raw.sum(axis=1).replace(0.0, np.nan), axis=0).mul(gross, axis=0).fillna(0.0)
    return contenders.cap_weights(out, 0.5)


def residual_rank(b: stress.Book, w: pd.DataFrame) -> pd.DataFrame:
    c = b.close
    members = b.sel.reindex_like(c).fillna(False)
    pool = c.pct_change().where(members).mean(axis=1)
    res = c.pct_change().sub(pool, axis=0).rolling(8).sum()
    return 1.0 + res.where(w > 1e-12).rank(axis=1, pct=True).fillna(0.0)


def vol_ratio(b: stress.Book, w: pd.DataFrame) -> pd.DataFrame:
    rv = b.close.pct_change().rolling(48).std().where(w > 1e-12)
    return rv.div(rv.median(axis=1), axis=0).clip(0.5, 2.0)


def main() -> int:
    rng = np.random.default_rng(31)
    b = stress.load("competition")
    w0 = stress.weights(b)
    base = stress.describe(*stress.run(b, w0))
    arms = {"T_res": retilt(w0, residual_rank(b, w0)), "T_vol": retilt(w0, vol_ratio(b, w0))}
    res = {"C0": base}
    for k, w in arms.items():
        res[k] = stress.describe(*stress.run(b, w))
    ctrl = []
    for _ in range(SEEDS):
        m = pd.DataFrame(rng.uniform(1.0, 2.0, w0.shape), index=w0.index, columns=w0.columns)
        ctrl.append(stress.describe(*stress.run(b, retilt(w0, m))))
    verdict = {}
    for k in arms:
        a = res[k]
        checks = {"fit_plus_0.25pp": a["fit"]["median_pct"] >= base["fit"]["median_pct"] + 0.25,
                  "holdout_at_least": a["holdout"]["median_pct"] >= base["holdout"]["median_pct"],
                  "worst_within_2pp": all(a[t]["worst_pct"] >= base[t]["worst_pct"] - 2.0 for t in ("fit", "holdout")),
                  "beats_18_of_20_random_fit": sum(a["fit"]["median_pct"] > c["fit"]["median_pct"] for c in ctrl) >= 18}
        verdict[k] = {"checks": {c: bool(v) for c, v in checks.items()}, "pass": bool(all(checks.values()))}
    out = {"arms": res, "random_fit_medians": sorted(round(c["fit"]["median_pct"], 2) for c in ctrl),
           "random_holdout_medians": sorted(round(c["holdout"]["median_pct"], 2) for c in ctrl), "verdict": verdict}
    (RESULTS / "strength_tilt.json").write_text(json.dumps(out, indent=1, default=str))
    for k in ("C0", *arms):
        print(f"{k:6s} " + " | ".join(f"{t} med {res[k][t]['median_pct']:+6.2f} P5 {res[k][t]['p_gt5']:.2f} worst {res[k][t]['worst_pct']:+6.2f} mdd {res[k][t]['median_maxdd_pct']:+6.2f}"
                                       for t in stress.PERIODS))
    print("random fit medians", out["random_fit_medians"])
    print("random holdout medians", out["random_holdout_medians"])
    print(json.dumps(verdict))
    record_trials([{"signal": "sizing_tilt", "gate": "strength_tilt", "config": f"strength_tilt:{k}",
                    "status": "pass" if verdict[k]["pass"] else "fail", "note": "DECISIONS.md#strength-tilt-outcome"} for k in arms])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
