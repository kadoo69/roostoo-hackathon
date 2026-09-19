from __future__ import annotations

import argparse
import datetime as dt
import json
import time

import pandas as pd

from bot import feed, portfolio, risk, universe, verify
from bot.execution import Executor
from bot.journal import Journal
from bot.report import from_equity
from bot.settings import Settings, credentials, load
from bot.strategy import evaluate_book
from venue.roostoo import RoostooClient

INITIAL_NAV = 100_000.0


class Bot:
    def __init__(self, settings: Settings):
        self.s = settings
        self.journal = Journal(settings.name)
        key, secret = credentials()
        self.client = RoostooClient(key, secret)
        self.client.sync_time()
        self.specs = self.client.exchange_info()
        self.executor = Executor(self.client, self.specs, settings, self.journal)
        self.state: dict[str, bool] = {}
        self.holdings: dict[str, float] = {}
        self.cash = INITIAL_NAV
        self.universe: list[str] = []
        self.universe_at: dt.datetime | None = None
        self.equity_curve: list[float] = []
        self.last_bar: pd.Timestamp | None = None

    def refresh_universe(self, now: dt.datetime) -> None:
        stale = (self.universe_at is None or
                 (now - self.universe_at).total_seconds()
                 >= self.s.universe_refresh_hours * 3600)
        if not stale:
            return
        sel = universe.select(self.s, self.specs)
        self.universe = sel["selected"]
        self.universe_at = now
        self.journal.write("universe", {"event": "refresh", **{
            k: v for k, v in sel.items() if k != "adv_usd"}})

    def bar_close_due(self, matrix: pd.DataFrame) -> bool:
        if matrix.empty:
            return False
        latest = matrix.index[-1]
        if self.last_bar is not None and latest <= self.last_bar:
            return False
        self.last_bar = latest
        return True

    def mark(self, quotes: dict) -> tuple[float, dict[str, float]]:
        prices = {}
        for sym in set(self.universe) | set(self.holdings):
            spec = self.executor.spec(sym)
            if spec and spec.pair in quotes:
                prices[sym] = float(quotes[spec.pair]["LastPrice"])
        equity = self.cash + sum(q * prices.get(s, 0.0)
                                 for s, q in self.holdings.items())
        return equity, prices

    def apply_dry_fill(self, plan: dict) -> None:
        if plan.get("skipped") or not self.s.dry_run:
            return
        qty, px = plan["quantity"], plan["price"]
        sym = plan["symbol"]
        fee = 0.0005 if plan["type"] == "LIMIT" else 0.0010
        if plan["side"] == "BUY":
            cost = qty * px * (1 + fee)
            if cost > self.cash:
                return
            self.cash -= cost
            self.holdings[sym] = self.holdings.get(sym, 0.0) + qty
        else:
            have = self.holdings.get(sym, 0.0)
            qty = min(qty, have)
            if qty <= 0:
                return
            self.cash += qty * px * (1 - fee)
            self.holdings[sym] = have - qty
            if self.holdings[sym] <= 1e-12:
                self.holdings.pop(sym, None)

    def cycle(self) -> dict:
        now = dt.datetime.now(dt.timezone.utc)
        self.refresh_universe(now)

        need = max(self.s.entry_bars, self.s.exit_bars) + 5
        frames = feed.bar_frame(self.universe, self.s.interval, need + 20)
        matrix = feed.close_matrix(frames)
        quotes = feed.roostoo_quotes(self.client)
        equity, prices = self.mark(quotes)
        self.equity_curve.append(equity)

        mirror = feed.mirror_check(quotes, self.specs, self.universe[:3])
        worst = max((abs(m["deviation_bps"]) for m in mirror), default=None)
        guard = risk.gate(self.equity_curve, self.executor.error_rate(), 0.0,
                          worst, self.s)
        derisk = risk.derisk_multiplier(now, self.s)

        fresh = self.bar_close_due(matrix)
        channels = evaluate_book(matrix, self.state, self.s) if fresh else {}
        if fresh:
            self.state = {s: c.held for s, c in channels.items()}

        target = ({} if guard["halt"]
                  else portfolio.target_weights(channels, self.s, derisk))
        current = portfolio.current_weights(self.holdings, prices, equity)
        orders = (portfolio.deltas(target, current, equity, prices)
                  if fresh or guard["halt"] else [])

        placed = []
        for o in orders:
            plan = self.executor.prepare(o, quotes)
            if plan is None:
                continue
            rec = self.executor.send(plan)
            self.apply_dry_fill(plan)
            placed.append(rec)
        self.executor.sweep_unfilled()

        snapshot = {
            "event": "cycle", "bar": str(matrix.index[-1]) if len(matrix) else None,
            "new_bar": fresh, "equity": round(equity, 2),
            "cash": round(self.cash, 2),
            "gross_exposure": round(sum(target.values()), 4),
            "n_universe": len(self.universe), "n_long": len(target),
            "derisk": derisk, "halt": guard["halt"], "breaches": guard["breaches"],
            "drawdown": guard["drawdown"], "orders": len(placed),
            "mirror_worst_bps": worst, "config_sha": self.s.config_sha256,
        }
        self.journal.write("cycles", snapshot)
        if fresh:
            self.journal.write("signals", {
                "bar": str(matrix.index[-1]),
                "channels": {s: c.as_dict() for s, c in channels.items()},
                "target_weights": target})
        return snapshot

    def loop(self, cycles: int | None = None) -> None:
        n = 0
        while cycles is None or n < cycles:
            try:
                self.cycle()
            except Exception as exc:
                self.journal.write("errors", {"event": "cycle_error",
                                              "error": repr(exc)})
            n += 1
            if cycles is None or n < cycles:
                time.sleep(self.s.poll_seconds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--cycles", type=int, default=None)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = Bot(load(a.config))
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(a.cycles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
