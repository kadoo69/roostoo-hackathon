"""Burst rider: buy a coin after a 15-minute burst, book at a fixed gain, or leave after a set time.

A position opens at the close of a bar whose 3-bar return is at least `thresh_pct`, in at most `n`
names at 1/n each, one entry per coin per `cooldown_bars`. It closes at the first later bar whose
high reaches `tp_pct` above the entry close, or after `hold_bars`. The live book sells at that bar's
close, not at the target, so live and simulated results understate the resting-limit fill the
study assumed. Operator override of a failed test: DECISIONS.md#burst-rider-override-2026-09-30
With `sigma_k` set, the trigger is per coin: the 3-bar return must reach `sigma_k` times the std of
that coin's 3-bar returns over the previous `sigma_bars` bars, in place of `thresh_pct`.
DECISIONS.md#ride-z3-declaration
Simultaneous triggers are ranked by 3-bar return, or by z (return over the trigger std) with `rank_by: z`.
DECISIONS.md#ride-rank-regime-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def trigger_level(r3: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Entry threshold per bar and coin on 3-bar returns `r3`. DECISIONS.md#ride-z3-declaration"""
    if cfg.get("sigma_k"):
        n = int(cfg.get("sigma_bars", 288))
        return float(cfg["sigma_k"]) * r3.rolling(n, min_periods=n // 2).std().shift(1)
    return pd.DataFrame(float(cfg.get("thresh_pct", 2.0)) / 100, index=r3.index, columns=r3.columns)


def target_pct(cfg: dict, sd: float) -> float:
    """Take-profit as a fraction of the entry price: `tp_vol_k` x one day of the coin's own volatility at entry
    (`sd`, its std of 3-bar returns, x sqrt(96)) when set and `sd` is known, else the fixed `tp_pct`.
    DECISIONS.md#competition-vol-exits-2026-10-04"""
    if cfg.get("tp_vol_k") and np.isfinite(sd) and sd > 0:
        return float(cfg["tp_vol_k"]) * float(sd) * float(np.sqrt(96))
    return float(cfg.get("tp_pct", 2.0)) / 100


def entry_sd(r3: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The coin's std of 3-bar returns over the previous `sigma_bars` bars, as the trigger uses it."""
    n = int(cfg.get("sigma_bars", 288))
    return r3.rolling(n, min_periods=n // 2).std().shift(1)


def weights(close: pd.DataFrame, high: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    hold = int(cfg.get("hold_bars", 48))
    n = int(cfg.get("n", 3))
    cool = int(cfg.get("cooldown_bars", 12))
    c = close.to_numpy(dtype=float)
    h = high.reindex_like(close).to_numpy(dtype=float)
    r3f = close / close.shift(3) - 1.0
    r3 = r3f.to_numpy(dtype=float)
    lvl = trigger_level(r3f, cfg).to_numpy(dtype=float)
    sd = entry_sd(r3f, cfg).to_numpy(dtype=float)
    T, N = c.shape
    out = np.zeros((T, N))
    entry, tpj = np.full(N, np.nan), np.full(N, np.nan)
    age = np.zeros(N, dtype=int)
    last = np.full(N, -10**9)
    for t in range(T):
        held = ~np.isnan(entry)
        for j in np.flatnonzero(held):
            age[j] += 1
            if (np.isfinite(h[t, j]) and h[t, j] >= entry[j] * (1 + tpj[j])) or age[j] >= hold:
                entry[j] = np.nan
        held = ~np.isnan(entry)
        free = n - int(held.sum())
        if free > 0:
            key = r3[t] / (lvl[t] / float(cfg["sigma_k"])) if cfg.get("rank_by") == "z" and cfg.get("sigma_k") else r3[t]
            cand = [(key[j], j) for j in range(N)
                    if not held[j] and np.isfinite(r3[t, j]) and np.isfinite(lvl[t, j]) and r3[t, j] >= lvl[t, j] and t - last[j] >= cool]
            for _, j in sorted(cand, reverse=True)[:free]:
                entry[j], age[j], last[j], tpj[j] = c[t, j], 0, t, target_pct(cfg, sd[t, j])
        out[t] = np.where(~np.isnan(entry), 1.0 / n, 0.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def live_step(close: pd.DataFrame, high: pd.DataFrame, cfg: dict, held: dict[str, list],
              last: dict[str, str]) -> tuple[dict[str, list], dict[str, str], dict[str, float]]:
    """One decision of the ride at the last bar of `close`, from the book's real ride positions.

    A live book cannot follow `weights()`: its path fills the slots with entries the book never
    took (blocked at a start, or reshuffled as the replay window moves), and those ghost slots stop
    every new entry (`DECISIONS.md#ride-ghost-slots-2026-10-01`). Here the slots are the positions
    the book holds. `held[s] = [entry bar, entry close, target, weight]` (target and weight fixed at
    entry; a record from before targets were stored is sized from the volatility at its entry bar when
    that bar is in `close`, else `tp_pct`; a record without a weight keeps 1 / max(n, positions held),
    so a book whose `n` was lowered keeps its open positions at their size and opens new 1 / n entries
    only as weight frees: DECISIONS.md#competition-two-slots-2026-10-04), `last[s]` = the bar of the last entry
    (cooldown). Ages count bars by time, so the exit after downtime uses every bar since the entry.
    Same rule as `weights()`, bar for bar (`tests/test_burst_rider_live.py`).
    """
    hold = int(cfg.get("hold_bars", 48))
    n = int(cfg.get("n", 3))
    cool = int(cfg.get("cooldown_bars", 12))
    t = close.index[-1]
    step = close.index[-1] - close.index[-2]
    hi = high.reindex_like(close)
    r3f = close / close.shift(3) - 1.0
    sd = entry_sd(r3f, cfg)
    keep = {}
    legacy = 1.0 / max(n, len(held)) if held else 1.0 / n
    for s, rec in held.items():
        at, px = pd.Timestamp(rec[0]), float(rec[1])
        wt = float(rec[3]) if len(rec) > 3 else legacy
        if len(rec) > 2:
            tp = float(rec[2])
        else:
            tp = target_pct(cfg, float(sd.at[at, s]) if s in sd and at in sd.index else float("nan"))
        since = hi[s].loc[hi.index > at] if s in hi else pd.Series(dtype=float)
        hit = bool((since >= px * (1 + tp)).any())
        if not hit and round((t - at) / step) < hold:
            keep[s] = [str(at), px, tp, wt]
    new_last = dict(last)
    free = int((1.0 - sum(v[3] for v in keep.values()) + 1e-9) * n)
    gate = cfg.get("regime_gate") or {}
    # Broad down market: no new entry, swap or churn this bar; the exits above have already run.
    gated = bool(gate) and breadth(close, int(gate.get("bars", 288))) < float(gate["min_breadth"])
    churn = cfg.get("trim_churn") or {}
    zmax = float(churn["zmax"]) if churn.get("zmax") else None
    swap = cfg.get("repeat_swap") or {}
    if not gated and free <= 0 and swap and keep and len(close) > 3:
        keep, new_last = repeat_swap(close, cfg, keep, new_last, swap)
        free = 0
    if not gated and free > 0 and len(close) > 3:
        r3, lvl = r3f.iloc[-1], trigger_level(r3f, cfg).iloc[-1]
        cand = []
        for s, r in r3.items():
            if s in keep or not np.isfinite(r) or not np.isfinite(lvl[s]) or r < lvl[s]:
                continue
            if zmax is not None and float(r) / (float(lvl[s]) / float(cfg["sigma_k"])) >= zmax:
                continue
            if s in last and round((t - pd.Timestamp(last[s])) / step) < cool:
                continue
            score = float(r) / (float(lvl[s]) / float(cfg["sigma_k"])) if cfg.get("rank_by") == "z" and cfg.get("sigma_k") else float(r)
            cand.append((score, close.columns.get_loc(s), s))
        for _, _, s in sorted(cand, reverse=True)[:free]:
            keep[s] = [str(t), float(close[s].iloc[-1]), target_pct(cfg, float(sd[s].iloc[-1])), 1.0 / n]
            new_last[s] = str(t)
    elif not gated and free <= 0 and churn and keep and len(close) > 3:
        keep, new_last = trim_churn(close, cfg, keep, new_last, churn)
    floor = t - step * (cool + hold)
    new_last = {s: at for s, at in new_last.items() if s in keep or pd.Timestamp(at) > floor}
    return keep, new_last, {s: v[3] for s, v in keep.items()}


def breadth(close: pd.DataFrame, bars: int = 288) -> float:
    """Share of coins whose return over the last `bars` bars is positive, at the last bar (coins without the
    history are left out). The regime gate's state. DECISIONS.md#competition-regime-gate-2026-10-05"""
    if len(close) <= bars:
        return 1.0
    r = close.iloc[-1] / close.iloc[-1 - bars] - 1.0
    r = r.dropna()
    return float((r > 0).mean()) if len(r) else 1.0


def trim_churn(close: pd.DataFrame, cfg: dict, keep: dict[str, list], last: dict[str, str],
               churn: dict) -> tuple[dict[str, list], dict[str, str]]:
    """With no free slot and a fresh trigger at `sigma_k` <= z < `zmax` (outside its cooldown, not held): cut every
    holding that is below its entry and at least `min_age_bars` old by `trim` of its weight, and buy the highest-z such
    trigger with the freed weight (capped at 1/n), its target `churn_tpk` x one day of its volatility instead of
    `tp_vol_k`. Winners and young positions are untouched, nothing is sold whole, and at most `max_positions` are held.
    The same rule as `archive.gates.ride_partial_trim.book` with `churn_tpk` (PT50C, `#ride-trim-recent-outcome`).
    Operator-ordered for the competition book: DECISIONS.md#competition-trim-churn-2026-10-05"""
    t = close.index[-1]
    step = close.index[-1] - close.index[-2]
    n, cool, k = int(cfg.get("n", 3)), int(cfg.get("cooldown_bars", 12)), float(cfg["sigma_k"])
    trim, age_min = float(churn.get("trim", 0.5)), int(churn.get("min_age_bars", 12))
    zmax, max_pos = float(churn.get("zmax", 5.0)), int(churn.get("max_positions", 4))
    if len(keep) >= max_pos:
        return keep, last
    r3f = close / close.shift(3) - 1.0
    lvl = trigger_level(r3f, cfg).iloc[-1]
    r3 = r3f.iloc[-1]
    cand = []
    for s, r in r3.items():
        if s in keep or not np.isfinite(r) or not np.isfinite(lvl[s]) or lvl[s] <= 0:
            continue
        z = float(r) / (float(lvl[s]) / k)
        if z < k or z >= zmax or (s in last and round((t - pd.Timestamp(last[s])) / step) < cool):
            continue
        cand.append((z, close.columns.get_loc(s), s))
    if not cand:
        return keep, last
    losers = [s for s, v in keep.items() if s in close and np.isfinite(close[s].iloc[-1])
              and round((t - pd.Timestamp(v[0])) / step) >= age_min and float(close[s].iloc[-1]) < float(v[1])]
    if not losers:
        return keep, last
    out = {s: list(v) for s, v in keep.items()}
    freed = 0.0
    for s in losers:
        cut = out[s][3] * trim
        out[s][3] -= cut
        freed += cut
    _, _, s = max(cand)
    sd = entry_sd(r3f, cfg)
    sd_s = float(sd[s].iloc[-1])
    tp = float(churn.get("churn_tpk", 1.0)) * sd_s * float(np.sqrt(96)) if np.isfinite(sd_s) and sd_s > 0 else float(cfg.get("tp_pct", 2.0)) / 100
    out[s] = [str(t), float(close[s].iloc[-1]), tp, min(freed, 1.0 / n)]
    return out, {**last, s: str(t)}


def repeat_swap(close: pd.DataFrame, cfg: dict, keep: dict[str, list], last: dict[str, str],
                swap: dict) -> tuple[dict[str, list], dict[str, str]]:
    """With every slot held, sell the weakest holding below its entry (at least `min_age_bars` old) to buy a repeat
    trigger: a coin triggering now that also triggered between `min_gap_bars` and `window_bars` bars ago. The new
    entry takes the sold position's weight. Paper only: DECISIONS.md#ride-swap-paper-2026-10-05"""
    t = close.index[-1]
    step = close.index[-1] - close.index[-2]
    win, gap, age_min = int(swap.get("window_bars", 72)), int(swap.get("min_gap_bars", 12)), int(swap.get("min_age_bars", 12))
    cool = int(cfg.get("cooldown_bars", 12))
    r3f = close / close.shift(3) - 1.0
    lvl = trigger_level(r3f, cfg)
    hit = (r3f >= lvl)
    now = hit.iloc[-1]
    past = hit.iloc[-1 - win:-gap].any() if len(hit) > win else hit.iloc[:-gap].any()
    cand = [(float(r3f[s].iloc[-1]), s) for s in close.columns if now.get(s, False) and past.get(s, False) and s not in keep
            and not (s in last and round((t - pd.Timestamp(last[s])) / step) < cool)]
    if not cand:
        return keep, last
    rets = {s: float(close[s].iloc[-1]) / v[1] - 1 for s, v in keep.items()
            if s in close and round((t - pd.Timestamp(v[0])) / step) >= age_min}
    if not rets:
        return keep, last
    weak = min(rets, key=rets.get)
    if rets[weak] >= 0:
        return keep, last
    wt = keep[weak][3]
    _, s = max(cand)
    sd = entry_sd(r3f, cfg)
    out = {k: v for k, v in keep.items() if k != weak}
    out[s] = [str(t), float(close[s].iloc[-1]), target_pct(cfg, float(sd[s].iloc[-1])), wt]
    return out, {**last, s: str(t)}


def probe_entry(close: pd.DataFrame, cfg: dict, held: dict[str, list], last: dict[str, str],
                min_z: float) -> tuple[dict[str, list], dict[str, str], dict[str, float]]:
    """One entry on an empty ride: the coin with the highest z (3-bar return over its trigger std)
    at or above `min_z` on the last bar, outside its cooldown, held under the ride's normal exits.
    Operator-ordered once on the competition account: DECISIONS.md#competition-probe-2026-10-04"""
    if held or len(close) <= 3 or not cfg.get("sigma_k"):
        return held, last, {}
    n, cool = int(cfg.get("n", 3)), int(cfg.get("cooldown_bars", 12))
    t, step = close.index[-1], close.index[-1] - close.index[-2]
    r3f = close / close.shift(3) - 1.0
    z = (r3f.iloc[-1] / (trigger_level(r3f, cfg).iloc[-1] / float(cfg["sigma_k"]))).dropna()
    z = z[[s for s in z.index if not (s in last and round((t - pd.Timestamp(last[s])) / step) < cool)]]
    if z.empty or z.max() < min_z:
        return held, last, {}
    s = str(z.idxmax())
    tp = target_pct(cfg, float(entry_sd(r3f, cfg)[s].iloc[-1]))
    return {s: [str(t), float(close[s].iloc[-1]), tp, 1.0 / n]}, {**last, s: str(t)}, {s: 1.0 / n}
