"""Fast-clock reversal exit WITH fast-clock re-entry.

signals/exit_clock.py deliberately forbids re-entry before the next slow close:
"a position released early cannot be re-entered until the next slow close,
which is what stops the faster clock from quietly becoming a faster ENTRY clock
too". DECISIONS.md#exit-clock-outcome then records the failure mode as the book
re-entering at the next SLOW close at a higher price.

This module lifts that one constraint and changes nothing else. The slow-clock
position comes from signals.donchian.position itself rather than a
reimplementation, because a harness that rebuilds the logic it tests has
produced a false result in this repo before.

Declared at config/reversal_reentry.yaml before any backtest was run.
All slow-to-fast mapping goes through exit_clock.to_fast, which aligns on CLOSE
times; a label-matched reindex leaks up to one slow bar of future price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.donchian import position as slow_position
from signals.exit_clock import to_fast


def position(slow_close: pd.DataFrame, fast_close: pd.DataFrame, entry: int,
             exit_lb: int, reclaim_bps: float = 0.0, max_cycles: int = 1,
             rng: np.random.Generator | None = None,
             random_rate: float | None = None) -> pd.DataFrame:
    """Positions on the FAST index.

    Entries still happen only at slow closes. Within a slow bar a held position
    may be RELEASED when a fast close breaks the fixed floor, and RETAKEN when a
    fast close reclaims that floor by `reclaim_bps`, up to `max_cycles` pairs.

    `random_rate` replaces the floor test with a coin flip at that per-bar
    probability, which is the nonsense control.
    """
    held_slow = slow_position(slow_close, entry, "lowchannel", exit_lb) > 0.5
    floor = slow_close.rolling(exit_lb).min().shift(1)
    ids = pd.DataFrame(
        np.repeat(np.arange(len(slow_close), dtype=float)[:, None],
                  slow_close.shape[1], axis=1),
        index=slow_close.index, columns=slow_close.columns)

    fh = to_fast(held_slow.astype(float), slow_close.index,
                 fast_close.index).to_numpy() > 0.5
    ff = to_fast(floor, slow_close.index, fast_close.index).to_numpy(dtype=float)
    sid = to_fast(ids, slow_close.index, fast_close.index).to_numpy(dtype=float)
    fc = fast_close.to_numpy(dtype=float)

    n = fc.shape[1]
    out = np.zeros_like(fc, dtype=float)
    released = np.zeros(n, dtype=bool)
    cycles = np.zeros(n, dtype=int)
    last_id = np.full(n, -1.0)
    mult = 1.0 + reclaim_bps / 1e4

    for i in range(fc.shape[0]):
        cur = sid[i]
        new_bar = ~np.isnan(cur) & (cur != last_id)
        cycles = np.where(new_bar, 0, cycles)
        released = np.where(new_bar, False, released)
        last_id = np.where(np.isnan(cur), last_id, cur)

        live = fh[i]
        px, flo = fc[i], ff[i]
        valid = live & np.isfinite(px) & np.isfinite(flo)

        if random_rate is None:
            trigger = valid & ~released & (px < flo)
        else:
            trigger = valid & ~released & (rng.random(n) < random_rate)
        released = np.where(trigger & (cycles < max_cycles), True, released)

        reclaim = valid & released & (px > flo * mult)
        cycles = np.where(reclaim, cycles + 1, cycles)
        released = np.where(reclaim, False, released)

        out[i] = np.where(live & ~released, 1.0, 0.0)

    return pd.DataFrame(out, index=fast_close.index, columns=fast_close.columns)
