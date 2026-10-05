"""Strongest-contender short-term books: top 3 across both sides, sized by strength.

Subclasses Bot and overrides only the target (through `bot.entry_guard.GuardedTarget`, which
applies the catch-up entry guard and the live minimum hold), so cold-start suppression, the drift band, kill
switches, mirror checks, the ladder (both sides), markouts and atomic state are inherited.
The live target is the last row of the same `signals.contenders.targets` the backtest scores.
DECISIONS.md#lowtf-contenders-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import pandas as pd
import yaml

from bot import feed
from bot.entry_guard import GuardedTarget
from bot.run import Bot
from bot.settings import ROOT, load
from signals import contenders


class ContendersBot(GuardedTarget, Bot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        with (ROOT / "config" / f"{settings.name}.yaml").open() as fh:
            self.cc = yaml.safe_load(fh)["contenders"]
        self.matrix = pd.DataFrame()

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        members = pd.DataFrame(True, index=m.index, columns=m.columns)
        entry_ok = None
        if contenders.needs_confirmation(self.cc):
            frames = feed.bar_frame(list(m.columns), self.s.interval, len(m) + 1)
            qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in frames.items() if len(f)})
            c4 = feed.close_matrix(feed.bar_frame(list(m.columns), "4h", 60))
            entry_ok = contenders.entry_confirmation(m, qv, c4, self.cc)
        short_on = pd.Series(False, index=m.index) if not self.s.shorts_enabled else None
        w = contenders.targets(m, members, self.cc, self.s.entry_bars, self.s.exit_bars,
                               short_on=short_on, entry_ok=entry_ok)
        last = w.iloc[-1]
        self.journal.write("signals", {"event": "contenders", "bar": str(m.index[-1]),
                                       "target": {s: round(float(v), 5) for s, v in last.items() if abs(v) > 1e-9}})
        target = {s: float(v) for s, v in last.items() if abs(v) > 1e-9}
        if self.cc.get("absorb_idle"):
            target = absorb_idle(target, self.current_weights(prices), float(self.cc["max_weight"]))
        target = {s: math.copysign(math.floor(abs(v) * derisk * 1e8) / 1e8, v) for s, v in target.items()}
        return self.guard(target, w, prices, live_min_hold(self.cc))


def live_min_hold(cc: dict) -> int:
    """Bars a live position is kept after its entry whatever the rule's target says (guard B):
    `live_min_hold_bars` when set, which leaves the rule's own path untouched, else `min_hold_bars`.
    DECISIONS.md#live-min-hold-6h-2026-10-05"""
    v = cc.get("live_min_hold_bars")
    return int(v if v is not None else (cc.get("min_hold_bars") or 0))


def absorb_idle(target: dict[str, float], current: dict[str, float], cap: float) -> dict[str, float]:
    """New entries take the cash left idle after held positions (which are never topped up) and
    the new entries' own targets, in proportion to those targets, each at most `cap`.
    DECISIONS.md#idle-cash-new-entry-declaration"""
    held = {s: w for s, w in target.items() if current.get(s, 0.0) * w > 0}
    fresh = {s: w for s, w in target.items() if s not in held}
    if not fresh:
        return target
    used = sum(min(abs(w), abs(current[s])) for s, w in held.items()) + sum(abs(w) for w in fresh.values())
    idle = 1.0 - used
    if idle <= 1e-9:
        return target
    base = sum(abs(w) for w in fresh.values())
    out = dict(target)
    for s, w in fresh.items():
        out[s] = math.copysign(min(cap, abs(w) + idle * abs(w) / base), w)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = ContendersBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
