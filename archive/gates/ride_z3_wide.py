"""Does the per-coin ride gain from a wider universe: z3 on the 27-coin pool against the 64-coin venue_all set.

Declared before any number: config/ride_z3_wide.yaml, DECISIONS.md#ride-z3-wide-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_scaled_entry import weights
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe

POOL = ("BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "XRPUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT", "DOGEUSDT",
        "UNIUSDT", "ENAUSDT", "AVAXUSDT", "WLDUSDT", "ADAUSDT", "LINKUSDT", "TAOUSDT", "ARBUSDT", "PUMPUSDT",
        "PEPEUSDT", "TRXUSDT", "LTCUSDT", "ONDOUSDT", "XLMUSDT", "TRUMPUSDT", "FETUSDT", "AAVEUSDT", "FILUSDT")


def run(close: pd.DataFrame, high: pd.DataFrame, tick: pd.Series, cfg: dict, cols: list[str],
        windows: dict) -> dict:
    cl_all, hi_all = close[cols], high[cols]
    r3 = cl_all / cl_all.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    z = (r3 / r3.rolling(sb, min_periods=sb // 2).std().shift(1)).to_numpy(dtype=float)
    out = {}
    for wn, (lo, hi_) in windows.items():
        m = (cl_all.index >= lo) & (cl_all.index <= hi_)
        cl, hi = cl_all.loc[m], hi_all.loc[m]
        w = weights(cl, hi, z[m], cfg, float(cfg["sigma_k"]), 1.0, None)
        net, _ = lwr.simulate(cl, w, tick.reindex(cols), True)
        eq = (1 + net).cumprod()
        starts = (w > 0) & (w.shift(1).fillna(0) == 0)
        outside = [c for c in cols if c not in POOL]
        ret = cl.pct_change().shift(-1).fillna(0)
        pnl = (w * ret).sum()
        out[wn] = {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
                   "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2),
                   "mean_gross": round(float(w.sum(axis=1).mean()), 2),
                   "entries": int(starts.to_numpy().sum()),
                   "entries_outside_pool": int(starts[outside].to_numpy().sum()) if outside else 0,
                   "gross_pnl_pct_outside_pool": round(float(pnl[outside].sum()) * 100, 2) if outside else 0.0,
                   "gross_pnl_pct_pool": round(float(pnl[[c for c in cols if c in POOL]].sum()) * 100, 2)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-03")
    ap.add_argument("--subsets", type=int, default=20)
    a = ap.parse_args(argv)
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "ride_z3_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp(a.start, tz="UTC")
    wide = sorted(set(universe("ride1_wide_5m")) | set(POOL))
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(wide, "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    have = [c for c in close.columns if c in tick.index]
    pool = [c for c in POOL if c in have]
    wide = [c for c in wide if c in have]
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end),
               "last_3d": (end - pd.Timedelta("3D"), end)}
    res = {"Z3": run(close, high, tick, cfg, pool, windows), "Z3W": run(close, high, tick, cfg, wide, windows)}
    beats = {wn: res["Z3W"][wn]["total_pct"] > res["Z3"][wn]["total_pct"] for wn in windows}
    dd_ok = {wn: res["Z3W"][wn]["max_dd_pct"] >= res["Z3"][wn]["max_dd_pct"] - 2.0 for wn in windows}
    control = None
    if all(beats.values()) and all(dd_ok.values()):
        rng = np.random.default_rng(13)
        sub = [run(close, high, tick, cfg, sorted(rng.choice(wide, size=len(pool), replace=False).tolist()),
                   {k: windows[k] for k in ("W2", "last_3d")}) for _ in range(a.subsets)]
        control = {wn: int(sum(res["Z3W"][wn]["total_pct"] > s[wn]["total_pct"] for s in sub)) for wn in ("W2", "last_3d")}
    passed = all(beats.values()) and all(dd_ok.values()) and control is not None and min(control.values()) >= 16
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "n_pool": len(pool), "n_wide": len(wide),
           "arms": res, "verdict": {"beats_Z3": beats, "dd_ok": dd_ok, "random_subsets_beaten": control,
                                    "recommended": passed},
           "ref": "DECISIONS.md#ride-z3-wide-declaration"}
    (RESULTS / "ride_z3_wide.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
