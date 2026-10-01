"""The venue accepts order_id or pair on a cancel, never both. DECISIONS.md#cancel-both-args-2026-10-01"""
from __future__ import annotations

import pytest

from venue.roostoo import RoostooClient


def _client(sent: list):
    c = RoostooClient.__new__(RoostooClient)
    c._request = lambda method, path, params, signed=False: sent.append((path, dict(params))) or {"Success": True}
    return c


def test_cancel_by_id_sends_the_id_alone_even_when_the_pair_is_known():
    sent: list = []
    _client(sent).cancel_order(order_id=42, pair="ETH/USD")
    assert sent == [("/v3/cancel_order", {"order_id": 42})]


def test_cancel_by_pair_sends_the_pair_alone():
    sent: list = []
    _client(sent).cancel_order(pair="ETH/USD")
    assert sent == [("/v3/cancel_order", {"pair": "ETH/USD"})]


def test_cancel_with_neither_refuses_instead_of_cancelling_everything():
    with pytest.raises(ValueError):
        _client([]).cancel_order()
