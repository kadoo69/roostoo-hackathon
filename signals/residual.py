"""Market-neutral prices: each coin with the common factor stripped out, point in time.

The factor is the equal-weight log return of the pool, which on these coins is almost the first
principal component (`gates.market_structure` measures the correlation). Each coin's beta to it is
an exponentially weighted covariance over variance using only bars BEFORE the current one, so the
residual never uses the bar it is applied to. DECISIONS.md#confirmations-and-residual-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def market_return(close: pd.DataFrame) -> pd.Series:
    return np.log(close).diff().mean(axis=1)


def betas(close: pd.DataFrame, halflife_bars: int) -> pd.DataFrame:
    r = np.log(close).diff()
    f = r.mean(axis=1)
    cov = r.mul(f, axis=0).ewm(halflife=halflife_bars, min_periods=halflife_bars).mean() \
        - r.ewm(halflife=halflife_bars, min_periods=halflife_bars).mean().mul(
            f.ewm(halflife=halflife_bars, min_periods=halflife_bars).mean(), axis=0)
    var = (f ** 2).ewm(halflife=halflife_bars, min_periods=halflife_bars).mean() \
        - f.ewm(halflife=halflife_bars, min_periods=halflife_bars).mean() ** 2
    return cov.div(var, axis=0).shift(1)


def residual_prices(close: pd.DataFrame, halflife_bars: int) -> pd.DataFrame:
    """A price path per coin that moves only on its own residual return (starts at 100)."""
    r = np.log(close).diff()
    f = r.mean(axis=1)
    b = betas(close, halflife_bars).fillna(1.0)
    resid = r - b.mul(f, axis=0)
    return 100.0 * np.exp(resid.fillna(0.0).cumsum())
