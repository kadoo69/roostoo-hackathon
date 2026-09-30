"""Stale-cycle guard: a cycle that slept after fetching its data sends nothing. DECISIONS.md#stale-cycle-guard"""
from __future__ import annotations

from bot.run import STALE_CYCLE_S, STALE_SLEEP_S, stale_cycle


def test_a_slow_awake_cycle_is_not_stale():
    assert not stale_cycle(0.0, 0.0, 120.0, 120.0)


def test_a_cycle_that_slept_is_stale_even_when_it_resumed_quickly():
    assert stale_cycle(0.0, 0.0, 3600.0 + 20.0, 20.0)
    assert stale_cycle(0.0, 0.0, 30.0, 30.0 - STALE_SLEEP_S - 0.1)
    assert not stale_cycle(0.0, 0.0, 30.0, 30.0 - STALE_SLEEP_S + 0.1)


def test_a_cycle_past_the_hard_limit_is_stale_without_sleeping():
    assert stale_cycle(0.0, 0.0, STALE_CYCLE_S + 1.0, STALE_CYCLE_S + 1.0)
