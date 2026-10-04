"""Regression: a booking bot must not flatten its book between bar closes.

Enabling booking makes `trades_every_cycle()` true. On a cycle that is not a bar
close, `channels` is empty by construction, so a target computed from it is
empty, and `deltas` reads an empty target as "sell everything". On 2026-09-22
this liquidated donchian_4h_cushion, donchian_1h and momentum_top5_cushion.
DECISIONS.md#booking-flattened-the-book
"""
from __future__ import annotations

import pytest

from bot import booking, portfolio
from bot.settings import load


def held_weights():
    return {"AAAUSDT": 0.34, "BBBUSDT": 0.33, "CCCUSDT": 0.33}


ALL = ("donchian_4h", "donchian_4h_cushion", "donchian_1h", "momentum_top5_4h",
       "momentum_top5_cushion", "momentum_top3_4h", "momentum_top3_full",
       "alpha_flow", "scalper_live")


def test_booking_is_enabled_on_every_bot():
    """Operator instruction 2026-09-22. DECISIONS.md#booking-on-every-bot."""
    for c in ALL:
        assert load(f"config/{c}.yaml").booking.get("enabled"), c


def test_every_bot_books_on_the_same_declared_ladder():
    for c in ALL:
        b = load(f"config/{c}.yaml").booking
        assert b["step_pct"] == 0.03 and b["skim_fraction"] == 0.15, c
        assert b["recycle"] is False, c


def test_a_book_that_computes_its_own_target_is_never_carried_forward():
    """A subclass that computes its target every cycle opts out of carry-forward."""
    from bot.run import Bot

    class SelfTargeting(Bot):
        def target_from_channels(self) -> bool:
            return False
    assert Bot.target_from_channels(object()) is True
    assert SelfTargeting.target_from_channels(object()) is False


def test_carrying_the_book_forward_emits_no_orders_when_nothing_gained():
    cur = held_weights()
    prices = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 30.0}
    refs = {s: prices[s] for s in cur}
    tgt, ev = booking.apply(dict(cur), cur, prices, refs, 100000.0,
                            load("config/donchian_1h.yaml").booking)
    assert ev == []
    orders = portfolio.deltas(tgt, cur, 100000.0, prices, no_trade_band=0.25)
    assert orders == []


def test_an_empty_target_against_a_held_book_is_a_full_liquidation():
    """The bug, stated as a fact about deltas, so the guard above has a reason."""
    cur = held_weights()
    prices = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 30.0}
    orders = portfolio.deltas({}, cur, 100000.0, prices, no_trade_band=0.25)
    assert len(orders) == 3
    assert all(o["side"] == "SELL" for o in orders)


def test_carrying_forward_still_lets_the_ladder_skim():
    cur = held_weights()
    prices = {"AAAUSDT": 10.4, "BBBUSDT": 20.0, "CCCUSDT": 30.0}
    refs = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 30.0}
    tgt, ev = booking.apply(dict(cur), cur, prices, refs, 100000.0,
                            load("config/donchian_1h.yaml").booking)
    assert [e["symbol"] for e in ev] == ["AAAUSDT"]
    plain = portfolio.deltas(tgt, cur, 100000.0, prices, no_trade_band=0.25)
    assert plain == [], "a 15% slice sits inside the 25% band and must be suppressed without force"
    orders = portfolio.deltas(tgt, cur, 100000.0, prices, no_trade_band=0.25,
                              force={e["symbol"] for e in ev})
    assert [o["side"] for o in orders] == ["SELL"]
    assert orders[0]["symbol"] == "AAAUSDT"


def test_short_ladder_covers_a_slice_after_a_three_percent_fall_and_never_tops_up():
    cfg = {"enabled": True, "step_pct": 0.03, "skim_fraction": 0.15, "min_skim_notional": 0.0, "shorts": True}
    refs = {"X": 100.0}
    out, ev = booking.apply({"X": -0.5}, {"X": -0.4}, {"X": 96.9}, refs, 1000.0, cfg)
    assert out["X"] == pytest.approx(-0.34) and ev and refs["X"] == 96.9
    out, ev = booking.apply({"X": -0.5}, {"X": -0.4}, {"X": 99.0}, {"X": 100.0}, 1000.0, cfg)
    assert out["X"] == pytest.approx(-0.4) and not ev
    off = {k: v for k, v in cfg.items() if k != "shorts"}
    out, ev = booking.apply({"X": -0.5}, {"X": -0.4}, {"X": 90.0}, {"X": 100.0}, 1000.0, off)
    assert out["X"] == -0.5 and not ev


CFG_BOOK = {"enabled": True, "step_pct": 0.03, "skim_fraction": 0.15, "min_skim_notional": 10.0}


def test_a_cash_capped_entry_is_completed_but_a_skimmed_position_is_never_topped_up():
    target, current, prices = {"PUMPUSDT": 1 / 3, "LTCUSDT": 1 / 3}, {"PUMPUSDT": 0.051, "LTCUSDT": 0.20}, {"PUMPUSDT": 0.0065, "LTCUSDT": 71.6}
    refs = {"PUMPUSDT": 0.0065, "LTCUSDT": 71.6}
    capped, _ = booking.apply(target, current, prices, dict(refs), 101_700.0, CFG_BOOK)
    assert capped["PUMPUSDT"] == 0.051 and capped["LTCUSDT"] == 0.20
    grown, _ = booking.apply(target, current, prices, dict(refs), 101_700.0, CFG_BOOK, grow={"PUMPUSDT"})
    assert grown["PUMPUSDT"] == pytest.approx(1 / 3) and grown["LTCUSDT"] == 0.20
    orders = portfolio.deltas(grown, current, 101_700.0, prices)
    assert [(o["symbol"], o["side"]) for o in orders] == [("PUMPUSDT", "BUY")]
    assert orders[0]["notional"] == pytest.approx((1 / 3 - 0.051) * 101_700.0, rel=1e-6)
    up = {"PUMPUSDT": 0.0067}
    skim, ev = booking.apply({"PUMPUSDT": 1 / 3}, {"PUMPUSDT": 0.30}, up, {"PUMPUSDT": 0.0065}, 101_700.0, CFG_BOOK,
                             grow={"PUMPUSDT"})
    assert ev and skim["PUMPUSDT"] == pytest.approx(0.30 * 0.85)
