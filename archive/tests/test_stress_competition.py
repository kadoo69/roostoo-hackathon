"""Tests for gates/stress_competition.py and reproductions of the live-path defects it reports.

The `test_repro_*` tests pin CURRENT behaviour of the live cycle that the red-team report flags
(the competition red-team report under results/stress); each fails once its defect is fixed, and should then be
rewritten to assert the fixed behaviour. DECISIONS.md#stress-harness-declaration
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from bot import feed, portfolio, risk
from bot.entry_guard import GuardedTarget
from bot.execution import Executor
from bot.journal import Journal
from bot.run import Bot
from bot.settings import load
from archive.gates import stress_competition as sc
from venue.roostoo import AmbiguousOrderError, PairSpec, RoostooError

SPEC = PairSpec("BTC/USD", 2, 5, 1, "crypto", True)
QUOTE = {"MaxBid": 100.0, "MinAsk": 100.01, "LastPrice": 100.0}


def comp_settings():
    return replace(load("config/competition.yaml"), dry_run=False)


def make_executor(tmp_path):
    client = Mock()
    client.place_order.return_value = {"OrderDetail": {"OrderID": 1, "Status": "PENDING"}}
    client.query_order.return_value = {"OrderDetails": []}
    return Executor(client, {SPEC.pair: SPEC}, comp_settings(), Journal("stress_comp", tmp_path))


def buy_plan(executor):
    return executor.prepare({"symbol": "BTCUSDT", "side": "BUY", "quantity": 1.0}, {"BTC/USD": QUOTE})


def test_drop_spells_removes_only_the_named_spell():
    idx = pd.date_range("2025-01-01", periods=6, freq="30min", tz="UTC")
    w = pd.DataFrame({"A": [0, 0.5, 0.5, 0, 0.5, 0.5], "B": [0, 0.5, 0.5, 0.5, 0, 0]}, index=idx, dtype=float)
    t = pd.DataFrame([{"symbol": "A", "entry": idx[1], "exit": idx[3], "open": False},
                      {"symbol": "A", "entry": idx[4], "exit": idx[5], "open": True}])
    out = sc.drop_spells(w, t.iloc[[0]])
    assert out["A"].tolist() == [0, 0, 0, 0, 0.5, 0.5]
    assert out["B"].equals(w["B"])
    assert sc.drop_spells(w, t.iloc[[1]])["A"].tolist() == [0, 0.5, 0.5, 0, 0, 0]


def test_window_returns_kill_freezes_at_first_breach():
    idx = pd.date_range("2025-01-01", periods=sc.BAR_14D + 48, freq="30min", tz="UTC")
    v = np.zeros(len(idx))
    v[10] = -0.30
    v[20] = 0.50
    wr = sc.window_returns(pd.Series(v, index=idx))
    first = wr.iloc[0]
    assert bool(first["killed"])
    assert first["ret_with_kill"] == pytest.approx(-0.30)
    assert first["ret"] == pytest.approx(0.7 * 1.5 - 1.0)


def test_window_returns_nonsense_control_flat_path_never_kills():
    idx = pd.date_range("2025-01-01", periods=sc.BAR_14D * 2, freq="30min", tz="UTC")
    wr = sc.window_returns(pd.Series(0.0, index=idx))
    assert not wr["killed"].any()
    assert (wr["ret"] == 0).all()


def test_stale_path_buys_flags_only_late_entries():
    signals = [{"event": "contenders", "bar": "2026-09-30 13:30:00+00:00", "target": {"TRXUSDT": 0.25}},
               {"event": "contenders", "bar": "2026-09-30 14:00:00+00:00", "target": {"TRXUSDT": 0.5}},
               {"event": "contenders", "bar": "2026-09-30 17:00:00+00:00", "target": {"PUMPUSDT": 0.5}},
               {"event": "contenders", "bar": "2026-09-30 16:30:00+00:00", "target": None}]
    orders = [{"event": "placed", "side": "BUY", "symbol": "TRXUSDT", "price": 1, "ts_utc": "2026-09-30T14:30:12+00:00"},
              {"event": "placed", "side": "BUY", "symbol": "PUMPUSDT", "price": 1, "ts_utc": "2026-09-30T17:30:07+00:00"},
              {"event": "placed", "side": "SELL", "symbol": "TRXUSDT", "price": 1, "ts_utc": "2026-09-30T15:30:09+00:00"}]
    out = sc.stale_path_buys(signals, orders)
    assert [o["symbol"] for o in out] == ["TRXUSDT"]


def test_repro_ambiguous_submit_blocks_exits_for_the_life_of_the_process(tmp_path):
    ex = make_executor(tmp_path)
    ex.client.place_order.side_effect = AmbiguousOrderError("timeout")
    with pytest.raises(AmbiguousOrderError):
        ex.send(buy_plan(ex))
    ex.client.place_order.side_effect = None
    sell = ex.prepare({"symbol": "BTCUSDT", "side": "SELL", "quantity": 1.0}, {"BTC/USD": QUOTE})
    for _ in range(5):
        ex.refresh_pending()
        ex.sweep_unfilled()
        with pytest.raises(AmbiguousOrderError, match="submission_blocked"):
            ex.send(sell)
    assert ex.submission_blocked is True
    assert ex.client.place_order.call_count == 1


def test_one_query_error_after_four_orders_neither_halts_nor_flattens(tmp_path):
    ex = make_executor(tmp_path)
    for _ in range(4):
        ex.refresh_pending()
        ex.send(buy_plan(ex))
    ex.client.query_order.side_effect = RoostooError("POST:/v3/query_order:timeout")
    ex.sweep_unfilled()
    assert ex.error_rate() < 0.25
    g = risk.gate([50_000.0, 50_100.0], ex.error_rate(), 0.2, 3.0, comp_settings())
    assert not g["halt"] and not g["freeze"]


def test_a_venue_outage_freezes_without_liquidating(tmp_path):
    ex = make_executor(tmp_path)
    ex.client.query_order.side_effect = RoostooError("POST:/v3/query_order:timeout")
    for _ in range(6):
        ex.refresh_pending()
        ex.sweep_unfilled()
    assert ex.error_rate() == 1.0
    g = risk.gate([50_000.0, 50_100.0], ex.error_rate(), 0.2, 3.0, comp_settings())
    assert g["freeze"] and not g["halt"]

def test_a_failed_pending_query_does_not_resubmit_a_resting_buy(tmp_path):
    ex = make_executor(tmp_path)
    ex.refresh_pending()
    ex.send(buy_plan(ex))
    ex.client.query_order.side_effect = RoostooError("POST:/v3/query_order:timeout")
    ex.refresh_pending()
    rec = ex.send(buy_plan(ex))
    assert rec["skipped"] == "order_already_pending"
    assert ex.client.place_order.call_count == 1

def test_repro_drawdown_halt_never_clears_once_flat():
    s = comp_settings()
    curve = [50_000.0, 52_000.0, 38_900.0] + [38_900.0] * 20_000
    assert risk.gate(curve, 0.0, 0.2, 3.0, s)["halt"]
    assert risk.gate(curve[:4999], 0.0, 0.2, 3.0, s)["halt"]
    assert not risk.gate(curve[-5000:], 0.0, 0.2, 3.0, s)["halt"]


def test_a_missing_quote_keeps_the_last_mark_and_does_not_trip_the_halt(tmp_path):
    bot = object.__new__(Bot)
    bot.universe, bot.holdings, bot.shorts, bot.cash = ["BTCUSDT"], {"BTCUSDT": 250.0}, {}, 25_000.0
    bot.executor = make_executor(tmp_path)
    bot.journal = Mock()
    full, _ = bot.mark({"BTC/USD": QUOTE})
    hole, prices = bot.mark({})
    zero, _ = bot.mark({"BTC/USD": {**QUOTE, "LastPrice": 0.0}})
    assert full == pytest.approx(50_000.0) and hole == pytest.approx(50_000.0) and zero == pytest.approx(50_000.0)
    assert prices["BTCUSDT"] == pytest.approx(100.0)
    assert not risk.gate([full, hole], 0.0, 0.2, 3.0, comp_settings())["halt"]

def test_mirror_rows_drop_for_zero_last_price_and_an_unheld_gap_does_not_breach(monkeypatch):
    specs = {"BTC/USD": SPEC, "ETH/USD": PairSpec("ETH/USD", 2, 4, 1, "crypto", True)}
    monkeypatch.setattr(feed, "binance_prices", lambda syms: {"BTCUSDT": 100.0, "ETHUSDT": 10.0})
    quotes = {"BTC/USD": QUOTE, "ETH/USD": {**QUOTE, "LastPrice": 0.0}}
    rows = feed.mirror_check(quotes, specs, ["BTCUSDT", "ETHUSDT"])
    assert [r["symbol"] for r in rows] == ["BTCUSDT"]
    held = {"BTCUSDT": 1.0}
    assert not (set(held) - {r["symbol"] for r in rows})
    g = risk.gate([1.0, 1.0], 0.0, 0.2, float("inf"), comp_settings())
    assert g["freeze"] and not g["halt"]

class _Guarded(GuardedTarget):
    def __init__(self, matrix):
        self.matrix = matrix
        self.s = SimpleNamespace(interval="30m")
        self.journal = Mock()
        self.holdings, self.shorts, self.equity_curve = {}, {}, [50_000.0]


def test_second_decision_after_cold_start_does_not_buy_a_path_entry_one_bar_late():
    last = pd.Timestamp.now(tz="UTC").floor("30min") - pd.Timedelta(minutes=30)
    idx = pd.date_range(end=last, periods=4, freq="30min")
    m = pd.DataFrame({"TRXUSDT": [1.0, 1.0, 1.0, 1.0]}, index=idx)
    w = pd.DataFrame({"TRXUSDT": [0.0, 0.25, 0.25, 0.5]}, index=idx)
    g = _Guarded(m.iloc[:3])
    assert g.guard({"TRXUSDT": 0.25}, w.iloc[:3], {"TRXUSDT": 1.0}, 0) == {}
    g.matrix, g.prev_processed = m, idx[2]
    assert g.guard({"TRXUSDT": 0.5}, w, {"TRXUSDT": 1.0}, 0) == {}


def test_universe_refresh_keeps_a_held_coin_so_the_rule_can_sell_it(tmp_path):
    bot = object.__new__(Bot)
    bot.s = comp_settings()
    bot.journal = Mock()
    bot.specs = {"BTC/USD": SPEC, "ETH/USD": PairSpec("ETH/USD", 2, 4, 1, "crypto", True)}
    bot.executor = Executor(Mock(), bot.specs, bot.s, Journal("stress_comp", tmp_path))
    bot.client = Mock()
    bot.client.balance.return_value = {"USD": {"Free": 25_000.0, "Lock": 0.0},
                                       "ETH": {"Free": 2_500.0, "Lock": 0.0}}
    bot.holdings, bot.cash, bot.shorts = {"ETHUSDT": 2_500.0}, 25_000.0, {}
    quotes = {"BTC/USD": QUOTE, "ETH/USD": {"MaxBid": 10.0, "MinAsk": 10.01, "LastPrice": 10.0}}
    bot.universe = ["BTCUSDT", "ETHUSDT"]
    bot.adopt_wallet()
    before, _ = bot.mark(quotes)
    bot.universe = ["BTCUSDT"]
    bot.adopt_wallet()
    after, prices = bot.mark(quotes)
    assert bot.holdings == {"ETHUSDT": 2_500.0} and after == pytest.approx(before)
    orders = portfolio.deltas({}, portfolio.current_weights(bot.holdings, prices, after), after, prices)
    assert [(o["symbol"], o["side"]) for o in orders] == [("ETHUSDT", "SELL")]


def test_an_ambiguous_submission_is_lifted_once_reconciliation_settles(tmp_path, monkeypatch):
    from bot import run
    bot = object.__new__(Bot)
    bot.executor = make_executor(tmp_path)
    bot.executor.submission_blocked = True
    bot.intents, bot.client, bot.journal, bot.blocked_cycles = Mock(), Mock(), Mock(), 0
    monkeypatch.setattr(run, "reconcile_intents", lambda *a: {"clean": False, "settled": 0})
    bot.settle_blocked_submission()
    assert bot.executor.submission_blocked and bot.blocked_cycles == 1
    monkeypatch.setattr(run, "reconcile_intents", lambda *a: {"clean": True, "settled": 1})
    bot.settle_blocked_submission()
    assert not bot.executor.submission_blocked and bot.blocked_cycles == 0

