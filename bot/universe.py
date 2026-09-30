from __future__ import annotations

import pandas as pd

from bot.feed import bar_frame
from bot.settings import Settings
from data.universe import STABLES as DATA_STABLES
from venue.roostoo import PairSpec

LEVERAGED = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
STABLES = DATA_STABLES


def venue_symbols(specs: dict[str, PairSpec], exclude_types=("stock",)) -> list[str]:
    return sorted(
        s.binance_symbol for s in specs.values()
        if s.can_trade and s.asset_type not in exclude_types
        and s.binance_symbol not in STABLES
        and not any(s.binance_symbol.endswith(x) for x in LEVERAGED)
    )


def binance_ranking(quote: str = "USDT") -> pd.Series:
    from data.binance import rest_get
    r = rest_get("/ticker/24hr", timeout=30)
    r.raise_for_status()
    f = pd.DataFrame(r.json())
    f = f[f["symbol"].str.endswith(quote)]
    f["quoteVolume"] = pd.to_numeric(f["quoteVolume"], errors="coerce")
    f = f[~f["symbol"].isin(STABLES)]
    f = f[~f["symbol"].str.endswith(LEVERAGED)]
    return f.set_index("symbol")["quoteVolume"].sort_values(ascending=False)


def median_dollar_volume(symbols: list[str], days: int = 30, max_stale_days: int = 2) -> pd.Series:
    """30-day median daily dollar volume of symbols still printing bars. A halted pair keeps its
    last month of volume forever, so without the freshness check TONUSDT, halted on Binance since
    2026-06-30, ranked in the top 30 for three months. DECISIONS.md#book-diagnosis-2026-09-23"""
    frames = bar_frame(symbols, "1d", days + 2)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=max_stale_days)
    out = {}
    for s, f in frames.items():
        if len(f) >= days // 2 and pd.Timestamp(f["open_time"].iloc[-1]) >= cutoff:
            out[s] = float(f["quote_volume"].tail(days).median())
    return pd.Series(out).sort_values(ascending=False)


def select(settings: Settings, specs: dict[str, PairSpec]) -> dict:
    """`binance_top` (default): the top `top_n_pool` of Binance by 30-day median dollar volume,
    intersected with Roostoo. `venue_all`: every tradable Roostoo crypto pair still printing
    Binance bars, the whole venue pool. DECISIONS.md#wide-pool-book-declaration"""
    venue = venue_symbols(specs)
    if getattr(settings, "universe_mode", "binance_top") == "venue_all":
        adv = median_dollar_volume(venue)
        tradable = list(adv.index)
        return {"pool_size": len(tradable), "pool": tradable, "venue_listed": len(venue),
                "selected": tradable, "n_selected": len(tradable), "mode": "venue_all",
                "adv_usd": {s: round(float(adv[s]), 2) for s in tradable}}
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
