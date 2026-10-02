"""Fade a move driven by aggressive taker flow, with a scalper's payoff shape.

Declared at config/scalper_v1.yaml. Two independent sources motivate the
conditioner: DECISIONS.md#flow-scalp-outcome and arXiv:2608.21888 both find
short-horizon reversal concentrating after taker-driven moves and growing with
flow intensity.

What differs from #flow-scalp-outcome is the PAYOFF SHAPE. That sweep used a
1.5 ATR target against a 1.0 ATR stop and its median trade lost money. Here the
target is SMALL and the stop is WIDE, with a hard time stop, which is what a
scalper actually is and which is untested in this repo.

Every position is simulated bar-by-bar on CLOSES only. No intrabar path is
claimed: a bar that would have touched both target and stop is resolved as a
stop, which is the unfavourable assumption.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    h, low, c = d["high"], d["low"], d["close"]
    pc = c.shift(1)
    tr = pd.concat([h - low, (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def trades(d: pd.DataFrame, f: pd.DataFrame, *, arm: str, ret_thresh: float,
           ofi_thresh: float, target_atr: float, stop_atr: float,
           time_stop_bars: int, cost_gate_multiple: float, round_trip_bps: float,
           cooldown_bars: int, max_per_day: int,
           rng: np.random.Generator | None = None,
           random_rate: float | None = None) -> pd.DataFrame:
    """One row per completed round trip, with net return in basis points."""
    c = d["close"].to_numpy(float)
    hi, lo = d["high"].to_numpy(float), d["low"].to_numpy(float)
    a = atr(d).to_numpy(float)
    ret = d["close"].pct_change().to_numpy(float)
    oz = f["ofi_z"].to_numpy(float)
    idx = d.index
    day = idx.normalize()

    n = len(c)
    out = []
    cooldown_until = -1
    per_day: dict = {}

    for i in range(1, n - 1):
        if i <= cooldown_until or not np.isfinite(a[i]) or a[i] <= 0:
            continue
        k = day[i]
        if per_day.get(k, 0) >= max_per_day:
            continue
        r, z = ret[i], oz[i]
        if not (np.isfinite(r) and np.isfinite(z)):
            continue

        if random_rate is not None:
            fire = rng.random() < random_rate
            side = -1 if r > 0 else 1
        elif arm == "no_flow_gate":
            fire = abs(r) >= ret_thresh
            side = -1 if r > 0 else 1
        else:
            up = (r >= ret_thresh) and (z >= ofi_thresh)
            dn = (r <= -ret_thresh) and (z <= -ofi_thresh)
            fire = up or dn
            # divergence fades the move; the sign flip rides it
            side = (-1 if up else 1) if arm == "divergence" else (1 if up else -1)
        if not fire:
            continue

        entry = c[i]
        tgt_bps = target_atr * a[i] / entry * 1e4
        if cost_gate_multiple > 0 and tgt_bps < cost_gate_multiple * round_trip_bps:
            continue

        tp = entry * (1.0 + side * target_atr * a[i] / entry)
        sl = entry * (1.0 - side * stop_atr * a[i] / entry)
        exit_px, exit_i, reason = c[min(i + time_stop_bars, n - 1)], None, "time"
        for j in range(i + 1, min(i + 1 + time_stop_bars, n)):
            hit_stop = (lo[j] <= sl) if side == 1 else (hi[j] >= sl)
            hit_tgt = (hi[j] >= tp) if side == 1 else (lo[j] <= tp)
            if hit_stop:                      # unfavourable resolution first
                exit_px, exit_i, reason = sl, j, "stop"
                break
            if hit_tgt:
                exit_px, exit_i, reason = tp, j, "target"
                break
        if exit_i is None:
            exit_i = min(i + time_stop_bars, n - 1)
            exit_px = c[exit_i]

        gross = side * (exit_px / entry - 1.0) * 1e4
        out.append({"ts": idx[i], "side": side, "entry": entry, "exit": exit_px,
                    "bars": exit_i - i, "reason": reason,
                    "gross_bps": gross, "net_bps": gross - round_trip_bps})
        per_day[k] = per_day.get(k, 0) + 1
        cooldown_until = exit_i + cooldown_bars

    return pd.DataFrame(out)
