"""Short-term books with shorts switched off: no new short, an open short can still close, the
ladder stays on. DECISIONS.md#short-term-shorts-off-2026-09-26"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.execution import Executor
from bot.journal import Journal
from bot.settings import load
from signals import acceleration
from venue.roostoo import PairSpec, RoostooClient

BOOKS = ("momentum_top3_1h", "momentum_top3_30m", "momentum_top3_15m", "momentum_top3_5m",
         "momentum_top3_1h_allcash", "momentum_top3_30m_allcash", "momentum_top3_15m_allcash",
         "momentum_top3_5m_allcash", "accel_15m")
QUOTE = {"BTC/USD": {"MaxBid": 100.00, "MinAsk": 100.01, "LastPrice": 100.00}}


def test_every_short_term_book_is_long_only_with_the_ladder_on():
    for b in BOOKS:
        s = load(f"config/{b}.yaml")
        assert not s.shorts_enabled, b
        assert s.booking["enabled"] and s.booking["step_pct"] == 0.03 and s.booking["skim_fraction"] == 0.15, b


def test_shorts_off_refuses_an_open_but_lets_a_held_short_close(tmp_path):
    spec = PairSpec("BTC/USD", 2, 5, 1.0, "crypto", True)
    ex = Executor(RoostooClient(), {spec.pair: spec}, load("config/momentum_top3_15m.yaml"), Journal("test", tmp_path))
    opened = ex.prepare({"symbol": "BTCUSDT", "side": "SHORT_OPEN", "quantity": 1.0}, QUOTE)
    closed = ex.prepare({"symbol": "BTCUSDT", "side": "SHORT_CLOSE", "quantity": 1.0}, QUOTE)
    assert opened["skipped"] == "shorts_not_enabled"
    assert closed is not None and closed.get("skipped") != "shorts_not_enabled"


def test_accel_guard_emits_no_short_when_shorts_are_off():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-01-01", periods=400, freq="15min", tz="UTC")
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(-0.002, 0.01, (400, 8)), axis=0)),
                         index=idx, columns=[f"C{i}USDT" for i in range(8)])
    members = pd.DataFrame(True, index=idx, columns=close.columns)
    cfg = {"n": 3, "momentum_bars": 40, "breadth_max": 0.4, "max_weight": 0.5, "short_bars": 12,
           "mid_bars": 48, "acc_entry_max": 2.0, "acc_exit": 1.5}
    assert (acceleration.guard_targets(close, members, cfg) < 0).any().any()
    assert not (acceleration.guard_targets(close, members, {**cfg, "shorts": False}) < 0).any().any()
