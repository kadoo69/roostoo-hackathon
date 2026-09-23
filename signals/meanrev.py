"""Intraday mean-reversion entries with volatility-scaled bracket exits.

The trend families in this repo are weight-vector simulations: a position is a
number that changes on a bar close, and cost is turnover times a fee. A bracket
order cannot be expressed that way. A take-profit and a stop-loss both live
INSIDE the bar, the one that fills depends on the path the price took, and the
holding period is therefore an output rather than an input. So this module
simulates trades, not weights.

Declared at config/scalp_meanrev.yaml before any backtest was run.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

AGG = {"open": "first", "high": "max", "low": "min", "close": "last",
       "quote_volume": "sum"}
RULE = {"5m": None, "15m": "15min", "30m": "30min", "1h": "1h"}
BARS_PER_DAY = {"5m": 288, "15m": 96, "30m": 48, "1h": 24}


@dataclass(frozen=True)
class Params:
    entry_z: float
    tp_atr: float
    sl_atr: float
    lookback_bars: int = 48
    atr_bars: int = 48
    max_hold_bars: int = 24


def bars(path: str, interval: str) -> pd.DataFrame:
    d = pd.read_parquet(path, columns=["open_time", "open", "high", "low",
                                       "close", "quote_volume"])
    d = d.set_index("open_time").sort_index()
    d = d[~d.index.duplicated(keep="last")]
    if RULE[interval] is not None:
        d = d.resample(RULE[interval]).agg(AGG).dropna(subset=["close"])
    return d


def zscore(close: pd.Series, lookback: int) -> pd.Series:
    """Deviation from the trailing mean, in trailing standard deviations.

    Both moments are taken on the window ENDING at the current bar, which is
    known at that bar's close. The entry then fills at the next bar's open, so
    nothing here is available earlier than it would have been live.
    """
    mean = close.rolling(lookback).mean()
    std = close.rolling(lookback).std(ddof=1)
    return (close - mean) / std.replace(0.0, np.nan)


def atr_pct(d: pd.DataFrame, lookback: int) -> pd.Series:
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"],
                    (d["high"] - prev).abs(),
                    (d["low"] - prev).abs()], axis=1).max(axis=1)
    return (tr.rolling(lookback).mean() / d["close"]).replace(0.0, np.nan)


def trades(d: pd.DataFrame, p: Params, same_bar: str = "stop",
           entries: np.ndarray | None = None) -> pd.DataFrame:
    """One long trade per oversold signal, exited by bracket or time stop.

    Entry fills at the open of the bar AFTER the signal bar. Exits are checked
    against each subsequent bar's high and low. When a single bar touches both
    brackets the STOP is taken, because the bar gives no information about which
    came first and the optimistic reading invents edge.
    """
    z = zscore(d["close"], p.lookback_bars)
    a = atr_pct(d, p.atr_bars)
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    lo = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    zz = z.to_numpy(float)
    aa = a.to_numpy(float)
    idx = d.index
    n = len(d)

    out = []
    i = 0
    while i < n - 1:
        fire = (zz[i] <= -p.entry_z) if entries is None else bool(entries[i])
        if not fire or not np.isfinite(aa[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = o[entry_i]
        if not np.isfinite(entry) or entry <= 0:
            i += 1
            continue
        tp = entry * (1.0 + p.tp_atr * aa[i])
        sl = entry * (1.0 - p.sl_atr * aa[i])
        last = min(entry_i + p.max_hold_bars, n - 1)
        exit_i, exit_px, reason = last, c[last], "time"
        for j in range(entry_i, last + 1):
            hit_sl = lo[j] <= sl
            hit_tp = h[j] >= tp
            if hit_sl and hit_tp:
                if same_bar == "stop":
                    exit_i, exit_px, reason = j, sl, "stop"
                else:
                    exit_i, exit_px, reason = j, tp, "target"
                break
            if hit_sl:
                exit_i, exit_px, reason = j, sl, "stop"
                break
            if hit_tp:
                exit_i, exit_px, reason = j, tp, "target"
                break
        out.append({"entry_ts": idx[entry_i], "exit_ts": idx[exit_i],
                    "entry": entry, "exit": exit_px, "reason": reason,
                    "bars_held": exit_i - entry_i + 1,
                    "gross_ret": exit_px / entry - 1.0,
                    "z": zz[i], "atr_pct": aa[i]})
        i = exit_i + 1                      # no pyramiding into the same name
    return pd.DataFrame(out)


def book_returns(per_symbol: dict[str, pd.DataFrame], index: pd.DatetimeIndex,
                 weight: float, max_concurrent: int,
                 fee_bps: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Convert per-name trades into a portfolio return series on `index`.

    A trade's P&L is spread evenly across the bars it was held, which is the
    same convention the trend gates use when they mark a position to the bar
    close. Fees are charged in full on the entry bar and the exit bar.
    Concurrency is capped by dropping trades that would exceed the cap, taking
    them in timestamp order, so the cap binds the way it would live.
    """
    rows = []
    for sym, t in per_symbol.items():
        if t.empty:
            continue
        rows.append(t.assign(symbol=sym))
    if not rows:
        z = pd.Series(0.0, index=index)
        return z, z.copy(), z.copy()
    allt = pd.concat(rows).sort_values("entry_ts").reset_index(drop=True)

    # Positional slicing, not boolean masks. A mask over the full index per
    # trade is O(trades x bars) and made a 5m sweep unrunnable: 16k trades
    # against a 210k-bar index is 3.4e9 element comparisons for what is really
    # 16k contiguous slices.
    n = len(index)
    a = index.searchsorted(allt["entry_ts"].to_numpy(), side="left")
    b = index.searchsorted(allt["exit_ts"].to_numpy(), side="right")
    pos = np.zeros(n, dtype=np.int32)
    gross = np.zeros(n, dtype=float)
    cost = np.zeros(n, dtype=float)
    ret = allt["gross_ret"].to_numpy(float)
    per_leg = weight * fee_bps / 1e4
    for k in range(len(allt)):
        i0, i1 = int(a[k]), int(b[k])
        if i1 <= i0 or i0 >= n:
            continue
        if pos[i0:i1].max() >= max_concurrent:
            continue
        pos[i0:i1] += 1
        gross[i0:i1] += weight * ret[k] / (i1 - i0)
        cost[i0] += per_leg
        cost[min(i1 - 1, n - 1)] += per_leg
    g = pd.Series(gross, index=index)
    c = pd.Series(cost, index=index)
    return g - c, g, c
