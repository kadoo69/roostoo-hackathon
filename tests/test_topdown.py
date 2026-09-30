"""The top-down rule respects its budgets and caps and never looks ahead. DECISIONS.md#topdown-ls-declaration"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from bot.settings import ROOT
from signals import topdown

CFG = yaml.safe_load((ROOT / "config" / "topdown_ls.yaml").read_text())["topdown"]


def _panel(drift: float, n: int = 400, k: int = 12, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    steps = rng.normal(drift, 0.02, (n, k)) + np.linspace(-0.004, 0.004, k)
    close = pd.DataFrame(100 * np.exp(np.cumsum(steps, axis=0)), index=idx, columns=[f"C{i}USDT" for i in range(k)])
    btc = pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n))), index=idx)
    return close, btc


def _members(close: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(True, index=close.index, columns=close.columns)


def test_budgets_caps_and_gross_hold_on_every_row():
    for drift in (0.004, 0.0, -0.004):
        close, btc = _panel(drift)
        w, reg = topdown.targets(close, _members(close), btc, CFG)
        assert (w.abs().sum(axis=1) <= 1.0 + 1e-9).all()
        assert (w.abs() <= CFG["max_weight"] + 1e-9).all().all()
        assert ((w > 0).sum(axis=1) <= CFG["n_long"]).all() and ((w < 0).sum(axis=1) <= CFG["n_short"]).all()
        for state, b in CFG["budgets"].items():
            rows = reg["state"] == state
            assert (w[rows].clip(lower=0).sum(axis=1) <= b["long"] + 1e-9).all()
            assert ((-w[rows].clip(upper=0)).sum(axis=1) <= b["short"] + 1e-9).all()


def test_uptrend_is_bull_and_long_downtrend_is_bear_and_short():
    close, btc = _panel(0.006)
    w, reg = topdown.targets(close, _members(close), btc, CFG)
    assert reg["state"].iloc[-50:].eq("bull").mean() > 0.8 and (w.iloc[-50:] >= 0).all().all()
    close, btc = _panel(-0.006)
    w, reg = topdown.targets(close, _members(close), btc, CFG)
    assert reg["state"].iloc[-50:].eq("bear").mean() > 0.8 and (w.iloc[-50:] <= 0).all().all()


def test_a_row_ignores_every_later_bar():
    close, btc = _panel(0.001)
    cut = close.index[300]
    w, reg = topdown.targets(close, _members(close), btc, CFG)
    c2, b2 = close.copy(), btc.copy()
    c2.loc[c2.index > cut] *= 1.7
    b2.loc[b2.index > cut] *= 0.5
    w2, reg2 = topdown.targets(c2, _members(c2), b2, CFG)
    pd.testing.assert_frame_equal(w.loc[:cut], w2.loc[:cut])
    pd.testing.assert_frame_equal(reg.loc[:cut], reg2.loc[:cut])
