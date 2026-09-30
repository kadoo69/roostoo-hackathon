"""Hold-time twins differ from their controls only in the minimum hold, and a young position is
never dropped by the rule. DECISIONS.md#live-hold-time-2026-09-26"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from bot import dashboard
from bot.settings import load
from gates import live_validation
from signals import contenders

TWINS = {"momentum_top3_15m_hold3h": ("momentum_top3_15m", 12),
         "momentum_top3_5m_hold2h": ("momentum_top3_5m", 24)}


def test_twins_differ_only_in_the_minimum_hold_and_are_registered():
    run = open("run_bots.sh").read()
    for book, (control, bars) in TWINS.items():
        a = yaml.safe_load(open(f"config/{book}.yaml"))
        b = yaml.safe_load(open(f"config/{control}.yaml"))
        diff = {k for k in set(a["contenders"]) | set(b["contenders"])
                if a["contenders"].get(k) != b["contenders"].get(k) and not k.endswith("_ref")}
        assert diff == {"min_hold_bars"} and a["contenders"]["min_hold_bars"] == bars
        changed_later = {"exit_bars", "exit_bars_changed"} if control == "momentum_top3_5m" else set()
        for sec in ("strategy", "booking", "execution", "risk"):
            sa = {k: v for k, v in a[sec].items() if not (sec == "strategy" and k in changed_later)}
            sb = {k: v for k, v in b[sec].items() if not (sec == "strategy" and k in changed_later)}
            assert sa == sb, (book, sec)
        s = load(f"config/{book}.yaml")
        assert not s.shorts_enabled and not s.target_lock.get("enabled")
        assert dashboard.BOTS[book] == f"config/{book}.yaml" and dashboard.CONTROL_OF[book] == control
        assert book in live_validation.BOOKS and f"config/{book}.yaml" in run


def test_a_position_is_kept_for_its_minimum_hold():
    rng = np.random.default_rng(8)
    idx = pd.date_range("2026-01-01", periods=400, freq="15min", tz="UTC")
    c = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.001, 0.012, (400, 8)), axis=0)),
                     index=idx, columns=[f"C{i}USDT" for i in range(8)])
    members = pd.DataFrame(True, index=idx, columns=c.columns)
    cfg = {"n": 3, "momentum_bars": 40, "breadth_max": 0.4, "max_weight": 0.5, "sticky": True, "min_hold_bars": 12}
    w = contenders.targets(c, members, cfg, short_on=pd.Series(False, index=idx))
    on = (w > 0).astype(int)
    for col in w.columns:
        runs = on[col].groupby((on[col] != on[col].shift()).cumsum()).agg(["first", "size"])
        held = runs[runs["first"] == 1]
        closed = held.iloc[:-1] if on[col].iloc[-1] == 1 else held
        assert (closed["size"] >= 12).all()


def test_slow_exit_twin_differs_only_in_exit_bars():
    a = yaml.safe_load(open("config/momentum_top3_15m_slowexit.yaml"))
    b = yaml.safe_load(open("config/momentum_top3_15m.yaml"))
    for sec in ("contenders", "booking", "execution", "risk", "short", "target_lock"):
        assert a[sec] == b[sec], sec
    diff = {k for k in set(a["strategy"]) | set(b["strategy"]) if a["strategy"].get(k) != b["strategy"].get(k)}
    assert diff == {"exit_bars"} and a["strategy"]["exit_bars"] == 40
    assert dashboard.CONTROL_OF["momentum_top3_15m_slowexit"] == "momentum_top3_15m"
    assert "momentum_top3_15m_slowexit" in live_validation.BOOKS
