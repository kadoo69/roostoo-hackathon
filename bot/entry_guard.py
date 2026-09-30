"""Live-book guards for rules whose target is the last row of a simulated path.

The rule's sticky slots and minimum hold run on the simulated path; after downtime the book
holds something else. Two guards act on the book's real positions instead.
A: on a catch-up decision (a bar skipped, or the decision more than one bar after the close)
no new position opens whose simulated entry is older than the latest bar.
B: the minimum hold counts from the bar the book really opened the position at, and keeps a
young position at its current weight and side whatever the rule's target says.
DECISIONS.md#catch-up-and-live-min-hold
"""
from __future__ import annotations

import pandas as pd

HELD_MIN = 0.01


def is_catch_up(prev_bar: pd.Timestamp | None, index: pd.DatetimeIndex, now: pd.Timestamp,
                step: pd.Timedelta) -> bool:
    if len(index) < 2 or prev_bar is None:
        return False
    return prev_bar < index[-2] or now - (index[-1] + step) > step


def drop_stale_entries(target: dict[str, float], current: dict[str, float],
                       prev_row: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    out, dropped = {}, []
    for s, w in target.items():
        held = current.get(s, 0.0) * w > 0 and abs(current.get(s, 0.0)) >= HELD_MIN
        if not held and prev_row.get(s, 0.0) * w > 0:
            dropped.append(s)
            continue
        out[s] = w
    return out, sorted(dropped)


def update_opened(opened: dict[str, list], current: dict[str, float],
                  bar: str | None) -> dict[str, list]:
    """`opened[s] = [bar, side]` for every real position; a new or flipped position is stamped
    with `bar`, the decision bar its order was sent on."""
    out = {}
    for s, w in current.items():
        if abs(w) < HELD_MIN:
            continue
        side = 1 if w > 0 else -1
        rec = opened.get(s)
        out[s] = rec if rec and rec[1] == side else [bar, side]
    return out


def keep_young(target: dict[str, float], current: dict[str, float], opened: dict[str, list],
               bar: pd.Timestamp, step: pd.Timedelta, min_bars: int,
               max_gross: float = 1.0) -> tuple[dict[str, float], list[str]]:
    """Young positions stay at their current weight and side; the rest of the target is scaled
    so gross stays within `max_gross`."""
    kept = {}
    for s, (at, side) in opened.items():
        if at is None or min_bars <= 0:
            continue
        age = (bar - pd.Timestamp(at)) / step
        w = current.get(s, 0.0)
        if age < min_bars and w * side > 0 and target.get(s, 0.0) * side <= 0:
            kept[s] = w
    if not kept:
        return target, []
    rest = {s: w for s, w in target.items() if s not in kept}
    room = max(0.0, max_gross - sum(abs(w) for w in kept.values()))
    gross = sum(abs(w) for w in rest.values())
    scale = min(1.0, room / gross) if gross > 0 else 1.0
    return {**{s: w * scale for s, w in rest.items()}, **kept}, sorted(kept)


class GuardedTarget:
    """Mixin for Bot subclasses that keep `self.matrix`: records the previous processed bar and
    applies A and B to a target built from the rule's weight matrix `w`."""

    def bar_close_due(self, matrix: pd.DataFrame) -> bool:
        self.matrix = matrix
        prev = self.last_bar
        due = super().bar_close_due(matrix)
        if due:
            self.prev_processed = prev
        return due

    def current_weights(self, prices: dict[str, float]) -> dict[str, float]:
        from bot import portfolio
        equity = self.equity_curve[-1] if self.equity_curve else 0.0
        return portfolio.current_weights(self.holdings, prices, equity, self.shorts) if equity > 0 else {}

    def guard(self, target: dict[str, float], w: pd.DataFrame, prices: dict[str, float],
              min_bars: int) -> dict[str, float]:
        m = self.matrix
        step = pd.Timedelta(self.s.interval.replace("m", "min"))
        bar = m.index[-1]
        current = self.current_weights(prices)
        self.opened = update_opened(getattr(self, "opened", {}), current, getattr(self, "last_decision_bar", None))
        now = pd.Timestamp.now(tz="UTC")
        if is_catch_up(getattr(self, "prev_processed", None), m.index, now, step) and len(w) > 1:
            prev_row = {s: float(v) for s, v in w.iloc[-2].items() if abs(v) > 1e-9}
            target, dropped = drop_stale_entries(target, current, prev_row)
            if dropped:
                self.journal.write("signals", {"event": "stale_entry_blocked", "bar": str(bar),
                                               "prev_processed": str(getattr(self, "prev_processed", None)),
                                               "symbols": dropped,
                                               "ref": "DECISIONS.md#catch-up-and-live-min-hold"})
        if min_bars:
            target, kept = keep_young(target, current, self.opened, bar, step, min_bars)
            if kept:
                self.journal.write("signals", {"event": "live_min_hold", "bar": str(bar), "kept": kept,
                                               "opened": {s: self.opened[s] for s in kept},
                                               "ref": "DECISIONS.md#catch-up-and-live-min-hold"})
        self.last_decision_bar = str(bar)
        return target
