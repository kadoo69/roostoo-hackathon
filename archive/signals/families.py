from __future__ import annotations

import numpy as np
import pandas as pd


def _neutralise(raw: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    live = raw.where(members.reindex_like(raw).fillna(False))
    return live.div(live.notna().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def _quantile_book(score: pd.DataFrame, members: pd.DataFrame, q: float,
                   invert: bool = False) -> pd.DataFrame:
    masked = score.where(members.reindex_like(score).fillna(False))
    ranks = masked.rank(axis=1, pct=True)
    longs = ranks <= q if invert else ranks >= 1 - q
    shorts = ranks >= 1 - q if invert else ranks <= q
    nl = longs.sum(axis=1).replace(0, np.nan)
    ns = shorts.sum(axis=1).replace(0, np.nan)
    return (longs.div(nl, axis=0).fillna(0.0) * 0.5
            - shorts.div(ns, axis=0).fillna(0.0) * 0.5)


def sma_trend(p, members, fast=20, slow=50):
    c = p["close"]
    return _neutralise(np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()), members)


def xsec_momentum(p, members, lookback=20, quantile=0.2):
    c = p["close"]
    return _quantile_book(c / c.shift(lookback) - 1.0, members, quantile)


def donchian_breakout(p, members, lookback=20):
    c, high, low = p["close"], p["high"], p["low"]
    up = high.rolling(lookback).max().shift(1)
    dn = low.rolling(lookback).min().shift(1)
    sig = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    sig = sig.mask(c > up, 1.0).mask(c < dn, -1.0)
    return _neutralise(sig.where(c.notna()), members)


def short_reversal(p, members, lookback=1, quantile=0.2):
    c = p["close"]
    return _quantile_book(c / c.shift(lookback) - 1.0, members, quantile, invert=True)


def volume_trend(p, members, fast=20, slow=50, vol=10):
    c, qv = p["close"], p["quote_volume"]
    trend = np.sign(c.rolling(fast).mean() - c.rolling(slow).mean())
    expanding = qv.rolling(vol).mean() > qv.rolling(slow).mean()
    return _neutralise(trend.where(expanding, 0.0), members)


REGISTRY = {
    "sma_trend": sma_trend,
    "xsec_momentum": xsec_momentum,
    "donchian_breakout": donchian_breakout,
    "short_reversal": short_reversal,
    "volume_trend": volume_trend,
}
