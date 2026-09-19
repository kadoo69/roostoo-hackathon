from __future__ import annotations

from bot.settings import Settings
from bot.strategy import Channel


def target_weights(channels: dict[str, Channel], settings: Settings,
                   derisk: float = 1.0) -> dict[str, float]:
    raw = {s: 1.0 / settings.weight_divisor
           for s, c in channels.items() if c.held}
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
