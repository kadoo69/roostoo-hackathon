"""Deterministic regime gate (follow-through, breadth) on new entries of the live ride with the churn.

Declared before any number: config/ride_regime_gate.yaml, DECISIONS.md#ride-regime-gate-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride1_wide_vs_live import frames
from archive.gates.ride_partial_trim import CHURN, book, stats
from archive.gates.ride_z3_wide import POOL
from core.config import RESULTS, ROOT
from data import universe as ru


def features(close: pd.DataFrame, z: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """FT and BR per bar, point in time. FT uses triggers 12..288 bars old with their 12-bar forward return."""
    fwd = close.shift(-12) / close - 1.0
    trig = (z >= 2.5)
    win = trig.astype(float).shift(12)
    good = (trig & (fwd > 0)).astype(float).shift(12)
    n = win.rolling(276, min_periods=1).sum().sum(axis=1)
    g = good.rolling(276, min_periods=1).sum().sum(axis=1)
    ft = (g / n.replace(0, np.nan)).fillna(0.5)
    r288 = close / close.shift(288) - 1.0
    br = (r288 > 0).sum(axis=1) / r288.notna().sum(axis=1).clip(lower=1)
    return ft, br


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    churn = CHURN
    specs = ru.tradable_symbols()
    close, high = frames(list(POOL), pd.Timestamp("2026-09-12", tz="UTC"))
    cols = [s for s in POOL if s in close.columns and s in specs]
    close, high = close[cols], high[cols]
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    zdf = r3 / sd
    z, dvol = zdf.to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    ft, br = features(close, zdf)
    gates = {"LIVE": None, "G_FT": (ft >= 0.5).to_numpy(), "G_BR": (br >= 0.4).to_numpy(),
             "G_BOTH": ((ft >= 0.5) & (br >= 0.4)).to_numpy()}
    end = close.index[-1]
    windows = {"last_14d": end - pd.Timedelta("14D"), "last_3d": end - pd.Timedelta("3D"), "last_1d": end - pd.Timedelta("1D")}
    res = {}
    for arm, allow in gates.items():
        res[arm] = {}
        for wn, a in windows.items():
            m = close.index >= a
            eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), z[m], dvol[m], cfg,
                          float(churn["trim"]), float(churn["zmax"]), float(churn["churn_tpk"]),
                          None if allow is None else allow[m])
            res[arm][wn] = {**stats(eq, close.index[m], ne),
                            "gate_open_share": None if allow is None else round(float(allow[m].mean()), 2)}
    dec = tuple(windows)

    def passes(arm: str) -> dict:
        b, x = res["LIVE"], res[arm]
        rt = [w for w in dec if x[w]["total_pct"] > b[w]["total_pct"]]
        sh = sum(1 for w in dec if x[w]["sharpe"] > b[w]["sharpe"])
        dd = x["last_14d"]["max_dd_pct"] >= b["last_14d"]["max_dd_pct"] - 2.0
        return {"return_wins": rt, "sharpe_wins": sh, "dd_14d_within_2pp": dd,
                "candidate": bool(len(rt) >= 2 and "last_3d" in rt and sh >= 2 and dd)}

    verdict = {a: passes(a) for a in ("G_FT", "G_BR", "G_BOTH")}
    now = {"FT": round(float(ft.iloc[-1]), 3), "BR": round(float(br.iloc[-1]), 3)}
    out = {"end": str(end), "arms": res, "verdict": verdict, "features_now": now,
           "ref": "DECISIONS.md#ride-regime-gate-declaration"}
    (RESULTS / "ride_regime_gate.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'arm':7}" + "".join(f"{w:>40}" for w in windows))
    for arm in gates:
        print(f"{arm:7}" + "".join(f"{res[arm][w]['total_pct']:>+8.2f}% dd{res[arm][w]['max_dd_pct']:>7.2f} sh{res[arm][w]['sharpe']:>6.2f} open{res[arm][w]['gate_open_share'] or 1:>5}" for w in windows))
    print("features now", now)
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
