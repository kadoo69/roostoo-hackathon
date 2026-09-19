from __future__ import annotations

import pandas as pd

from core.config import CACHE
from data import daily, universe

RULE = {"4h": "4h", "8h": "8h", "12h": "12h", "1d": "1D", "2d": "2D", "3d": "3D"}
FIELDS = ["open", "high", "low", "close", "quote_volume"]


def panel(interval: str) -> dict[str, pd.DataFrame]:
    path = CACHE / f"ohlc_{interval}.parquet"
    if path.exists():
        stacked = pd.read_parquet(path)
    else:
        hourly = universe.load_panel("1h")
        stacked = (
            hourly.set_index("open_time")
            .groupby("symbol")
            .resample(RULE[interval])
            .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                 close=("close", "last"), quote_volume=("quote_volume", "sum"))
            .reset_index()
            .dropna(subset=["close"])
        )
        stacked.to_parquet(path, index=False)
    return {f: stacked.pivot(index="open_time", columns="symbol", values=f)
            for f in FIELDS}


def members_at(interval: str, index: pd.Index) -> pd.DataFrame:
    p = daily.build()
    hourly = universe.load_panel("1h")
    base = universe.membership(hourly).reindex(p["close"].index).fillna(False)
    return universe.pit_top_n(p, base).reindex(index, method="ffill").fillna(False)


def atr(panel: dict[str, pd.DataFrame], lookback: int) -> pd.DataFrame:
    high, low, close = panel["high"], panel["low"], panel["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low).stack(),
                    (high - prev).abs().stack(),
                    (low - prev).abs().stack()], axis=1).max(axis=1).unstack()
    return tr.rolling(lookback).mean().shift(1)
