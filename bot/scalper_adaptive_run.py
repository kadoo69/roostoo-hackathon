"""Adaptive short-term scalper (paper): trades whichever fast clock earned most over the last week.

Every `reselect_minutes` the 5m, 15m and 30m contenders rules are replayed on the last
`lookback_days` of Binance bars with the backtest's own simulator (ladder, fee, tick), and the
book trades the clock with the best trailing return, switching only on a `switch_margin_pp` lead.
The bot runs on 5m bars; a slower clock's weights reach it by bar CLOSE time.
DECISIONS.md#scalper-adaptive-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.contenders_run import ContendersBot
from bot.settings import ROOT, load
from gates.let_winners_run import simulate
from signals import contenders
from signals.exit_clock import to_fast

MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
WARMUP_BARS = 100


def pick_clock(scores: dict[str, float], current: str | None, margin_pp: float) -> str:
    """Best trailing score, but the current clock is kept unless beaten by `margin_pp` points."""
    best = max(scores, key=scores.get)
    if current in scores and scores[best] - scores[current] < margin_pp:
        return current
    return best


def clock_weights(close: pd.DataFrame, qv: pd.DataFrame, close4: pd.DataFrame, cc: dict,
                  entry: int, exit_lb: int) -> pd.DataFrame:
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    ok = (contenders.entry_confirmation(close, qv.reindex_like(close), close4, cc)
          if contenders.needs_confirmation(cc) else None)
    off = pd.Series(False, index=close.index)
    return contenders.targets(close, members, cc, entry, exit_lb, short_on=off, entry_ok=ok)


def frames_to(frames: dict[str, pd.DataFrame], field: str) -> pd.DataFrame:
    return pd.DataFrame({s: f.set_index("open_time")[field] for s, f in frames.items() if len(f)}).sort_index()


class AdaptiveScalperBot(ContendersBot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        raw = yaml.safe_load((ROOT / "config" / f"{settings.name}.yaml").read_text())
        self.ad = raw["adaptive"]
        self.clock_cfgs = {}
        for iv, name in self.ad["clocks"].items():
            c = yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())
            self.clock_cfgs[iv] = {"cc": c["contenders"], "entry": int(c["strategy"]["entry_bars"]),
                                   "exit": int(c["strategy"]["exit_bars"])}
        self.ad_path = ROOT / "live" / settings.name / "adaptive.json"
        saved = json.loads(self.ad_path.read_text()) if self.ad_path.exists() else {}
        self.clock = saved.get("clock") or self.ad.get("start_clock", "15m")
        self.selected_at = pd.Timestamp(saved["at"]) if saved.get("at") else None

    def tick_map(self) -> pd.Series:
        return pd.Series({sp.binance_symbol: sp.tick for sp in self.specs.values()})

    def reselect(self, now: pd.Timestamp, symbols: list[str]) -> None:
        days = float(self.ad["lookback_days"])
        c4 = feed.close_matrix(feed.bar_frame(symbols, "4h", int(days * 6) + 60))
        scores, detail = {}, {}
        for iv, spec in self.clock_cfgs.items():
            bars = int(days * 1440 / MINUTES[iv]) + WARMUP_BARS
            fr = feed.bar_frame(symbols, iv, bars)
            close, qv = frames_to(fr, "close"), frames_to(fr, "quote_volume")
            w = clock_weights(close, qv, c4, spec["cc"], spec["entry"], spec["exit"])
            net, turn = simulate(close, w, self.tick_map(), True)
            window = net.loc[now - pd.Timedelta(days=days):]
            scores[iv] = round(float(np.expm1(np.log1p(window).sum()) * 100), 3)
            detail[iv] = {"bars": int(len(close)), "turnover": round(float(turn.loc[window.index].sum()), 2)}
        prev = self.clock
        self.clock = pick_clock(scores, prev, float(self.ad["switch_margin_pp"]))
        self.selected_at = now
        self.ad_path.parent.mkdir(parents=True, exist_ok=True)
        self.ad_path.write_text(json.dumps({"clock": self.clock, "at": now.isoformat(), "scores": scores}))
        self.journal.write("signals", {"event": "adaptive_select", "clock": self.clock, "previous": prev,
                                       "switched": self.clock != prev, "trailing_pct": scores,
                                       "detail": detail, "lookback_days": days,
                                       "ref": "DECISIONS.md#scalper-adaptive-declaration"})

    def reselect_due(self, now: pd.Timestamp) -> bool:
        return (self.selected_at is None
                or now - self.selected_at >= pd.Timedelta(minutes=int(self.ad["reselect_minutes"])))

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        cols = list(m.columns)
        now = pd.Timestamp.now(tz="UTC")
        if self.reselect_due(now):
            try:
                self.reselect(now, cols)
            except Exception as exc:                      # noqa: BLE001
                self.journal.write("errors", {"event": "adaptive_select_failed", "error": repr(exc),
                                              "kept_clock": self.clock})
        iv = self.clock
        spec = self.clock_cfgs[iv]
        need = WARMUP_BARS + 60
        if iv == self.s.interval:
            close = m
            qv = frames_to(feed.bar_frame(cols, iv, len(m) + 1), "quote_volume")
        else:
            fr = feed.bar_frame(cols, iv, need)
            close, qv = frames_to(fr, "close"), frames_to(fr, "quote_volume")
        c4 = feed.close_matrix(feed.bar_frame(cols, "4h", 60))
        w = clock_weights(close, qv, c4, spec["cc"], spec["entry"], spec["exit"])
        w5 = w if iv == self.s.interval else to_fast(w, close.index, m.index).fillna(0.0)
        last = w5.iloc[-1]
        target = {s: float(v) for s, v in last.items() if abs(v) > 1e-9}
        self.journal.write("signals", {"event": "contenders", "bar": str(m.index[-1]), "clock": iv,
                                       "target": {s: round(v, 5) for s, v in target.items()}})
        target = {s: math.copysign(math.floor(abs(v) * derisk * 1e8) / 1e8, v) for s, v in target.items()}
        min_hold = int(spec["cc"].get("min_hold_bars") or 0) * MINUTES[iv] // MINUTES[self.s.interval]
        return self.guard(target, w5, prices, min_hold)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = AdaptiveScalperBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
