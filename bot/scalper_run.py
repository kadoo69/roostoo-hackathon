"""Live paper scalper: fade taker-driven moves on 30m bars.

config/scalper_live.yaml. DECISIONS.md#scalper-v1-outcome killed this family in
backtest - 0 of 64 arms cleared the pre-registered floor and every arm had a
POSITIVE median and a NEGATIVE mean trade. It runs here on explicit operator
instruction, paper only, to accumulate forward evidence.

Subclasses Bot so it inherits everything already hardened: cold-start entry
suppression, the drift no-trade band, kill switches, mirror checks, markout
instrumentation, atomic state and journalling.

WHAT TO WATCH: mean net basis points per trade. Win rate and median are both
expected to look good and are not evidence of anything.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.run import Bot
from bot.settings import ROOT, load
from signals import orderflow
from signals.scalper import atr


class ScalperBot(Bot):
    def __init__(self, settings, mode: str = "continuous"):
        super().__init__(settings, mode=mode)
        with (ROOT / "config" / "scalper_live.yaml").open() as fh:
            self.sc = yaml.safe_load(fh)["scalper"]
        self.bar_cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self.open_trades: dict[str, dict] = {}
        self.day_count: dict[str, int] = {}
        self.cooldown: dict[str, str] = {}

    def compute_target(self, channels, derisk, prices):
        target, rows = self.scalper_targets(prices)
        if rows:
            self.journal.write("signals", {"event": "scan", "rows": rows})
        return {k: v * derisk for k, v in target.items()}

    def trades_every_cycle(self) -> bool:
        """Exits are target/stop/time, so they can fire between bar closes."""
        return True

    def target_from_channels(self) -> bool:
        """This book computes its own target every cycle from its own state.

        Carrying holdings forward instead would stop `scalper_targets` being
        called between bar closes, which is where every one of its exits fires.
        """
        return False

    MAX_BAR_AGE_MIN = 90
    BAR_TTL_S = 120

    def _bars(self, sym: str) -> pd.DataFrame | None:
        """LIVE bars from Binance, never the parquet cache.

        data/cache/5m stopped at 2026-09-19 05:30, over 32 hours before this bot
        was first started. A scalper computing 'live' signals from a stale file
        would journal meaningless forward evidence that looks identical to real
        evidence. The cache is for backtests only.
        """
        # Bars are 30m; the cycle is 60s. Refetching every cycle would make ~23
        # REST calls a minute for data that changes twice an hour, alongside six
        # other books already polling. Cached for BAR_TTL_S.
        import time as _t
        hit = self.bar_cache.get(sym)
        if hit and _t.time() - hit[0] < self.BAR_TTL_S:
            d = hit[1]
        else:
            try:
                f = feed.closed_bars(sym, self.sc["bar_interval"],
                                     self.sc["lookback"] + self.sc["atr_bars"] + 10)
            except Exception:
                return None
            if not len(f):
                return None
            d = f.set_index("open_time").sort_index()
            self.bar_cache[sym] = (_t.time(), d)
        age_min = (dt.datetime.now(dt.timezone.utc) - d.index[-1]).total_seconds() / 60.0
        if age_min > self.MAX_BAR_AGE_MIN:
            self.journal.write("errors", {
                "event": "scalper_bars_stale", "symbol": sym,
                "last_bar": str(d.index[-1]), "age_min": round(age_min, 1),
                "max_age_min": self.MAX_BAR_AGE_MIN})
            return None
        return d[["open", "high", "low", "close", "volume",
                  "quote_volume", "trades", "taker_buy_quote"]]

    def scalper_targets(self, prices: dict[str, float]) -> tuple[dict, list]:
        """Target weights plus the signal rows the journal records."""
        sc = self.sc
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        rows, target = [], {}

        for sym, t in list(self.open_trades.items()):
            px = prices.get(sym)
            if px is None:
                target[sym] = t["weight"]
                continue
            age = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(t["opened"])).total_seconds() / 60.0
            bar_min = 30 if sc["bar_interval"] == "30m" else 15
            reason = ("target" if px >= t["target"] else
                      "stop" if px <= t["stop"] else
                      "time" if age >= sc["time_stop_bars"] * bar_min else None)
            if reason:
                net = (px / t["entry"] - 1.0) * 1e4 - sc["round_trip_bps"]
                self.journal.write("scalper", {
                    "event": "close", "symbol": sym, "reason": reason,
                    "entry": t["entry"], "exit": px,
                    "gross_bps": round((px / t["entry"] - 1.0) * 1e4, 3),
                    "net_bps": round(net, 3),
                    "minutes_held": round(age, 1)})
                self.cooldown[sym] = today
                self.open_trades.pop(sym, None)
            else:
                target[sym] = t["weight"]

        if len(self.open_trades) >= sc["max_concurrent"]:
            return target, rows

        for sym in self.universe:
            if sym in self.open_trades or self.day_count.get(f"{sym}:{today}", 0) >= sc["max_trades_per_day_per_symbol"]:
                continue
            d = self._bars(sym)
            if d is None or len(d) < sc["lookback"] + sc["atr_bars"] + 2:
                continue
            f = orderflow.features(d, sc["lookback"])
            a = float(atr(d, sc["atr_bars"]).iloc[-1])
            r = float(d["close"].pct_change().iloc[-1])
            z = float(f["ofi_z"].iloc[-1])
            px = prices.get(sym) or float(d["close"].iloc[-1])
            if not all(np.isfinite(v) for v in (a, r, z, px)) or a <= 0:
                continue
            # LONG-ONLY SPOT: only a taker-driven SELL-off is fadeable here.
            # Fading a rally needs a short, which costs 10 bps on both legs with
            # no maker discount, so it is out of scope for this book.
            fires = (r <= -sc["ret_thresh"]) and (z <= -sc["ofi_thresh"])
            tgt_bps = sc["target_atr"] * a / px * 1e4
            gated = tgt_bps < sc["cost_gate_multiple"] * sc["round_trip_bps"]
            rows.append({"symbol": sym, "ret": round(r, 5), "ofi_z": round(z, 3),
                         "target_bps": round(tgt_bps, 2), "fires": bool(fires),
                         "cost_gated": bool(gated)})
            if not fires or gated:
                continue
            t = {"entry": px, "weight": sc["weight_per_trade"],
                 "target": px * (1 + sc["target_atr"] * a / px),
                 "stop": px * (1 - sc["stop_atr"] * a / px),
                 "opened": dt.datetime.now(dt.timezone.utc).isoformat()}
            self.open_trades[sym] = t
            self.day_count[f"{sym}:{today}"] = self.day_count.get(f"{sym}:{today}", 0) + 1
            target[sym] = t["weight"]
            self.journal.write("scalper", {"event": "open", "symbol": sym,
                                           "entry": px, "target": t["target"],
                                           "stop": t["stop"], "ret": round(r, 5),
                                           "ofi_z": round(z, 3)})
            if len(self.open_trades) >= sc["max_concurrent"]:
                break
        return target, rows


def stats(name: str = "scalper_live") -> dict:
    """Forward per-trade record. The MEAN is what decides this family."""
    from bot.journal import Journal
    closes = [r for r in Journal(name).read("scalper") if r.get("event") == "close"]
    if not closes:
        return {"n": 0, "verdict": "no closed scalps yet"}
    net = np.array([r["net_bps"] for r in closes], dtype=float)
    mean = float(net.mean())
    n = len(net)
    if n < 200:
        verdict = (f"{n} of 200 trades. Backtest says median and win rate will look "
                   "GOOD and the mean will be negative; only the mean decides.")
    elif mean > 10:
        verdict = f"mean {mean:.2f} bps clears the round trip - backtest was WRONG, investigate"
    elif mean > 0:
        verdict = f"mean {mean:.2f} bps positive but under the 10 bps round trip"
    else:
        verdict = f"mean {mean:.2f} bps NEGATIVE over {n} trades - family settled forward too"
    return {"n": n, "mean_net_bps": round(mean, 3),
            "median_net_bps": round(float(np.median(net)), 3),
            "win_rate": round(float((net > 0).mean()), 4),
            "total_net_bps": round(float(net.sum()), 1),
            "backtest_mean_bps": -5.93, "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default=str(ROOT / "config/scalper_live.yaml"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        print(json.dumps(stats(), indent=2))
        return 0
    bot = ScalperBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
