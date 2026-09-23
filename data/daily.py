from __future__ import annotations

import pandas as pd

from core.config import CACHE
from data import universe

FIELDS = ["close", "quote_volume", "volume"]


def _path() -> object:
    return CACHE / "daily.parquet"


def build(refresh: bool = False) -> dict[str, pd.DataFrame]:
    path = _path()
    if path.exists() and not refresh:
        stacked = pd.read_parquet(path)
    else:
        panel = universe.load_panel("1h")
        panel = panel.set_index("open_time")
        agg = (
            panel.groupby("symbol")
            .resample("1D")
            .agg(close=("close", "last"),
                 quote_volume=("quote_volume", "sum"),
                 volume=("volume", "sum"),
                 bars=("close", "count"))
            .reset_index()
        )
        stacked = agg[agg["bars"] > 0].drop(columns="bars")
        stacked.to_parquet(path, index=False)

    return {
        field: stacked.pivot(index="open_time", columns="symbol", values=field)
        for field in FIELDS
    }


def tick_size(close: pd.DataFrame, window: int = 90) -> pd.DataFrame:
    steps = close.diff().abs()
    steps = steps.where(steps > 0)
    return steps.rolling(window, min_periods=5).min().shift(1)


def half_spread_bps(close: pd.DataFrame, window: int = 90,
                    floor: pd.Series | None = None) -> pd.DataFrame:
    ticks = tick_size(close, window)
    if floor is not None:
        ticks = ticks.clip(lower=floor.reindex(ticks.columns), axis=1)
    return (ticks / close * 1e4 / 2.0).clip(upper=500.0)


def venue_tick_floor() -> pd.Series:
    from data import universe

    return pd.Series({
        s.binance_symbol: s.tick for s in universe.roostoo_specs().values()
    })
