from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from core.config import CACHE, prereg
from data import binance, repairs
from venue.roostoo import PairSpec, RoostooClient

LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)USDT$")
STABLES = {
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "DAIUSDT", "USDPUSDT",
    "EURUSDT", "AEURUSDT", "USD1USDT", "XUSDUSDT", "PAXGUSDT", "USDEUSDT",
}


class UniverseError(RuntimeError):
    pass


def roostoo_specs(refresh: bool = False) -> dict[str, PairSpec]:
    cache = CACHE / "roostoo_specs.parquet"
    if cache.exists() and not refresh:
        frame = pd.read_parquet(cache)
        return {
            r.pair: PairSpec(r.pair, int(r.price_precision), int(r.amount_precision),
                             float(r.min_order), r.asset_type, bool(r.can_trade))
            for r in frame.itertuples()
        }
    specs = RoostooClient().exchange_info()
    cache.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([vars(s) for s in specs.values()]).to_parquet(cache, index=False)
    return specs


def tradable_symbols() -> dict[str, PairSpec]:
    excluded = set(prereg()["universe"]["exclude_asset_types"])
    return {
        s.binance_symbol: s
        for s in roostoo_specs().values()
        if s.can_trade and s.asset_type not in excluded
    }


def research_symbols() -> list[str]:
    ever = binance.listed_symbols_ever("USDT")
    return sorted(
        s for s in ever
        if not LEVERAGED.search(s) and s not in STABLES
    )


def working_set() -> list[str]:
    tradable = set(tradable_symbols())
    delisted = set(research_symbols()) - binance.currently_trading("USDT")
    return sorted(tradable | delisted)


def _panel_path(interval: str) -> object:
    return CACHE / f"panel_{interval}.parquet"


def build_panel(symbols: list[str], interval: str = "1h", workers: int = 8) -> pd.DataFrame:
    frames = binance.klines_many(symbols, interval=interval, workers=workers)
    missing = sorted(set(symbols) - set(frames))
    panel = pd.concat(frames.values(), ignore_index=True)
    panel = panel[["symbol", "open_time", "close_time", "open", "high", "low",
                   "close", "volume", "quote_volume", "trades"]]
    panel, applied = repairs.apply(panel, interval)
    panel.attrs["missing"] = missing
    panel.attrs["repairs"] = applied
    panel.to_parquet(_panel_path(interval), index=False)
    pd.DataFrame(applied).to_json(
        CACHE / f"repairs_{interval}.json", orient="records", indent=2)
    return panel


def load_panel(interval: str = "1h") -> pd.DataFrame:
    path = _panel_path(interval)
    if not path.exists():
        raise UniverseError(f"panel:{interval}:not_built")
    return pd.read_parquet(path)


def listing_windows(panel: pd.DataFrame) -> pd.DataFrame:
    return (
        panel.groupby("symbol")["open_time"]
        .agg(first_bar="min", last_bar="max", bars="count")
        .reset_index()
    )


def membership(panel: pd.DataFrame, min_history_bars: int | None = None,
               freq: str = "1D") -> pd.DataFrame:
    if min_history_bars is None:
        min_history_bars = prereg()["universe"]["min_history_bars"]

    counts = (
        panel.set_index("open_time")
        .groupby("symbol")
        .resample(freq)["close"]
        .count()
        .rename("bars")
        .reset_index()
    )
    wide = counts.pivot(index="open_time", columns="symbol", values="bars").fillna(0.0)
    cumulative = wide.cumsum()
    matured = cumulative.shift(1) >= min_history_bars
    live = wide > 0
    return (matured & live).fillna(False)


def spread_filter(specs: dict[str, PairSpec], prices: dict[str, float],
                  max_spread_bps: float | None = None) -> list[str]:
    if max_spread_bps is None:
        max_spread_bps = prereg()["universe"]["max_spread_bps"]
    return sorted(
        sym for sym, spec in specs.items()
        if spec.pair in prices and spec.spread_bps(prices[spec.pair]) <= max_spread_bps
    )


def pit_top_n(panel_daily: dict, base_members: pd.DataFrame,
              top_n: int | None = None, size_lookback: int | None = None,
              max_spread_bps: float | None = None) -> pd.DataFrame:
    cfg = prereg()["universe"]
    top_n = top_n or cfg["top_n"]
    size_lookback = size_lookback or cfg["size_lookback_days"]
    max_spread_bps = max_spread_bps or cfg["max_spread_bps"]

    from data import daily

    close = panel_daily["close"]
    adv = panel_daily["quote_volume"].rolling(size_lookback).median().shift(1)
    spread = daily.half_spread_bps(close, floor=daily.venue_tick_floor()) * 2.0

    excluded = [c for c in close.columns if c in STABLES or LEVERAGED.search(c)]
    eligible = base_members.reindex_like(close).fillna(False) & (spread <= max_spread_bps)
    eligible[excluded] = False
    ranked = adv.where(eligible).rank(axis=1, ascending=False)
    return (ranked <= top_n) & eligible


def live_top_n(panel_daily: dict, base_members: pd.DataFrame,
               top_n: int | None = None) -> pd.DataFrame:
    import json

    from core.config import CACHE

    top_n = top_n or prereg()["universe"]["top_n"]
    live = json.loads((CACHE / "top20_live.json").read_text())
    chosen = [r["symbol"] for r in live[:top_n]]
    close = panel_daily["close"]
    mask = pd.DataFrame(False, index=close.index, columns=close.columns)
    for sym in chosen:
        if sym in mask.columns:
            mask[sym] = True
    return mask & base_members.reindex_like(close).fillna(False)
