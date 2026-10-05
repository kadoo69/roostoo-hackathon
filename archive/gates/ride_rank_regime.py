"""Rank simultaneous triggers by z instead of 3-bar return, and ride_5m, against the live rule on recent windows only.

Declared: config/ride_rank_regime.yaml, DECISIONS.md#ride-rank-regime-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride1_wide_vs_live import book, frames
from archive.gates.ride_partial_trim import stats
from archive.gates.ride_z3_wide import POOL
from core.config import RESULTS, ROOT
from data import universe as ru

OPEN = pd.Timestamp("2026-10-04 12:00", tz="UTC")


def main() -> int:
    live = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    r5 = next(iter(yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    specs = ru.tradable_symbols()
    close, high = frames(list(POOL), pd.Timestamp("2026-09-15", tz="UTC"))
    cols = [s for s in POOL if s in close.columns and s in specs]
    close, high = close[cols], high[cols]
    r3 = close / close.shift(3) - 1.0
    sb = int(live["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z = r3 / sd
    lvl_live = float(live["sigma_k"]) * sd
    tp_live = float(live["tp_vol_k"]) * sd * np.sqrt(96)
    lvl5 = pd.DataFrame(float(r5["thresh_pct"]) / 100, index=r3.index, columns=cols)
    tp5 = pd.DataFrame(float(r5["tp_pct"]) / 100, index=r3.index, columns=cols)
    arms = {"B2": (lvl_live, tp_live, int(live["n"]), int(live["cooldown_bars"]), None),
            "B2Z": (lvl_live, tp_live, int(live["n"]), int(live["cooldown_bars"]), z),
            "RIDE5": (lvl5, tp5, int(r5["n"]), int(r5["cooldown_bars"]), None)}
    end = close.index[-1]
    windows = {"last_14d": (end - pd.Timedelta("14D"), end), "last_3d": (end - pd.Timedelta("3D"), end),
               "last_1d": (end - pd.Timedelta("1D"), end), "since_open": (OPEN, end)}
    res = {}
    for arm, (lvl, tp, n, cool, rank) in arms.items():
        res[arm] = {}
        for wn, (a, b) in windows.items():
            m = (close.index >= a) & (close.index <= b)
            eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), r3.loc[m].to_numpy(float),
                          lvl.loc[m].to_numpy(float), tp.loc[m].to_numpy(float), n, int(live["hold_bars"]), cool,
                          None if rank is None else rank.loc[m].to_numpy(float))
            res[arm][wn] = stats(eq, close.index[m], ne)
    dec = ("last_14d", "last_3d", "last_1d")

    def passes(arm: str) -> dict:
        b, x = res["B2"], res[arm]
        rt = [w for w in dec if x[w]["total_pct"] > b[w]["total_pct"]]
        sh = sum(1 for w in dec if x[w]["sharpe"] > b[w]["sharpe"])
        dd = x["last_14d"]["max_dd_pct"] >= b["last_14d"]["max_dd_pct"] - 2.0
        ok = len(rt) >= 2 and "last_3d" in rt and sh >= 2 and dd
        return {"return_wins": rt, "sharpe_wins": sh, "dd_14d_within_2pp": dd, "candidate": bool(ok)}

    verdict = {a: passes(a) for a in ("B2Z", "RIDE5")}
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "verdict": verdict,
           "ref": "DECISIONS.md#ride-rank-regime-declaration"}
    (RESULTS / "ride_rank_regime.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'arm':6}" + "".join(f"{w:>34}" for w in windows))
    for arm in arms:
        print(f"{arm:6}" + "".join(f"{res[arm][w]['total_pct']:>+8.2f}% dd{res[arm][w]['max_dd_pct']:>7.2f} sh{res[arm][w]['sharpe']:>6.2f} e{res[arm][w]['entries_per_day']:>4.1f}" for w in windows))
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
