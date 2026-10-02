from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import prereg

TRADING_DAYS = 365


def realised_vol(returns: pd.Series, lookback: int) -> pd.Series:
    return returns.rolling(lookback).std().shift(1) * np.sqrt(TRADING_DAYS)


def vol_scalar(returns: pd.Series, target: float, lookback: int,
               max_multiple: float) -> pd.Series:
    vol = realised_vol(returns, lookback)
    scalar = (target / vol).replace([np.inf, -np.inf], np.nan)
    return scalar.clip(upper=max_multiple).fillna(0.0)


def asymmetric_scalar(scalar: pd.Series) -> pd.Series:
    out = scalar.copy().to_numpy()
    held = 0.0
    for i, want in enumerate(out):
        held = want if want < held else held + 0.25 * (want - held)
        out[i] = held
    return pd.Series(out, index=scalar.index)


def circuit_breaker(net: pd.Series, threshold: float,
                    rearm_fraction: float = 0.5) -> pd.Series:
    equity = (1.0 + net.fillna(0.0)).cumprod()
    drawdown = (equity / equity.cummax() - 1.0).shift(1).fillna(0.0).to_numpy()
    rearm = -threshold * rearm_fraction
    state = np.ones(drawdown.shape[0])
    armed = True
    for i, dd in enumerate(drawdown):
        if armed and dd <= -threshold:
            armed = False
        elif not armed and dd >= rearm:
            armed = True
        state[i] = 1.0 if armed else 0.0
    return pd.Series(state, index=net.index)


def apply(weights: pd.DataFrame, unlevered_net: pd.Series, target: float,
          asymmetric: bool, breaker: bool = True) -> pd.DataFrame:
    cfg = prereg()["overlay"]
    scalar = vol_scalar(unlevered_net, target, cfg["vol_lookback_days"],
                        cfg["max_leverage_multiple"])
    if asymmetric:
        scalar = asymmetric_scalar(scalar)
    if breaker:
        scalar = scalar * circuit_breaker(unlevered_net, cfg["drawdown_circuit_breaker"])
    return weights.mul(scalar.reindex(weights.index).fillna(0.0), axis=0)


def composite(perf: dict) -> float:
    cap = prereg()["objective"]["calmar_cap"]
    parts = [perf["sharpe"], perf["sortino"], min(perf["calmar"], cap)]
    return float(np.mean([p if np.isfinite(p) else 0.0 for p in parts]))
