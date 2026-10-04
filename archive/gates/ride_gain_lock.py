"""Gain locks that arm after +1 dvol against the live ride (z >= 2.5, V2 targets, 24 h hold).

Declared before any number: config/ride_gain_lock.yaml, DECISIONS.md#ride-gain-lock-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_z3_wide import POOL
from bot import feed
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr

ARMS = {"L24": None, "BE1": "be", "LK1": "lock", "TR1": "trail"}


def weights(close: pd.DataFrame, high: pd.DataFrame, z: np.ndarray, dvol: np.ndarray, cfg: dict,
            mode: str | None) -> pd.DataFrame:
    hold = int(cfg["hold_bars"])
    n, cool, k, tpk = int(cfg["n"]), int(cfg["cooldown_bars"]), float(cfg["sigma_k"]), float(cfg["tp_vol_k"])
    c = close.to_numpy(dtype=float)
    h = high.reindex_like(close).to_numpy(dtype=float)
    T, N = c.shape
    out = np.zeros((T, N))
    entry, tp, dv, peak = np.full(N, np.nan), np.full(N, np.nan), np.full(N, np.nan), np.full(N, np.nan)
    armed = np.zeros(N, dtype=bool)
    age, last = np.zeros(N, dtype=int), np.full(N, -10**9)
    for t in range(T):
        for j in np.flatnonzero(~np.isnan(entry)):
            age[j] += 1
            hit = np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + tp[j])
            if np.isfinite(c[t, j]):
                peak[j] = max(peak[j], c[t, j])
            lock = False
            if mode and armed[j] and np.isfinite(c[t, j]):
                level = {"be": entry[j], "lock": entry[j] * (1 + 0.5 * dv[j]), "trail": peak[j] * (1 - dv[j])}[mode]
                lock = c[t, j] <= level
            if mode and np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + dv[j]):
                armed[j] = True
            if hit or lock or age[j] >= hold:
                entry[j] = tp[j] = dv[j] = peak[j] = np.nan
                armed[j] = False
        held = ~np.isnan(entry)
        free = n - int(held.sum())
        if free > 0:
            cand = [(z[t, j], j) for j in range(N) if not held[j] and np.isfinite(z[t, j]) and np.isfinite(c[t, j])
                    and np.isfinite(dvol[t, j]) and z[t, j] >= k and t - last[j] >= cool]
            for _, j in sorted(cand, reverse=True)[:free]:
                entry[j], age[j], last[j], tp[j] = c[t, j], 0, t, tpk * dvol[t, j]
                dv[j], peak[j], armed[j] = dvol[t, j], c[t, j], False
        out[t] = np.where(~np.isnan(entry), 1.0 / n, 0.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp("2026-09-03", tz="UTC")
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high = col("close").loc[start:], col("high").loc[start:]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    close, high = close[list(tick.index)], high[list(tick.index)]
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z, dvol = (r3 / sd).to_numpy(dtype=float), (sd * np.sqrt(96)).to_numpy(dtype=float)
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end), "last_3d": (end - pd.Timedelta("3D"), end)}
    res = {}
    for arm, mode in ARMS.items():
        res[arm] = {}
        for wn, (lo, hi_) in windows.items():
            m = (close.index >= lo) & (close.index <= hi_)
            cl, hi = close.loc[m], high.loc[m]
            w = weights(cl, hi, z[m], dvol[m], cfg, mode)
            net, _ = lwr.simulate(cl, w, tick, True)
            eq = (1 + net).cumprod()
            starts = (w > 0) & (w.shift(1).fillna(0) == 0)
            days = (cl.index[-1] - cl.index[0]) / pd.Timedelta("1D")
            res[arm][wn] = {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
                            "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2),
                            "entries_per_day": round(float(starts.to_numpy().sum()) / days, 1),
                            "mean_gross": round(float(w.sum(axis=1).mean()), 2)}
    cands = ["BE1", "LK1", "TR1"]
    key = {a: (min(v["total_pct"] for v in res[a].values()), min(v["max_dd_pct"] for v in res[a].values())) for a in cands}
    best = max(cands, key=lambda a: key[a])
    base_worst = min(v["total_pct"] for v in res["L24"].values())
    rec = (res[best]["last_3d"]["total_pct"] > res["L24"]["last_3d"]["total_pct"]
           and any(res[best][w]["total_pct"] > res["L24"][w]["total_pct"] for w in ("W1", "W2"))
           and key[best][0] >= base_worst)
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "best": best,
           "worst_window": key, "recommended": bool(rec), "ref": "DECISIONS.md#ride-gain-lock-declaration"}
    (RESULTS / "ride_gain_lock.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
