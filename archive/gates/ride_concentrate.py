"""One slot (the whole book in the strongest burst) against the live two slots, over 12 start offsets.

Declared before any number: config/ride_concentrate.yaml, DECISIONS.md#ride-concentrate-declaration
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


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    ch = CHURN
    specs = ru.tradable_symbols()
    close, high = frames(list(POOL), pd.Timestamp("2026-09-10", tz="UTC"))
    cols = [s for s in POOL if s in close.columns and s in specs]
    close, high = close[cols], high[cols]
    r3 = close / close.shift(3) - 1.0
    sd = r3.rolling(288, min_periods=144).std().shift(1)
    z, dv = (r3 / sd).to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    end = close.index[-1]
    out = {}
    for span in ("14D", "3D"):
        rows = []
        for k in range(12):
            a = end - pd.Timedelta(span) - pd.Timedelta(hours=2 * k)
            m = (close.index >= a) & (close.index <= a + pd.Timedelta(span))
            res = {}
            for arm, n in (("LIVE", 2), ("N1", 1)):
                eq, ne = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), z[m], dv[m], {**cfg, "n": n},
                              float(ch["trim"]), float(ch["zmax"]), float(ch["churn_tpk"]))
                res[arm] = stats(eq, close.index[m], ne)
            rows.append(res)
        L = np.array([[r["LIVE"]["total_pct"], r["LIVE"]["max_dd_pct"], r["LIVE"]["sharpe"]] for r in rows])
        N = np.array([[r["N1"]["total_pct"], r["N1"]["max_dd_pct"], r["N1"]["sharpe"]] for r in rows])
        out[span] = {"wins": int((N[:, 0] > L[:, 0]).sum()),
                     "median": {"LIVE": np.median(L, axis=0).round(2).tolist(), "N1": np.median(N, axis=0).round(2).tolist()},
                     "worst": {"LIVE": L[:, 0].min().round(2), "N1": N[:, 0].min().round(2)},
                     "live": L[:, 0].round(1).tolist(), "n1": N[:, 0].round(1).tolist()}
    ok = all(out[s]["wins"] >= 8 and out[s]["median"]["N1"][1] >= out[s]["median"]["LIVE"][1] - 5.0 for s in out)
    res = {"spans": out, "candidate": bool(ok), "ref": "DECISIONS.md#ride-concentrate-declaration"}
    (RESULTS / "ride_concentrate.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
