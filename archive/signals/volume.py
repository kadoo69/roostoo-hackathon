from __future__ import annotations

import numpy as np
import pandas as pd

FAST = 5
SLOW = 20
ZLOOK = 60


def _z(frame: pd.DataFrame, lookback: int = ZLOOK) -> pd.DataFrame:
    mu = frame.rolling(lookback).mean()
    sd = frame.rolling(lookback).std()
    return ((frame - mu) / sd.replace(0.0, np.nan))


def vol_trend(p: dict) -> pd.DataFrame:
    v = p["quote_volume"]
    return np.sign(v.rolling(FAST).mean() - v.rolling(SLOW).mean())


def vol_z(p: dict) -> pd.DataFrame:
    return _z(p["quote_volume"])


def taker_imbalance(p: dict) -> pd.DataFrame:
    v = p["volume"].replace(0.0, np.nan)
    return (2.0 * p["taker_buy_base"] / v - 1.0)


def taker_imbalance_z(p: dict) -> pd.DataFrame:
    return _z(taker_imbalance(p))


def signed_volume(p: dict) -> pd.DataFrame:
    v = p["quote_volume"]
    change = v / v.rolling(SLOW).mean() - 1.0
    return change * np.sign(p["close"] / p["open"] - 1.0)


def avg_trade_size(p: dict) -> pd.DataFrame:
    size = p["quote_volume"] / p["trades"].replace(0.0, np.nan)
    return size / size.rolling(SLOW).median() - 1.0


def vol_confirmed_mom(p: dict) -> pd.DataFrame:
    v = p["quote_volume"]
    mom = np.sign(p["close"] / p["close"].shift(FAST) - 1.0)
    return mom.where(v > v.rolling(SLOW).median(), 0.0)


REGISTRY = {
    "vol_trend": vol_trend,
    "vol_z": vol_z,
    "taker_imbalance": taker_imbalance,
    "taker_imbalance_z": taker_imbalance_z,
    "signed_volume": signed_volume,
    "avg_trade_size": avg_trade_size,
    "vol_confirmed_mom": vol_confirmed_mom,
}


def book(score: pd.DataFrame, members: pd.DataFrame, quantile: float = 0.2
         ) -> pd.DataFrame:
    masked = score.where(members.reindex_like(score).fillna(False))
    masked = masked.replace([np.inf, -np.inf], np.nan)
    ranks = masked.rank(axis=1, pct=True)
    longs = ranks >= 1.0 - quantile
    shorts = ranks <= quantile
    nl = longs.sum(axis=1).replace(0, np.nan)
    ns = shorts.sum(axis=1).replace(0, np.nan)
    w = (longs.div(nl, axis=0).fillna(0.0) * 0.5
         - shorts.div(ns, axis=0).fillna(0.0) * 0.5)
    return w.fillna(0.0)
