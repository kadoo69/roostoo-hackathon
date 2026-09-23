"""Wilder's RSI, vectorised across a panel.

Wilder smoothing with Wilder's SEED: the first average is a simple mean of the
first `period` changes and every later value carries (period-1)/period of the
prior. Seeding the recursion from the first change instead, which is what a bare
`ewm(adjust=False)` does, is a different and faster-reacting indicator - it
crosses 50 more often, and a rule whose entire signal is a level cross is not
robust to that difference.

Validated against the standard 33-point Wilder series, where RSI(14) is 70.53
at the first defined point and 66.32 at the next.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(x: pd.DataFrame | pd.Series, period: int):
    seed = x.rolling(period).mean()
    out = x.astype(float).copy()
    out.iloc[:period] = np.nan
    out.iloc[period] = seed.iloc[period]
    return out.ewm(alpha=1.0 / period, adjust=False).mean()


def rsi(close: pd.DataFrame | pd.Series, period: int = 14):
    d = close.diff()
    au = _wilder(d.clip(lower=0.0), period)
    ad = _wilder((-d).clip(lower=0.0), period)
    rs = au.divide(ad.where(ad > 0.0))
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.mask((ad <= 0.0) & (au > 0.0), 100.0).mask((ad <= 0.0) & (au <= 0.0), 50.0)


def cross_up(series, level: float):
    return (series > level) & (series.shift(1) <= level)


def cross_down(series, level: float):
    return (series < level) & (series.shift(1) >= level)
