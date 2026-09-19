from __future__ import annotations

import numpy as np
import pandas as pd

PAPER_LOOKBACKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)


def _channel_state(close: pd.DataFrame, lookback: int) -> np.ndarray:
    upper = close.rolling(lookback).max().shift(1).to_numpy(dtype=float)
    lower = close.rolling(lookback).min().shift(1).to_numpy(dtype=float)
    mid = (upper + lower) / 2.0
    px = close.to_numpy(dtype=float)

    n_rows, n_cols = px.shape
    out = np.zeros((n_rows, n_cols), dtype=float)
    held = np.zeros(n_cols, dtype=bool)
    stop = np.full(n_cols, np.nan)

    for i in range(n_rows):
        p, u, m = px[i], upper[i], mid[i]
        valid = np.isfinite(p) & np.isfinite(u) & np.isfinite(m)

        stop = np.where(held & valid, np.fmax(stop, m), stop)
        exiting = held & valid & (p < stop)
        held = held & ~exiting
        stop = np.where(exiting, np.nan, stop)

        entering = (~held) & valid & (p > u)
        held = held | entering
        stop = np.where(entering, m, stop)

        held = held & np.isfinite(p)
        out[i] = held
    return out


def conviction(close: pd.DataFrame, lookbacks: tuple[int, ...] = PAPER_LOOKBACKS
               ) -> pd.DataFrame:
    stack = np.mean([_channel_state(close, lb) for lb in lookbacks], axis=0)
    return pd.DataFrame(stack, index=close.index, columns=close.columns)


def monthly_snapshot(members: pd.DataFrame) -> pd.DataFrame:
    stamps = members.index.to_series().groupby(
        [members.index.year, members.index.month]).transform("min")
    snap = members.loc[members.index.isin(stamps.unique())]
    return snap.reindex(members.index, method="ffill").fillna(False)


def book(close: pd.DataFrame, members: pd.DataFrame, top_n: int = 20,
         lookbacks: tuple[int, ...] = PAPER_LOOKBACKS) -> pd.DataFrame:
    live = monthly_snapshot(members.reindex_like(close).fillna(False))
    conv = conviction(close, lookbacks).where(live, 0.0)
    return conv / float(top_n)


def paper_vol_scalar(net: pd.Series, target: float = 0.25, lookback: int = 90,
                     cap: float = 1.0, periods_per_year: int = 365) -> pd.Series:
    vol = net.rolling(lookback).std().shift(1) * np.sqrt(periods_per_year)
    scalar = (target / vol).replace([np.inf, -np.inf], np.nan)
    return scalar.clip(upper=cap).fillna(0.0)


def vol_targeted_book(raw: pd.DataFrame, unlevered_net: pd.Series,
                      target: float = 0.25, lookback: int = 90,
                      max_gross: float = 1.0, periods_per_year: int = 365
                      ) -> pd.DataFrame:
    vol = unlevered_net.rolling(lookback).std().shift(1) * np.sqrt(periods_per_year)
    scalar = (target / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = raw.abs().sum(axis=1)
    headroom = (max_gross / gross.where(gross > 0)).fillna(0.0)
    return raw.mul(np.minimum(scalar, headroom), axis=0)
