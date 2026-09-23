import copy
import datetime as dt

from bot.readiness import inspect


def fixture():
    now = dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc)
    cfg = {"poll_seconds": 60, "fee_bps": 10, "initial_nav": 1000, "candidates": [{"name": "control"}]}
    book = {"cash": 899.9, "holdings": {"BTCUSDT": 1}, "marks": {"BTCUSDT": 101},
            "pending": [], "fees": .1, "events": [{"event": "fill", "side": "BUY", "symbol": "BTCUSDT",
            "quantity": 1, "price": 100, "fee": .1}], "nav": [{"equity": 1000.9}]}
    return {"last_cycle": now.isoformat(), "books": {"control": book}}, cfg, now


def test_healthy_paper_account_is_not_live_certification():
    state, cfg, now = fixture()
    report = inspect(state, cfg, now)
    assert report["paper_accounting_healthy"]
    assert not report["competition_ready"]
    assert not report["authenticated_trading_enabled"]


def test_stale_account_is_flagged():
    state, cfg, now = fixture()
    assert not inspect(state, cfg, now + dt.timedelta(minutes=5))["paper_accounting_healthy"]


def test_accounting_discrepancies_are_detected():
    state, cfg, now = fixture()
    for key, value in [("cash", -1), ("fees", 0), ("holdings", {}), ("marks", {})]:
        damaged = copy.deepcopy(state)
        damaged["books"]["control"][key] = value
        assert not inspect(damaged, cfg, now)["paper_accounting_healthy"]


def test_duplicate_and_unfunded_pending_orders_are_detected():
    state, cfg, now = fixture()
    order = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 5, "price": 100}
    state["books"]["control"]["pending"] = [order, order]
    failures = inspect(state, cfg, now)["failures"]
    assert "control:duplicate_pending_symbol" in failures
    assert "control:cash_or_buy_reservation_invalid" in failures
