"""A bar close is never decided on a partial universe. DECISIONS.md#live-audit-2026-09-24"""
from __future__ import annotations

import pandas as pd

from bot import feed
from bot.run import MAX_DEFERRALS, incomplete_hold


def _bars(last: str, n: int = 5) -> pd.DataFrame:
    t = pd.date_range(end=pd.Timestamp(last, tz="UTC"), periods=n, freq="15min")
    return pd.DataFrame({"open_time": t, "close": range(n)})


def test_a_transient_failure_is_retried_not_dropped(monkeypatch):
    calls = {"NEARUSDT": 0}

    def flaky(symbol, interval, limit, asof=None):
        if symbol == "NEARUSDT":
            calls["NEARUSDT"] += 1
            if calls["NEARUSDT"] == 1:
                raise ConnectionError("reset")
        return _bars("2026-09-24 12:15")

    monkeypatch.setattr(feed, "closed_bars", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    frames = feed.bar_frame(["ONDOUSDT", "NEARUSDT"], "15m", 10)
    assert set(frames) == {"ONDOUSDT", "NEARUSDT"} and calls["NEARUSDT"] == 2
    assert feed.data_gaps(["ONDOUSDT", "NEARUSDT"], frames) == {"missing": [], "stale": []}


def test_missing_and_stale_symbols_are_reported():
    frames = {"A": _bars("2026-09-24 12:15"), "B": _bars("2026-09-24 12:00")}
    gaps = feed.data_gaps(["A", "B", "C"], frames)
    assert gaps == {"missing": ["C"], "stale": ["B"]}


def test_a_gap_defers_the_bar_a_bounded_number_of_times():
    m = pd.DataFrame({"A": [1.0]}, index=[pd.Timestamp("2026-09-24 12:15", tz="UTC")])
    state: dict = {}
    gaps = {"missing": ["NEARUSDT"], "stale": []}
    held = [incomplete_hold(gaps, m, state) for _ in range(MAX_DEFERRALS + 2)]
    assert held == [True] * MAX_DEFERRALS + [False, False]
    assert incomplete_hold({"missing": [], "stale": []}, m, state) is False and state == {}


def test_every_symbol_is_cut_at_the_same_instant(monkeypatch):
    seen = []

    def record(symbol, interval, limit, asof=None):
        seen.append(asof)
        return _bars("2026-09-24 12:15")

    monkeypatch.setattr(feed, "closed_bars", record)
    feed.bar_frame(["A", "B", "C"], "15m", 10)
    assert len(set(seen)) == 1 and seen[0] is not None
