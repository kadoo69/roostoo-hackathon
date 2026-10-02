"""Market-neutral residual spread: long the coins strongest against the equal-weight pool, short the
weakest, equal dollars, held while they stay near the top or bottom. Every row uses closes up to that
row only. DECISIONS.md#residual-spread-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def residual(close: pd.DataFrame, members: pd.DataFrame, bars: int) -> pd.DataFrame:
    lr = np.log(close).diff().where(members)
    return lr.sub(lr.mean(axis=1), axis=0).rolling(bars, min_periods=bars).sum().where(members)


def weights(score: pd.DataFrame, n: int = 2, keep: int = 5, leg: float = 0.25) -> pd.DataFrame:
    """Long the `n` highest scores, short the `n` lowest, `leg` each; a held name stays while it ranks
    within the top (or bottom) `keep`."""
    s = score.to_numpy()
    out = np.zeros(s.shape)
    longs: list[int] = []
    shorts: list[int] = []
    for i in range(len(s)):
        row = s[i]
        ok = np.isfinite(row)
        if ok.sum() < 2 * keep:
            longs, shorts = [], []
            continue
        order = np.argsort(np.where(ok, -row, np.inf))
        valid = order[: int(ok.sum())]
        top, bottom = set(valid[:keep]), set(valid[::-1][:keep])
        longs = [j for j in longs if j in top]
        shorts = [j for j in shorts if j in bottom]
        for j in valid:
            if len(longs) >= n:
                break
            if j not in longs and j not in shorts:
                longs.append(j)
        for j in valid[::-1]:
            if len(shorts) >= n:
                break
            if j not in shorts and j not in longs:
                shorts.append(j)
        out[i, longs] = leg
        out[i, shorts] = -leg
    return pd.DataFrame(out, index=score.index, columns=score.columns)
