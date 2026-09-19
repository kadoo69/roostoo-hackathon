from __future__ import annotations

import pandas as pd

from bot.feed import bar_frame
from bot.settings import Settings
from venue.roostoo import PairSpec

LEVERAGED = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
STABLES = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "DAIUSDT", "USDPUSDT",
           "EURUSDT", "AEURUSDT", "USD1USDT", "XUSDUSDT", "PAXGUSDT", "USDEUSDT"}


def venue_symbols(specs: dict[str, PairSpec], exclude_types=("stock",)) -> list[str]:
    return sorted(
        s.binance_symbol for s in specs.values()
        if s.can_trade and s.asset_type not in exclude_types
        and s.binance_symbol not in STABLES
        and not any(s.binance_symbol.endswith(x) for x in LEVERAGED)
    )


def binance_ranking(quote: str = "USDT") -> pd.Series:
    import requests
    from data.binance import REST
    r = requests.get(f"{REST}/ticker/24hr", timeout=30)
    r.raise_for_status()
    f = pd.DataFrame(r.json())
    f = f[f["symbol"].str.endswith(quote)]
    f["quoteVolume"] = pd.to_numeric(f["quoteVolume"], errors="coerce")
    f = f[~f["symbol"].isin(STABLES)]
    f = f[~f["symbol"].str.endswith(LEVERAGED)]
    return f.set_index("symbol")["quoteVolume"].sort_values(ascending=False)


def median_dollar_volume(symbols: list[str], days: int = 30) -> pd.Series:
    frames = bar_frame(symbols, "1d", days + 2)
    out = {}
    for s, f in frames.items():
        if len(f) >= days // 2:
            out[s] = float(f["quote_volume"].tail(days).median())
    return pd.Series(out).sort_values(ascending=False)


def select(settings: Settings, specs: dict[str, PairSpec]) -> dict:
    venue = venue_symbols(specs)
    broad = binance_ranking(settings.quote)
    pool = list(broad.head(max(settings.top_n_pool * 6, 120)).index)
    adv = median_dollar_volume(sorted(set(pool) | set(venue)))
    ranked = adv.sort_values(ascending=False)
    top_pool = list(ranked.head(settings.top_n_pool).index)
    tradable = [s for s in top_pool if s in venue]
    return {
        "pool_size": settings.top_n_pool,
        "pool": top_pool,
        "venue_listed": len(venue),
        "selected": tradable,
        "n_selected": len(tradable),
        "adv_usd": {s: round(float(ranked[s]), 2) for s in tradable},
    }
