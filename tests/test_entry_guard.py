"""Catch-up entry guard and live minimum hold. DECISIONS.md#catch-up-and-live-min-hold"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from bot.entry_guard import GuardedTarget, drop_stale_entries, is_catch_up, keep_young, update_opened

STEP = pd.Timedelta("5min")
IDX = pd.date_range("2026-09-25 05:00", periods=5, freq="5min", tz="UTC")


def test_catch_up_on_a_skipped_bar_or_a_late_decision():
    on_time = IDX[-1] + STEP + pd.Timedelta(seconds=20)
    assert not is_catch_up(IDX[-2], IDX, on_time, STEP)
    assert is_catch_up(IDX[-3], IDX, on_time, STEP)
    assert is_catch_up(IDX[-2], IDX, IDX[-1] + 2 * STEP + pd.Timedelta(seconds=1), STEP)
    assert not is_catch_up(None, IDX, on_time, STEP)


def test_stale_entries_are_dropped_but_fresh_and_held_names_stay():
    target = {"PUMP": 0.4, "TAO": 0.3, "NEW": 0.2, "HELD": -0.1}
    prev = {"PUMP": 0.5, "TAO": 0.5, "HELD": -0.2}
    out, dropped = drop_stale_entries(target, {"HELD": -0.1, "TAO": 0.001}, prev)
    assert dropped == ["PUMP", "TAO"]
    assert out == {"NEW": 0.2, "HELD": -0.1}


def test_a_side_flip_on_the_previous_row_is_not_stale():
    out, dropped = drop_stale_entries({"X": -0.5}, {}, {"X": 0.5})
    assert out == {"X": -0.5} and dropped == []


def test_opened_stamps_new_and_flipped_positions_and_forgets_closed_ones():
    o = update_opened({}, {"A": 0.5, "B": -0.2, "DUST": 0.001}, "b1")
    assert o == {"A": ["b1", 1], "B": ["b1", -1]}
    o = update_opened(o, {"A": 0.4, "B": 0.3}, "b2")
    assert o == {"A": ["b1", 1], "B": ["b2", 1]}


def test_young_positions_keep_weight_and_side_and_gross_stays_at_one():
    opened = {"PUMP": [str(IDX[3]), 1], "TAO": [str(IDX[3]), 1]}
    current = {"PUMP": 0.5, "TAO": 0.5}
    out, kept = keep_young({"PUMP": -0.5, "LINK": 0.5}, current, opened, IDX[4], STEP, 3)
    assert kept == ["PUMP", "TAO"]
    assert out["PUMP"] == 0.5 and out["TAO"] == 0.5
    assert out.get("LINK", 0.0) == 0.0
    assert sum(abs(w) for w in out.values()) <= 1 + 1e-12


def test_a_position_is_released_at_its_minimum_age():
    opened = {"TAO": [str(IDX[1]), 1]}
    out, kept = keep_young({}, {"TAO": 0.5}, opened, IDX[4], STEP, 3)
    assert kept == [] and out == {}
    out, kept = keep_young({}, {"TAO": 0.5}, {"TAO": [None, 1]}, IDX[4], STEP, 3)
    assert kept == []


class _Base:
    def bar_close_due(self, matrix):
        latest = matrix.index[-1]
        if self.last_bar is not None and latest <= self.last_bar:
            return False
        self.last_bar = latest
        return True


class _Book(GuardedTarget, _Base):
    def __init__(self, last_bar):
        self.last_bar = last_bar
        self.s = SimpleNamespace(interval="5m")
        self.events = []
        self.journal = SimpleNamespace(write=lambda kind, rec: self.events.append(rec))
        self.opened, self.last_decision_bar = {}, None
        self.weights = {}

    def current_weights(self, prices):
        return dict(self.weights)


def test_wake_up_replay_of_2026_09_25_0525(monkeypatch):
    idx = pd.date_range("2026-09-25 04:00", "2026-09-25 05:20", freq="5min", tz="UTC")
    book = _Book(last_bar=pd.Timestamp("2026-09-25 03:10", tz="UTC"))
    w = pd.DataFrame(0.0, index=idx[:-1], columns=["PUMP", "TAO", "ONDO"])
    w.loc[idx[-4]:, ["PUMP", "TAO"]] = 0.5
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-09-25 05:25:14", tz="UTC")))
    matrix = pd.DataFrame(1.0, index=idx[:-1], columns=w.columns)
    assert book.bar_close_due(matrix)
    out = book.guard({"PUMP": 0.5, "TAO": 0.5}, w, {}, 3)
    assert out == {}
    assert book.events[-1]["event"] == "stale_entry_blocked"

    book.weights = {"PUMP": 0.5, "TAO": 0.5}
    book.last_decision_bar = str(idx[-2])
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-09-25 05:26:01", tz="UTC")))
    w2 = pd.DataFrame(0.0, index=idx, columns=w.columns)
    w2.loc[idx[-4]:idx[-2], ["PUMP", "TAO"]] = 0.5
    w2.loc[idx[-1], "PUMP"] = -0.5
    assert book.bar_close_due(pd.DataFrame(1.0, index=idx, columns=w.columns))
    out = book.guard({"PUMP": -0.5}, w2, {}, 3)
    assert out == {"PUMP": 0.5, "TAO": 0.5}
    assert book.events[-1]["event"] == "live_min_hold"
