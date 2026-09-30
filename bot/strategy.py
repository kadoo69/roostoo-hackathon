from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from bot.settings import Settings
from signals import donchian

REPLAY_BARS = 150
REGIME_SYMBOL = "BTCUSDT"


@dataclass
class Channel:
    symbol: str
    upper: float
    floor: float
    close: float
    bars: int
    held: bool
    action: str

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(closes: pd.Series, held: bool, settings: Settings) -> Channel | None:
    s = closes.dropna()
    need = max(settings.entry_bars, settings.exit_bars) + 1
    if len(s) < need:
        return None
    prior = s.iloc[:-1]
    upper = float(prior.tail(settings.entry_bars).max())
    floor = float(prior.tail(settings.exit_bars).min())
    close = float(s.iloc[-1])

    action = "hold" if held else "flat"
    if held and close < floor:
        action = "exit"
        held = False
    elif not held and close > upper:
        action = "enter"
        held = True
    return Channel(symbol=str(s.name), upper=upper, floor=floor, close=close,
                   bars=len(s), held=held, action=action)


def evaluate_book(matrix: pd.DataFrame, state: dict[str, bool],
                  settings: Settings) -> dict[str, Channel]:
    out = {}
    for sym in matrix.columns:
        ch = evaluate(matrix[sym], bool(state.get(sym, False)), settings)
        if ch is not None:
            out[sym] = ch
    return out


def replay_book(matrix: pd.DataFrame, settings: Settings) -> dict[str, Channel]:
    """Channel state derived from the bars themselves, not stepped from a saved flag.

    `evaluate` advances a persisted flag by ONE bar, the latest. A bar close the
    process never saw - downtime, a crash, a book started mid-trend, a name that
    joined the universe after its breakout - was therefore lost for good, and the
    book sat flat through a trend the backtest held. On 2026-09-23 donchian_4h
    was missing 3 of the 19 names its rule held and donchian_4h_cushion 12.

    This replays the backtest's own `signals.donchian.position` over the matrix to
    get the state at the previous bar, then applies `evaluate` to the latest bar,
    so `action` still reads enter, exit, hold or flat. Over REPLAY_BARS the replay
    matched the full-history state on every one of 107,391 sampled cells at 4h
    and 1h. DECISIONS.md#live-validation-2026-09-23.
    """
    pos = donchian.position(matrix, settings.entry_bars, "lowchannel", settings.exit_bars)
    prev = pos.iloc[-2] if len(pos) > 1 else pos.iloc[-1] * 0.0
    out = {}
    for sym in matrix.columns:
        ch = evaluate(matrix[sym], bool(prev.get(sym, 0.0) > 0.5), settings)
        if ch is not None:
            out[sym] = ch
    return out


def short_bars_needed(settings: Settings) -> int:
    """Bars a short book must fetch: the regime mean plus its latest bar, or the replay."""
    if not settings.shorts_enabled:
        return 0
    return max(REPLAY_BARS, int(settings.short["regime_bars"]) + 2)


def replay_short_book(matrix: pd.DataFrame, settings: Settings) -> dict[str, bool]:
    """Breakdown state at the latest bar, replayed from the bars as the long channel is.

    The rule is `signals.donchian.breakdown_position`, the S1 sleeve's own, so the live
    book and gates/short_paper_books.py cannot drift apart. DECISIONS.md#short-paper-books
    """
    if not settings.shorts_enabled or matrix.empty:
        return {}
    cfg = settings.short
    pos = donchian.breakdown_position(matrix, int(cfg["entry_bars"]), int(cfg["exit_bars"]))
    last = pos.iloc[-1]
    return {str(s): bool(last[s]) for s in matrix.columns if bool(last[s])}


def short_regime(btc_close: pd.Series, settings: Settings, matrix: pd.DataFrame | None = None) -> dict:
    """Whether the book may open or hold shorts at the latest bar, with the numbers behind it.

    `breadth_below` reads the pool itself: shorts are on while fewer than `breadth_max` of the
    names have positive momentum. DECISIONS.md#lowtf-breadth-shorts-declaration
    """
    cfg = settings.short
    if cfg.get("regime") == "breadth_below":
        if matrix is None or matrix.empty:
            return {"on": False, "reason": "no_matrix"}
        mb = int(cfg.get("momentum_bars", settings.momentum_bars))
        mom = matrix.iloc[-1] / matrix.shift(mb).iloc[-1] - 1.0
        mom = mom.dropna()
        if mom.empty:
            return {"on": False, "reason": "no_momentum"}
        breadth = float((mom > 0).mean())
        return {"on": breadth < float(cfg["breadth_max"]), "breadth": round(breadth, 3),
                "breadth_max": float(cfg["breadth_max"]), "names": int(len(mom))}
    bars = int(cfg["regime_bars"])
    s = btc_close.dropna()
    if cfg.get("regime") != "btc_below_mean":
        raise ValueError(f"short_regime:{cfg.get('regime')}")
    if len(s) < bars:
        return {"on": False, "reason": f"history:{len(s)}<{bars}"}
    flag = donchian.bear_regime(s, bars)
    return {"on": bool(flag.iloc[-1]), "btc_close": float(s.iloc[-1]),
            "btc_mean": round(float(s.tail(bars).mean()), 6), "bars": bars}
