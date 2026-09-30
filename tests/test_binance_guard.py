"""A 418/429 stops all Binance calls until Retry-After passes. DECISIONS.md#binance-rate-guard-2026-09-27"""
import pytest

from bot import feed


class R:
    def __init__(self, code, headers):
        self.status_code, self.headers = code, headers


def test_ban_blocks_further_calls_without_touching_the_network(monkeypatch):
    calls = []
    monkeypatch.setattr(feed, "_GUARD", {"until": 0.0})
    monkeypatch.setattr(feed.SESSION, "get", lambda *a, **k: calls.append(1) or R(418, {"retry-after": "120"}))
    with pytest.raises(feed.FeedError):
        feed.binance_get("/klines")
    with pytest.raises(feed.FeedError, match="backoff"):
        feed.binance_get("/klines")
    assert len(calls) == 1 and feed._GUARD["until"] > 0


def test_normal_response_passes_through(monkeypatch):
    monkeypatch.setattr(feed, "_GUARD", {"until": 0.0})
    monkeypatch.setattr(feed.SESSION, "get", lambda *a, **k: R(200, {"x-mbx-used-weight-1m": "100"}))
    assert feed.binance_get("/klines").status_code == 200
