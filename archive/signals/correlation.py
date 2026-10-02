"""Correlation-aware transforms on a weight matrix.

Every function here takes the weights the live bot would have built and returns
a replacement. None of them looks at a return that is not already known at the
rebalance bar: the correlation matrix is estimated on bars strictly before the
row being rewritten.

Declared at config/correlation_cap.yaml before any backtest was run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def effective_bets(w: np.ndarray, C: np.ndarray) -> float:
    """(sum w)^2 / (w' C w): the number of independent positions the book holds.

    Equals n for n uncorrelated equal weights and 1 when everything moves
    together, so it is the quantity the live reading of 1.49 on five names was
    measuring.  Scale-invariant, which is why a haircut cannot improve it and
    only a change of composition can.
    """
    s = w.sum()
    if s <= 0:
        return 0.0
    v = float(w @ C @ w)
    return float(s * s / v) if v > 0 else 0.0


def _corr(ret: pd.DataFrame, cols: list[str], bars: int) -> np.ndarray:
    """Trailing correlation of `cols`, with missing history as zero correlation.

    Zero is the conservative fill: it tells the caller the names are
    independent, which can only make a diversification rule LESS willing to
    intervene.  Filling with a high correlation would let a name with no data
    trigger a haircut the evidence does not support.
    """
    sub = ret[cols].tail(bars)
    C = sub.corr(min_periods=max(20, bars // 4)).to_numpy(float)
    C = np.where(np.isfinite(C), C, 0.0)
    np.fill_diagonal(C, 1.0)
    return C


def apply(w: pd.DataFrame, close: pd.DataFrame, rule: str, bars: int,
          exponent: float = 1.0, shrinkage: float = 0.0,
          threshold: float = 0.75, max_per_cluster: int = 2,
          rank: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Rewrite `w` row by row under `rule`. Returns (weights, effective_bets).

    Rows are only touched where the book holds two or more names; a one-name
    book has one bet by definition and nothing to diversify.
    """
    ret = close.pct_change(fill_method=None)
    out = w.copy()
    eff = pd.Series(np.nan, index=w.index)
    idx = w.index
    for i in range(len(idx)):
        row = w.iloc[i]
        held = row[row > 0]
        if len(held) < 2:
            eff.iloc[i] = float(len(held))
            continue
        cols = list(held.index)
        hist = ret.iloc[:i]                       # strictly before this bar
        if len(hist) < max(20, bars // 4):
            eff.iloc[i] = float(len(held))
            continue
        C = _corr(hist, cols, bars)
        vec = held.to_numpy(float)
        e = effective_bets(vec, C)
        eff.iloc[i] = e
        n = len(cols)

        if rule == "baseline":
            continue
        if rule == "scale":
            k = min(1.0, (e / n) ** exponent) if n > 0 else 1.0
            out.iloc[i, out.columns.get_indexer(cols)] = vec * k
        elif rule == "reweight":
            off = (C.sum(axis=1) - 1.0) / max(n - 1, 1)     # mean corr to rest
            raw = 1.0 / np.maximum(1e-6, 1.0 + off)
            raw = raw / raw.sum()
            blend = (1.0 - shrinkage) * raw + shrinkage * (vec / vec.sum())
            out.iloc[i, out.columns.get_indexer(cols)] = blend * vec.sum()
        elif rule == "cluster_cap":
            order = (list(rank.iloc[i][cols].sort_values(ascending=False).index)
                     if rank is not None else cols)
            keep, clusters = [], []
            pos = {c: j for j, c in enumerate(cols)}
            for c in order:
                j = pos[c]
                hit = next((g for g in clusters
                            if any(C[j, pos[m]] >= threshold for m in g)), None)
                if hit is None:
                    clusters.append([c])
                    keep.append(c)
                elif len(hit) < max_per_cluster:
                    hit.append(c)
                    keep.append(c)
            drop = [c for c in cols if c not in keep]
            if drop:
                out.iloc[i, out.columns.get_indexer(drop)] = 0.0
        else:
            raise ValueError(rule)

        # Effective bets must be measured on the weights the book ACTUALLY
        # holds. Reporting the pre-transform value would make every arm look
        # identical on the one statistic the experiment exists to move, and
        # would have hidden whether a rule diversified or merely shrank.
        new = out.iloc[i][cols].to_numpy(float)
        if new.sum() > 0:
            live_idx = [j for j, v in enumerate(new) if v > 0]
            eff.iloc[i] = effective_bets(new[live_idx],
                                         C[np.ix_(live_idx, live_idx)])
        else:
            eff.iloc[i] = 0.0
    return out, eff


def beta_match(w: pd.DataFrame, target_mean_gross: float) -> pd.DataFrame:
    """Scale the baseline book by ONE constant to hit a mean gross exposure.

    This is the control. It reproduces the exposure reduction of a correlation
    rule while carrying no correlation information at all, so any advantage the
    rule shows over this is the part that is actually about correlation.
    """
    g = w.abs().sum(axis=1)
    cur = float(g.mean())
    if cur <= 0:
        return w
    return w * min(1.0, target_mean_gross / cur)
