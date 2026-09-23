"""Profit-booking forward test: momentum top-3 with a skim ladder, plus an alt-data collector.

config/alpha_flow.yaml. Control is momentum_top3_full, identical in every other
respect, so the only treatment is the ladder.

The ladder skims `skim_fraction` of a position each time its mark reaches the
position's reference price times one plus `step_pct`, then resets the reference
to the mark. A runner is therefore booked repeatedly on the way up and a
position that never gains is never touched. Booked cash IDLES: it is not
recycled, because DECISIONS.md#alpha-flow-declaration measures recycling into
the same equal-weight target to be arithmetically a rebalance that only pays
fees, and recycling into lower-ranked names to be worse than holding cash.

WHAT TO WATCH: median 14-day return against the control, and mean gross. The
holdout return gain is NOT significant (p=0.14) and the drawdown gain is
reproduced by a random-timing control, so if this is only reducing exposure the
return will track the control while gross sits near 0.51.

Subclasses Bot, so cold-start suppression, the drift band, kill switches, mirror
checks, markout instrumentation and atomic state are inherited unchanged.
"""
from __future__ import annotations

import argparse
import json

import yaml

from bot.alt_data import Collector
from bot.run import Bot
from bot.settings import ROOT, load


class AlphaFlowBot(Bot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        with (ROOT / "config" / "alpha_flow.yaml").open() as fh:
            cfg = yaml.safe_load(fh)
        self.alt = Collector(cfg.get("alt_data", {}))

    def cycle(self):
        """Collect on EVERY cycle, never inside compute_target.

        compute_target runs only at a bar close once booking is on, so a
        collector living there ran once per 4h bar instead of every 15 minutes,
        silently, from 2026-09-22. The collector throttles itself and works on a
        background thread, so calling it every cycle costs nothing.
        DECISIONS.md#live-validation-2026-09-23
        """
        out = super().cycle()
        snap = self.alt.collect(sorted(self.holdings) or list(self.universe)[:6])
        if snap:
            self.journal.write("signals", {"event": "alt_data", **snap})
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = AlphaFlowBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
