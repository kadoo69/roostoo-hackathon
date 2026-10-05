"""Lone-burst filter: no new entry on bars where many coins trigger at once. Declared: config/ride_lone_burst.yaml,
DECISIONS.md#ride-lone-burst-declaration"""
import json
import numpy as np
import pandas as pd
import yaml
from archive.gates.ride1_wide_vs_live import frames
from archive.gates.ride_partial_trim import book, stats
from archive.gates.ride_z3_wide import POOL
from data import universe as ru
cfg = next(iter(yaml.safe_load(open("config/competition_z25.yaml"))["adaptive"]["burst_arms"].values()))
close, high = frames(list(POOL), pd.Timestamp("2026-09-10", tz="UTC"))
specs = ru.tradable_symbols(); cols = [s for s in POOL if s in close.columns and s in specs]; close, high = close[cols], high[cols]
r3 = close / close.shift(3) - 1; sd = r3.rolling(288, min_periods=144).std().shift(1); zdf = r3 / sd
z, dv = zdf.to_numpy(float), (sd * np.sqrt(96)).to_numpy(float); N = (zdf >= 2.5).sum(axis=1).to_numpy()
end = close.index[-1]; arms = {"LONE2": N <= 2, "LONE4": N <= 4}; out = {}
for span in ("14D", "3D"):
    res = {"LIVE": []} | {a: [] for a in arms}
    for k in range(12):
        a0 = end - pd.Timedelta(span) - pd.Timedelta(hours=2 * k); m = (close.index >= a0) & (close.index <= a0 + pd.Timedelta(span))
        c, h = close.loc[m].to_numpy(float), high.loc[m].to_numpy(float)
        res["LIVE"].append(stats(*book(c, h, z[m], dv[m], cfg, None, None)[:1], close.index[m], 0))
        for a, al in arms.items(): res[a].append(stats(*book(c, h, z[m], dv[m], cfg, None, None, None, al[m])[:1], close.index[m], 0))
    L = np.array([x["total_pct"] for x in res["LIVE"]]); out[span] = {}
    for a, v in res.items():
        rr, dd, sh = (np.array([x[f] for x in v]) for f in ("total_pct", "max_dd_pct", "sharpe"))
        out[span][a] = {"median_ret": round(float(np.median(rr)), 2), "median_dd": round(float(np.median(dd)), 2), "median_sharpe": round(float(np.median(sh)), 2),
                        "wins": int((rr > L).sum()), "worst": round(float(rr.min()), 2)}
ver = {a: all(out[s][a]["wins"] >= 8 and out[s][a]["median_dd"] >= out[s]["LIVE"]["median_dd"] for s in out) for a in arms}
share = {a: round(float(arms[a][close.index >= end - pd.Timedelta("14D")].mean()), 2) for a in arms}
res = {"spans": out, "candidate": ver, "bar_open_share_14d": share, "ref": "DECISIONS.md#ride-lone-burst-declaration"}
json.dump(res, open("results/ride_lone_burst.json", "w"), indent=1); print(json.dumps(res, indent=1))
