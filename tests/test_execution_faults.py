from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from bot.execution import Executor
from bot.journal import Journal
from bot.settings import load
from venue.roostoo import AmbiguousOrderError, PairSpec, RoostooClient


@pytest.mark.parametrize("path", ["/v3/place_order", "/v6/short_open", "/v6/short_close"])
@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), ValueError("bad_json")])
def test_ambiguous_submission_is_never_retried(path, failure):
    client = RoostooClient(max_retries=3)
    client.session.post = Mock(side_effect=failure)
    with pytest.raises(AmbiguousOrderError, match="reconcile_before_retry"):
        client._request("POST", path)
    assert client.session.post.call_count == 1


def test_read_only_query_can_retry(monkeypatch):
    monkeypatch.setattr("venue.roostoo.time.sleep", lambda _: None)
    response = Mock()
    response.json.return_value = {"Success": True}
    client = RoostooClient(max_retries=3)
    client.session.post = Mock(side_effect=[requests.Timeout(), response])
    assert client._request("POST", "/v3/query_order") == {"Success": True}
    assert client.session.post.call_count == 2


def make_executor(tmp_path, **changes):
    spec = replace(PairSpec("BTC/USD", 2, 5, 1, "crypto", True), **changes)
    client = Mock()
    settings = replace(load("config/donchian_4h.yaml"), dry_run=False)
    return Executor(client, {spec.pair: spec}, settings, Journal("faults", tmp_path))


def test_ambiguous_submission_latches_executor(tmp_path):
    executor = make_executor(tmp_path)
    executor.client.place_order.side_effect = AmbiguousOrderError("unknown")
    plan = {"pair": "BTC/USD", "side": "BUY", "quantity": 1, "price": 100, "type": "LIMIT"}
    with pytest.raises(AmbiguousOrderError):
        executor.send(plan)
    with pytest.raises(AmbiguousOrderError, match="submission_blocked"):
        executor.send(plan)
    assert executor.client.place_order.call_count == 1
    assert executor.errors == 1


@pytest.mark.parametrize("field,value", [("MaxBid", 0), ("MaxBid", 101), ("MinAsk", float("inf")),
                                         ("LastPrice", float("nan")), ("LastPrice", None), ("MinAsk", "bad")])
def test_invalid_quotes_cannot_produce_orders(tmp_path, field, value):
    executor = make_executor(tmp_path)
    quote = {"MaxBid": 100, "MinAsk": 100.01, "LastPrice": 100, field: value}
    plan = executor.prepare({"symbol": "BTCUSDT", "side": "BUY", "quantity": 1}, {"BTC/USD": quote})
    assert plan["skipped"] == "invalid_quote_or_quantity"


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf"), None])
def test_invalid_quantities_cannot_produce_orders(tmp_path, quantity):
    executor = make_executor(tmp_path)
    quote = {"MaxBid": 100, "MinAsk": 100.01, "LastPrice": 100}
    plan = executor.prepare({"symbol": "BTCUSDT", "side": "BUY", "quantity": quantity}, {"BTC/USD": quote})
    assert plan["skipped"] == "invalid_quote_or_quantity"


@pytest.mark.parametrize("changes", [{"can_trade": False}, {"asset_type": "stock"}])
def test_untradable_pair_is_rejected(tmp_path, changes):
    executor = make_executor(tmp_path, **changes)
    plan = executor.prepare({"symbol": "BTCUSDT", "side": "BUY", "quantity": 1}, {"BTC/USD": {}})
    assert plan["skipped"] == "pair_not_tradable"
