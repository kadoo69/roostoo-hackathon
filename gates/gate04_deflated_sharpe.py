from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

from core import artifacts
from core.config import gate_config, trial_count
from costs.model import CostModel
from data import daily, intraday
from gates.asymmetry_test import SPLIT, context
from portfolio.backtest import PERIODS_PER_YEAR, run
from portfolio.construct import apply_no_trade_band
from signals.families import REGISTRY

warnings.filterwarnings("ignore")
GATE = "g4_deflated_sharpe"
EULER = 0.5772156649015329


def expected_max_sharpe(trial_sharpes: np.ndarray, n_trials: int) -> float:
    v = float(np.var(trial_sharpes, ddof=1))
    if v <= 0 or n_trials < 2:
        return 0.0
    a = stats.norm.ppf(1.0 - 1.0 / n_trials)
    b = stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return np.sqrt(v) * ((1.0 - EULER) * a + EULER * b)


def deflated_sharpe(returns: pd.Series, sr_benchmark: float) -> dict:
    r = returns.dropna()
    t = len(r)
    sr = float(r.mean() / r.std()) if r.std() > 0 else 0.0
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    if denom <= 0 or t < 2:
        return {"sharpe_per_obs": sr, "dsr": float("nan"), "observations": t}
    z = (sr - sr_benchmark) * np.sqrt(t - 1.0) / np.sqrt(denom)
    return {"sharpe_per_obs": sr, "skew": round(skew, 4), "kurtosis": round(kurt, 4),
            "observations": t, "z": round(float(z), 4),
            "dsr": round(float(stats.norm.cdf(z)), 6)}


def min_track_record_length(returns: pd.Series, sr_benchmark: float,
                            confidence: float = 0.95) -> float:
    r = returns.dropna()
    sr = float(r.mean() / r.std()) if r.std() > 0 else 0.0
    if sr <= sr_benchmark:
        return float("inf")
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    z = stats.norm.ppf(confidence)
    return 1.0 + denom * (z / (sr - sr_benchmark)) ** 2


def candidate_returns() -> dict[str, tuple[pd.Series, int]]:
    from core.config import prereg

    cfg = prereg()["family_comparison"]
    costs = CostModel.from_prereg()
    picks = [("volume_trend", "1d"), ("xsec_momentum", "8h"),
             ("sma_trend", "1d"), ("donchian_breakout", "1d")]
    out = {}
    for fam, iv in picks:
        ctx = context(iv)
        w = apply_no_trade_band(REGISTRY[fam](ctx["panel"], ctx["members"],
                                              **cfg["families"][fam]["params"]))
        net, _, _ = run(w.loc[SPLIT:], ctx["close"].loc[SPLIT:],
                        ctx["spread"].loc[SPLIT:], costs, "LIMIT", ctx["ppy"])
        out[f"{fam}_{iv}"] = (net.dropna(), ctx["ppy"])

    p1 = intraday.panel("1d")
    c1 = p1["close"]
    sp1 = daily.half_spread_bps(c1, 90, daily.venue_tick_floor())
    btc = pd.DataFrame(0.0, index=c1.index, columns=c1.columns)
    btc.loc[c1["BTCUSDT"].dropna().index, "BTCUSDT"] = 1.0
    net, _, _ = run(btc.loc[SPLIT:], c1.loc[SPLIT:], sp1.loc[SPLIT:], costs, "LIMIT", 365)
    out["btc_hold_1d"] = (net.dropna(), 365)
    return out


def trial_sharpe_sample() -> np.ndarray:
    frames = []
    for path, col, ppy_col in [
        ("results/family_comparison.json", "sharpe", "iv"),
        ("results/horizon_search_raw.json", "sharpe", "iv"),
        ("results/asymmetry_raw.json", "sharpe", "iv"),
    ]:
        try:
            f = pd.read_json(path)
        except ValueError:
            continue
        ppy = f[ppy_col].map(PERIODS_PER_YEAR)
        frames.append((f[col] / np.sqrt(ppy)).dropna())
    return pd.concat(frames).to_numpy() if frames else np.array([])


def main() -> int:
    cfg = gate_config(GATE)
    artifacts.require_passed("g1_data_integrity")

    sample = trial_sharpe_sample()
    n = trial_count()
    sr0 = expected_max_sharpe(sample, n)

    results = {}
    for name, (net, ppy) in candidate_returns().items():
        d = deflated_sharpe(net, sr0)
        d["sharpe_annual"] = round(d["sharpe_per_obs"] * np.sqrt(ppy), 4)
        d["passes"] = bool(d["dsr"] >= cfg["min_dsr_probability"])
        d["min_track_record_obs"] = round(min_track_record_length(net, sr0), 1)
        d["min_track_record_years"] = (round(d["min_track_record_obs"] / ppy, 2)
                                       if np.isfinite(d["min_track_record_obs"]) else None)
        results[name] = d

    passed = any(v["passes"] for k, v in results.items() if k != "btc_hold_1d")
    artifacts.write(GATE, passed, {
        "n_trials": n,
        "trial_sharpes_sampled": int(sample.size),
        "trial_sharpe_variance_per_obs": round(float(np.var(sample, ddof=1)), 8),
        "expected_max_sharpe_under_null_per_obs": round(sr0, 6),
        "expected_max_sharpe_under_null_annual_365": round(sr0 * np.sqrt(365), 4),
        "threshold_min_dsr": cfg["min_dsr_probability"],
        "candidates": results,
        "surviving": [k for k, v in results.items() if v["passes"] and k != "btc_hold_1d"],
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
