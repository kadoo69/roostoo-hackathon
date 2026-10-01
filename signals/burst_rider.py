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


def live_step(close: pd.DataFrame, high: pd.DataFrame, cfg: dict, held: dict[str, list],
              last: dict[str, str]) -> tuple[dict[str, list], dict[str, str], dict[str, float]]:
    """One decision of the ride at the last bar of `close`, from the book's real ride positions.

    A live book cannot follow `weights()`: its path fills the slots with entries the book never
    took (blocked at a start, or reshuffled as the replay window moves), and those ghost slots stop
    every new entry (`DECISIONS.md#ride-ghost-slots-2026-10-01`). Here the slots are the positions
    the book holds. `held[s] = [entry bar, entry close]`, `last[s]` = the bar of the last entry
    (cooldown). Ages count bars by time, so the exit after downtime uses every bar since the entry.
    Same rule as `weights()`, bar for bar (`tests/test_burst_rider_live.py`).
    """
    thresh = float(cfg.get("thresh_pct", 2.0)) / 100
    tp = float(cfg.get("tp_pct", 2.0)) / 100
    hold = int(cfg.get("hold_bars", 48))
    n = int(cfg.get("n", 3))
    cool = int(cfg.get("cooldown_bars", 12))
    t = close.index[-1]
    step = close.index[-1] - close.index[-2]
    hi = high.reindex_like(close)
    keep = {}
    for s, (at, px) in held.items():
        at = pd.Timestamp(at)
        since = hi[s].loc[hi.index > at] if s in hi else pd.Series(dtype=float)
        hit = bool((since >= float(px) * (1 + tp)).any())
        if not hit and round((t - at) / step) < hold:
            keep[s] = [str(at), float(px)]
    new_last = dict(last)
    free = n - len(keep)
    if free > 0 and len(close) > 3:
        r3 = close.iloc[-1] / close.iloc[-4] - 1.0
        cand = []
        for s, r in r3.items():
            if s in keep or not np.isfinite(r) or r < thresh:
                continue
            if s in last and round((t - pd.Timestamp(last[s])) / step) < cool:
                continue
            cand.append((float(r), close.columns.get_loc(s), s))
        for _, _, s in sorted(cand, reverse=True)[:free]:
            keep[s] = [str(t), float(close[s].iloc[-1])]
            new_last[s] = str(t)
    floor = t - step * (cool + hold)
    new_last = {s: at for s, at in new_last.items() if s in keep or pd.Timestamp(at) > floor}
    return keep, new_last, {s: 1.0 / n for s in keep}
