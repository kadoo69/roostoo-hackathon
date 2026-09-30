"""Hedge explorer (paper): trade every rule variant at once, shifting capital toward what pays live.

Capital is split across the variants of `config/<book>.yaml` (and cash). The book holds the
capital-weighted blend of every variant's current target, so any entry a variant takes is taken,
and each position is held under its own variant's rule. Every `update_minutes` each variant's
share is multiplied by exp(eta x its return since the last update, in percent), renormalised, and
floored so no variant stops being explored (the Hedge / exponential-weights rule).
DECISIONS.md#hedge-explorer-declaration
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd

from bot import feed
from bot.scalper_adaptive_run import CASH, MINUTES, WARMUP_BARS, AdaptiveScalperBot, clock_weights, frames_to
from bot.settings import ROOT, load
from gates.let_winners_run import simulate
from signals import burst_rider
from signals.exit_clock import to_fast


def hedge_update(weights: dict[str, float], returns_pct: dict[str, float], eta: float,
                 floor: float) -> dict[str, float]:
    """One exponential-weights step with an exploration floor; the result sums to 1."""
    raw = {k: w * math.exp(eta * returns_pct.get(k, 0.0)) for k, w in weights.items()}
    total = sum(raw.values())
    w = {k: v / total for k, v in raw.items()}
    w = {k: max(v, floor) for k, v in w.items()}
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def blend(frames: dict[str, pd.DataFrame], weights: dict[str, float]) -> pd.DataFrame:
    """Capital-weighted sum of variant weight frames on one index; gross stays within 1."""
    out = None
    for k, f in frames.items():
        part = f * weights.get(k, 0.0)
        out = part if out is None else out.add(part, fill_value=0.0)
    return out.fillna(0.0)


class HedgeExplorerBot(AdaptiveScalperBot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        self.hedge_path = ROOT / "live" / settings.name / "hedge.json"
        saved = json.loads(self.hedge_path.read_text()) if self.hedge_path.exists() else {}
        arms = list(self.variants) + ([CASH] if self.ad.get("allow_cash") else [])
        start = {k: 1.0 / len(arms) for k in arms}
        self.weights = {k: float(saved.get("weights", {}).get(k, start[k])) for k in arms}
        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}
        self.updated_at = pd.Timestamp(saved["at"]) if saved.get("at") else None

    def variant_frames(self, symbols: list[str], bars_by_clock: dict[str, int]) -> tuple[dict, dict]:
        c4 = feed.close_matrix(feed.bar_frame(symbols, "4h", 120))
        data = {}
        for iv, n in bars_by_clock.items():
            fr = feed.bar_frame(symbols, iv, n)
            data[iv] = (frames_to(fr, "close"), frames_to(fr, "quote_volume"), frames_to(fr, "high"))
        ws = {}
        for vid, v in self.variants.items():
            close, qv, high = data[v["clock"]]
            ws[vid] = (burst_rider.weights(close, high, v["cc"]) if v.get("type") == "burst"
                       else clock_weights(close, qv, c4, v["cc"], v["entry"], v["exit"]))
        return ws, data

    def update(self, now: pd.Timestamp, symbols: list[str]) -> None:
        days = float(self.ad["warm_days"])
        clocks = {v["clock"] for v in self.variants.values()}
        ws, data = self.variant_frames(symbols, {iv: int(days * 1440 / MINUTES[iv]) + WARMUP_BARS for iv in clocks})
        prev = self.updated_at
        rets = {}
        if prev is not None:
            for vid, w in ws.items():
                iv = self.variants[vid]["clock"]
                net, _ = simulate(data[iv][0], w, self.tick_map(), True)
                close_t = net.index + pd.Timedelta(minutes=MINUTES[iv])
                seg = net[(close_t > prev) & (close_t <= now)]
                rets[vid] = round(float(np.expm1(np.log1p(seg).sum()) * 100), 4)
            if CASH in self.weights:
                rets[CASH] = 0.0
            before = dict(self.weights)
            self.weights = hedge_update(self.weights, rets, float(self.ad["eta_per_pct"]), float(self.ad["floor"]))
            book_ret = sum(before[k] * rets.get(k, 0.0) for k in before)
            self.journal.write("hedge", {"from": prev.isoformat(), "to": now.isoformat(), "returns_pct": rets,
                                         "book_pct": round(book_ret, 4),
                                         "mean_pct": round(float(np.mean(list(rets.values()))), 4),
                                         "weights_before": {k: round(v, 5) for k, v in before.items()},
                                         "weights_after": {k: round(v, 5) for k, v in self.weights.items()},
                                         "ref": "DECISIONS.md#hedge-explorer-declaration"})
        self.updated_at = now
        top = sorted(self.weights.items(), key=lambda kv: -kv[1])
        self.hedge_path.parent.mkdir(parents=True, exist_ok=True)
        self.hedge_path.write_text(json.dumps({"at": now.isoformat(), "weights": self.weights, "last_returns_pct": rets}))
        self.ad_path.write_text(json.dumps({"clock": f"{top[0][0]} {top[0][1]:.0%}", "at": now.isoformat(),
                                            "scores": {k: round(v * 100, 2) for k, v in top}}))

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        m = self.matrix
        if m.empty:
            return {}
        cols = list(m.columns)
        now = pd.Timestamp.now(tz="UTC")
        if self.updated_at is None or now - self.updated_at >= pd.Timedelta(minutes=int(self.ad["update_minutes"])):
            try:
                self.update(now, cols)
            except Exception as exc:                      # noqa: BLE001
                self.journal.write("errors", {"event": "hedge_update_failed", "error": repr(exc)})
        clocks = {v["clock"] for v in self.variants.values()}
        ws, data = self.variant_frames(cols, {iv: WARMUP_BARS + 60 for iv in clocks})
        on5 = {}
        for vid, w in ws.items():
            iv = self.variants[vid]["clock"]
            f = w.reindex(columns=cols).fillna(0.0)
            on5[vid] = f.reindex(m.index).fillna(0.0) if iv == self.s.interval else to_fast(f, data[iv][0].index, m.index).fillna(0.0)
        w5 = blend(on5, self.weights)
        last = w5.iloc[-1]
        target = {s: float(v) for s, v in last.items() if abs(v) > 1e-6}
        self.journal.write("signals", {"event": "contenders", "bar": str(m.index[-1]), "variant": "hedge_blend",
                                       "target": {s: round(v, 5) for s, v in target.items()},
                                       "top_weights": {k: round(v, 3) for k, v in sorted(self.weights.items(), key=lambda kv: -kv[1])[:5]}})
        target = {s: math.copysign(math.floor(abs(v) * derisk * 1e8) / 1e8, v) for s, v in target.items()}
        return self.guard(target, w5, prices, int(self.ad.get("min_hold_bars", 3)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = HedgeExplorerBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
