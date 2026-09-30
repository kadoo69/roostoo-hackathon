"""The loop wakes shortly after each bar close. DECISIONS.md#bar-close-alignment-2026-09-27"""
from bot.run import next_sleep


def test_wakes_two_seconds_after_the_next_close_when_that_is_sooner_than_the_poll():
    assert next_sleep(1000 * 300 + 290.0, 30, 300) == 12.0
    assert next_sleep(1000 * 300 + 100.0, 30, 300) == 30
    assert next_sleep(1000 * 300 + 1.0, 30, 300) == 1.0
    assert next_sleep(1000 * 300 + 2.5, 30, 300) == 30
    assert abs(next_sleep(1000 * 14400 + 14399.9, 30, 14400) - 2.1) < 1e-6
    assert next_sleep(1000 * 300 + 299.9, 30, 300) >= 0.5
