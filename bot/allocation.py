from __future__ import annotations

import numpy as np
import pandas as pd


def allocate(scores: np.ndarray, returns: np.ndarray, policy: dict,
             periods_per_year: int = 2190) -> np.ndarray:
    weights = np.zeros(len(scores), dtype=float)
    eligible = np.flatnonzero(np.isfinite(scores))
    ordered = eligible[np.argsort(-scores[eligible], kind="stable")][:policy["n_positions"]]
    if not len(ordered):
        return weights
    history = returns[:, ordered]
    if len(history) < policy.get("risk_bars", 90) or not np.isfinite(history).all():
        return weights
    vol = history.std(axis=0, ddof=1)
    raw = np.ones(len(ordered)) if policy["sizing"] == "equal" else 1 / np.maximum(vol, 1e-6)
    budget = policy["max_gross"] * len(ordered) / policy["n_positions"]
    selected = np.minimum(raw / raw.sum() * budget, policy["max_single"])
    forecast = float((history @ selected).std(ddof=1) * np.sqrt(periods_per_year))
    if forecast > policy["target_vol"]:
        selected *= policy["target_vol"] / forecast
    selected[selected < policy["min_weight"]] = 0
    weights[ordered] = selected
    return weights


def targets(matrix: pd.DataFrame, signals: dict[str, bool], policy: dict,
            periods_per_year: int) -> dict[str, float]:
    close = matrix.reindex(sorted(matrix.columns), axis=1)
    scores = (close.iloc[-1] / close.iloc[-1-policy.get("momentum_bars", 40)] - 1).where(
        pd.Series(signals).reindex(close.columns).fillna(False))
    history = close.pct_change(fill_method=None).tail(policy.get("risk_bars", 90))
    weights = allocate(scores.to_numpy(), history.to_numpy(), policy, periods_per_year)
    return {s: float(w) for s, w in zip(close.columns, weights) if w > 0}
