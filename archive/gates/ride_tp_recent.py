"""Nearer volatility-scaled take-profits on the live ride with the churn, on the operator's recent windows.

Declared before any number: config/ride_tp_recent.yaml, DECISIONS.md#ride-tp-recent-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride1_wide_vs_live import frames
from archive.gates.ride_partial_trim import book, stats
from archive.gates.ride_z3_wide import POOL
from core.config import RESULTS, ROOT
from data import universe as ru

ARMS = {"LIVE": 2.0, "TP15": 1.5, "TP10": 1.0, "TP05": 0.5}


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    churn = cfg["trim_churn"]
    specs = ru.tradable_symbols()
    close, high = frames(list(POOL), pd.Timestamp("2026-09-15", tz="UTC"))
    cols = [s for s in POOL if s in close.columns and s in specs]
    close, high = close[cols], high[cols]
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z, dvol = (r3 / sd).to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    end = close.index[-1]
    windows = {"last_14d": end - pd.Timedelta("14D"), "last_3d": end - pd.Timedelta("3D"), "last_1d": end - pd.Timedelta("1D")}
    res = {}
    for arm, tpk in ARMS.items():
        c = {**cfg, "tp_vol_k": tpk}
        ctp = min(float(churn["churn_tpk"]), tpk)
        res[arm] = {}
        for wn, a in windows.items():
            m = close.index >= a
            eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), z[m], dvol[m], c,
                          float(churn["trim"]), float(churn["zmax"]), ctp)
            res[arm][wn] = stats(eq, close.index[m], ne)
    dec = tuple(windows)

    def passes(arm: str) -> dict:
        b, x = res["LIVE"], res[arm]
        rt = [w for w in dec if x[w]["total_pct"] > b[w]["total_pct"]]
        sh = sum(1 for w in dec if x[w]["sharpe"] > b[w]["sharpe"])
        dd = x["last_14d"]["max_dd_pct"] >= b["last_14d"]["max_dd_pct"] - 2.0
        return {"return_wins": rt, "sharpe_wins": sh, "dd_14d_within_2pp": dd,
                "candidate": bool(len(rt) >= 2 and "last_3d" in rt and sh >= 2 and dd)}

    verdict = {a: passes(a) for a in ("TP15", "TP10", "TP05")}
    cands = [a for a, v in verdict.items() if v["candidate"]]
    verdict["best"] = max(cands, key=lambda a: min(res[a][w]["sharpe"] for w in dec)) if cands else None
    out = {"end": str(end), "arms": res, "verdict": verdict, "ref": "DECISIONS.md#ride-tp-recent-declaration"}
    (RESULTS / "ride_tp_recent.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'arm':6}" + "".join(f"{w:>34}" for w in windows))
    for arm in ARMS:
        print(f"{arm:6}" + "".join(f"{res[arm][w]['total_pct']:>+8.2f}% dd{res[arm][w]['max_dd_pct']:>7.2f} sh{res[arm][w]['sharpe']:>6.2f} e{res[arm][w]['entries_per_day']:>4.1f}" for w in windows))
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
