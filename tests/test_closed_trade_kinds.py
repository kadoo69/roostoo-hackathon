"""Closed trades are labelled exit, skim or trim. DECISIONS.md#closed-trade-kinds-2026-09-27"""
from __future__ import annotations

from bot import blotter


def _order(ts, side, qty, px, sym="ENAUSDT"):
    return {"event": "dry_run", "ts_utc": ts, "symbol": sym, "side": side, "quantity": qty, "price": px,
            "type": "LIMIT"}


def _run(monkeypatch, orders, signals):
    class FakeJournal:
        def __init__(self, bot):
            pass

        def read(self, stream):
            return orders if stream == "orders" else signals

    monkeypatch.setattr(blotter, "Journal", FakeJournal)
    return blotter.build("x")["closed"]


def test_skim_trim_and_exit_are_told_apart(monkeypatch):
    orders = [_order("2026-09-27T10:00:00+00:00", "BUY", 1000.0, 1.0),
              _order("2026-09-27T11:00:00.5+00:00", "SELL", 150.0, 1.03),
              _order("2026-09-27T12:00:00+00:00", "SELL", 300.0, 0.99),
              _order("2026-09-27T13:00:00+00:00", "SELL", 550.0, 1.01)]
    signals = [{"event": "skim", "ts_utc": "2026-09-27T11:00:00+00:00",
                "skims": [{"symbol": "ENAUSDT", "notional": 154.5}]}]
    kinds = [c["exit_kind"] for c in _run(monkeypatch, orders, signals)]
    assert kinds == ["skim", "trim", "exit"]


def test_a_skim_on_another_coin_does_not_label_this_sale(monkeypatch):
    orders = [_order("2026-09-27T10:00:00+00:00", "BUY", 1000.0, 1.0),
              _order("2026-09-27T11:00:00+00:00", "SELL", 400.0, 1.03)]
    signals = [{"event": "skim", "ts_utc": "2026-09-27T11:00:00+00:00",
                "skims": [{"symbol": "WLDUSDT", "notional": 100.0}]}]
    assert [c["exit_kind"] for c in _run(monkeypatch, orders, signals)] == ["trim"]


def test_a_sale_spanning_two_lots_labels_every_slice_exit(monkeypatch):
    orders = [_order("2026-09-27T10:00:00+00:00", "BUY", 100.0, 1.0),
              _order("2026-09-27T10:30:00+00:00", "BUY", 100.0, 1.1),
              _order("2026-09-27T11:00:00+00:00", "SELL", 200.0, 1.2)]
    closed = _run(monkeypatch, orders, [])
    assert len(closed) == 2 and {c["exit_kind"] for c in closed} == {"exit"}
