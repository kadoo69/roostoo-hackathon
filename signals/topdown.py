"""Top-down long/short targets: market regime, then side budgets, then coins, then sizing.

One implementation for the backtest (gates/topdown_ls.py) and the live book (bot/topdown_run.py),
so the two cannot drift apart. Every value at a row uses closes up to that row only.
DECISIONS.md#topdown-ls-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals import donchian

STATES = ("bull", "neutral", "bear")


def regime(close: pd.DataFrame, members: pd.DataFrame, btc: pd.Series, cfg: dict) -> pd.DataFrame:
    """Breadth (share of pool coins with positive momentum), BTC against its long mean, and the
    resulting state: bull when both agree up, bear when both agree down, neutral otherwise."""
    mom = close / close.shift(cfg["momentum_bars"]) - 1.0
    live = members & mom.notna()
    breadth = (mom > 0).where(live).mean(axis=1)
    btc = btc.reindex(close.index)
    btc_up = btc > btc.rolling(cfg["regime_bars"]).mean()
    state = pd.Series("neutral", index=close.index)
    state[(breadth >= cfg["breadth_bull"]) & btc_up] = "bull"
    state[(breadth <= cfg["breadth_bear"]) & ~btc_up] = "bear"
    return pd.DataFrame({"breadth": breadth, "btc_up": btc_up, "state": state})


def _side(scores: pd.DataFrame, n: int, vol: pd.DataFrame, budget: pd.Series, cfg: dict) -> pd.DataFrame:
    pick = (scores.rank(axis=1, ascending=False, method="first") <= n) & scores.notna()
    if cfg["sizing"] == "inverse_vol":
        raw = (1.0 / vol).where(pick & vol.gt(0))
    else:
        raw = pick.astype(float).where(pick)
    w = raw.div(raw.sum(axis=1), axis=0).mul(budget, axis=0)
    return w.clip(upper=cfg["max_weight"]).fillna(0.0)


def targets(close: pd.DataFrame, members: pd.DataFrame, btc: pd.Series, cfg: dict,
            entry: int = 20, exit_lb: int = 10, reg: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Signed target weights per row (longs positive, shorts negative) and the regime frame.

    Longs: names in a live Donchian breakout with positive momentum, strongest first. Shorts:
    names in a live breakdown with negative momentum, weakest first. Each side is sized inside
    the budget its regime allows, capped per name, and the book never exceeds 1.0 gross.
    """
    members = members.reindex_like(close).fillna(False).astype(bool)
    reg = regime(close, members, btc, cfg) if reg is None else reg
    mom = close / close.shift(cfg["momentum_bars"]) - 1.0
    vol = np.log(close).diff().rolling(cfg["vol_bars"], min_periods=cfg["vol_bars"] // 2).std()
    long_ch = (donchian.position(close, entry, "lowchannel", exit_lb) > 0.5) & members
    short_ch = donchian.breakdown_position(close, entry, exit_lb) & members & ~long_ch
    budgets = cfg["budgets"]
    lb = reg["state"].map({s: budgets[s]["long"] for s in STATES}).astype(float)
    sb = reg["state"].map({s: budgets[s]["short"] for s in STATES}).astype(float)
    wl = _side(mom.where(long_ch & (mom > 0)), cfg["n_long"], vol, lb, cfg)
    ws = _side((-mom).where(short_ch & (mom < 0)), cfg["n_short"], vol, sb, cfg)
    w = wl - ws
    gross = w.abs().sum(axis=1)
    w = w.div(gross.clip(lower=1.0), axis=0)
    return w, reg
