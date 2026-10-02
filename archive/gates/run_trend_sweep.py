from __future__ import annotations

import warnings

import pandas as pd

from costs.model import CostModel
from data import daily, universe
from portfolio.backtest import run
from archive.portfolio.construct import apply_no_trade_band, cap_net_exposure, holding_period_days
from archive.signals.base import declaration
from archive.signals.trend import REGISTRY

warnings.filterwarnings("ignore")


def configs() -> list[dict]:
    out = []
    for pair in declaration("sma_crossover").extras["pair_grid"]:
        out.append({"signal": "sma_crossover", "kwargs": {"pair": tuple(pair)},
                    "label": f"{pair[0]}/{pair[1]}"})
    for lb in declaration("sma_distance").lookback_grid:
        out.append({"signal": "sma_distance", "kwargs": {"lookback": lb},
                    "label": f"{lb}d"})
    decl = declaration("volume_confirmed_trend")
    for vlb in decl.extras["volume_lookback_grid"]:
        out.append({"signal": "volume_confirmed_trend",
                    "kwargs": {"volume_lookback": vlb, "pair": (20, 50)},
                    "label": f"vol{vlb}"})
    return out


def build_context() -> dict:
    p = daily.build()
    hourly = universe.load_panel("1h")
    base = universe.membership(hourly).reindex(p["close"].index).fillna(False)
    return {
        "panel": p,
        "base": base,
        "spreads": daily.half_spread_bps(p["close"], floor=daily.venue_tick_floor()),
        "costs": CostModel.from_prereg(),
        "pit": universe.pit_top_n(p, base),
        "live": universe.live_top_n(p, base),
    }


def evaluate(ctx: dict, members: pd.DataFrame, cfg: dict,
             execution: str, band: bool) -> dict:
    fn = REGISTRY[cfg["signal"]]
    raw = fn(ctx["panel"], members, **cfg["kwargs"])
    weights = cap_net_exposure(raw)
    if band:
        weights = apply_no_trade_band(weights)
    net, n, g = run(weights, ctx["panel"]["close"], ctx["spreads"],
                    ctx["costs"], execution=execution)
    nd, gd = n.as_dict(), g.as_dict()
    return {
        "gross_sharpe": gd["sharpe"], "net_sharpe": nd["sharpe"],
        "net_annual_return": nd["annual_return"], "max_drawdown": nd["max_drawdown"],
        "sortino": nd["sortino"], "calmar": nd["calmar"],
        "annual_turnover": nd["annual_turnover"], "annual_cost_drag": nd["annual_cost_drag"],
        "mean_gross_exposure": nd["mean_gross_exposure"],
        "holding_period_days": round(holding_period_days(weights), 1),
        "days": nd["days"],
    }
