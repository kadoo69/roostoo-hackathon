from __future__ import annotations

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


def target_weights(channels: dict[str, Channel], settings: Settings,
                   derisk: float = 1.0) -> dict[str, float]:
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
    if settings.full_deployment and held:
        raw = {s: 1.0 / len(held) for s in held}
    else:
        divisor = settings.n_positions or settings.weight_divisor
        raw = {s: 1.0 / divisor for s in held}
    gross = sum(raw.values())
    scale = min(1.0, settings.max_gross / gross) if gross > 0 else 0.0
    return {s: round(w * scale * derisk, 8) for s, w in raw.items()}


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


def current_weights(holdings: dict[str, float], prices: dict[str, float],
                    equity: float) -> dict[str, float]:
    if equity <= 0:
        return {}
    return {s: (q * prices[s]) / equity
            for s, q in holdings.items() if s in prices and q > 0}
