from __future__ import annotations

import numpy as np
import pandas as pd

from signals.base import cross_sectional_weights, declaration


def _validate_pair(name: str, pair: tuple[int, int]) -> None:
    grid = [tuple(p) for p in declaration(name).extras["pair_grid"]]
    if tuple(pair) not in grid:
        raise ValueError(f"{name}:{pair}:outside_declared_grid")


def _directional(signal: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    live = signal.where(members.reindex_like(signal).fillna(False))
    count = live.notna().sum(axis=1).replace(0, np.nan)
    return live.div(count, axis=0).fillna(0.0)


def sma_crossover(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                  pair: tuple[int, int] = (20, 50)) -> pd.DataFrame:
    _validate_pair("sma_crossover", pair)
    fast, slow = pair
    close = panel["close"]
    signal = np.sign(close.rolling(fast).mean() - close.rolling(slow).mean())
    return _directional(signal, members)


def sma_distance(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                 lookback: int = 50) -> pd.DataFrame:
    decl = declaration("sma_distance")
    if lookback not in decl.lookback_grid:
        raise ValueError(f"sma_distance:{lookback}:outside_declared_grid")
    close = panel["close"]
    score = close / close.rolling(lookback).mean() - 1.0
    return cross_sectional_weights(score, members, decl.quantile, min_members=8)


def volume_confirmed_trend(panel: dict[str, pd.DataFrame], members: pd.DataFrame,
                           volume_lookback: int = 10,
                           pair: tuple[int, int] = (20, 50)) -> pd.DataFrame:
    decl = declaration("volume_confirmed_trend")
    _validate_pair("volume_confirmed_trend", pair)
    if volume_lookback not in decl.extras["volume_lookback_grid"]:
        raise ValueError(f"volume_confirmed_trend:{volume_lookback}:outside_declared_grid")

    fast, slow = pair
    close, qv = panel["close"], panel["quote_volume"]
    trend = np.sign(close.rolling(fast).mean() - close.rolling(slow).mean())
    expanding = qv.rolling(volume_lookback).mean() > qv.rolling(slow).mean()
    return _directional(trend.where(expanding, 0.0), members)


REGISTRY = {
    "sma_crossover": sma_crossover,
    "sma_distance": sma_distance,
    "volume_confirmed_trend": volume_confirmed_trend,
}
