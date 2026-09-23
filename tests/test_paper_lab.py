from dataclasses import replace

import pandas as pd
import pytest

from bot.execution import Executor
from bot.journal import Journal
from bot.paper_lab import advance, comparison, fresh_book, nav, settle, submit, trace_candidate
from bot.settings import load
from venue.roostoo import PairSpec


def settings():
    return replace(load("config/donchian_4h.yaml"), entry_bars=3, exit_bars=2, min_history_bars=4)


def frame(values):
    times = pd.date_range("2026-09-01", periods=len(values), freq="4h", tz="UTC")
    return pd.DataFrame({"open_time": times, "close_time": times + pd.Timedelta("4h") - pd.Timedelta("1ms"),
                         "open": [v - 0.1 for v in values], "close": values,
                         "quote_volume": [100] * len(values), "taker_buy_quote": [60] * len(values)})


def test_replay_remembers_breakout_before_latest_bar():
    f = frame([10, 11, 12, 13, 12.5])
    held, last = advance(f, False, None, settings(), "channel", pd.Timestamp("2026-09-01T20:00Z"))
    assert held
    assert pd.Timestamp(last) == f.open_time.iloc[-1]


def test_restart_replays_intermediate_exit():
    f = frame([10, 11, 12, 13, 9, 10])
    held, _ = advance(f, True, str(f.open_time.iloc[3]), settings(), "channel", pd.Timestamp("2026-09-02T00:00Z"))
    assert not held


def test_flow_confirms_entry_without_changing_exit():
    f = frame([10, 11, 12, 13])
    now = pd.Timestamp("2026-09-01T16:00Z")
    assert not advance(f, False, None, settings(), "flow_entry", now)[0]
    f.loc[3, ["quote_volume", "taker_buy_quote"]] = [200, 150]
    assert advance(f, False, None, settings(), "flow_entry", now)[0]
    f = frame([10, 11, 12, 13, 9])
    assert not advance(f, True, str(f.open_time.iloc[3]), settings(), "flow_entry", pd.Timestamp("2026-09-01T20:00Z"))[0]


def test_missing_stale_and_nan_bars_fail_closed():
    f = frame([10, 11, 12, 13, 14])
    now = pd.Timestamp("2026-09-01T20:00Z")
    with pytest.raises(ValueError, match="non_contiguous"):
        advance(f.drop(index=2), False, None, settings(), "channel", now)
    with pytest.raises(ValueError, match="stale"):
        advance(f.iloc[:-1], False, None, settings(), "channel", now)
    f.loc[2, "close"] = float("nan")
    with pytest.raises(ValueError, match="invalid_close"):
        advance(f, False, None, settings(), "channel", now)


def order():
    return {"symbol": "BTCUSDT", "pair": "BTC/USD", "side": "BUY", "quantity": 1.0,
            "price": 100.0, "submitted": 1000.0}


def quote(bid=99.0, ask=101.0):
    return {"BTC/USD": {"MaxBid": bid, "MinAsk": ask, "LastPrice": 100.0}}


def test_no_same_snapshot_fill_and_later_cross_charges_fee():
    book = fresh_book(1000)
    book["pending"] = [order()]
    settle(book, quote(99, 100), 1000, 0.001, 900)
    assert not book["holdings"]
    settle(book, quote(), 1001, 0.001, 900)
    assert not book["holdings"]
    settle(book, quote(99, 100), 1002, 0.001, 900)
    assert book["holdings"] == {"BTCUSDT": 1.0}
    assert book["cash"] == pytest.approx(899.9)
    assert book["fees"] == pytest.approx(0.1)
    assert len(book["events"]) == 1


def test_expired_order_cannot_fill_after_downtime():
    book = fresh_book(1000)
    book["pending"] = [order()]
    settle(book, quote(99, 100), 1900, 0.001, 900)
    assert not book["holdings"]
    assert book["events"][0]["event"] == "expired"


def test_submit_reserves_cash_and_cannot_duplicate_orders(tmp_path):
    spec = PairSpec("BTC/USD", 2, 5, 1, "crypto", True)
    executor = Executor(None, {spec.pair: spec}, settings(), Journal("test", tmp_path))
    book = fresh_book(1000)
    q = quote(100, 100.01)
    submit(book, {"BTCUSDT": 1}, {"BTCUSDT": 100}, q, executor, 1000, 0.001)
    assert len(book["pending"]) == 1
    plan = book["pending"][0]
    assert plan["quantity"] * plan["price"] * 1.001 <= 1000
    submit(book, {"BTCUSDT": 1}, {"BTCUSDT": 100}, q, executor, 1001, 0.001)
    assert len(book["pending"]) == 1
    assert not book["holdings"]
    settle(book, quote(99.99, 100), 1002, 0.001, 900)
    assert book["cash"] >= 0
    assert nav(book, {"BTCUSDT": 100}) == pytest.approx(1000 - book["fees"])


def test_missing_mark_never_values_a_holding_at_zero():
    book = fresh_book(1000)
    book["holdings"] = {"BTCUSDT": 1}
    with pytest.raises(ValueError, match="missing_marks"):
        nav(book, {})


def test_comparison_never_selects_short_sample_winner():
    book = fresh_book(1000)
    book["nav"] = [{"time": "2026-09-19T00:00Z", "equity": 1000, "gross": 0},
                   {"time": "2026-09-19T01:00Z", "equity": 1100, "gross": 0.1}]
    result = comparison({"sha": "test", "books": {"a": book}},
                        {"initial_nav": 1000, "min_comparison_days": 28, "fee_bps": 10})
    assert result["winner"] is None
    assert result["status"] == "insufficient_forward_evidence"
    assert result["bots"][0]["metrics"] is None


def test_each_candidate_gets_append_only_decision_and_event_logs(tmp_path):
    journal = Journal("paper_lab_test/test_bot", tmp_path)
    book = fresh_book(1000)
    book["events"] = [{"event": "submitted", "symbol": "BTCUSDT", "side": "BUY",
                       "quantity": 1, "price": 100, "time": 1}]
    book["target"] = {"BTCUSDT": .4}
    candidate = {"name": "test_bot", "family": "channel", "interval": "4h",
                 "selection_basis": "unit test"}
    trace_candidate(journal, "paper_lab_test", candidate, book, {"BTCUSDT": 100}, 0,
                    pd.Timestamp("2026-09-21T00:00:00Z"))
    decisions = journal.read("decisions")
    orders = journal.read("orders")
    assert decisions[0]["bot"] == "test_bot"
    assert decisions[0]["target"] == {"BTCUSDT": .4}
    assert orders[0]["event"] == "submitted"
    assert book["trace"]["decision_records"] == 1
    assert book["trace"]["event_records"] == 1
