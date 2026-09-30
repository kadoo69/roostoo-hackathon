"""Strongest contenders on both sides: rank every live signal by momentum size, hold the top N,
size by strength. One implementation for the backtest (gates/lowtf_contenders.py) and the live
books (bot/contenders_run.py). Every row uses closes up to that row only.
DECISIONS.md#lowtf-contenders-declaration
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals import donchian


def cap_weights(w: pd.DataFrame, cap: float, rounds: int = 5) -> pd.DataFrame:
    """Clip each row at `cap` and hand the excess to the uncapped names in proportion to their
    weight; what cannot be placed stays in cash."""
    for _ in range(rounds):
        clipped = w.clip(upper=cap)
        excess = (w - clipped).sum(axis=1)
        if not (excess > 1e-12).any():
            return clipped
        room = clipped.where(clipped < cap - 1e-12, 0.0)
        share = room.div(room.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
        w = clipped + share.mul(excess, axis=0)
    return w.clip(upper=cap)


def stretch(close: pd.DataFrame, bars: int = 20) -> pd.DataFrame:
    """(close - mean) / standard deviation of the close over `bars`. DECISIONS.md#lowtf-exhaustion-declaration"""
    mean = close.rolling(bars).mean()
    return (close - mean) / close.rolling(bars).std()


def _in_ranges(z: np.ndarray, ranges: list) -> np.ndarray:
    out = np.zeros(z.shape, dtype=bool)
    for lo, hi in ranges or []:
        lo = -np.inf if lo is None else lo
        hi = np.inf if hi is None else hi
        out |= (z >= lo) & (z < hi)
    return out


def _pick_with_entry_filter(close: pd.DataFrame, strength: pd.DataFrame, is_long: pd.DataFrame,
                            is_short: pd.DataFrame, cfg: dict, entry_ok: pd.DataFrame | None = None,
                            entry: int = 20) -> pd.DataFrame:
    """Top-n by strength where a name NOT held on the previous row may not enter from a skipped
    stretch bucket; a held name is never forced out by the filter. With `sticky`, a held name keeps
    its slot while it is still a candidate on its side and new names fill only free slots.
    `entry_ok` blocks new entries where False; `failed_breakout_bars` closes a position whose close
    returns through the level it broke within that many bars and bars re-entry until the channel
    resets; `time_stop_bars` is its control. DECISIONS.md#let-winners-run-declaration,
    DECISIONS.md#breakout-quality-declaration"""
    z = stretch(close).to_numpy()
    st = strength.to_numpy()
    blocked = (is_long.to_numpy() & _in_ranges(z, cfg.get("skip_long_z"))) | \
              (is_short.to_numpy() & _in_ranges(z, cfg.get("skip_short_z")))
    if entry_ok is not None:
        blocked |= ~entry_ok.reindex_like(strength).fillna(False).astype(bool).to_numpy()
    px = close.to_numpy()
    hi = close.rolling(entry).max().shift(1).to_numpy()
    lo = close.rolling(entry).min().shift(1).to_numpy()
    fb = int(cfg.get("failed_breakout_bars") or 0)
    ts = int(cfg.get("time_stop_bars") or 0)
    mh = int(cfg.get("min_hold_bars") or 0)
    hold_age = np.zeros(st.shape[1], dtype=int)
    level = np.full(st.shape[1], np.nan)
    entry_px = np.full(st.shape[1], np.nan)
    age = np.zeros(st.shape[1], dtype=int)
    barred = np.zeros(st.shape[1], dtype=bool)
    n = int(cfg["n"])
    sticky = bool(cfg.get("sticky"))
    side = np.where(is_long.to_numpy(), 1.0, np.where(is_short.to_numpy(), -1.0, 0.0)).copy()
    out = np.zeros(st.shape, dtype=bool)
    prev = np.zeros(st.shape[1], dtype=bool)
    prev_side = np.zeros(st.shape[1])
    for i in range(len(st)):
        row = st[i].copy()
        row[blocked[i] & ~prev] = np.nan
        barred &= np.isfinite(st[i]) & (side[i] != 0)
        if fb or ts:
            held_now = prev & (side[i] == prev_side)
            age = np.where(held_now, age + 1, 0)
            out_ = np.zeros(len(row), dtype=bool)
            if fb:
                back_l = (prev_side > 0) & (px[i] < level)
                back_s = (prev_side < 0) & (px[i] > level)
                out_ |= held_now & (age <= fb) & (back_l | back_s)
            if ts:
                loss = np.where(prev_side > 0, px[i] < entry_px, px[i] > entry_px)
                out_ |= held_now & (age == ts) & loss
            barred |= out_
        row[barred] = np.nan
        ok = np.isfinite(row)
        sel = np.zeros(len(row), dtype=bool)
        if sticky:
            keep = prev & ok & (side[i] == prev_side)
            sel |= keep
            free = n - int(keep.sum())
            new = ok & ~keep
            if free > 0 and new.any():
                cand = np.where(new)[0]
                sel[cand[np.argsort(-row[cand], kind="stable")][:free]] = True
        elif ok.any():
            sel[np.argsort(-np.where(ok, row, -np.inf), kind="stable")[:n]] = True
        out[i] = sel & ok
        if mh:
            young = prev & (hold_age < mh)
            out[i] |= young
            side[i] = np.where(young & ~(sel & ok), prev_side, side[i])
        hold_age = np.where(out[i], np.where(prev, hold_age + 1, 1), 0)
        fresh = out[i] & ~prev
        level = np.where(fresh, np.where(side[i] > 0, hi[i], lo[i]), np.where(out[i], level, np.nan))
        entry_px = np.where(fresh, px[i], np.where(out[i], entry_px, np.nan))
        prev = out[i]
        prev_side = np.where(prev, side[i], 0.0)
    pick = pd.DataFrame(out, index=strength.index, columns=strength.columns)
    pick.attrs["side"] = pd.DataFrame(side, index=strength.index, columns=strength.columns)
    return pick


def targets(close: pd.DataFrame, members: pd.DataFrame, cfg: dict, entry: int = 20,
            exit_lb: int = 10, short_on: pd.Series | None = None,
            entry_ok: pd.DataFrame | None = None) -> pd.DataFrame:
    """Signed weights per row: up to `n` names across both sides, weight proportional to
    |momentum| (equal across the chosen names with `equal_weight`), at most `max_weight` each,
    gross at most 1. DECISIONS.md#burst-strong-and-equal-weight-declaration"""
    members = members.reindex_like(close).fillna(False).astype(bool)
    mb = int(cfg["momentum_bars"])
    mom = close / close.shift(mb) - 1.0
    long_ch = (donchian.position(close, entry, "lowchannel", exit_lb) > 0.5) & members
    short_ch = donchian.breakdown_position(close, entry, exit_lb) & members & ~long_ch
    if cfg.get("sides") == "short":
        short_on = pd.Series(True, index=close.index)
    elif short_on is None:
        short_on = donchian.breadth_short_regime(close, mb, float(cfg["breadth_max"]), members)
    on = pd.DataFrame(np.repeat(short_on.reindex(close.index).fillna(False).to_numpy()[:, None],
                                close.shape[1], axis=1), index=close.index, columns=close.columns)
    long_s = mom.where(long_ch & (mom > 0) & (cfg.get("sides") != "short"))
    short_s = (-mom).where(short_ch & (mom < 0) & on)
    strength = long_s.combine_first(short_s)
    if (cfg.get("skip_long_z") or cfg.get("skip_short_z") or cfg.get("sticky") or entry_ok is not None
            or cfg.get("failed_breakout_bars") or cfg.get("time_stop_bars") or cfg.get("min_hold_bars")):
        pick = _pick_with_entry_filter(close, strength, long_s.notna(), short_s.notna(), cfg, entry_ok, entry)
    else:
        pick = (strength.rank(axis=1, ascending=False, method="first") <= int(cfg["n"])) & strength.notna()
    raw = strength.where(pick)
    if cfg.get("min_hold_bars"):
        raw = raw.fillna(strength.ffill().where(pick))
    if cfg.get("equal_weight"):
        raw = raw.notna().astype(float).where(raw.notna())
    w = raw.div(raw.sum(axis=1), axis=0).fillna(0.0)
    w = cap_weights(w, float(cfg["max_weight"]))
    sign = pd.DataFrame(np.where(long_s.notna(), 1.0, -1.0), index=close.index, columns=close.columns)
    if "side" in pick.attrs:
        sign = pick.attrs["side"].where(pick.attrs["side"] != 0, sign)
    return (w * sign).fillna(0.0)


def entry_confirmation(close: pd.DataFrame, quote_volume: pd.DataFrame, close4: pd.DataFrame,
                       cfg: dict) -> pd.DataFrame:
    """Where a NEW entry is allowed: the coin's 4h 20/10 channel agrees with the side its momentum
    points to (long channel for positive momentum, breakdown for negative), and the entry bar's
    quote volume is at least `volume_confirm` times its prior 20-bar median, and, with
    `prior_return_min`, the close has moved more than that fraction in the side's direction over
    `prior_return_bars` bars (the entry rides a move already under way), and, with `accel_confirm`,
    the side-signed acceleration (`signals.acceleration.features`) lies in (`min`, `max`]: the move
    is speeding up but is not a blow-off. `sides: short` makes the book short-only with its switch
    always on. DECISIONS.md#short-accel-declaration
    DECISIONS.md#breakout-quality-outcome, DECISIONS.md#burst-strong-and-equal-weight-declaration"""
    from signals.exit_clock import to_fast

    ok = pd.DataFrame(True, index=close.index, columns=close.columns)
    is_long = (close / close.shift(int(cfg["momentum_bars"])) - 1.0) > 0
    if cfg.get("htf_confirm"):
        c4 = close4.reindex(columns=close.columns)
        up = to_fast((donchian.position(c4, 20, "lowchannel", 10) > 0.5).astype(float), c4.index, close.index).fillna(0.0) > 0.5
        dn = to_fast(donchian.breakdown_position(c4, 20, 10).astype(float), c4.index, close.index).fillna(0.0) > 0.5
        ok &= (up & is_long) | (dn & ~is_long)
    if cfg.get("volume_confirm"):
        qv = quote_volume.reindex_like(close)
        ok &= qv >= float(cfg["volume_confirm"]) * qv.rolling(20, min_periods=10).median().shift(1)
    if cfg.get("prior_return_min"):
        prior = close / close.shift(int(cfg["prior_return_bars"])) - 1.0
        m = float(cfg["prior_return_min"])
        ok &= (is_long & (prior > m)) | (~is_long & (prior < -m))
    if cfg.get("accel_confirm"):
        from signals.acceleration import features

        a = cfg["accel_confirm"]
        acc = features(close, {"short_bars": a["short_bars"], "mid_bars": a["mid_bars"]})["acc"]
        a_side = acc.where(is_long, -acc)
        ok &= (a_side > float(a["min"])) & (a_side <= float(a["max"]))
    return ok


def needs_confirmation(cfg: dict) -> bool:
    return bool(cfg.get("htf_confirm") or cfg.get("volume_confirm") or cfg.get("prior_return_min")
                or cfg.get("accel_confirm"))


def reverse_on_exit(w: pd.DataFrame, close: pd.DataFrame, exit_lb: int = 10, max_bars: int = 24,
                    cap: float = 0.5) -> pd.DataFrame:
    """Add the opposite position on a coin whose held position just ended on a channel break, held
    until its own channel exit, `max_bars`, or the base rule wanting the coin again.
    DECISIONS.md#stop-and-reverse-declaration"""
    W = w.reindex_like(close).fillna(0.0).to_numpy()
    px = close.to_numpy()
    lo = close.rolling(exit_lb).min().shift(1).to_numpy()
    hi = close.rolling(exit_lb).max().shift(1).to_numpy()
    rev = np.zeros(W.shape)
    cur = np.zeros(W.shape[1])
    age = np.zeros(W.shape[1], dtype=int)
    for i in range(1, len(W)):
        prev, now = W[i - 1], W[i]
        ended = (prev != 0) & (now == 0)
        broke_l = ended & (prev > 0) & (px[i] < lo[i])
        broke_s = ended & (prev < 0) & (px[i] > hi[i])
        age = np.where(cur != 0, age + 1, 0)
        stop = ((cur < 0) & (px[i] > hi[i])) | ((cur > 0) & (px[i] < lo[i])) | (age >= max_bars) | (now != 0)
        cur = np.where(stop, 0.0, cur)
        cur = np.where(broke_l, -np.minimum(np.abs(prev), cap), cur)
        cur = np.where(broke_s, np.minimum(np.abs(prev), cap), cur)
        age = np.where(broke_l | broke_s, 0, age)
        rev[i] = cur
    out = W + rev
    gross = np.abs(out).sum(axis=1, keepdims=True)
    out = out / np.maximum(gross, 1.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)
