"""Insight 1 (enter only breakouts already running) and insight 3 (equal weights) as separate
books beside their controls. DECISIONS.md#burst-strong-and-equal-weight-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from bot import dashboard
from bot.settings import load
from gates import live_validation
from signals import contenders

CFG = {"n": 3, "momentum_bars": 40, "breadth_max": 0.40, "max_weight": 0.50}


def _panel(seed: int = 11, n: int = 300, k: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    drift = np.linspace(-0.002, 0.006, k)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.012, (n, k)), axis=0)),
                        index=idx, columns=[f"C{i}USDT" for i in range(k)])


def test_prior_return_gate_blocks_exactly_the_entries_below_the_threshold():
    c = _panel()
    qv = pd.DataFrame(1.0, index=c.index, columns=c.columns)
    cfg = {**CFG, "prior_return_bars": 4, "prior_return_min": 0.02}
    ok = contenders.entry_confirmation(c, qv, pd.DataFrame(), cfg)
    prior = c / c.shift(4) - 1.0
    is_long = (c / c.shift(40) - 1.0) > 0
    assert ok.equals((is_long & (prior > 0.02)) | (~is_long & (prior < -0.02)))
    assert contenders.needs_confirmation(cfg) and not contenders.needs_confirmation(CFG)


def test_prior_return_gate_only_removes_entries_never_forces_out_a_held_name():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    ok = (c / c.shift(4) - 1.0) > 0.02
    base = contenders.targets(c, members, {**CFG, "sticky": True}, short_on=pd.Series(False, index=c.index))
    gated = contenders.targets(c, members, {**CFG, "sticky": True}, short_on=pd.Series(False, index=c.index),
                               entry_ok=ok)
    fresh = (gated > 0) & ~(gated.shift(1, fill_value=0.0) > 0)
    assert ok[fresh].all().all()
    assert ((gated > 0).sum().sum()) <= ((base > 0).sum().sum())


def test_equal_weight_splits_evenly_and_keeps_the_same_names():
    c = _panel()
    members = pd.DataFrame(True, index=c.index, columns=c.columns)
    off = pd.Series(False, index=c.index)
    w = contenders.targets(c, members, {**CFG, "sticky": True}, short_on=off)
    e = contenders.targets(c, members, {**CFG, "sticky": True, "equal_weight": True}, short_on=off)
    assert ((w > 0) == (e > 0)).all().all()
    for _, row in e.iterrows():
        held = row[row > 0]
        if len(held):
            assert np.allclose(held, min(0.5, 1.0 / len(held)))


def test_new_books_are_separate_registered_and_differ_from_their_controls_by_one_knob():
    for book, control, knobs in (("burst_strong_15m", "burst_15m", {"prior_return_bars", "prior_return_min"}),
                                 ("momentum_top3_15m_eq", "momentum_top3_15m", {"equal_weight", "sizing"})):
        a = yaml.safe_load(open(f"config/{book}.yaml"))["contenders"]
        b = yaml.safe_load(open(f"config/{control}.yaml"))["contenders"]
        diff = {k for k in set(a) | set(b) if a.get(k) != b.get(k) and not k.endswith("_ref")}
        assert diff == knobs, (book, diff)
        s = load(f"config/{book}.yaml")
        assert not s.shorts_enabled and not s.target_lock.get("enabled") and s.booking["enabled"]
        assert dashboard.BOTS[book] == f"config/{book}.yaml" and dashboard.CONTROL_OF[book] == control
        assert book in live_validation.BOOKS
    run = open("run_bots.sh").read()
    assert "config/burst_strong_15m.yaml" in run and "config/momentum_top3_15m_eq.yaml" in run


def test_retired_books_are_off_the_dashboard_and_the_start_list():
    run = open("run_bots.sh").read().split("\n")[6]
    for book in ("momentum_top3_1h", "momentum_top3_15m_allcash", "momentum_top3_5m_allcash"):
        assert book not in dashboard.BOTS and book not in live_validation.BOOKS
        assert f"config/{book}.yaml" not in run
