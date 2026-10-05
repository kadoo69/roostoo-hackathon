"""Regime long/short book: the contenders rule whose short side is switched on, and long
entries switched off, only while the market regime is DOWN (`signals.regime_ls.state`).
With `short.enabled: false` the short side stays off and only the long block acts (the R4 arm of
`#regime-competition-outcome`, `#competition-r4-2026-10-05`).
Everything else (guards, ladder, kill switches, state) is inherited from ContendersBot.
DECISIONS.md#regime-ls-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import pandas as pd
import yaml

from bot import feed
from bot.contenders_run import ContendersBot
from bot.settings import ROOT, load
from signals import contenders, regime_ls


def regime_targets(close: pd.DataFrame, qv: pd.DataFrame, close4: pd.DataFrame, cc: dict, rcfg: dict,
                   entry: int, exit_lb: int, shorts: bool = True) -> tuple[pd.DataFrame, pd.Series]:
    """Weights of the regime book on `close` and the regime per row; `shorts=False` keeps the
    long block in DOWN and never shorts."""
    reg = regime_ls.state(close, rcfg)
    down = reg == "DOWN"
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    is_long = (close / close.shift(int(cc["momentum_bars"])) - 1.0) > 0
    ok = contenders.entry_confirmation(close, qv, close4, cc) if contenders.needs_confirmation(cc) else \
        pd.DataFrame(True, index=close.index, columns=close.columns)
    block_long = pd.DataFrame(down.to_numpy()[:, None].repeat(close.shape[1], axis=1), index=close.index,
                              columns=close.columns) & is_long
    short_on = down if shorts else pd.Series(False, index=close.index)
    return contenders.targets(close, members, cc, entry, exit_lb, short_on=short_on, entry_ok=ok & ~block_long), reg


class RegimeLSBot(ContendersBot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        self.rcfg = yaml.safe_load((ROOT / "config" / f"{settings.name}.yaml").read_text())["regime"]

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        frames = feed.bar_frame(list(m.columns), self.s.interval, len(m) + 1)
        qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in frames.items() if len(f)})
        c4 = feed.close_matrix(feed.bar_frame(list(m.columns), "4h", 60))
        w, reg = regime_targets(m, qv, c4, self.cc, self.rcfg, self.s.entry_bars, self.s.exit_bars,
                                shorts=self.s.shorts_enabled)
        last = w.iloc[-1]
        self.journal.write("signals", {"event": "contenders", "bar": str(m.index[-1]), "regime": str(reg.iloc[-1]),
                                       "target": {s: round(float(v), 5) for s, v in last.items() if abs(v) > 1e-9}})
        target = {s: math.copysign(math.floor(abs(float(v)) * derisk * 1e8) / 1e8, float(v))
                  for s, v in last.items() if abs(v) > 1e-9}
        return self.guard(target, w, prices, int(self.cc.get("min_hold_bars") or 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = RegimeLSBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
