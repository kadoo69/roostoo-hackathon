from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from bot.settings import Settings


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
