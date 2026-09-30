"""Red-team harness helpers. DECISIONS.md#stress-harness-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gates import stress


def _idx(n: int, freq: str = "30min") -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")


def test_trades_reads_spells_with_excursions() -> None:
    idx = _idx(8)
    close = pd.DataFrame({"A": [10, 10, 11, 9, 12, 12, 12, 12.0], "B": [5.0] * 8}, index=idx)
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    w.loc[idx[1]:idx[4], "A"] = 0.5
    w.loc[idx[6]:, "B"] = 0.3
    t = stress.trades(w, close).set_index("symbol")
    a = t.loc["A"]
    assert a["entry"] == idx[1] and a["exit"] == idx[5] and a["bars"] == 4
    assert np.isclose(a["ret"], 0.2) and np.isclose(a["mfe"], 0.2) and np.isclose(a["mae"], -0.1)
    assert not a["open"] and bool(t.loc["B"]["open"])


def test_regimes_label_from_closed_bars_only() -> None:
    idx = _idx(40, "4h")
    btc = pd.Series(100.0, index=idx)
    btc.iloc[30:] = 110.0
    lab = stress.regimes(pd.DataFrame({"BTCUSDT": btc}), idx)
    assert lab.iloc[30] == "chop"
    assert lab.iloc[31] == "up"


def test_verdict_applies_the_declared_break_rule() -> None:
    base = {"holdout": {"median_pct": 2.0, "worst_pct": -10.0, "median_maxdd_pct": -8.0}}
    ok = {"holdout": {"median_pct": 1.5, "worst_pct": -20.0, "median_maxdd_pct": -9.0}}
    bad = {"holdout": {"median_pct": 0.8, "worst_pct": -26.0, "median_maxdd_pct": -16.0}}
    assert stress.verdict(base, ok) == {"holdout": []}
    assert stress.verdict(base, bad) == {"holdout": ["lost>half", "worst<-25", "maxdd<-15"]}


def test_outage_mask_covers_the_declared_share() -> None:
    m = stress._outage_mask(_idx(5000), np.random.default_rng(0))
    assert 0.08 <= m.mean() < 0.12
