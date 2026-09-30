"""Acceleration book: trend on two horizons plus the change in return, long and short.

One implementation for the backtest (gates/accel.py) and the live books (bot/accel_run.py).
Every row uses closes up to that row only. DECISIONS.md#accel-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals import donchian
from signals.contenders import _in_ranges, cap_weights, stretch


def features(close: pd.DataFrame, cfg: dict) -> dict[str, pd.DataFrame]:
    """Short and mid momentum, and acceleration in units of recent volatility."""
    lc = np.log(close)
    k, mid = int(cfg["short_bars"]), int(cfg["mid_bars"])
    m_s = lc - lc.shift(k)
    m_m = lc - lc.shift(mid)
    prior = lc.shift(k) - lc.shift(2 * k)
    vol = lc.diff().rolling(mid, min_periods=mid // 2).std() * np.sqrt(k)
    acc = (m_s - prior) / vol.replace(0.0, np.nan)
    return {"m_s": m_s, "m_m": m_m, "acc": acc}


def targets(close: pd.DataFrame, members: pd.DataFrame, cfg: dict, flip: bool = False) -> pd.DataFrame:
    """Signed weights per row. Enter the top `n_enter` candidates by |acceleration|, keep a held
    name while it is still a candidate on its side and ranks within `n_keep`; weights proportional
    to |acceleration|, at most `max_weight` each, gross at most 1. `flip` is the nonsense control:
    the same trend filter with the acceleration condition reversed."""
    members = members.reindex_like(close).fillna(False).astype(bool)
    f = features(close, cfg)
    m_s, m_m, acc = f["m_s"], f["m_m"], f["acc"]
    sgn = -1.0 if flip else 1.0
    breadth_on = donchian.breadth_short_regime(close, int(cfg["mid_bars"]), float(cfg["breadth_max"]), members)
    on = np.repeat(breadth_on.reindex(close.index).fillna(False).to_numpy()[:, None], close.shape[1], axis=1)
    long_c = (members & (m_m > 0) & (m_s > 0) & (sgn * acc > 0)).to_numpy()
    short_c = (members & (m_m < 0) & (m_s < 0) & (sgn * acc < 0)).to_numpy() & on
    strength = np.abs(acc.to_numpy())
    z = stretch(close).to_numpy() if (cfg.get("skip_long_z") or cfg.get("skip_short_z")) else None
    blocked = np.zeros(close.shape, dtype=bool)
    if z is not None:
        blocked = (long_c & _in_ranges(z, cfg.get("skip_long_z"))) | (short_c & _in_ranges(z, cfg.get("skip_short_z")))
    n_enter, n_keep = int(cfg["n_enter"]), int(cfg["n_keep"])
    out = np.zeros(close.shape)
    held_side = np.zeros(close.shape[1])
    for i in range(len(close)):
        side = np.where(long_c[i], 1.0, np.where(short_c[i], -1.0, 0.0))
        score = np.where(side != 0, strength[i], np.nan)
        ok = np.isfinite(score)
        rank = np.full(len(score), np.inf)
        if ok.any():
            order = np.argsort(-np.where(ok, score, -np.inf), kind="stable")
            rank[order] = np.arange(len(order))
        keep = (held_side != 0) & (side == held_side) & (rank < n_keep)
        new = ok & ~keep & ~blocked[i]
        slots = n_enter - int(keep.sum())
        pick = keep.copy()
        if slots > 0 and new.any():
            cand = np.where(new)[0]
            cand = cand[np.argsort(rank[cand], kind="stable")][:slots]
            pick[cand] = True
        held_side = np.where(pick, side, 0.0)
        out[i] = np.where(pick, strength[i], 0.0)
    w = pd.DataFrame(out, index=close.index, columns=close.columns)
    w = w.div(w.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
    w = cap_weights(w, float(cfg["max_weight"]))
    side_df = pd.DataFrame(np.where(long_c, 1.0, -1.0), index=close.index, columns=close.columns)
    return (w * side_df).fillna(0.0)


def guard_targets(close: pd.DataFrame, members: pd.DataFrame, cfg: dict,
                  entry: int = 20, exit_lb: int = 10) -> pd.DataFrame:
    """The contenders rule with its stretch filter, plus an acceleration guard: refuse a new entry
    whose side-signed acceleration exceeds `acc_entry_max` or is at or below -`acc_exit`, and close a
    held name early when it falls to -`acc_exit`. `cfg["shorts"] = False` switches the short side off.
    DECISIONS.md#accel-guard-declaration, DECISIONS.md#short-term-shorts-off-2026-09-26"""
    members = members.reindex_like(close).fillna(False).astype(bool)
    mb = int(cfg["momentum_bars"])
    mom = close / close.shift(mb) - 1.0
    long_ch = (donchian.position(close, entry, "lowchannel", exit_lb) > 0.5) & members
    short_ch = donchian.breakdown_position(close, entry, exit_lb) & members & ~long_ch
    on = donchian.breadth_short_regime(close, mb, float(cfg["breadth_max"]), members)
    if cfg.get("shorts") is False:
        on = on & False
    on = np.repeat(on.reindex(close.index).fillna(False).to_numpy()[:, None], close.shape[1], axis=1)
    long_c = (long_ch & (mom > 0)).to_numpy()
    short_c = (short_ch & (mom < 0)).to_numpy() & on
    side_now = np.where(long_c, 1.0, np.where(short_c, -1.0, 0.0))
    strength = np.abs(mom.to_numpy())
    acc = features(close, cfg)["acc"].to_numpy()
    z = stretch(close).to_numpy()
    skip = (long_c & _in_ranges(z, cfg.get("skip_long_z"))) | (short_c & _in_ranges(z, cfg.get("skip_short_z")))
    n = int(cfg["n"])
    a_in, a_out = float(cfg["acc_entry_max"]), float(cfg["acc_exit"])
    out = np.zeros(close.shape)
    held = np.zeros(close.shape[1])
    mh = int(cfg.get("min_hold_bars") or 0)
    age = np.zeros(close.shape[1], dtype=int)
    last_str = np.zeros(close.shape[1])
    for i in range(len(close)):
        side = side_now[i].copy()
        young = (held != 0) & (age < mh)
        side = np.where(young, held, side)
        a_side = np.nan_to_num(acc[i] * side, nan=0.0)
        keep = ((held != 0) & (side == held) & (a_side > -a_out)) | young
        ok = (side != 0) & np.isfinite(strength[i])
        new = ok & ~keep & ~skip[i] & (a_side <= a_in) & (a_side > -a_out)
        pick = np.zeros(len(side), dtype=bool)
        cand = np.where(keep | new)[0]
        if len(cand):
            pick[cand[np.argsort(-strength[i][cand], kind="stable")][:n]] = True
        pick |= young
        s_i = np.where(np.isfinite(strength[i]), strength[i], last_str)
        age = np.where(pick, np.where(held != 0, age + 1, 1), 0)
        held = np.where(pick, side, 0.0)
        last_str = np.where(pick, s_i, 0.0)
        out[i] = np.where(pick, s_i, 0.0) * held
    w = pd.DataFrame(out, index=close.index, columns=close.columns)
    mag = w.abs()
    mag = mag.div(mag.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
    mag = cap_weights(mag, float(cfg["max_weight"]))
    return (mag * np.sign(w)).fillna(0.0)
