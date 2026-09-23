from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from bot.settings import Settings
from signals import donchian

REPLAY_BARS = 150


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
