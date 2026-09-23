from __future__ import annotations

import numpy as np
import pandas as pd


def validate_policy(policy: dict) -> None:
    for key, minimum in (("n_positions", 1), ("risk_bars", 2), ("momentum_bars", 1)):
        value = policy.get(key, {"risk_bars": 90, "momentum_bars": 40}.get(key))
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"invalid_allocation:{key}")
    if policy.get("sizing") not in {"equal", "inverse_vol", "conviction_vol"}:
        raise ValueError("invalid_allocation:sizing")
    for key in ("max_gross", "max_single", "min_weight", "target_vol"):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"invalid_allocation:{key}")
    if not policy["min_weight"] <= policy["max_single"] <= policy["max_gross"] <= 1:
        raise ValueError("invalid_allocation:exposure_bounds")
    full = policy.get("full_deployment", False)
    if not isinstance(full, bool):
        raise ValueError("invalid_allocation:full_deployment")
    eta = policy.get("conviction_eta", 0.35)
    if (isinstance(eta, bool) or not isinstance(eta, (int, float))
            or not np.isfinite(eta) or eta <= 0):
        raise ValueError("invalid_allocation:conviction_eta")


def _bounded_simplex(raw: np.ndarray, budget: float,
                     lower: float, upper: float) -> np.ndarray:
    """Scale positive scores onto a capped simplex without clip/renormalize bugs."""
    raw = np.asarray(raw, dtype=float)
    if raw.ndim != 1 or not len(raw) or not np.isfinite(raw).all() or (raw <= 0).any():
        raise ValueError("invalid_allocation:raw_weights")
    target = min(float(budget), len(raw) * upper)
    floor = lower if target >= len(raw) * lower else 0.0
    if target <= 0:
        return np.zeros(len(raw))
    lo, hi = 0.0, max(target / raw.min(), upper / raw.min())
    for _ in range(100):
        mid = (lo + hi) / 2
        total = np.clip(raw * mid, floor, upper).sum()
        if total < target:
            lo = mid
        else:
            hi = mid
    out = np.clip(raw * ((lo + hi) / 2), floor, upper)
    # The bisection residual is numerical only and must not be renormalized,
    # because renormalization can breach an active single-name cap.
    return out


def allocate(scores: np.ndarray, returns: np.ndarray, policy: dict,
             periods_per_year: int = 2190) -> np.ndarray:
    validate_policy(policy)
    scores = np.asarray(scores, dtype=float)
    returns = np.asarray(returns, dtype=float)
    if scores.ndim != 1 or returns.ndim != 2 or returns.shape[1] != len(scores):
        raise ValueError("invalid_allocation:shape")
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        raise ValueError("invalid_allocation:annualization")
    weights = np.zeros(len(scores), dtype=float)
    eligible = np.flatnonzero(np.isfinite(scores))
    ordered = eligible[np.argsort(-scores[eligible], kind="stable")][:policy["n_positions"]]
    if not len(ordered):
        return weights
    history = returns[-policy.get("risk_bars", 90):, ordered]
    if len(history) < policy.get("risk_bars", 90) or not np.isfinite(history).all():
        return weights
    vol = history.std(axis=0, ddof=1)
    if policy["sizing"] == "equal":
        raw = np.ones(len(ordered))
    elif policy["sizing"] == "inverse_vol":
        raw = 1 / np.maximum(vol, 1e-6)
    else:
        selected_scores = scores[ordered]
        median = np.median(selected_scores)
        mad = np.median(np.abs(selected_scores - median))
        robust_scale = max(1.4826 * mad, 1e-8)
        z = np.clip((selected_scores - median) / robust_scale, -2, 2)
        raw = np.exp(policy.get("conviction_eta", 0.35) * z) / np.maximum(vol, 1e-6)
    if policy.get("full_deployment", False):
        budget = policy["max_gross"]
        selected = _bounded_simplex(raw, budget, policy["min_weight"], policy["max_single"])
    else:
        budget = policy["max_gross"] * len(ordered) / policy["n_positions"]
        selected = np.minimum(raw / raw.sum() * budget, policy["max_single"])
    forecast = float((history @ selected).std(ddof=1) * np.sqrt(periods_per_year))
    if forecast > policy["target_vol"]:
        selected *= policy["target_vol"] / forecast
    selected[selected < policy["min_weight"]] = 0
    for _ in range(len(selected) + 1):
        forecast = float((history @ selected).std(ddof=1) * np.sqrt(periods_per_year))
        if forecast <= policy["target_vol"] * (1 + 1e-12):
            break
        selected *= policy["target_vol"] / forecast
        selected[selected < policy["min_weight"]] = 0
    weights[ordered] = selected
    return weights


def targets(matrix: pd.DataFrame, signals: dict[str, bool], policy: dict,
            periods_per_year: int) -> dict[str, float]:
    validate_policy(policy)
    if len(matrix) < max(policy.get("momentum_bars", 40), policy.get("risk_bars", 90)) + 1:
        raise ValueError("insufficient_allocation_history")
    if not matrix.index.is_unique or not matrix.index.is_monotonic_increasing or not matrix.columns.is_unique:
        raise ValueError("invalid_allocation_index")
    close = matrix.reindex(sorted(matrix.columns), axis=1)
    scores = (close.iloc[-1] / close.iloc[-1-policy.get("momentum_bars", 40)] - 1).where(
        pd.Series(signals).reindex(close.columns).fillna(False))
    history = close.pct_change(fill_method=None).tail(policy.get("risk_bars", 90))
    weights = allocate(scores.to_numpy(), history.to_numpy(), policy, periods_per_year)
    return {s: float(w) for s, w in zip(close.columns, weights) if w > 0}
