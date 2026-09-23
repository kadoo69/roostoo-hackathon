from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import yaml

from bot.execution import Executor
from bot.journal import Journal
from bot.paper_lab import fresh_book, settle
from bot.scalper import setup, step, validate_frame
from bot.settings import load
from venue.roostoo import PairSpec


def environment(tmp_path):
    cfg = yaml.safe_load(open("config/paper_scalper.yaml"))
    candidate = cfg["candidates"][0]
    spec = PairSpec("BTC/USD", 2, 5, 1, "crypto", True)
    executor = Executor(None, {spec.pair: spec}, load("config/donchian_4h.yaml"), Journal("scalp_test", tmp_path))
    close = np.array([100 + .02 * (i % 4) for i in range(39)] + [100.5])
    frame = pd.DataFrame({"open": close - .01, "close": close, "high": close + .02, "low": close - .02,
                          "quote_volume": [100.] * 39 + [200.], "taker_buy_quote": [60.] * 39 + [150.]})
    context = frame.copy()
    context["close"] = np.linspace(95, 101, len(context))
    frames = {("15min", "BTCUSDT"): frame, ("1h", "BTCUSDT"): context}
    quotes = {"BTC/USD": {"MaxBid": 100.5, "MinAsk": 100.51, "LastPrice": 100.5}}
    now = pd.Timestamp("2026-09-20T12:00Z")
    return cfg, candidate, executor, frames, quotes, now


def tick(book, env, now=None, selected=None):
    cfg, candidate, executor, frames, quotes, initial = env
    now = now or initial
    step(book, frames, selected if selected is not None else ["BTCUSDT"], quotes,
         {"BTCUSDT": quotes["BTC/USD"]["LastPrice"]}, executor, now.timestamp(), now, cfg, candidate, 1)


def enter(book, env):
    tick(book, env)
    plan = deepcopy(book["pending"][0])
    env[4]["BTC/USD"]["MinAsk"] = plan["price"]
    env[4]["BTC/USD"]["MaxBid"] = plan["price"] - .01
    later = env[5] + pd.Timedelta(seconds=15)
    settle(book, env[4], later.timestamp(), .001, 120)
    tick(book, env, later)
    return plan


def test_selective_entry_and_equity_risk_cap(tmp_path):
    env = environment(tmp_path)
    book = fresh_book(100000)
    tick(book, env)
    assert len(book["pending"]) == 1
    order = book["pending"][0]
    assert order["notional"] <= 25000
    assert order["notional"] * (order["stop_fraction"] + .0025 + .0001) <= 251
    tick(book, env)
    assert len(book["pending"]) == 1


@pytest.mark.parametrize("direction,reason", [(1, "take_profit"), (-1, "stop_loss")])
def test_profit_and_loss_exit_use_later_quote_not_trigger_price(tmp_path, direction, reason):
    env = environment(tmp_path)
    book = fresh_book(100000)
    enter(book, env)
    trade = book["trade"]
    bid = trade["take"] * 1.001 if direction > 0 else trade["stop"] * .999
    env[4]["BTC/USD"] = {"MaxBid": bid, "MinAsk": bid + .01, "LastPrice": bid}
    trigger = env[5] + pd.Timedelta(seconds=30)
    tick(book, env, trigger)
    assert book["pending"][0]["reason"] == reason
    settle(book, env[4], trigger.timestamp(), .001, 120)
    assert book["holdings"]
    env[4]["BTC/USD"]["MaxBid"] = bid - .2
    settle(book, env[4], trigger.timestamp() + 15, .001, 120)
    assert not book["holdings"]
    assert book["events"][-1]["price"] == pytest.approx((bid - .2) * .9995)
    tick(book, env, trigger + pd.Timedelta(seconds=15))
    assert book["blocked_symbol"] == "BTCUSDT"
    assert not book["pending"]


def test_expired_exit_remains_latched_after_bounce(tmp_path):
    env = environment(tmp_path)
    book = fresh_book(100000)
    enter(book, env)
    bid = book["trade"]["stop"] - 1
    env[4]["BTC/USD"] = {"MaxBid": bid, "MinAsk": bid + .01, "LastPrice": bid}
    trigger = env[5] + pd.Timedelta(seconds=30)
    tick(book, env, trigger)
    settle(book, env[4], trigger.timestamp() + 121, .001, 120)
    env[4]["BTC/USD"] = {"MaxBid": 100.5, "MinAsk": 100.51, "LastPrice": 100.5}
    tick(book, env, trigger + pd.Timedelta(seconds=121))
    assert book["pending"][0]["reason"] == "stop_loss"


def test_reinvestment_scales_with_equity_not_previous_bet(tmp_path):
    env = environment(tmp_path)
    a, b = fresh_book(100000), fresh_book(110000)
    tick(a, env)
    tick(b, env)
    assert b["pending"][0]["notional"] / a["pending"][0]["notional"] == pytest.approx(1.1, abs=1e-6)


def test_wide_spread_and_daily_limit_prevent_entry(tmp_path):
    env = environment(tmp_path)
    book = fresh_book(100000)
    env[4]["BTC/USD"]["MinAsk"] = 101
    tick(book, env)
    assert not book["pending"]
    env[4]["BTC/USD"]["MinAsk"] = 100.51
    book["entries_today"] = 6
    tick(book, env, env[5] + pd.Timedelta(minutes=15))
    assert not book["pending"]


def test_candle_validation_rejects_invalid_volume(tmp_path):
    env = environment(tmp_path)
    frame = env[3]["15min", "BTCUSDT"].copy()
    validate_frame(frame)
    frame.loc[0, "quote_volume"] = float("nan")
    with pytest.raises(ValueError, match="invalid_scalper"):
        validate_frame(frame)


def test_hourly_trend_required(tmp_path):
    env = environment(tmp_path)
    frame, context = env[3]["15min", "BTCUSDT"], env[3]["1h", "BTCUSDT"].copy()
    context["close"] = np.linspace(101, 95, len(context))
    assert setup(frame, context, env[1]["rules"]) is None


@pytest.mark.parametrize("mode,reason", [("time", "time_exit"), ("universe", "universe_exit"), ("halt", "risk_halt")])
def test_other_exit_paths(tmp_path, mode, reason):
    env = environment(tmp_path)
    book = fresh_book(100000)
    enter(book, env)
    if mode == "halt":
        book["daily_halted"] = True
    tick(book, env, env[5] + pd.Timedelta(minutes=61 if mode == "time" else 1),
         selected=[] if mode == "universe" else None)
    assert book["pending"][0]["reason"] == reason


def test_reentry_requires_reset_then_new_breakout(tmp_path):
    env = environment(tmp_path)
    book = fresh_book(100000)
    book.update(blocked_symbol="BTCUSDT", reset_after_bar="2026-09-20 11:45:00+00:00",
                cooldown_until=(env[5] + pd.Timedelta(minutes=30)).timestamp())
    tick(book, env, env[5] + pd.Timedelta(minutes=45))
    assert not book["pending"]
    env[3]["15min", "BTCUSDT"].loc[39, "close"] = 100.01
    tick(book, env, env[5] + pd.Timedelta(minutes=60))
    assert "blocked_symbol" not in book
    assert not book["pending"]
    env[3]["15min", "BTCUSDT"].loc[39, "close"] = 100.5
    tick(book, env, env[5] + pd.Timedelta(minutes=75))
    assert len(book["pending"]) == 1


def test_lab_cycle_and_restart_with_mock_public_data(tmp_path, monkeypatch):
    from bot import paper_lab
    from bot.settings import ROOT
    from bot.readiness import inspect
    env = environment(tmp_path)
    cfg, candidate, executor, frames, quotes, _ = env
    now = pd.Timestamp.now(tz="UTC")
    for interval in ("15min", "1h"):
        frame = frames[interval, "BTCUSDT"]
        if interval == "1h":
            frame["open"] = frame.close - .01
            frame["high"] = frame.close + .02
            frame["low"] = frame.close - .02
        width = pd.Timedelta(interval)
        frame["open_time"] = pd.date_range(end=now.floor(interval) - width, periods=len(frame), freq=interval)
        frame["close_time"] = frame.open_time + width - pd.Timedelta(milliseconds=1)
    class PublicClient:
        def sync_time(self):
            return 0

        def exchange_info(self):
            return executor.specs

        def ticker(self):
            self.last_ticker_server_time_ms = self._timestamp()
            return quotes

        def _timestamp(self):
            return int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)

    monkeypatch.setattr(paper_lab, "RoostooClient", PublicClient)
    monkeypatch.setattr(paper_lab, "full_universe", lambda *args: {"selected": ["BTCUSDT"], "ranking_count": 1})
    monkeypatch.setattr(paper_lab.feed, "closed_bars", lambda symbol, interval, limit: frames["15min" if interval == "15m" else interval, symbol])
    monkeypatch.setattr(paper_lab.feed, "mirror_check", lambda *args: [{"deviation_bps": 0, "material": False}])
    lab = paper_lab.Lab(ROOT / "config/paper_scalper.yaml", tmp_path)
    report = lab.cycle()
    assert report["bots"][0]["pending"] == 1
    assert report["bots"][0]["fills"] == 0
    assert inspect(lab.state, cfg, pd.Timestamp.now(tz="UTC").to_pydatetime())["paper_accounting_healthy"]
    saved = deepcopy(lab.state)
    lab.lock.close()
    resumed = paper_lab.Lab(ROOT / "config/paper_scalper.yaml", tmp_path)
    assert resumed.state == saved
    resumed.lock.close()
