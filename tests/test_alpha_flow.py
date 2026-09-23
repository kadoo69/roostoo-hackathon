from __future__ import annotations

import pytest

from bot import booking


def run(base, current, prices, refs, equity=1000.0, enabled=True, step=0.03, frac=0.15, floor=0.0):
    cfg = {"enabled": enabled, "step_pct": step, "skim_fraction": frac,
           "min_skim_notional": floor}
    return booking.apply(base, current, prices, refs, equity, cfg)


def test_a_fresh_entry_takes_the_full_target_and_seeds_its_reference():
    refs = {}
    t, ev = run({"AAA": 1.0}, {}, {"AAA": 10.0}, refs)
    assert t["AAA"] == pytest.approx(1.0)
    assert refs["AAA"] == 10.0
    assert ev == []


def test_a_gain_of_one_step_skims_the_declared_fraction():
    refs = {"AAA": 10.0}
    t, ev = run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": 10.31}, refs)
    assert len(ev) == 1
    assert t["AAA"] == pytest.approx(0.85)
    assert refs["AAA"] == 10.31


def test_a_gain_below_the_step_never_trades_and_never_tops_up():
    refs = {"AAA": 10.0}
    t, ev = run({"AAA": 1.0}, {"AAA": 0.5}, {"AAA": 10.2}, refs)
    assert ev == []
    assert t["AAA"] == pytest.approx(0.5)


def test_booked_cash_is_never_recycled_into_the_same_name():
    refs = {"AAA": 10.0}
    run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": 11.0}, refs)
    t, ev = run({"AAA": 1.0}, {"AAA": 0.85}, {"AAA": 11.0}, refs)
    assert ev == []
    assert t["AAA"] <= 0.85 + 1e-9


def test_the_ladder_rearms_so_a_runner_is_booked_repeatedly():
    refs = {"AAA": 10.0}
    n = 0
    for px in (10.4, 10.8, 11.2):
        _, ev = run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": px}, refs)
        n += len(ev)
    assert n == 3
    assert refs["AAA"] == 11.2


def test_disabling_booking_reproduces_the_plain_target():
    refs = {"AAA": 10.0}
    t, ev = run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": 20.0}, refs, enabled=False)
    assert t["AAA"] == pytest.approx(1.0)
    assert ev == []


def test_a_reference_is_dropped_when_the_name_leaves_the_book():
    refs = {"AAA": 10.0, "OLD": 5.0}
    for enabled in (True, False):
        refs.setdefault("OLD", 5.0)
        run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": 10.0}, refs, enabled=enabled)
        assert "OLD" not in refs


def test_a_skim_below_the_minimum_notional_is_not_taken():
    refs = {"AAA": 10.0}
    t, ev = run({"AAA": 1.0}, {"AAA": 1.0}, {"AAA": 11.0}, refs, equity=10.0, floor=100.0)
    assert ev == []
    assert t["AAA"] == pytest.approx(1.0)
    assert refs["AAA"] == 10.0


def test_a_missing_price_leaves_the_target_untouched():
    refs = {"AAA": 10.0}
    t, ev = run({"AAA": 1.0}, {"AAA": 1.0}, {}, refs)
    assert t["AAA"] == pytest.approx(1.0)
    assert ev == []


def test_a_position_that_predates_booking_is_given_a_reference():
    """18 holdings and 0 refs on 2026-09-22: the ladder could never fire."""
    refs = {}
    t, ev = run({"AAA": 1.0}, {"AAA": 0.9}, {"AAA": 10.0}, refs)
    assert refs["AAA"] == 10.0
    assert ev == []
    assert t["AAA"] == pytest.approx(0.9)


def test_a_seeded_reference_then_books_on_the_next_step():
    refs = {}
    run({"AAA": 1.0}, {"AAA": 0.9}, {"AAA": 10.0}, refs)
    t, ev = run({"AAA": 1.0}, {"AAA": 0.9}, {"AAA": 10.4}, refs)
    assert len(ev) == 1
    assert t["AAA"] == pytest.approx(0.9 * 0.85)
