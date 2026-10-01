"""Market regime for the regime long/short book: DOWN, UP or NEUTRAL from the equal-weight pool index
and breadth over a short window, with a confirmation count so a single bar never flips the state.
Every row uses closes up to that row only. DECISIONS.md#regime-ls-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def raw(close: pd.DataFrame, cfg: dict) -> pd.Series:
    n = int(cfg["window_bars"])
    r = close.pct_change(fill_method=None)
    index_ret = np.expm1(np.log1p(r.mean(axis=1)).rolling(n).sum())
    rose = (close / close.shift(n) - 1.0) > 0
    valid = close.notna() & close.shift(n).notna()
    breadth = rose.where(valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    out = pd.Series("NEUTRAL", index=close.index)
    out[(index_ret <= float(cfg["down_return"])) & (breadth <= float(cfg["down_breadth"]))] = "DOWN"
    out[(index_ret >= float(cfg["up_return"])) & (breadth >= float(cfg["up_breadth"]))] = "UP"
    out[index_ret.isna()] = "NEUTRAL"
    return out


def state(close: pd.DataFrame, cfg: dict) -> pd.Series:
    """DOWN after `confirm_bars` consecutive raw DOWN rows; leaves DOWN after as many rows that are not.
    Outside DOWN the state is the raw label (UP or NEUTRAL)."""
    k = int(cfg["confirm_bars"])
    lab = raw(close, cfg).to_numpy()
    out = np.empty(len(lab), dtype=object)
    down, run_in, run_out = False, 0, 0
    for i, x in enumerate(lab):
        is_down = x == "DOWN"
        run_in = run_in + 1 if is_down else 0
        run_out = run_out + 1 if not is_down else 0
        if not down and run_in >= k:
            down = True
        elif down and run_out >= k:
            down = False
        out[i] = "DOWN" if down else ("NEUTRAL" if x == "DOWN" else x)
    return pd.Series(out, index=close.index)
