"""A halted pair must not rank on stale volume. DECISIONS.md#book-diagnosis-2026-09-23"""
from __future__ import annotations

import pandas as pd

from bot import universe


def _frame(last: pd.Timestamp, vol: float) -> pd.DataFrame:
    t = pd.date_range(end=last, periods=32, freq="1D")
    return pd.DataFrame({"open_time": t, "quote_volume": vol})


def test_halted_pair_is_dropped_and_live_pair_kept(monkeypatch):
    today = pd.Timestamp.now(tz="UTC").floor("D")
    frames = {"TONUSDT": _frame(today - pd.Timedelta(days=85), 9e9), "BTCUSDT": _frame(today, 1e9)}
    monkeypatch.setattr(universe, "bar_frame", lambda symbols, interval, limit: frames)
    adv = universe.median_dollar_volume(["TONUSDT", "BTCUSDT"])
    assert list(adv.index) == ["BTCUSDT"]
