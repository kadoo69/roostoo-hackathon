"""Donchian position with the exit clock decoupled from the entry clock.

The entry, the channel and the exit LEVEL are all computed on the slow bar and
are unchanged from the live bots. The only difference is how often the fixed
level is compared against price.

Declared at config/exit_clock.yaml before any backtest was run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _bar_seconds(idx: pd.DatetimeIndex) -> float:
    d = pd.Series(idx).diff().dt.total_seconds().dropna()
    if d.empty:
        raise ValueError("cannot infer bar length from a single-row index")
    return float(d.mode().iloc[0])


def to_fast(slow: pd.DataFrame, slow_index: pd.DatetimeIndex,
            fast_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Carry a slow-clock series onto a fast index without leaking.

    A plain `reindex(fast_index, method="ffill")` matches on LABELS, and since
    bars are labelled by open time the 4h row labelled 04:00 holds a price from
    08:00. Forward-filling it onto the 1h bar labelled 04:00 hands the caller
    three hours of the future. This aligns on close times instead, so a slow
    row only becomes visible once its bar has actually finished.
    """
    sk = slow_index + pd.Timedelta(seconds=_bar_seconds(slow_index))
    fk = fast_index + pd.Timedelta(seconds=_bar_seconds(fast_index))
    out = slow.copy()
    out.index = sk
    return out.reindex(fk, method="ffill").set_axis(fast_index)


def position(slow_close: pd.DataFrame, fast_close: pd.DataFrame, entry: int,
             exit_lb: int) -> pd.DataFrame:
    """Positions on the FAST index. Entries only at slow closes.

    At each slow bar the 20-bar high and the `exit_lb`-bar low are computed on
    closes strictly before that bar, exactly as `signals.donchian.position`
    does, so the level is identical to the live rule and is then held fixed for
    the whole slow bar.

    Inside the slow bar the fixed level is compared against each fast close.
    Only closes are used, never a fast bar's high or low, so the simulation
    makes no claim about the path inside a fast bar either. A position released
    early cannot be re-entered until the next slow close, which is what stops
    the faster clock from quietly becoming a faster ENTRY clock too.
    """
    upper = slow_close.rolling(entry).max().shift(1)
    floor = slow_close.rolling(exit_lb).min().shift(1)
    cols = slow_close.columns

    # Binance bars are labelled by OPEN time, so the 4h bar labelled 04:00
    # closes at 08:00. Mapping a fast bar onto the slow bar with the same or an
    # earlier LABEL therefore hands the simulation a price up to one slow bar
    # in the future, which is worth a Sharpe of 7.3 and is entirely fictional.
    # Align on when each bar is actually KNOWN - its close time - instead.
    slow_known = slow_close.index + pd.Timedelta(seconds=_bar_seconds(slow_close.index))
    fast_known = fast_close.index + pd.Timedelta(seconds=_bar_seconds(fast_close.index))
    pos_in_slow = slow_known.searchsorted(fast_known, side="right") - 1
    u = upper.to_numpy(float)
    f = floor.to_numpy(float)
    sp = slow_close.to_numpy(float)
    fp = fast_close.reindex(columns=cols).to_numpy(float)

    rows = len(fast_close)
    out = np.zeros((rows, len(cols)), dtype=float)
    held = np.zeros(len(cols), dtype=bool)
    stop = np.full(len(cols), np.nan)
    last_slow = -1

    for i in range(rows):
        s = int(pos_in_slow[i])
        if s < 0:
            continue
        if s != last_slow:                      # a slow bar just closed
            last_slow = s
            p, uu, ff = sp[s], u[s], f[s]
            valid = np.isfinite(p) & np.isfinite(uu) & np.isfinite(ff)
            stop = np.where(held & valid, ff, stop)
            exiting = held & valid & (p < stop)
            held &= ~exiting
            stop = np.where(exiting, np.nan, stop)
            entering = (~held) & valid & (p > uu)
            held |= entering
            stop = np.where(entering, ff, stop)
        else:                                   # inside the slow bar
            q = fp[i]
            ok = held & np.isfinite(q) & np.isfinite(stop)
            exiting = ok & (q < stop)
            held &= ~exiting
            stop = np.where(exiting, np.nan, stop)
        out[i] = held
    return pd.DataFrame(out, index=fast_close.index, columns=cols)
