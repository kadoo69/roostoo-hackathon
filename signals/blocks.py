"""Pick across blocks: at most one position per block of coins that move together.

Blocks are average-linkage clusters of the trailing `window_bars` log-return correlations (a pair
joins a block at correlation >= `min_corr`), recomputed every `refresh_bars` from bars before the
refresh only. The candidate set is the contenders rule's own path with room for `n_candidates`
names; each bar keeps held names first, then the strongest, taking at most one name per block and
`n` in all, sized by strength with a `max_weight` cap. DECISIONS.md#pick-across-blocks-2026-10-01
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


def block_labels(close: pd.DataFrame, window_bars: int, refresh_bars: int, min_corr: float) -> pd.DataFrame:
    """Block id per coin per bar; before a full window every coin is its own block."""
    r = np.log(close).diff()
    cols = list(close.columns)
    out = np.tile(np.arange(len(cols)), (len(close), 1))
    for start in range(window_bars + 1, len(close), refresh_bars):
        win = r.iloc[start - window_bars:start].dropna(axis=1, thresh=int(window_bars * 0.8))
        if win.shape[1] < 2:
            continue
        c = win.corr().to_numpy()
        c = np.nan_to_num(c, nan=0.0)
        d = squareform(np.clip(1.0 - c, 0.0, None), checks=False)
        lab = fcluster(linkage(d, "average"), t=1.0 - min_corr, criterion="distance")
        row = np.arange(len(cols)) + 10_000
        for s, g in zip(win.columns, lab):
            row[cols.index(s)] = g
        out[start:start + refresh_bars] = row
    return pd.DataFrame(out, index=close.index, columns=cols)


def select(w_big: pd.DataFrame, blocks: pd.DataFrame, n: int, max_weight: float) -> pd.DataFrame:
    wb = w_big.reindex_like(blocks).fillna(0.0).to_numpy()
    bl = blocks.to_numpy()
    out = np.zeros_like(wb)
    prev = np.zeros(wb.shape[1], dtype=bool)
    for t in range(len(wb)):
        cand = np.flatnonzero(wb[t] != 0)
        order = sorted(cand, key=lambda j: (not prev[j], -abs(wb[t, j])))
        used, pick = set(), []
        for j in order:
            if len(pick) >= n:
                break
            if bl[t, j] in used:
                continue
            used.add(bl[t, j])
            pick.append(j)
        if pick:
            raw = np.abs(wb[t, pick])
            w = np.minimum(max_weight, raw / raw.sum())
            out[t, pick] = np.sign(wb[t, pick]) * w
        prev = out[t] != 0
    return pd.DataFrame(out, index=blocks.index, columns=blocks.columns)
