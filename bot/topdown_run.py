"""Top-down long/short paper book. config/topdown_ls.yaml, rule in signals/topdown.py.

Subclasses Bot and overrides only the target, so cold-start suppression, the drift band, kill
switches, mirror checks, the ladder (both sides here), markouts and atomic state are inherited.
The live target is the last row of the same `signals.topdown.targets` the backtest scores.
DECISIONS.md#topdown-ls-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import pandas as pd
import yaml

from bot.run import Bot
from bot.settings import ROOT, load
from signals import topdown


class TopDownBot(Bot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        with (ROOT / "config" / f"{settings.name}.yaml").open() as fh:
            self.td = yaml.safe_load(fh)["topdown"]
        self.matrix = pd.DataFrame()
        self.last_regime: dict = {}

    def bar_close_due(self, matrix: pd.DataFrame) -> bool:
        self.matrix = matrix
        return super().bar_close_due(matrix)

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        members = pd.DataFrame(True, index=m.index, columns=m.columns)
        w, reg = topdown.targets(m, members, self.regime_closes(m), self.td,
                                 self.s.entry_bars, self.s.exit_bars)
        last = w.iloc[-1]
        r = reg.iloc[-1]
        self.last_regime = {"bar": str(m.index[-1]), "state": str(r["state"]),
                            "breadth": round(float(r["breadth"]), 3), "btc_up": bool(r["btc_up"])}
        self.journal.write("signals", {"event": "topdown", **self.last_regime,
                                       "target": {s: round(float(v), 5) for s, v in last.items() if abs(v) > 1e-9}})
        return {s: math.copysign(math.floor(abs(float(v)) * derisk * 1e8) / 1e8, float(v))
                for s, v in last.items() if abs(v) > 1e-9}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = TopDownBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
