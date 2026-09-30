from __future__ import annotations

import math

import pandas as pd

from bot.settings import Settings
from bot.strategy import Channel
from core.config import prereg


def rank_and_select(channels: dict[str, Channel], matrix: "pd.DataFrame",
                    settings: Settings) -> tuple[dict[str, Channel], dict]:
    held = {s: c for s, c in channels.items() if c.held}
    if not settings.n_positions or not settings.ranking_rule:
        return held, {"rule": None, "ranked": len(held), "kept": len(held)}
    scores = {}
    for sym in held:
        if sym not in matrix.columns:
            continue
        col = matrix[sym].dropna()
        if len(col) < settings.momentum_bars + 1:
            continue
        if settings.ranking_rule == "momentum":
            scores[sym] = float(col.iloc[-1] / col.iloc[-1 - settings.momentum_bars] - 1.0)
        elif settings.ranking_rule == "breakout":
            prior = col.iloc[:-1].tail(settings.entry_bars)
            scores[sym] = float(col.iloc[-1] / prior.max() - 1.0)
        else:
            scores[sym] = 0.0
    ordered = sorted(scores, key=scores.get, reverse=True)[: settings.n_positions]
    return ({s: held[s] for s in ordered},
            {"rule": settings.ranking_rule, "ranked": len(scores),
             "kept": len(ordered),
             "scores": {s: round(scores[s], 5) for s in ordered}})


def select_shorts(broken: dict[str, bool], channels: dict[str, Channel], n_longs: int,
                  matrix: "pd.DataFrame", settings: Settings, regime_on: bool) -> tuple[list[str], dict]:
    """The S1 sleeve's selection: breakdowns whose long channel is not live, most negative
    momentum first, filling only the slots the longs leave free. DECISIONS.md#short-paper-books
    """
    if not settings.shorts_enabled:
        return [], {}
    cfg = settings.short
    slots = int(cfg.get("slots") or settings.n_positions or settings.weight_divisor)
    free = slots if cfg.get("own_slots") else max(0, slots - n_longs)
    info = {"regime_on": regime_on, "free_slots": free, "broken": len(broken)}
    if not regime_on or free == 0:
        return [], info
    scores = {}
    for sym, on in broken.items():
        if not on or sym not in matrix.columns:
            continue
        ch = channels.get(sym)
        if ch is not None and ch.held:
            continue
        col = matrix[sym].dropna()
        if len(col) < settings.momentum_bars + 1:
            continue
        score = -float(col.iloc[-1] / col.iloc[-1 - settings.momentum_bars] - 1.0)
        if cfg.get("require_negative_momentum") and score <= 0:
            continue
        scores[sym] = score
    picked = sorted(scores, key=scores.get, reverse=True)[:free]
    info.update({"candidates": len(scores), "kept": len(picked),
                 "scores": {s: round(scores[s], 5) for s in picked}})
    return picked, info


def hold_shorts(target: dict[str, float], current: dict[str, float]) -> dict[str, float]:
    """A held short is never topped up: its target is at most its current size, as in S1."""
    out = dict(target)
    for sym, w in target.items():
        cw = current.get(sym, 0.0)
        if w < 0 and cw < 0:
            out[sym] = max(w, cw)
    return out


def target_weights(channels: dict[str, Channel], settings: Settings,
                   derisk: float = 1.0, shorts: list[str] | None = None) -> dict[str, float]:
    """Target weights for the held names.

    `full_deployment` spreads the book across whatever actually signalled
    instead of leaving (n-k)/n in cash when only k of n slots fire. Screen 2
    ranks on (Final - Initial)/Initial, so idle cash is pure drag on the metric
    that decides qualification. DECISIONS.md#full-deployment-outcome measures
    the trade: a higher right tail on both windows, bought with a deeper fit
    window drawdown. Off by default; every existing book is unchanged.

    Gross is capped on GROSS, never on a scalar - CLAUDE.md records a defect
    where capping the scalar let a book reach 1.45x against a 1x rule.
    """
    held = [s for s, c in channels.items() if c.held]
    short = [s for s in (shorts or []) if s not in held]
    k = len(held) + len(short)
    if settings.full_deployment and k:
        per = 1.0 / k
    else:
        per = 1.0 / (settings.n_positions or settings.weight_divisor)
    raw = {s: per for s in held}
    raw.update({s: -per for s in short})
    gross = sum(abs(w) for w in raw.values())
    scale = min(1.0, settings.max_gross / gross) if gross > 0 else 0.0
    return {s: math.copysign(math.floor(abs(w) * scale * derisk * 1e8) / 1e8, w)
            for s, w in raw.items()}


def deltas(target: dict[str, float], current: dict[str, float],
           equity: float, prices: dict[str, float],
           min_notional: float = 1.0,
           no_trade_band: float | None = None,
           force: set[str] | None = None) -> list[dict]:
    """Orders to move `current` to `target`.

    `no_trade_band` suppresses a rebalance whose size is inside the band,
    relative to the larger of the two weights. It defaults to the
    pre-registered portfolio.no_trade_band, which carries
    no_trade_band_is_fitted false and a grid of exactly one value.

    Without it the book chases price drift: a held position's weight moves
    with its mark, so an unchanged target still emits a small order every
    cycle. The BACKTEST never sees this, because it measures turnover as
    |w_t - w_{t-1}| on TARGET weights and never models a drifting holding.
    Five of donchian_1h's eleven closed trades on 2026-09-20 were exactly
    this, at 3 to 19 dollars a round trip, paying full fees the backtest
    never charged. DECISIONS.md#live-rebalance-chases-drift
    """
    if no_trade_band is None:
        no_trade_band = prereg()["portfolio"]["no_trade_band"]
    out = []
    for sym in sorted(set(target) | set(current)):
        tw = target.get(sym, 0.0)
        cw = current.get(sym, 0.0)
        px = prices.get(sym)
        if px is None or px <= 0:
            continue
        if tw < 0 or cw < 0:
            out.extend(_short_legs(sym, tw, cw, equity, px, min_notional, no_trade_band,
                                   sym in (force or ())))
            continue
        notional = (tw - cw) * equity
        if abs(notional) < min_notional:
            continue
        # An open or a close is never inside the band: one side is zero, so the
        # move always exceeds band * max(|tw|, |cw|). Only drift is suppressed.
        #
        # `force` exempts a symbol from the band. A booking skim is a DELIBERATE
        # trade of a declared size, not drift, and a 15% slice sits inside the
        # 25% band, so without this exemption every skim is silently suppressed
        # and the ladder never trades. DECISIONS.md#booking-flattened-the-book
        scale = max(abs(tw), abs(cw))
        if (sym not in (force or ())) and scale > 0 and abs(tw - cw) <= no_trade_band * scale:
            continue
        out.append({"symbol": sym, "side": "BUY" if notional > 0 else "SELL",
                    "target_weight": tw, "current_weight": cw,
                    "notional": round(notional, 4),
                    "quantity": abs(notional) / px, "price": px})
    return out


def _short_legs(sym: str, tw: float, cw: float, equity: float, px: float,
                min_notional: float, band: float, forced: bool) -> list[dict]:
    """Orders for a name whose current or target weight is short.

    A flip is two legs, the short closed and the long opened, never one netted order,
    because the venue keeps shorts apart from the spot wallet. The drift band applies
    only between two non-zero weights of the same sign, as in the backtest.
    DECISIONS.md#short-paper-books
    """
    legs = []
    same_short = tw < 0 and cw < 0
    if same_short and not forced and abs(tw - cw) <= band * max(abs(tw), abs(cw)):
        return legs
    s_t, s_c = max(0.0, -tw), max(0.0, -cw)
    l_t, l_c = max(0.0, tw), max(0.0, cw)
    if s_t != s_c:
        change = (s_t - s_c) * equity
        if abs(change) >= min_notional or (s_t == 0.0 and s_c > 0.0):
            legs.append({"symbol": sym, "side": "SHORT_OPEN" if change > 0 else "SHORT_CLOSE",
                         "target_weight": tw, "current_weight": cw,
                         "notional": round(-change, 4), "quantity": abs(change) / px,
                         "price": px, "close_all": s_t == 0.0 and s_c > 0.0})
    if l_t != l_c:
        change = (l_t - l_c) * equity
        if abs(change) >= min_notional:
            legs.append({"symbol": sym, "side": "BUY" if change > 0 else "SELL",
                         "target_weight": tw, "current_weight": cw,
                         "notional": round(change, 4), "quantity": abs(change) / px, "price": px})
    return legs


DUST_NOTIONAL = 10.0


def current_weights(holdings: dict[str, float], prices: dict[str, float],
                    equity: float, shorts: dict[str, dict] | None = None) -> dict[str, float]:
    """Held weights, with a lot-step residue below DUST_NOTIONAL treated as flat.

    A residue counted as held capped a re-entry at the residue's weight under the
    never-top-up rule. DECISIONS.md#execution-gaps-2026-09-23

    Shorts enter as negative weights sized by their notional at the mark.
    """
    if equity <= 0:
        return {}
    out = {s: (q * prices[s]) / equity
           for s, q in holdings.items() if s in prices and q > 0 and q * prices[s] >= DUST_NOTIONAL}
    for s, pos in (shorts or {}).items():
        qty = float(pos.get("qty", 0.0))
        if s in prices and qty > 0 and qty * prices[s] >= DUST_NOTIONAL:
            out[s] = -(qty * prices[s]) / equity
    return out


def short_value(pos: dict, price: float) -> float:
    """What a full close returns before its fee: collateral plus P&L, never below zero,
    because the venue caps a short's loss at the collateral backing it."""
    qty, entry, coll = float(pos["qty"]), float(pos["entry"]), float(pos["collateral"])
    return max(0.0, coll + qty * (entry - price))
