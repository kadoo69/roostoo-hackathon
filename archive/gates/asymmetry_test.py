from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from core.config import prereg
from data import daily
from archive.data import intraday
from archive.portfolio.asymmetric import screen3
from portfolio.backtest import PERIODS_PER_YEAR, evaluate

warnings.filterwarnings("ignore")
SPLIT = "2023-01-01"
BARS_PER_DAY = {"4h": 6.0, "8h": 3.0, "12h": 2.0, "1d": 1.0}
BARS_14D = {"4h": 84, "8h": 42, "12h": 28, "1d": 14}


def context(interval: str) -> dict:
    p = intraday.panel(interval)
    members = intraday.members_at(interval, p["close"].index)
    cols = members.columns[members.any()].tolist()
    p = {k: v[cols] for k, v in p.items()}
    members = members[cols]
    close = p["close"]
    return {
        "panel": p, "members": members, "close": close,
        "spread": daily.half_spread_bps(close, 90, daily.venue_tick_floor()),
        "atr": intraday.atr(p, prereg()["asymmetry"]["atr_lookback_bars"]),
        "ppy": PERIODS_PER_YEAR[interval], "interval": interval,
    }


def target(ctx: dict, fast: int, slow: int, vol_bars: int) -> pd.DataFrame:
    close, qv = ctx["close"], ctx["panel"]["quote_volume"]
    trend = np.sign(close.rolling(fast).mean() - close.rolling(slow).mean())
    expanding = qv.rolling(vol_bars).mean() > qv.rolling(slow).mean()
    live = trend.where(expanding, 0.0).where(ctx["members"].reindex_like(close).fillna(False))
    return live.div(live.notna().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def bootstrap(net: pd.Series, bars: int, ppy: int, draws: int = 2000,
              seed: int = 20260919) -> dict:
    rng = np.random.default_rng(seed)
    r = net.dropna()
    if len(r) <= bars + 1:
        return {}
    z = pd.Series(0.0, index=range(bars))
    comps, rets = [], []
    for _ in range(draws):
        i = rng.integers(0, len(r) - bars)
        seg = r.iloc[i:i + bars].reset_index(drop=True)
        comps.append(screen3(evaluate(seg, seg, z, z, z, ppy).as_dict()))
        rets.append(seg.add(1).prod() - 1)
    c, q = pd.Series(comps), pd.Series(rets)
    return {"median_screen3": round(float(c.median()), 4),
            "p_screen3_positive": round(float((c > 0).mean()), 4),
            "median_return": round(float(q.median()), 6),
            "p_return_positive": round(float((q > 0).mean()), 4),
            "p5_return": round(float(q.quantile(0.05)), 6),
            "p95_return": round(float(q.quantile(0.95)), 6),
            "p_return_above_5pct": round(float((q > 0.05).mean()), 4),
            "flat_fraction": round(float((q.abs() < 1e-9).mean()), 4)}
