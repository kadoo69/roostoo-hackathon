from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import prereg


def apply_no_trade_band(target: pd.DataFrame, band: float | None = None) -> pd.DataFrame:
    if band is None:
        band = prereg()["portfolio"]["no_trade_band"]

    values = target.to_numpy(dtype=float)
    held = np.zeros(values.shape[1])
    out = np.empty_like(values)
    for i in range(values.shape[0]):
        want = values[i]
        scale = np.maximum(np.abs(want), np.abs(held))
        move = np.abs(want - held) > band * np.where(scale > 0, scale, 1.0)
        held = np.where(move, want, held)
        out[i] = held
    return pd.DataFrame(out, index=target.index, columns=target.columns)


def cap_net_exposure(weights: pd.DataFrame, cap: float | None = None) -> pd.DataFrame:
    if cap is None:
        cap = prereg()["portfolio"]["max_net_exposure"]
    net = weights.sum(axis=1)
    excess = (net.abs() - cap).clip(lower=0.0) * np.sign(net)
    count = (weights != 0).sum(axis=1).replace(0, np.nan)
    return weights.sub((excess / count).fillna(0.0), axis=0).where(weights != 0, 0.0)


def holding_period_days(weights: pd.DataFrame) -> float:
    active = (weights.abs() > 1e-12)
    flips = (active != active.shift(1)).sum().sum()
    return float(active.sum().sum() / max(flips / 2.0, 1.0))
