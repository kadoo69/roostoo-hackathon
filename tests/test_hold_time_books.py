"""Hold-time twins differ from their controls only in the minimum hold, and a young position is
never dropped by the rule. DECISIONS.md#live-hold-time-2026-09-26"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from signals import contenders

TWINS = {"momentum_top3_15m_hold3h": ("momentum_top3_15m", 12),
         "momentum_top3_5m_hold2h": ("momentum_top3_5m", 24)}


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
