from __future__ import annotations

import datetime as dt

from bot.settings import Settings


def derisk_multiplier(now: dt.datetime, settings: Settings) -> float:
    start = dt.datetime.fromisoformat(settings.derisk_start_utc)
    end = dt.datetime.fromisoformat(settings.derisk_end_utc)
    if now <= start:
        return 1.0
    if now >= end:
        return 0.0
    span = (end - start).total_seconds()
    return round(1.0 - (now - start).total_seconds() / span, 4)


def drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def gate(equity_curve: list[float], error_rate: float, ticker_age_s: float,
         mirror_bps: float | None, settings: Settings) -> dict:
    """`halt` (drawdown) empties the target; `freeze` (venue errors, a stale ticker, a mirror
    breach) holds the book as it is and sends no new orders, because liquidating through a
    failing venue or at prices that cannot be trusted turns a data fault into a loss.
    DECISIONS.md#live-faults-2026-10-01"""
    breaches, soft = [], []
    dd = drawdown(equity_curve)
    if dd <= -settings.kill_max_drawdown:
        breaches.append(f"drawdown:{dd:.4f}")
    if error_rate >= settings.kill_error_rate:
        soft.append(f"error_rate:{error_rate:.3f}")
    if ticker_age_s >= settings.kill_stale_ticker_s:
        soft.append(f"stale_ticker:{ticker_age_s:.0f}s")
    if mirror_bps is not None and abs(mirror_bps) >= settings.mirror_max_deviation_bps:
        soft.append(f"mirror_deviation:{mirror_bps:.2f}bps")
    return {"halt": bool(breaches), "freeze": bool(soft) and not breaches,
            "breaches": breaches + soft, "drawdown": round(dd, 5)}
