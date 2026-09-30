"""Breadth-switched shorts with their own slots, live and backtest agree. DECISIONS.md#lowtf-breadth-shorts-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd

from dataclasses import replace

from bot import portfolio
from bot.settings import load
from bot.strategy import Channel, short_regime
from gates.short_paper_books import sleeve
from signals import donchian


def _shorts_on():
    """The mechanism under test, on the 15m book's parameters with its short switch forced on (the
    live book runs long-only since DECISIONS.md#short-term-shorts-off-2026-09-26)."""
    s = load("config/momentum_top3_15m.yaml")
    return replace(s, short={**s.short, "enabled": True})


def _matrix(n_up: int, n_down: int, bars: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2026-09-01", periods=bars, freq="15min", tz="UTC")
    cols = {}
    for i in range(n_up):
        cols[f"U{i}USDT"] = 100 * np.exp(np.linspace(0, 0.1 + 0.01 * i, bars))
    for i in range(n_down):
        cols[f"D{i}USDT"] = 100 * np.exp(np.linspace(0, -0.1 - 0.01 * i, bars))
    return pd.DataFrame(cols, index=idx)


def test_breadth_switch_turns_on_only_when_most_of_the_pool_falls():
    s = _shorts_on()
    assert short_regime(pd.Series(dtype=float), s, _matrix(2, 8))["on"] is True
    assert short_regime(pd.Series(dtype=float), s, _matrix(6, 4))["on"] is False
    assert donchian.breadth_short_regime(_matrix(2, 8), 40, 0.40).iloc[-1]


def test_own_slots_are_not_crowded_out_by_longs_and_rising_names_are_never_shorted():
    s = _shorts_on()
    m = _matrix(3, 5)
    held = {c: Channel(c, 0, 0, 0, 80, True, "hold") for c in m.columns if c.startswith("U")}
    broken = {c: True for c in m.columns}
    pick, info = portfolio.select_shorts(broken, held, len(held), m, s, True)
    assert info["free_slots"] == 3 and len(pick) == 3
    assert pick == ["D4USDT", "D3USDT", "D2USDT"]
    assert all(c.startswith("D") for c in pick)


def test_live_pick_matches_the_backtest_sleeve():
    s = _shorts_on()
    m = _matrix(3, 5)
    live = pd.DataFrame(False, index=m.index, columns=m.columns)
    live[[c for c in m.columns if c.startswith("U")]] = True
    brk = pd.DataFrame(True, index=m.index, columns=m.columns) & ~live
    mom = m / m.shift(40) - 1.0
    flag = donchian.breadth_short_regime(m, 40, 0.40)
    ref = sleeve(flag, brk, live, live, mom, 3, own_slots=True, negative_momentum=True).iloc[-1]
    held = {c: Channel(c, 0, 0, 0, 80, True, "hold") for c in m.columns if c.startswith("U")}
    pick, _ = portfolio.select_shorts({c: True for c in m.columns}, held, 3, m, s, bool(flag.iloc[-1]))
    assert sorted(ref[ref].index) == sorted(pick)
