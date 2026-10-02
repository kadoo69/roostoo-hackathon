from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from core import artifacts
from core.config import gate_config, record_trials
from costs.model import CostModel
from data import daily, universe
from portfolio.backtest import run
from archive.signals.base import cross_sectional_weights, declaration
from archive.signals.library import REGISTRY

warnings.filterwarnings("ignore")
GATE = "g2_parameter_sensitivity"
NULL_DRAWS = 200
NULL_SEED = 20260919


def context() -> dict:
    panel_daily = daily.build()
    hourly = universe.load_panel("1h")
    members = universe.membership(hourly).reindex(panel_daily["close"].index).fillna(False)
    spreads = daily.half_spread_bps(panel_daily["close"], floor=daily.venue_tick_floor())
    return {
        "panel": panel_daily,
        "members": members,
        "spreads": spreads,
        "costs": CostModel.from_prereg(),
    }


def null_distribution(ctx: dict, draws: int = NULL_DRAWS) -> dict:
    rng = np.random.default_rng(NULL_SEED)
    close = ctx["panel"]["close"]
    sharpes = []
    for _ in range(draws):
        noise = pd.DataFrame(rng.standard_normal(close.shape),
                             index=close.index, columns=close.columns)
        weights = cross_sectional_weights(noise, ctx["members"], 0.2)
        _, _, gross = run(weights, close, ctx["spreads"], ctx["costs"])
        sharpes.append(gross.as_dict()["sharpe"])
    series = pd.Series(sharpes)
    return {
        "draws": draws,
        "mean": round(float(series.mean()), 4),
        "std": round(float(series.std()), 4),
        "p95": round(float(series.quantile(0.95)), 4),
        "p99": round(float(series.quantile(0.99)), 4),
    }


def sweep(ctx: dict, name: str) -> list[dict]:
    decl = declaration(name)
    fn = REGISTRY[name]
    rows = []
    for lookback in decl.lookback_grid:
        weights = fn(ctx["panel"], ctx["members"], lookback)
        _, net, gross = run(weights, ctx["panel"]["close"], ctx["spreads"], ctx["costs"])
        rows.append({
            "signal": name,
            "lookback": lookback,
            "gross_sharpe": gross.as_dict()["sharpe"],
            "net_sharpe": net.as_dict()["sharpe"],
            "net_annual_return": net.as_dict()["annual_return"],
            "max_drawdown": net.as_dict()["max_drawdown"],
            "annual_turnover": net.as_dict()["annual_turnover"],
            "annual_cost_drag": net.as_dict()["annual_cost_drag"],
        })
    return rows


def stability(rows: list[dict], cfg: dict) -> dict:
    sharpes = [r["net_sharpe"] for r in rows]
    peak = max(sharpes)
    peak_at = sharpes.index(peak)
    neighbours = [sharpes[i] for i in (peak_at - 1, peak_at + 1) if 0 <= i < len(sharpes)]

    if peak <= 0:
        return {
            "peak_net_sharpe": peak,
            "peak_lookback": rows[peak_at]["lookback"],
            "neighbour_ratio": None,
            "peak_isolation": None,
            "passed": False,
            "reason": "no_positive_configuration",
        }

    ratio = min(n / peak for n in neighbours) if neighbours else 0.0
    others = [s for i, s in enumerate(sharpes) if i != peak_at]
    isolation = (peak - np.mean(others)) / abs(peak) if others else 1.0
    return {
        "peak_net_sharpe": peak,
        "peak_lookback": rows[peak_at]["lookback"],
        "neighbour_ratio": round(float(ratio), 4),
        "peak_isolation": round(float(isolation), 4),
        "passed": bool(ratio >= cfg["min_neighbour_sharpe_ratio_to_peak"]
                       and isolation <= cfg["max_peak_isolation_score"]),
        "reason": None,
    }


def main() -> int:
    cfg = gate_config(GATE)
    artifacts.require_passed("g1_data_integrity")
    ctx = context()

    null = null_distribution(ctx)
    per_signal, trials = {}, []
    for name in REGISTRY:
        rows = sweep(ctx, name)
        per_signal[name] = {
            "declaration": {
                "family": declaration(name).family,
                "mechanism": declaration(name).mechanism,
                "failure_mode": declaration(name).failure_mode,
            },
            "grid": rows,
            "stability": stability(rows, cfg),
            "best_gross_sharpe_z_vs_null": round(
                (max(r["gross_sharpe"] for r in rows) - null["mean"]) / null["std"], 3),
        }
        trials += [{"signal": r["signal"], "lookback": r["lookback"],
                    "gate": GATE, "net_sharpe": r["net_sharpe"],
                    "gross_sharpe": r["gross_sharpe"]} for r in rows]

    total_trials = record_trials(trials)
    passed = any(v["stability"]["passed"] for v in per_signal.values())

    artifacts.write(GATE, passed, {
        "null_distribution": null,
        "signals": per_signal,
        "trials_recorded_this_gate": len(trials),
        "trials_cumulative": total_trials,
        "surviving_signals": [k for k, v in per_signal.items() if v["stability"]["passed"]],
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
