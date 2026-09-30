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


def breakdown_position(close: pd.DataFrame, entry: int, exit_lb: int) -> pd.DataFrame:
    """Short channel state: set when the close breaks below the prior `entry`-bar low,
    cleared when it closes above the prior `exit_lb`-bar high, exit checked first.

    The S1 sleeve's rule, moved here from gates/competition_wf.py so the live book and the
    backtest share one implementation. DECISIONS.md#short-paper-books
    """
    lower = close.rolling(entry).min().shift(1).to_numpy(dtype=float)
    upper = close.rolling(exit_lb).max().shift(1).to_numpy(dtype=float)
    px = close.to_numpy(dtype=float)
    out = np.zeros(px.shape, dtype=bool)
    state = np.zeros(px.shape[1], dtype=bool)
    for i in range(len(px)):
        valid = np.isfinite(px[i]) & np.isfinite(lower[i]) & np.isfinite(upper[i])
        state = np.where(state & valid & (px[i] > upper[i]), False, state)
        state = state | (valid & (px[i] < lower[i]))
        state &= np.isfinite(px[i])
        out[i] = state
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def bear_regime(btc_close: pd.Series, bars: int) -> pd.Series:
    """True where the close is below its own `bars`-bar mean, the S1 regime flag."""
    return btc_close < btc_close.rolling(bars).mean()


def breadth_short_regime(close: pd.DataFrame, momentum_bars: int, breadth_max: float,
                         members: pd.DataFrame | None = None) -> pd.Series:
    """True where fewer than `breadth_max` of the pool have positive `momentum_bars` momentum.
    DECISIONS.md#lowtf-breadth-shorts-declaration"""
    mom = close / close.shift(momentum_bars) - 1.0
    ok = mom.notna() if members is None else (mom.notna() & members.reindex_like(mom).fillna(False).astype(bool))
    breadth = (mom > 0).where(ok).mean(axis=1)
    return (breadth < breadth_max) & breadth.notna()
