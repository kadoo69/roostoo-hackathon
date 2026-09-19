from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from bot import feed, portfolio, risk, verify
from bot.execution import Executor
from bot.journal import Journal
from bot.run import Bot
from bot.settings import load
from venue.roostoo import PairSpec, RoostooClient


def settings():
    return load("config/bot_a_4h.yaml")


def executor(tmp_path):
    spec = PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)
    return Executor(RoostooClient(), {spec.pair: spec}, settings(),
                    Journal("test", tmp_path)), spec


def test_limit_prices_remain_passive(tmp_path):
    ex, spec = executor(tmp_path)
    tight = {"MaxBid": 100.00, "MinAsk": 100.01, "LastPrice": 100.00}
    assert ex.limit_price(spec, "BUY", tight) < tight["MinAsk"]
    assert ex.limit_price(spec, "SELL", tight) > tight["MaxBid"]
    wide = {"MaxBid": 100.00, "MinAsk": 101.00, "LastPrice": 100.50}
    assert wide["MaxBid"] < ex.limit_price(spec, "BUY", wide) < wide["MinAsk"]
    assert wide["MaxBid"] < ex.limit_price(spec, "SELL", wide) < wide["MinAsk"]


def test_spread_limit_is_enforced(tmp_path):
    ex, _ = executor(tmp_path)
    order = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 1.0}
    quote = {"BTC/USD": {"MaxBid": 100.0, "MinAsk": 100.1, "LastPrice": 100.0}}
    plan = ex.prepare(order, quote)
    assert plan["skipped"] == "spread_exceeds_limit"


def test_stale_ticker_halts():
    result = risk.gate([100000.0], 0.0, 121.0, 0.0, settings())
    assert result["halt"]
    assert result["breaches"] == ["stale_ticker:121s"]


def test_gross_exposure_is_capped():
    class Held:
        held = True

    target = portfolio.target_weights({str(i): Held() for i in range(30)}, settings())
    assert sum(target.values()) == pytest.approx(1.0)


def test_signal_parity_on_causal_matrix():
    rng = np.random.default_rng(7)
    index = pd.date_range("2026-01-01", periods=80, freq="4h", tz="UTC")
    matrix = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.02, (80, 5)), axis=0)),
                          index=index, columns=list("ABCDE"))
    result = verify.signal_parity(matrix, settings())
    assert result["checked"] > 0
    assert result["mismatches"] == 0


def test_mirror_check_requires_bulk_prices(monkeypatch):
    spec = PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)
    monkeypatch.setattr(feed, "binance_prices", lambda symbols: {"BTCUSDT": 100.0})
    rows = feed.mirror_check({"BTC/USD": {"LastPrice": 100.01}},
                             {"BTC/USD": spec}, ["BTCUSDT"])
    assert rows[0]["deviation_bps"] == pytest.approx(1.0)


def test_ticker_records_server_timestamp(monkeypatch):
    client = RoostooClient()
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {
        "ServerTime": 123456, "Data": {"BTC/USD": {"LastPrice": 100}}})
    assert client.ticker()["BTC/USD"]["LastPrice"] == 100
    assert client.last_ticker_server_time_ms == 123456


def test_authenticated_orders_remain_blocked_until_reconciliation_exists():
    with pytest.raises(RuntimeError, match="restart_reconciliation"):
        Bot(replace(settings(), dry_run=False))
