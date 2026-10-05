"""Live-book guards for rules whose target is the last row of a simulated path.

The rule's sticky slots and minimum hold run on the simulated path; after downtime the book
holds something else. Two guards act on the book's real positions instead.
A: on every decision, no new position opens whose simulated entry is older than the latest bar,
except an entry the previous on-time decision wanted and did not fill (its retry). Guarding only
catch-up and first decisions let a blocked name be bought one bar later
(`#restart-stale-entry-2026-10-01`, `#stale-rebuy-2026-10-01`).
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
               max_gross: float = 1.0, no_trim: bool = False) -> tuple[dict[str, float], list[str]]:
    """Young positions stay at their current weight and side; the rest of the target is scaled
    so gross stays within `max_gross`. With `no_trim` a young position is also kept when the
    target only shrinks it (DECISIONS.md#live-hold-no-trim-2026-10-05)."""
    kept = {}
    for s, (at, side) in opened.items():
        if at is None or min_bars <= 0:
            continue
        age = (bar - pd.Timestamp(at)) / step
        w = current.get(s, 0.0)
        t = target.get(s, 0.0)
        if age < min_bars and w * side > 0 and (t * side <= 0 or (no_trim and abs(t) < abs(w))):
            kept[s] = w
    if not kept:
        return target, []
    return fit_new_entries(target, current, kept, max_gross), sorted(kept)


def protect_losses(target: dict[str, float], current: dict[str, float], prices: dict[str, float],
                   entries: dict[str, float], max_loss: float,
                   max_gross: float = 1.0, no_floor: frozenset[str] | set[str] = frozenset()) -> tuple[dict[str, float], list[str]]:
    """A long the target would sell or shrink is kept at its current weight while its price is below
    its entry but no more than `max_loss` below it; the rest of the target is scaled to fit `max_gross`.
    Past `max_loss`, or at or above entry, the rule's target stands; a symbol in `no_floor` is kept at any
    depth below entry. DECISIONS.md#live-no-loss-exit-2026-10-05, DECISIONS.md#ena-no-floor-2026-10-05"""
    kept = {}
    for s, w in current.items():
        e, px = entries.get(s), prices.get(s)
        if w < HELD_MIN or not e or not px:
            continue
        if target.get(s, 0.0) < w and px < e and (s in no_floor or px >= e * (1.0 - max_loss)):
            kept[s] = w
    if not kept:
        return target, []
    return fit_new_entries(target, current, kept, max_gross), sorted(kept)


def fit_new_entries(target: dict[str, float], current: dict[str, float], kept: dict[str, float],
                    max_gross: float) -> dict[str, float]:
    """Kept positions and every name already held stay at their target weight; only names not yet held
    (new entries) are scaled to fit the room left under `max_gross`, so a guard can never shrink a held
    position by crowding (21:00 IST 2026-10-05 sold FIL and ENA that way).
    DECISIONS.md#guard-crowding-fix-2026-10-05"""
    out = {**target, **kept}
    held = {s for s, w in current.items() if abs(w) >= HELD_MIN}
    fixed = {s: w for s, w in out.items() if s in kept or s in held}
    new = {s: w for s, w in out.items() if s not in fixed}
    room = max(0.0, max_gross - sum(abs(w) for w in fixed.values()))
    gross = sum(abs(w) for w in new.values())
    scale = min(1.0, room / gross) if gross > 0 else 1.0
    return {**{s: w * scale for s, w in new.items()}, **fixed}


def seed_now(cfg: dict, bar: pd.Timestamp, current: dict[str, float]) -> bool:
    """True only on the decision for `cfg["seed_bar"]`: that one decision buys the rule's whole
    current target instead of only its fresh entries (guard A off once); held names stay as they are.
    DECISIONS.md#competition-r4-seed-2026-10-05"""
    seed = cfg.get("seed_bar")
    return bool(seed) and pd.Timestamp(seed) == pd.Timestamp(bar)


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
        first = not getattr(self, "guard_seen_decision", False)
        self.guard_seen_decision = True
        late = first or is_catch_up(getattr(self, "prev_processed", None), m.index, now, step)
        if seed_now(getattr(self, "cc", None) or {}, bar, current):
            self.journal.write("signals", {"event": "seed_entry", "bar": str(bar), "target": target,
                                           "ref": "DECISIONS.md#competition-r4-seed-2026-10-05"})
        elif len(w) > 1:
            retry = set() if late else set(getattr(self, "pending_entries", {}) or {})
            prev_row = {s: float(v) for s, v in w.iloc[-2].items() if abs(v) > 1e-9 and s not in retry}
            target, dropped = drop_stale_entries(target, current, prev_row)
            if dropped:
                self.journal.write("signals", {"event": "stale_entry_blocked", "bar": str(bar),
                                               "prev_processed": str(getattr(self, "prev_processed", None)),
                                               "symbols": dropped, "late": late,
                                               "ref": "DECISIONS.md#stale-rebuy-2026-10-01"})
        if min_bars:
            target, kept = keep_young(target, current, self.opened, bar, step, min_bars,
                                      no_trim=bool((getattr(self, "cc", None) or {}).get("live_hold_no_trim")))
            if kept:
                self.journal.write("signals", {"event": "live_min_hold", "bar": str(bar), "kept": kept,
                                               "opened": {s: self.opened[s] for s in kept},
                                               "ref": "DECISIONS.md#catch-up-and-live-min-hold"})
        max_loss = (getattr(self, "cc", None) or {}).get("live_no_loss_exit_max")
        if max_loss is not None:
            no_floor = set((getattr(self, "cc", None) or {}).get("live_hold_below_cost") or [])
            target, held = protect_losses(target, current, prices, self.entry_prices(), float(max_loss),
                                          no_floor=no_floor)
            if held:
                self.journal.write("signals", {"event": "loss_hold", "bar": str(bar), "kept": held,
                                               "ref": "DECISIONS.md#live-no-loss-exit-2026-10-05"})
        self.last_decision_bar = str(bar)
        return target

    def entry_prices(self) -> dict[str, float]:
        """Average cost of each open long from the book's own fills (`bot.blotter`); empty on any
        read failure, which leaves the rule's exits in force."""
        try:
            from bot.blotter import build
            lots: dict[str, list[float]] = {}
            for lot in build(self.s.name).get("open") or []:
                acc = lots.setdefault(lot["symbol"], [0.0, 0.0])
                acc[0] += float(lot.get("qty") or 0.0)
                acc[1] += float(lot.get("cost_basis") or 0.0)
            return {s: c / q for s, (q, c) in lots.items() if q > 0}
        except Exception as exc:                                  # noqa: BLE001
            self.journal.write("errors", {"event": "entry_prices_failed", "error": repr(exc)[:200]})
            return {}
