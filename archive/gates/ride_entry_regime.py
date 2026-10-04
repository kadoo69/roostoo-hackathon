"""Pullback entries and trend-regime rotation against the live 2-slot ride, in an explicit bar-level book.

Declared before any number: config/ride_entry_regime.yaml, DECISIONS.md#ride-entry-regime-declaration
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

FEE = 0.0005
ARMS = {"B2": (None, False), "PB05": (0.5, False), "PB10": (1.0, False), "RG": (None, True)}
TESTS = {"pullback": ["PB05", "PB10"], "regime_rotation": ["RG"]}


def book(c: np.ndarray, h: np.ndarray, lo: np.ndarray, z: np.ndarray, s: np.ndarray, dvol: np.ndarray,
         trend: np.ndarray, cfg: dict, pull: float | None, rotate: bool) -> np.ndarray:
    n, hold, cool = int(cfg["n"]), int(cfg["hold_bars"]), int(cfg["cooldown_bars"])
    k, tpk = float(cfg["sigma_k"]), float(cfg["tp_vol_k"])
    T, N = c.shape
    cash, eq = 1.0, np.ones(T)
    pos: dict[int, list] = {}
    pend: dict[int, list] = {}
    last = np.full(N, -10**9)
    for t in range(T):
        for j in list(pos):
            q, px, tp, age = pos[j]
            age += 1
            tgt = px * (1 + tp)
            if np.isfinite(h[t, j]) and h[t, j] >= tgt:
                cash += q * tgt * (1 - FEE)
                del pos[j]
            elif age >= hold and np.isfinite(c[t, j]):
                cash += q * c[t, j] * (1 - FEE)
                del pos[j]
            else:
                pos[j][3] = age
        for j in list(pend):
            lim, alloc, ttl, tp = pend[j]
            if np.isfinite(lo[t, j]) and lo[t, j] <= lim:
                q = alloc * (1 - FEE) / lim
                pos[j] = [q, lim, tp, 0]
                cash -= alloc
                del pend[j]
            elif ttl <= 1:
                del pend[j]
            else:
                pend[j][2] = ttl - 1
        value = cash + sum(q * (c[t, j] if np.isfinite(c[t, j]) else px) for j, (q, px, _, _) in pos.items())
        reserved = sum(v[1] for v in pend.values())
        trig = sorted([(z[t, j], j) for j in range(N) if j not in pos and j not in pend and np.isfinite(z[t, j])
                       and np.isfinite(c[t, j]) and np.isfinite(dvol[t, j]) and z[t, j] >= k and t - last[j] >= cool],
                      reverse=True)
        if rotate and trig and trend[t] and len(pos) + len(pend) >= n and pos:
            ret = {j: c[t, j] / px - 1 for j, (q, px, _, age) in pos.items() if age >= 12 and np.isfinite(c[t, j])}
            if ret:
                jw = min(ret, key=ret.get)
                if ret[jw] < 0:
                    cash += pos[jw][0] * c[t, jw] * (1 - FEE)
                    del pos[jw]
        free = n - len(pos) - len(pend)
        for _, j in trig[:max(free, 0)]:
            alloc = min(value / n, cash - reserved)
            if alloc <= value * 0.05:
                break
            last[j] = t
            tp = tpk * dvol[t, j]
            if pull is None:
                pos[j] = [alloc * (1 - FEE) / c[t, j], c[t, j], tp, 0]
                cash -= alloc
            else:
                pend[j] = [c[t, j] * (1 - pull * s[t, j]), alloc, 6, tp]
                reserved += alloc
        eq[t] = cash + sum(q * (c[t, j] if np.isfinite(c[t, j]) else px) for j, (q, px, _, _) in pos.items())
    return eq


def main() -> int:
    cfg = next(iter(yaml.safe_load((ROOT / "config" / "competition_z25.yaml").read_text())["adaptive"]["burst_arms"].values()))
    start = pd.Timestamp("2026-08-30", tz="UTC")
    nbar = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta("5min")) + 10
    fr = feed.bar_frame(list(POOL), "5m", nbar)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    close, high, low = col("close").loc[start:], col("high").loc[start:], col("low").loc[start:]
    specs = ru.tradable_symbols()
    keep = [s for s in close.columns if s in specs]
    close, high, low = close[keep], high[keep].reindex_like(close[keep]), low[keep].reindex_like(close[keep])
    r3 = close / close.shift(3) - 1.0
    sb = int(cfg["sigma_bars"])
    sd = r3.rolling(sb, min_periods=sb // 2).std().shift(1)
    z, s, dvol = (r3 / sd).to_numpy(float), sd.to_numpy(float), (sd * np.sqrt(96)).to_numpy(float)
    r864 = close / close.shift(864) - 1.0
    trend = (((r864 > 0).sum(axis=1) / r864.notna().sum(axis=1).clip(lower=1) >= 0.6) & (r864.mean(axis=1) > 0.03)).to_numpy()
    end = close.index[-1]
    windows = {"W1": (pd.Timestamp("2026-09-05", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")),
               "W2": (pd.Timestamp("2026-09-19", tz="UTC"), end), "last_3d": (end - pd.Timedelta("3D"), end)}
    res = {}
    for arm, (pull, rot) in ARMS.items():
        res[arm] = {}
        for wn, (a, b) in windows.items():
            m = (close.index >= a) & (close.index <= b)
            eq = book(close.loc[m].to_numpy(float), high.loc[m].to_numpy(float), low.loc[m].to_numpy(float),
                      z[m], s[m], dvol[m], trend[m], cfg, pull, rot)
            res[arm][wn] = {"total_pct": round(float(eq[-1] - 1) * 100, 2),
                            "max_dd_pct": round(float((eq / np.maximum.accumulate(eq) - 1).min()) * 100, 2),
                            "trend_on_share": round(float(trend[m].mean()), 2)}
    base_worst = min(v["total_pct"] for v in res["B2"].values())
    verdict = {}
    for test, cands in TESTS.items():
        key = {a: (min(v["total_pct"] for v in res[a].values()), min(v["max_dd_pct"] for v in res[a].values())) for a in cands}
        best = max(cands, key=lambda a: key[a])
        rec = (res[best]["last_3d"]["total_pct"] > res["B2"]["last_3d"]["total_pct"]
               and any(res[best][w]["total_pct"] > res["B2"][w]["total_pct"] for w in ("W1", "W2"))
               and key[best][0] >= base_worst)
        verdict[test] = {"best": best, "worst_window": key, "recommended": bool(rec)}
    out = {"windows": {k: [str(v[0]), str(v[1])] for k, v in windows.items()}, "arms": res, "verdict": verdict,
           "ref": "DECISIONS.md#ride-entry-regime-declaration"}
    (RESULTS / "ride_entry_regime.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
