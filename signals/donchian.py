from __future__ import annotations

import numpy as np
import pandas as pd


def position(close: pd.DataFrame, entry: int, exit_mode: str = "midpoint",
             exit_lb: int | None = None) -> pd.DataFrame:
    upper = close.rolling(entry).max().shift(1).to_numpy(dtype=float)
    lower = close.rolling(entry).min().shift(1).to_numpy(dtype=float)
    mid = (upper + lower) / 2.0
    floor = (close.rolling(exit_lb or entry).min().shift(1).to_numpy(dtype=float)
             if exit_mode == "lowchannel" else mid)
    px = close.to_numpy(dtype=float)

    rows, cols = px.shape
    out = np.zeros((rows, cols), dtype=float)
    held = np.zeros(cols, dtype=bool)
    stop = np.full(cols, np.nan)

    ratchet = exit_mode == "midpoint"
    for i in range(rows):
        p, u, f = px[i], upper[i], floor[i]
        valid = np.isfinite(p) & np.isfinite(u) & np.isfinite(f)

        stop = np.where(held & valid, np.fmax(stop, f) if ratchet else f, stop)
        exiting = held & valid & (p < stop)
        held &= ~exiting
        stop = np.where(exiting, np.nan, stop)

        entering = (~held) & valid & (p > u)
        held |= entering
        stop = np.where(entering, f, stop)

        held &= np.isfinite(p)
        out[i] = held
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def book(close: pd.DataFrame, members: pd.DataFrame, entry: int,
         exit_mode: str = "midpoint", exit_lb: int | None = None,
         top_n: int = 20) -> pd.DataFrame:
    live = members.reindex_like(close).fillna(False)
    return position(close, entry, exit_mode, exit_lb).where(live, 0.0) / float(top_n)
