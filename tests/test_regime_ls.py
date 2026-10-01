"""Regime long/short book. DECISIONS.md#regime-ls-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.regime_ls_run import regime_targets
from signals import regime_ls

CFG = {"window_bars": 8, "down_return": -0.01, "down_breadth": 0.25, "up_return": 0.01, "up_breadth": 0.75,
       "confirm_bars": 2}


def _panel(path: np.ndarray, n: int = 6) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=len(path), freq="30min", tz="UTC")
    return pd.DataFrame({f"C{i}USDT": path * (1 + 0.001 * i) for i in range(n)}, index=idx)


def test_down_needs_two_confirming_bars_and_leaves_after_two():
    path = np.concatenate([np.full(20, 100.0), np.linspace(100, 95, 12), np.linspace(95, 99, 12), np.full(12, 99.0)])
    c = _panel(path)
    raw = regime_ls.raw(c, CFG)
    st = regime_ls.state(c, CFG)
    first_raw = int(np.argmax(raw.to_numpy() == "DOWN"))
    first_state = int(np.argmax(st.to_numpy() == "DOWN"))
    assert first_state == first_raw + 1
    last_down = len(st) - 1 - int(np.argmax(st.to_numpy()[::-1] == "DOWN"))
    after = raw.to_numpy()[last_down - 1:last_down + 3]
    assert (st.iloc[last_down + 1:] != "DOWN").all() and "DOWN" not in list(after[2:])


def test_regime_uses_only_past_rows():
    path = np.concatenate([np.full(20, 100.0), np.linspace(100, 95, 12)])
    c = _panel(path)
    full = regime_ls.state(c, CFG)
    cut = regime_ls.state(c.iloc[:25], CFG)
    assert (full.iloc[:25] == cut).all()


def test_shorts_only_in_down_and_no_new_longs_there():
    rng = np.random.default_rng(1)
    up = np.cumprod(1 + rng.normal(0.004, 0.003, 120))
    down = up[-1] * np.cumprod(1 + rng.normal(-0.006, 0.003, 60))
    c = _panel(np.concatenate([up, down]), 8)
    c = c * pd.Series(np.linspace(1.0, 1.05, 8), index=c.columns)
    qv = pd.DataFrame(1e6, index=c.index, columns=c.columns)
    cc = {"n": 3, "momentum_bars": 40, "breadth_max": 0.4, "max_weight": 0.5, "sticky": True, "skip_short_z": []}
    w, reg = regime_targets(c, qv, c.iloc[::8], cc, CFG, 20, 10)
    down_rows = (reg == "DOWN").to_numpy()
    assert down_rows.any() and (w.to_numpy()[~down_rows] >= 0).all()
    assert (w.to_numpy()[down_rows] < 0).any()
    new_long = (w > 0) & (w.shift(1).fillna(0.0) <= 0)
    assert not new_long.to_numpy()[down_rows].any()
