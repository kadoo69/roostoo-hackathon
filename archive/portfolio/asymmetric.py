from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config import prereg

BPS = 1e-4


@dataclass(frozen=True)
class Params:
    stop_atr: float
    trail_atr: float
    vol_target_daily: float
    daily_loss_breaker: float
    cash_buffer: float
    max_gross: float
    bars_per_day: float
    fee_rate: float


def _vol_scalar(history: list[float], target_bar_vol: float, window: int) -> float:
    if len(history) < window:
        return 1.0
    realised = float(np.std(history[-window:]))
    if realised <= 0:
        return 1.0
    return min(target_bar_vol / realised, 1.0)


def simulate(panel: dict[str, pd.DataFrame], target: pd.DataFrame,
             atr: pd.DataFrame, spread_bps: pd.DataFrame, p: Params) -> dict:
    cols = target.columns
    close = panel["close"][cols].to_numpy(float)
    high = panel["high"][cols].to_numpy(float)
    low = panel["low"][cols].to_numpy(float)
    open_ = panel["open"][cols].to_numpy(float)
    tgt = target.to_numpy(float)
    a = atr[cols].to_numpy(float)
    half = spread_bps[cols].reindex(target.index).to_numpy(float)
    n_bars, n_sym = close.shape

    pos = np.zeros(n_sym)
    stop = np.full(n_sym, np.nan)
    peak = np.full(n_sym, np.nan)
    day_index = target.index.normalize()

    net = np.zeros(n_bars)
    turn = np.zeros(n_bars)
    stopped = np.zeros(n_bars)
    hist: list[float] = []
    vol_window = max(int(round(p.bars_per_day * 20)), 10)
    target_bar_vol = p.vol_target_daily / np.sqrt(p.bars_per_day)

    day_pnl = 0.0
    current_day = day_index[0]
    halted = False

    for t in range(1, n_bars):
        if day_index[t] != current_day:
            current_day, day_pnl, halted = day_index[t], 0.0, False

        prev_close = close[t - 1]
        held = pos != 0
        realised = np.zeros(n_sym)

        if held.any():
            long_hit = held & (pos > 0) & np.isfinite(stop) & (low[t] <= stop)
            short_hit = held & (pos < 0) & np.isfinite(stop) & (high[t] >= stop)
            gap_long = np.where(np.isfinite(open_[t]), np.fmin(stop, open_[t]), stop)
            gap_short = np.where(np.isfinite(open_[t]), np.fmax(stop, open_[t]), stop)
            exit_px = np.where(long_hit, gap_long,
                               np.where(short_hit, gap_short, close[t]))
            valid = np.isfinite(prev_close) & (prev_close > 0) & np.isfinite(exit_px)
            realised = np.where(valid, exit_px / np.where(valid, prev_close, 1.0) - 1.0, 0.0)

            gain = np.where(pos > 0, high[t], low[t])
            peak = np.where(held & np.isfinite(gain),
                            np.where(pos > 0, np.fmax(peak, gain), np.fmin(peak, gain)),
                            peak)
            trail = np.where(pos > 0, peak - p.trail_atr * a[t], peak + p.trail_atr * a[t])
            stop = np.where(held & np.isfinite(trail),
                            np.where(pos > 0, np.fmax(stop, trail), np.fmin(stop, trail)),
                            stop)
            stop = np.where(held & np.isfinite(close[t]),
                            np.where(pos > 0, np.fmin(stop, close[t]),
                                     np.fmax(stop, close[t])),
                            stop)

            exited = long_hit | short_hit
            stopped[t] = exited.sum()

        bar_pnl = float(np.nansum(pos * realised))

        if held.any():
            pos = np.where(exited, 0.0, pos)
            stop = np.where(exited, np.nan, stop)
            peak = np.where(exited, np.nan, peak)
        net[t] = bar_pnl
        day_pnl += bar_pnl
        hist.append(bar_pnl)

        if day_pnl <= -p.daily_loss_breaker:
            halted = True
        if halted:
            turn[t] += float(np.abs(pos).sum())
            pos = np.zeros(n_sym)
            stop = np.full(n_sym, np.nan)
            peak = np.full(n_sym, np.nan)
            continue

        want = np.nan_to_num(tgt[t])
        scalar = _vol_scalar(hist, target_bar_vol, vol_window)
        want = want * scalar
        gross = np.abs(want).sum()
        cap = p.max_gross * (1.0 - p.cash_buffer)
        if gross > cap and gross > 0:
            want = want * (cap / gross)

        opened = (np.sign(want) != np.sign(pos)) & (want != 0)
        delta = np.abs(want - pos)
        turn[t] += float(delta.sum())

        stop = np.where(opened & np.isfinite(a[t]),
                        np.where(want > 0,
                                 np.fmin(close[t] - p.stop_atr * a[t], close[t]),
                                 np.fmax(close[t] + p.stop_atr * a[t], close[t])), stop)
        peak = np.where(opened, close[t], peak)
        flat = want == 0
        stop = np.where(flat, np.nan, stop)
        peak = np.where(flat, np.nan, peak)
        pos = want

        cost_bps = p.fee_rate / BPS + np.nan_to_num(half[t])
        net[t] -= float(np.nansum(delta * cost_bps) * BPS)

    idx = target.index
    return {
        "net": pd.Series(net, index=idx),
        "turnover": pd.Series(turn, index=idx),
        "stops_hit": pd.Series(stopped, index=idx),
    }


def screen3(perf: dict) -> float:
    cfg = prereg()["objective"]
    w = cfg["weights"]
    parts = {
        "sortino": min(perf["sortino"], cfg["sortino_cap"]),
        "sharpe": min(perf["sharpe"], cfg["sharpe_cap"]),
        "calmar": min(perf["calmar"], cfg["calmar_cap"]),
    }
    return float(sum(w[k] * (v if np.isfinite(v) else 0.0) for k, v in parts.items()))
