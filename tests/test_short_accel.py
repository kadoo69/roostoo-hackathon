"""Short-only book: breakdowns with negative momentum, confirmed by the 4h breakdown, volume, a
fall already under way and accelerating downside. DECISIONS.md#short-accel-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

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
