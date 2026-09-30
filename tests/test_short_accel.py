"""Short-only book: breakdowns with negative momentum, confirmed by the 4h breakdown, volume, a
fall already under way and accelerating downside. DECISIONS.md#short-accel-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from bot import dashboard
from bot.settings import load
from gates import live_validation
from signals import contenders
from signals.acceleration import features


def _falling(seed: int = 4, n: int = 400, k: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    drift = np.linspace(-0.006, 0.002, k)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.012, (n, k)), axis=0)),
                        index=idx, columns=[f"C{i}USDT" for i in range(k)])


CFG = yaml.safe_load(open("config/short_accel_15m.yaml"))["contenders"]


def test_short_only_book_never_goes_long_and_shorts_without_a_breadth_switch():
    c = _falling()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    cfg = {k: v for k, v in CFG.items() if k not in ("htf_confirm", "volume_confirm", "prior_return_min", "accel_confirm")}
    w = contenders.targets(c, members, cfg, short_on=pd.Series(False, index=c.index))
    assert not (w > 0).any().any()
    assert (w < 0).any().any()
    assert (w.abs().sum(axis=1) <= 1 + 1e-9).all()


def test_short_confirmation_needs_a_falling_hour_and_accelerating_non_blowoff_downside():
    c = _falling()
    qv = pd.DataFrame(1.0, index=c.index, columns=c.columns)
    cfg = {**CFG, "htf_confirm": False, "volume_confirm": None}
    ok = contenders.entry_confirmation(c, qv, pd.DataFrame(), cfg)
    short = (c / c.shift(40) - 1.0) < 0
    prior = c / c.shift(4) - 1.0
    a_side = -features(c, {"short_bars": 12, "mid_bars": 48})["acc"]
    want = short & (prior < -0.02) & (a_side > 0) & (a_side <= 2.0)
    assert ok[short].equals(want[short])


def test_short_accel_book_is_registered_short_only_without_lock():
    s = load("config/short_accel_15m.yaml")
    assert s.shorts_enabled and not s.target_lock.get("enabled") and s.booking["enabled"] and s.booking["shorts"]
    assert CFG["sides"] == "short" and CFG["htf_confirm"] and CFG["accel_confirm"]["max"] == 2.0
    assert dashboard.BOTS["short_accel_15m"] == "config/short_accel_15m.yaml"
    assert "short_accel_15m" in live_validation.BOOKS
    assert "config/short_accel_15m.yaml" in open("run_bots.sh").read()


def test_short_pullback_drops_only_the_4h_breakdown_and_falling_hour_filters():
    a = yaml.safe_load(open("config/short_pullback_15m.yaml"))["contenders"]
    diff = {k for k in set(a) | set(CFG) if a.get(k) != CFG.get(k) and not k.endswith("_ref")}
    assert diff == {"htf_confirm", "prior_return_bars", "prior_return_min"} and a["htf_confirm"] is False
    assert a["sides"] == "short" and a["accel_confirm"] == CFG["accel_confirm"] and a["volume_confirm"] == 1.5
    s = load("config/short_pullback_15m.yaml")
    assert s.shorts_enabled and not s.target_lock.get("enabled")
    assert dashboard.CONTROL_OF["short_pullback_15m"] == "short_accel_15m"
    assert "short_pullback_15m" in live_validation.BOOKS and "config/short_pullback_15m.yaml" in open("run_bots.sh").read()
