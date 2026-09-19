from __future__ import annotations

import pandas as pd

from bot.settings import Settings
from bot.strategy import Channel


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
    divisor = settings.n_positions or settings.weight_divisor
    raw = {s: 1.0 / divisor for s, c in channels.items() if c.held}
    gross = sum(raw.values())
    scale = min(1.0, settings.max_gross / gross) if gross > 0 else 0.0
    return {s: round(w * scale * derisk, 8) for s, w in raw.items()}


def deltas(target: dict[str, float], current: dict[str, float],
           equity: float, prices: dict[str, float],
           min_notional: float = 1.0) -> list[dict]:
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
