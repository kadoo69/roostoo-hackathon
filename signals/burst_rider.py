"""Burst rider: buy a coin after a 15-minute burst, book at a fixed gain, or leave after a set time.

A position opens at the close of a bar whose 3-bar return is at least `thresh_pct`, in at most `n`
names at 1/n each, one entry per coin per `cooldown_bars`. It closes at the first later bar whose
high reaches `tp_pct` above the entry close, or after `hold_bars`. The live book sells at that bar's
close, not at the target, so live and simulated results understate the resting-limit fill the
study assumed. Operator override of a failed test: DECISIONS.md#burst-rider-override-2026-09-30
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def weights(close: pd.DataFrame, high: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    thresh = float(cfg.get("thresh_pct", 2.0)) / 100
    tp = float(cfg.get("tp_pct", 2.0)) / 100
    hold = int(cfg.get("hold_bars", 48))
    n = int(cfg.get("n", 3))
    cool = int(cfg.get("cooldown_bars", 12))
    c = close.to_numpy(dtype=float)
    h = high.reindex_like(close).to_numpy(dtype=float)
    r3 = close.to_numpy(dtype=float) / close.shift(3).to_numpy(dtype=float) - 1.0
    T, N = c.shape
    out = np.zeros((T, N))
    entry = np.full(N, np.nan)
    age = np.zeros(N, dtype=int)
    last = np.full(N, -10**9)
    for t in range(T):
        held = ~np.isnan(entry)
        for j in np.flatnonzero(held):
            age[j] += 1
            if (np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + tp)) or age[j] >= hold:
                entry[j] = np.nan
        held = ~np.isnan(entry)
        free = n - int(held.sum())
        if free > 0:
            cand = [(r3[t, j], j) for j in range(N)
                    if not held[j] and np.isfinite(r3[t, j]) and r3[t, j] >= thresh and t - last[j] >= cool]
            for _, j in sorted(cand, reverse=True)[:free]:
                entry[j], age[j], last[j] = c[t, j], 0, t
        out[t] = np.where(~np.isnan(entry), 1.0 / n, 0.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)
