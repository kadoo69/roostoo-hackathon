"""Acceleration-guard paper books: the contenders rule plus an acceleration entry guard and early exit.

Subclasses Bot and overrides only the target (through `bot.entry_guard.GuardedTarget`, which
applies the catch-up entry guard and the live minimum hold), so cold-start suppression, the drift band, kill
switches, mirror checks, the ladder (both sides), markouts and atomic state are inherited.
The live target is the last row of the same `signals.acceleration.guard_targets` the backtest scores.
DECISIONS.md#accel-guard-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import pandas as pd
import yaml

from bot.entry_guard import GuardedTarget
from bot.run import Bot
from bot.settings import ROOT, load
from signals import acceleration


class AccelBot(GuardedTarget, Bot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        with (ROOT / "config" / f"{settings.name}.yaml").open() as fh:
            self.cc = yaml.safe_load(fh)["accel"]
        self.matrix = pd.DataFrame()

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        members = pd.DataFrame(True, index=m.index, columns=m.columns)
        w = acceleration.guard_targets(m, members, {**self.cc, "shorts": self.s.shorts_enabled},
                                       self.s.entry_bars, self.s.exit_bars)
        last = w.iloc[-1]
        self.journal.write("signals", {"event": "accel_guard", "bar": str(m.index[-1]),
                                       "target": {s: round(float(v), 5) for s, v in last.items() if abs(v) > 1e-9}})
        target = {s: math.copysign(math.floor(abs(float(v)) * derisk * 1e8) / 1e8, float(v))
                  for s, v in last.items() if abs(v) > 1e-9}
        return self.guard(target, w, prices, int(self.cc.get("min_hold_bars") or 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = AccelBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
