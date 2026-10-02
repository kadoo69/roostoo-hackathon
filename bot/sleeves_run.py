"""Live book of separately accounted sleeves: the competition rule and the momentum ride, half each.

Every 5m decision: the rule's target comes from the 30m contenders path (a coin enters only on the
bar its path opened it, never late), the ride's from `burst_rider.live_step` on the sleeve's own
positions; `bot.sleeves` advances each sleeve's ledger at the current marks, rescales them to the real
account equity, and the account target is the sum of the sleeves' units. The account-level profit
ladder must be off (each sleeve runs its own). State: `live/<book>/sleeves.json`, kept as before and
after the last decided bar so a re-decided bar starts from the same state.
DECISIONS.md#sleeves-declaration
"""
from __future__ import annotations

import argparse
import json

import yaml

from bot import feed, sleeves
from bot.scalper_adaptive_run import (AdaptiveScalperBot, bars_needed, build_variants, load_clock,
                                      variant_weights)
from bot.settings import ROOT, load
from signals import burst_rider
from signals.exit_clock import to_fast


class SleevesBot(AdaptiveScalperBot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        raw = yaml.safe_load((ROOT / "config" / f"{settings.name}.yaml").read_text())
        self.sc = raw["sleeves"]
        if (raw.get("booking") or {}).get("enabled"):
            raise ValueError("sleeves books run the ladder per sleeve: set booking.enabled false")
        self.rule_spec = build_variants({"clocks": {self.sc["rule_clock"]: self.sc["rule_config"]}})[self.sc["rule_clock"]]
        self.ride_cfg = dict(self.sc["ride"])
        self.state_path = ROOT / "live" / settings.name / "sleeves.json"

    def _load(self, bar: str, equity: float) -> dict:
        saved = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if saved.get("bar") == bar:
            return saved["before"]
        if saved.get("after"):
            return saved["after"]
        sl = sleeves.init(["rule", "ride"], [float(self.sc["rule_share"]), 1 - float(self.sc["rule_share"])], equity)
        return {"sleeves": [s.to_dict() for s in sl], "ride": {"held": {}, "last": {}}}

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        cols = list(m.columns)
        bar = str(m.index[-1])
        equity = self.equity_curve[-1] if self.equity_curve else 0.0
        if equity <= 0:
            return {}
        before = self._load(bar, equity)
        sl = [sleeves.Sleeve.from_dict(d) for d in before["sleeves"]]
        px = {s: float(p) for s, p in prices.items() if p and s in cols}
        spec = self.rule_spec
        d = load_clock(cols, spec["clock"], bars_needed(spec), False)
        c4 = feed.close_matrix(feed.bar_frame(cols, "4h", 60))
        w = variant_weights(spec, d, c4).reindex(columns=cols).fillna(0.0)
        w5 = to_fast(w, d["close"].index, m.index).fillna(0.0)
        now_row, prev_row = w5.iloc[-1], (w5.iloc[-2] if len(w5) > 1 else w5.iloc[-1] * 0)
        rule_t = {s: float(v) for s, v in now_row.items()
                  if v > 0 and (s in sl[0].units or prev_row.get(s, 0.0) <= 0)}
        d5 = load_clock(cols, "5m", bars_needed({"cc": self.ride_cfg}), False)
        closed = d5["close"].index <= m.index[-1]
        held = {s: v for s, v in before["ride"]["held"].items() if s in sl[1].units}
        held, last, ride_t = burst_rider.live_step(d5["close"].loc[closed], d5["high"].loc[closed], self.ride_cfg,
                                                   held, dict(before["ride"]["last"]))
        sleeves.step(sl[0], rule_t, px)
        sleeves.step(sl[1], ride_t, px)
        sleeves.rescale(sl, px, equity)
        target = sleeves.account_weights(sl, px, equity)
        after = {"sleeves": [s.to_dict() for s in sl], "ride": {"held": held, "last": last}}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"bar": bar, "before": before, "after": after}))
        self.journal.write("signals", {"event": "sleeves", "bar": bar, "rule_target": rule_t, "ride_target": ride_t,
                                       "sleeve_equity": {s.name: round(s.equity(px), 2) for s in sl},
                                       "target": {s: round(v, 5) for s, v in target.items()},
                                       "ref": "DECISIONS.md#sleeves-declaration"})
        target = {s: v * derisk for s, v in target.items() if v > 1e-6}
        self.opened = getattr(self, "opened", {})
        self.last_decision_bar = bar
        return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = SleevesBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
