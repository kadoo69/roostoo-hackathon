"""DECISIONS.md#underfill-chase-cap-2026-10-05: a cash-capped entry is completed only while the price
is within the cap of the capped order's price."""
import json
from types import SimpleNamespace

import pytest

from bot import booking, portfolio
from bot.run import Bot, chase_capped

CFG = {"enabled": True, "step_pct": 0.03, "skim_fraction": 0.15, "min_skim_notional": 10.0}


def test_no_cap_keeps_every_underfilled_symbol_growable():
    assert chase_capped({"PUMPUSDT"}, {"PUMPUSDT": 0.006492}, {"PUMPUSDT": 0.007}, None) == (
        {"PUMPUSDT"}, {})


def test_completion_waits_once_the_price_runs_past_the_cap():
    allowed, blocked = chase_capped({"PUMPUSDT"}, {"PUMPUSDT": 0.006492},
                                    {"PUMPUSDT": 0.006636}, 0.01)
    assert allowed == set() and blocked["PUMPUSDT"] == pytest.approx(0.006636 / 0.006492 - 1)


def test_completion_proceeds_within_the_cap_and_below_the_reference():
    refs = {"A": 1.0, "B": 1.0}
    allowed, blocked = chase_capped({"A", "B"}, refs, {"A": 1.0099, "B": 0.95}, 0.01)
    assert allowed == {"A", "B"} and blocked == {}


def test_a_symbol_without_reference_or_price_keeps_the_old_behaviour():
    allowed, _ = chase_capped({"A", "B"}, {"B": 1.0}, {"A": 2.0}, 0.01)
    assert allowed == {"A", "B"}


def test_the_10_04_pump_completion_would_not_have_been_bought():
    # 16:15Z on 10-04: PUMP held at about 5% after the capped entry at 0.006492, mark 0.006636.
    prices = {"PUMPUSDT": 0.006636, "LTCUSDT": 71.3}
    current = {"PUMPUSDT": 0.05, "LTCUSDT": 1 / 3}
    target = {"PUMPUSDT": 1 / 3, "LTCUSDT": 1 / 3}
    refs = {"PUMPUSDT": 0.006636, "LTCUSDT": 71.3}
    growable, _ = chase_capped({"PUMPUSDT"}, {"PUMPUSDT": 0.006492}, prices, 0.01)
    booked, _ = booking.apply(target, current, prices, dict(refs), 100_000.0, CFG, grow=growable)
    assert booked["PUMPUSDT"] == pytest.approx(0.05)
    assert not [o for o in portfolio.deltas(booked, current, 100_000.0, prices)
                if o["symbol"] == "PUMPUSDT"]


def test_the_capped_order_price_is_recovered_from_the_journal(tmp_path):
    d = tmp_path / "live" / "b"
    d.mkdir(parents=True)
    rows = [{"event": "placed", "side": "BUY", "symbol": "PUMPUSDT", "price": 0.006492,
             "cash_capped_from": 33910.1},
            {"event": "placed", "side": "BUY", "symbol": "UNIUSDT", "price": 9.045}]
    (d / "orders-2026-10-04.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    bot = SimpleNamespace(journal=SimpleNamespace(dir=d),
                          holdings={"PUMPUSDT": 1.0, "UNIUSDT": 1.0})
    assert Bot.capped_entry_prices(bot) == {"PUMPUSDT": 0.006492}
