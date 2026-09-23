"""Donchian entry with an exit lookback that shortens as unrealised gain grows.

Not a take-profit: there is no ceiling, and a winner can run indefinitely.
Not a uniformly faster exit: a losing position keeps the full base lookback.
Only the distance a PROFITABLE position may retrace changes.

Declared at config/ratchet.yaml before any backtest was run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def position(close: pd.DataFrame, entry: int, base_bars: int,
             tight_bars: int, trigger_gain: float) -> pd.DataFrame:
    """Positions on `close`'s own clock.

    The floor is always the minimum close over the active lookback, taken on
    bars strictly BEFORE the current one, identical to signals.donchian. The
    only thing the ratchet changes is how many bars that minimum spans.

    `trigger_gain` of 0 or a `tight_bars` equal to `base_bars` reduces this to
    the plain rule, which is what the uniform controls use.
    """
    px = close.to_numpy(dtype=float)
    rows, cols = px.shape
    upper = close.rolling(entry).max().shift(1).to_numpy(dtype=float)
    # both candidate floors precomputed; the ratchet picks between them per name
    floor_base = close.rolling(base_bars).min().shift(1).to_numpy(dtype=float)
    floor_tight = close.rolling(tight_bars).min().shift(1).to_numpy(dtype=float)

    out = np.zeros((rows, cols), dtype=float)
    held = np.zeros(cols, dtype=bool)
    entry_px = np.full(cols, np.nan)
    tight = np.zeros(cols, dtype=bool)          # latched, never loosens

    for i in range(rows):
        p, u = px[i], upper[i]
        fb, ft = floor_base[i], floor_tight[i]
        valid = np.isfinite(p) & np.isfinite(u) & np.isfinite(fb) & np.isfinite(ft)

        # promote to the tight lookback once the gain threshold is cleared;
        # the latch means a subsequent retrace cannot widen the floor again
        gain = np.where(held & np.isfinite(entry_px) & (entry_px > 0),
                        p / entry_px - 1.0, -np.inf)
        tight |= held & (gain >= trigger_gain)

        floor = np.where(tight, ft, fb)
        exiting = held & valid & (p < floor)
        held &= ~exiting
        entry_px = np.where(exiting, np.nan, entry_px)
        tight &= ~exiting

        entering = (~held) & valid & (p > u)
        held |= entering
        entry_px = np.where(entering, p, entry_px)
        tight = np.where(entering, False, tight)

        held &= np.isfinite(p)
        out[i] = held
    return pd.DataFrame(out, index=close.index, columns=close.columns)
