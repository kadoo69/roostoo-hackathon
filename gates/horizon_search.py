from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from core.config import prereg
from costs.model import CostModel
from data import daily, intraday, universe
from portfolio import overlay
from portfolio.backtest import PERIODS_PER_YEAR, evaluate, run
from portfolio.construct import apply_no_trade_band, cap_net_exposure, holding_period_days

warnings.filterwarnings("ignore")
SPLIT = "2023-01-01"


def signal_weights(panel: dict, members: pd.DataFrame, fast: int, slow: int,
                   vol_bars: int) -> pd.DataFrame:
    close, qv = panel["close"], panel["quote_volume"]
    trend = np.sign(close.rolling(fast).mean() - close.rolling(slow).mean())
    expanding = qv.rolling(vol_bars).mean() > qv.rolling(slow).mean()
    signal = trend.where(expanding, 0.0)
    live = signal.where(members.reindex_like(signal).fillna(False))
    count = live.notna().sum(axis=1).replace(0, np.nan)
    return apply_no_trade_band(cap_net_exposure(live.div(count, axis=0).fillna(0.0)))


def directional_accuracy(weights: pd.DataFrame, close: pd.DataFrame) -> float:
    fwd = np.sign(close.pct_change(fill_method=None).shift(-1))
    side = np.sign(weights)
    mask = (side != 0) & fwd.notna()
    if not mask.to_numpy().sum():
        return float("nan")
    return float((side[mask] == fwd[mask]).to_numpy().sum() / mask.to_numpy().sum())


def bootstrap(net: pd.Series, bars_per_14d: int, ppy: int, draws: int = 2000,
              seed: int = 20260919) -> dict:
    rng = np.random.default_rng(seed)
    r = net.dropna()
    if len(r) <= bars_per_14d + 1:
        return {}
    z = pd.Series(0.0, index=range(bars_per_14d))
    comps, rets = [], []
    for _ in range(draws):
        i = rng.integers(0, len(r) - bars_per_14d)
        seg = r.iloc[i:i + bars_per_14d].reset_index(drop=True)
        comps.append(overlay.composite(evaluate(seg, seg, z, z, z, ppy).as_dict()))
        rets.append(seg.add(1).prod() - 1)
    c, q = pd.Series(comps), pd.Series(rets)
    return {
        "median_composite": round(float(c.median()), 4),
        "p_composite_positive": round(float((c > 0).mean()), 4),
        "median_return": round(float(q.median()), 6),
        "p_return_positive": round(float((q > 0).mean()), 4),
        "p5_return": round(float(q.quantile(0.05)), 6),
        "p95_return": round(float(q.quantile(0.95)), 6),
        "flat_fraction": round(float((q.abs() < 1e-9).mean()), 4),
    }
