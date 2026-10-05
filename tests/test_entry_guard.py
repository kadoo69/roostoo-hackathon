"""Catch-up entry guard and live minimum hold. DECISIONS.md#catch-up-and-live-min-hold"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

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


def test_seed_bar_lifts_the_stale_guard_on_that_one_decision_only():
    from bot.entry_guard import seed_now
    bar = pd.Timestamp("2026-10-05 08:00", tz="UTC")
    cfg = {"seed_bar": "2026-10-05 08:00:00+00:00"}
    assert seed_now(cfg, bar, {}) and seed_now(cfg, bar, {"ADA": 0.3})
    assert not seed_now(cfg, bar + pd.Timedelta("30min"), {})
    assert not seed_now(cfg, bar - pd.Timedelta("30min"), {})
    assert not seed_now({}, bar, {})


def test_seed_bar_keeps_old_entries_that_the_guard_would_drop():
    book = _Book(IDX[-2])
    book.cc = {"seed_bar": str(IDX[-1])}
    book.matrix = pd.DataFrame(1.0, index=IDX, columns=["ADA", "SUI"])
    w = pd.DataFrame({"ADA": [0.5] * 5, "SUI": [0.3] * 5}, index=IDX)
    out = book.guard({"ADA": 0.5, "SUI": 0.3}, w, {}, 0)
    assert out == {"ADA": 0.5, "SUI": 0.3}
    assert any(e.get("event") == "seed_entry" for e in book.events)
    book2 = _Book(IDX[-2])
    book2.cc = {}
    book2.matrix = book.matrix
    assert book2.guard({"ADA": 0.5, "SUI": 0.3}, w, {}, 0) == {}


def test_live_min_hold_overrides_only_the_live_guard():
    from bot.contenders_run import live_min_hold
    assert live_min_hold({"live_min_hold_bars": 12, "min_hold_bars": 3}) == 12
    assert live_min_hold({"min_hold_bars": 3}) == 3
    assert live_min_hold({}) == 0
    assert live_min_hold({"live_min_hold_bars": 0, "min_hold_bars": 3}) == 0


def test_no_trim_keeps_a_young_position_the_target_only_shrinks():
    """2026-10-05 19:00 IST: the rule cut ENA from 0.34 to 0.24 inside the operator's 6 h hold and the
    bot sold 29% of it at a loss. DECISIONS.md#live-hold-no-trim-2026-10-05"""
    bar = pd.Timestamp("2026-10-05 13:00", tz="UTC")
    opened = {"ENA": ["2026-10-05 12:00:00+00:00", 1], "ADA": ["2026-10-05 08:00:00+00:00", 1]}
    current = {"ENA": 0.34, "ADA": 0.50}
    target = {"ENA": 0.24, "ADA": 0.50, "FIL": 0.26}
    out, kept = keep_young(target, current, opened, bar, pd.Timedelta("30min"), 12, no_trim=True)
    assert kept == ["ENA"] and out["ENA"] == 0.34 and abs(sum(out.values()) - 1.0) < 1e-9
    out2, kept2 = keep_young(target, current, opened, bar, pd.Timedelta("30min"), 12)
    assert kept2 == [] and out2["ENA"] == 0.24
    late = bar + pd.Timedelta("6h")
    assert keep_young(target, current, opened, late, pd.Timedelta("30min"), 12, no_trim=True)[1] == []


def test_protect_losses_keeps_a_small_loser_and_lets_a_big_one_go():
    from bot.entry_guard import protect_losses
    current = {"ENAUSDT": 0.24, "ADAUSDT": 0.50, "FILUSDT": 0.15}
    entries = {"ENAUSDT": 0.2571, "ADAUSDT": 0.2725, "FILUSDT": 1.0921}
    target = {"ADAUSDT": 0.30, "FILUSDT": 0.20, "AAVEUSDT": 0.20}
    prices = {"ENAUSDT": 0.2521, "ADAUSDT": 0.2740, "FILUSDT": 1.0950}
    out, kept = protect_losses(target, current, prices, entries, 0.05)
    assert kept == ["ENAUSDT"] and out["ENAUSDT"] == 0.24
    assert out["ADAUSDT"] == 0.30 and sum(out.values()) <= 1.0 + 1e-9
    crowded = {"ADAUSDT": 0.50, "FILUSDT": 0.30, "AAVEUSDT": 0.20}
    out2, _ = protect_losses(crowded, current, prices, entries, 0.05)
    assert out2["ENAUSDT"] == 0.24 and out2["ADAUSDT"] == 0.50
    assert out2["AAVEUSDT"] == pytest.approx(1.0 - 0.24 - 0.50 - 0.15)
    deep = {**prices, "ENAUSDT": 0.2571 * 0.94}
    assert protect_losses(target, current, deep, entries, 0.05)[1] == []
    assert protect_losses(target, current, prices, {}, 0.05)[1] == []


def test_no_floor_symbol_is_kept_at_any_loss():
    from bot.entry_guard import protect_losses
    current = {"ENAUSDT": 0.24, "ADAUSDT": 0.50}
    entries = {"ENAUSDT": 0.2571, "ADAUSDT": 0.2725}
    target = {"ADAUSDT": 0.40}
    deep = {"ENAUSDT": 0.2571 * 0.90, "ADAUSDT": 0.2725 * 0.90}
    out, kept = protect_losses(target, current, deep, entries, 0.05, no_floor={"ENAUSDT"})
    assert kept == ["ENAUSDT"] and out["ENAUSDT"] == 0.24 and out["ADAUSDT"] == 0.40
    above = {"ENAUSDT": 0.27, "ADAUSDT": 0.2725 * 0.90}
    assert protect_losses(target, current, above, entries, 0.05, no_floor={"ENAUSDT"})[1] == []


def test_guards_never_crowd_a_held_position_down():
    """2026-10-05 21:00 IST: regime DOWN, target {AAVE: 0.5}; the hold kept ENA and FIL, the loss guard
    kept ADA, and the gross cap then shrank ENA and FIL, selling them below cost."""
    from bot.entry_guard import protect_losses
    bar = pd.Timestamp("2026-10-05 15:00", tz="UTC")
    opened = {"ENAUSDT": ["2026-10-05 12:00:00+00:00", 1], "FILUSDT": ["2026-10-05 12:00:00+00:00", 1],
              "ADAUSDT": ["2026-10-05 08:00:00+00:00", 1], "AAVEUSDT": ["2026-10-05 14:30:00+00:00", 1]}
    current = {"ADAUSDT": 0.50, "ENAUSDT": 0.24, "FILUSDT": 0.15, "AAVEUSDT": 0.09}
    t1, _ = keep_young({"AAVEUSDT": 0.5}, current, opened, bar, pd.Timedelta("30min"), 12, no_trim=True)
    entries = {"ADAUSDT": 0.2725, "ENAUSDT": 0.2571, "FILUSDT": 1.0921, "AAVEUSDT": 180.0}
    prices = {"ADAUSDT": 0.268, "ENAUSDT": 0.2476, "FILUSDT": 1.0818, "AAVEUSDT": 182.0}
    t2, kept = protect_losses(t1, current, prices, entries, 0.05, no_floor={"ENAUSDT"})
    for s in ("ADAUSDT", "ENAUSDT", "FILUSDT"):
        assert t2[s] >= current[s] - 1e-12, s


def test_a_held_name_reserves_only_what_it_holds_so_new_entries_are_bought():
    """2026-10-06 00:30 IST (the 18:30Z bar): the regime left DOWN and the rule wanted FIL 0.5 and UNI 0.152
    with 8.5k cash idle; the loss guard kept ADA and ENA, and AAVE, held at 0.10 and never topped up, was
    counted at its 0.348 target, so the room was negative and both entries were scaled to zero."""
    from bot.entry_guard import protect_losses
    current = {"ADAUSDT": 0.541, "ENAUSDT": 0.265, "AAVEUSDT": 0.10}
    target = {"AAVEUSDT": 0.34785, "FILUSDT": 0.5, "UNIUSDT": 0.15215}
    entries = {"ADAUSDT": 0.2725, "ENAUSDT": 0.2571, "AAVEUSDT": 180.0}
    prices = {"ADAUSDT": 0.2651, "ENAUSDT": 0.2498, "AAVEUSDT": 182.0, "FILUSDT": 1.13, "UNIUSDT": 9.0}
    out, kept = protect_losses(target, current, prices, entries, 0.05, no_floor={"ENAUSDT"})
    assert kept == ["ADAUSDT", "ENAUSDT"]
    room = 1.0 - (0.541 + 0.265 + 0.10)
    assert out["FILUSDT"] + out["UNIUSDT"] == pytest.approx(room)
    assert out["FILUSDT"] / out["UNIUSDT"] == pytest.approx(0.5 / 0.15215)
    assert out["ADAUSDT"] == 0.541 and out["ENAUSDT"] == 0.265 and out["AAVEUSDT"] == 0.34785
