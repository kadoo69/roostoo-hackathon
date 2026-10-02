from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

from core import artifacts
from core.config import gate_config, trial_count, trial_counts_by_family
from costs.model import CostModel
from data import daily
from archive.data import intraday
from archive.gates.asymmetry_test import SPLIT, context
from portfolio.backtest import PERIODS_PER_YEAR, run
from archive.portfolio.construct import apply_no_trade_band
from archive.signals.families import REGISTRY

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


def selected_donchian() -> pd.Series:
    from data import flow, universe
    from signals import donchian

    costs = CostModel.from_prereg()
    p4 = flow.panel("4h")
    close = p4["close"]
    spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())
    pdl = daily.build()
    base = universe.membership(universe.load_panel("1h")).reindex(
        pdl["close"].index).fillna(False)
    trad = sorted(set(universe.tradable_symbols()) & set(close.columns)
                  - universe.STABLES)
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    rmask[trad] = True
    sel = universe.pit_top_n(pdl, base, top_n=30).reindex(
        close.index, method="ffill").fillna(False) & rmask
    w = donchian.position(close, 20, "lowchannel", 10).where(sel, 0.0) / 20.0
    g = w.abs().sum(axis=1)
    w = w.div(np.maximum(1.0, g), axis=0)
    net, _, _ = run(w.loc[SPLIT:], close.loc[SPLIT:], spreads.loc[SPLIT:],
                    costs, "LIMIT", PERIODS_PER_YEAR["4h"])
    return ((1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


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
    out["donchian_4h_roostoo_top30"] = (selected_donchian(), 365)
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


HOMOGENEOUS_VARIANCE = 0.00088663


def wide_trial_sample() -> np.ndarray:
    frames = [pd.Series(trial_sharpe_sample())]
    try:
        f = pd.read_json("results/donchian_lowtf.json")
        rows = pd.DataFrame(list(f["results"]))
        rows = rows[rows["mode"] != "benchmark"]
        frames.append((rows["daily_sharpe"] / np.sqrt(365)).dropna())
    except (ValueError, KeyError):
        pass
    return pd.concat(frames).to_numpy()


def main() -> int:
    cfg = gate_config(GATE)
    artifacts.require_passed("g1_data_integrity")

    n = trial_count()
    families = trial_counts_by_family()
    n_sharpe = families["sharpe"]
    candidates = candidate_returns()

    variants = {
        "homogeneous_42": HOMOGENEOUS_VARIANCE,
        "wide_sample": float(np.var(wide_trial_sample(), ddof=1)),
    }

    report = {}
    for vname, var in variants.items():
        block = {"trial_sharpe_variance_per_obs": round(var, 8), "counts": {}}
        for n_trials in sorted({1, 21, n_sharpe, n}):
            a = stats.norm.ppf(1.0 - 1.0 / n_trials) if n_trials >= 2 else 0.0
            b = stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e)) if n_trials >= 2 else 0.0
            sr0 = (np.sqrt(var) * ((1.0 - EULER) * a + EULER * b)
                   if n_trials >= 2 else 0.0)
            row = {"expected_max_sharpe_null_annual": round(sr0 * np.sqrt(365), 4)}
            for name, (net, ppy) in candidates.items():
                d = deflated_sharpe(net, sr0)
                mt = min_track_record_length(net, sr0)
                row[name] = {
                    "sharpe_annual": round(d["sharpe_per_obs"] * np.sqrt(ppy), 4),
                    "skew": d.get("skew"), "kurtosis": d.get("kurtosis"),
                    "observations": d["observations"], "dsr": d["dsr"],
                    "passes": bool(d["dsr"] >= cfg["min_dsr_probability"]),
                    "min_track_record_obs": (None if not np.isfinite(mt)
                                             else round(mt, 1)),
                }
            block["counts"][f"n_{n_trials}"] = row
        report[vname] = block

    headline = report["homogeneous_42"]["counts"][f"n_{n}"]
    passed = any(v["passes"] for k, v in headline.items()
                 if isinstance(v, dict) and k != "btc_hold_1d")
    artifacts.write(GATE, passed, {
        "n_trials": n,
        "n_trials_sharpe_family": n_sharpe,
        "trial_families": families,
        "counting_rule_ref": "DECISIONS.md#trial-counting-rule",
        "counting_rule_note": "The raw ledger length and the Sharpe-family count are "
                              "reported together and neither replaces the other. "
                              "The gate verdict uses the raw count. Both fail.",
        "threshold_min_dsr": cfg["min_dsr_probability"],
        "variance_note": "homogeneous_42 is the estimator established at N=131; "
                         "wide_sample adds the low-timeframe channel trials",
        "report": report,
        "surviving_at_full_count": [
            k for k, v in headline.items()
            if isinstance(v, dict) and v["passes"] and k != "btc_hold_1d"],
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
