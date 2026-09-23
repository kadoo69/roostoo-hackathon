import datetime as dt

from bot import lock

CFG = {"enabled": True, "window_start_utc": "2026-10-04T00:00:00+00:00",
       "window_end_utc": "2026-10-18T00:00:00+00:00", "lock_return": 0.05, "keep_gross": 0.3}
T0 = dt.datetime(2026, 10, 4, 1, tzinfo=dt.timezone.utc)
BOOK = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}


def test_outside_the_window_nothing_changes():
    st = {}
    out, ev, force = lock.apply(BOOK, 100_000, st, CFG, T0 - dt.timedelta(days=1))
    assert out == BOOK and ev is None and not force and st == {}


def test_the_window_anchors_its_starting_equity_once():
    st = {}
    lock.apply(BOOK, 100_000, st, CFG, T0)
    lock.apply(BOOK, 103_000, st, CFG, T0 + dt.timedelta(hours=5))
    assert st["start_equity"] == 100_000


def test_below_the_threshold_the_book_is_untouched():
    st = {}
    lock.apply(BOOK, 100_000, st, CFG, T0)
    out, ev, _ = lock.apply(BOOK, 104_999, st, CFG, T0 + dt.timedelta(days=2))
    assert out == BOOK and ev is None and "locked_at" not in st


def test_reaching_the_threshold_locks_and_caps_gross_and_forces_the_trades():
    st = {}
    lock.apply(BOOK, 100_000, st, CFG, T0)
    out, ev, force = lock.apply(BOOK, 105_000, st, CFG, T0 + dt.timedelta(days=3))
    assert ev["event"] == "target_lock"
    assert abs(sum(out.values()) - 0.3) < 1e-6
    assert force == {"A", "B", "C"}


def test_a_lock_holds_even_if_the_book_falls_back_and_later_entries_are_capped():
    st = {}
    lock.apply(BOOK, 100_000, st, CFG, T0)
    lock.apply(BOOK, 106_000, st, CFG, T0 + dt.timedelta(days=3))
    out, ev, force = lock.apply({"D": 1.0}, 101_000, st, CFG, T0 + dt.timedelta(days=5))
    assert ev is None and not force
    assert abs(out["D"] - 0.3) < 1e-9


def test_a_new_window_re_anchors_and_unlocks():
    st = {}
    lock.apply(BOOK, 100_000, st, CFG, T0)
    lock.apply(BOOK, 106_000, st, CFG, T0 + dt.timedelta(days=3))
    nxt = dict(CFG, window_start_utc="2026-11-01T00:00:00+00:00", window_end_utc="2026-11-15T00:00:00+00:00")
    out, ev, _ = lock.apply(BOOK, 120_000, st, nxt, dt.datetime(2026, 11, 1, 2, tzinfo=dt.timezone.utc))
    assert out == BOOK and "locked_at" not in st and st["start_equity"] == 120_000


def test_disabled_is_a_no_op():
    out, ev, force = lock.apply(BOOK, 200_000, {}, dict(CFG, enabled=False), T0)
    assert out == BOOK and ev is None and not force
