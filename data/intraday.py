from __future__ import annotations

import pandas as pd

from core.config import CACHE
from data import daily, universe

RULE = {"4h": "4h", "8h": "8h", "12h": "12h", "1d": "1D", "2d": "2D", "3d": "3D"}


def panel(interval: str, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    path = CACHE / f"panel_{interval}_wide.parquet"
    if path.exists():
        stacked = pd.read_parquet(path)
    else:
        hourly = universe.load_panel("1h")
        if symbols is not None:
            hourly = hourly[hourly["symbol"].isin(symbols)]
        agg = (
            hourly.set_index("open_time")
            .groupby("symbol")
            .resample(RULE[interval])
            .agg(close=("close", "last"), quote_volume=("quote_volume", "sum"))
            .reset_index()
            .dropna(subset=["close"])
        )
        stacked = agg
        stacked.to_parquet(path, index=False)
    return {
        f: stacked.pivot(index="open_time", columns="symbol", values=f)
        for f in ["close", "quote_volume"]
    }


def members_at(interval: str, index: pd.Index) -> pd.DataFrame:
    p = daily.build()
    hourly = universe.load_panel("1h")
    base = universe.membership(hourly).reindex(p["close"].index).fillna(False)
    pit = universe.pit_top_n(p, base)
    return pit.reindex(index, method="ffill").fillna(False)
