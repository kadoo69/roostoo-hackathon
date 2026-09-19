from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from costs.model import CostModel

DAYS_PER_YEAR = 365
PERIODS_PER_YEAR = {'1h':8760,'4h':2190,'8h':1095,'12h':730,'1d':365,'2d':182,'3d':121}


@dataclass(frozen=True)
class Performance:
    total_return: float
    annual_return: float
    annual_volatility: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    annual_turnover: float
    annual_cost_drag: float
    days: int
    mean_gross_exposure: float

    def as_dict(self) -> dict:
        return {k: (None if v is None or (isinstance(v, float) and not np.isfinite(v))
                    else round(float(v), 6))
                for k, v in asdict(self).items()}


def _drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def evaluate(net: pd.Series, gross: pd.Series, turnover: pd.Series,
             cost: pd.Series, exposure: pd.Series,
             periods_per_year: int = DAYS_PER_YEAR) -> Performance:
    global DAYS_PER_YEAR_ACTIVE
    DAYS_PER_YEAR_ACTIVE = periods_per_year
    net = net.dropna()
    if net.empty or net.std() == 0:
        return Performance(0, 0, 0, 0, 0, 0, 0, 0, 0, len(net), 0)

    equity = (1.0 + net).cumprod()
    years = len(net) / periods_per_year
    annual_return = equity.iloc[-1] ** (1 / years) - 1.0 if years > 0 else 0.0
    annual_vol = net.std() * np.sqrt(periods_per_year)
    downside = np.sqrt((net.clip(upper=0.0) ** 2).mean()) * np.sqrt(periods_per_year)
    max_dd = _drawdown(equity)

    return Performance(
        total_return=equity.iloc[-1] - 1.0,
        annual_return=annual_return,
        annual_volatility=annual_vol,
        sharpe=net.mean() / net.std() * np.sqrt(periods_per_year) if net.std() else 0.0,
        sortino=net.mean() * periods_per_year / downside if downside else 0.0,
        calmar=annual_return / abs(max_dd) if max_dd else 0.0,
        max_drawdown=max_dd,
        annual_turnover=turnover.mean() * periods_per_year,
        annual_cost_drag=cost.mean() * periods_per_year,
        days=len(net),
        mean_gross_exposure=exposure.mean(),
    )


def run(weights: pd.DataFrame, close: pd.DataFrame, half_spread_bps: pd.DataFrame,
        costs: CostModel, execution: str = "MARKET", periods_per_year: int = DAYS_PER_YEAR
        ) -> tuple[pd.Series, Performance, Performance]:
    returns = close.pct_change(fill_method=None)
    aligned = weights.reindex_like(returns).fillna(0.0)

    gross = (aligned.shift(1) * returns).sum(axis=1, min_count=1)

    traded = (aligned - aligned.shift(1)).abs()
    fee_bps = costs.spot_fee(execution) * 1e4
    crossing = half_spread_bps.reindex_like(traded).fillna(0.0) if execution == "MARKET" else 0.0
    cost = (traded * (fee_bps + crossing) / 1e4).sum(axis=1)

    net = gross - cost.shift(1).fillna(0.0)
    turn = traded.sum(axis=1)
    exposure = aligned.abs().sum(axis=1)
    zero = pd.Series(0.0, index=cost.index)
    return (net,
            evaluate(net, gross, turn, cost, exposure, periods_per_year),
            evaluate(gross, gross, turn, zero, exposure, periods_per_year))
