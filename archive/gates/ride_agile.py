"""Which loosened ride to deploy: sigma 2.5 with the +5% / 24 h exits, or nearer take-profits and shorter holds.

Declared before any number: config/ride_agile.yaml, DECISIONS.md#ride-agile-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_scaled_entry import weights
from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr

ARMS = {"Z3": (3.0, 5.0, 288), "A25": (2.5, 5.0, 288), "B25": (2.5, 3.0, 144), "C25": (2.5, 2.0, 72)}


def main() -> int:
    base = next(iter(yaml.safe_load((ROOT / "config" / "ride_z3_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp("2026-09-03", tz="UTC")
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    close, high = close[list(tick.index)], high[list(tick.index)]
    r3 = close / close.shift(3) - 1.0
    sb = int(base["sigma_bars"])
    z = (r3 / r3.rolling(sb, min_periods=sb // 2).std().shift(1)).to_numpy(dtype=float)
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end), "last_3d": (end - pd.Timedelta("3D"), end)}
    res = {}
    for arm, (k, tp, hold) in ARMS.items():
        cfg = dict(base, sigma_k=k, tp_pct=tp, hold_bars=hold)
        res[arm] = {}
        for wn, (lo, hi_) in windows.items():
            m = (close.index >= lo) & (close.index <= hi_)
            cl, hi = close.loc[m], high.loc[m]
            w = weights(cl, hi, z[m], cfg, k, 1.0, None)
            net, _ = lwr.simulate(cl, w, tick, True)
            eq = (1 + net).cumprod()
            starts = (w > 0) & (w.shift(1).fillna(0) == 0)
            days = (cl.index[-1] - cl.index[0]) / pd.Timedelta("1D")
            res[arm][wn] = {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
                            "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2),
                            "entries_per_day": round(float(starts.to_numpy().sum()) / days, 1),
                            "mean_gross": round(float(w.sum(axis=1).mean()), 2)}
    cands = ["A25", "B25", "C25"]
    key = {a: (min(v["total_pct"] for v in res[a].values()), min(v["max_dd_pct"] for v in res[a].values())) for a in cands}
    pick = max(cands, key=lambda a: key[a])
    losing = {a: int(np.sum([v["total_pct"] < 0 for v in res[a].values()])) for a in cands}
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "worst_window": key,
           "pick": pick, "windows_losing": losing, "tell_operator_first": all(x >= 2 for x in losing.values()),
           "ref": "DECISIONS.md#ride-agile-declaration"}
    (RESULTS / "ride_agile.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
