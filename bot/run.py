from __future__ import annotations

import argparse
import datetime as dt
import json
import time

import pandas as pd

from bot import booking, feed, portfolio, regime, risk, universe
from bot.execution import Executor
from bot.intents import IntentLog
from bot.intents import reconcile as reconcile_intents
from bot.journal import Journal
from bot.markout import HORIZONS_S
from bot.settings import Settings, load, make_client
from bot.state import Store, wallet_positions
from bot.strategy import REPLAY_BARS, replay_book

INITIAL_NAV = 100_000.0


MARKOUT_RETAIN_S = max(HORIZONS_S) + 600


FEE_RATE = {"LIMIT": 0.0005, "MARKET": 0.0010}


class Bot:
    def __init__(self, settings: Settings, mode: str = "continuous"):
        self.mode = mode
        self.s = settings
        self.journal = Journal(settings.name)
        self.client = make_client(settings)
        self.client.sync_time()
        self.specs = self.client.exchange_info()
        self.executor = Executor(self.client, self.specs, settings, self.journal)
        # Live orders were blocked outright until this existed. Every unresolved
        # intent from a previous process is settled against the venue before a
        # single new order may be sent, and if any cannot be settled the block
        # stays on. DECISIONS.md#testnet-live
        if not settings.dry_run:
            self.intents = IntentLog(settings.name)
            self.executor.intents = self.intents
            report = reconcile_intents(self.intents, self.client, self.journal)
            if not report["clean"]:
                self.executor.submission_blocked = True
                self.journal.write("errors", {
                    "event": "live_blocked_unresolved_intents", **report})
        else:
            self.intents = None
        self.mirror_breaches = 0
        self.recent_symbols: dict[str, float] = {}
        self.store = Store(settings.name)
        saved = self.store.load()
        if saved.get("config_sha") not in (None, settings.config_sha256):
            self.journal.write("errors", {
                "event": "config_changed_mid_run",
                "saved_sha": saved.get("config_sha"),
                "current_sha": settings.config_sha256})
        self.state = {k: bool(v) for k, v in saved.get("state", {}).items()}
        self.holdings = {k: float(v) for k, v in saved.get("holdings", {}).items()}
        self.cash = float(saved.get("cash", INITIAL_NAV))
        self.universe = list(saved.get("universe", []))
        self.universe_at = (dt.datetime.fromisoformat(saved["universe_at"])
                            if saved.get("universe_at") else None)
        self.equity_curve = [float(x) for x in saved.get("equity_curve", [])]
        self.last_bar = (pd.Timestamp(saved["last_bar"])
                         if saved.get("last_bar") else None)
        # A process with no restored bar memory would otherwise treat the most
        # recent CLOSED bar as fresh and open positions at the live price, minutes
        # or hours past the close the signal was computed on.
        # config/cold_start.yaml, DECISIONS.md#cold-start-chases-the-bar
        self.cold_start = self.last_bar is None
        self.skim_refs = {k: float(v) for k, v in
                          (saved.get('skim_refs') or {}).items()}
        self.skims = int(saved.get('skims') or 0)
        self.journal.write("lifecycle", {
            "event": "resumed" if saved else "cold_start",
            # A one-shot diagnostic run resumes state exactly like a supervised
            # worker does, so without this the health counter reads a `--once`
            # invocation as a restart. See DECISIONS.md#restart-telemetry.
            "mode": mode,
            "config_sha": settings.config_sha256,
            "restored_positions": len(self.holdings),
            "restored_cash": round(self.cash, 2),
            "last_bar": str(self.last_bar) if self.last_bar is not None else None,
            "dry_run": settings.dry_run})
        if not settings.dry_run:
            self.adopt_wallet()

    def adopt_wallet(self) -> None:
        """Adopt the venue wallet, but only the part of it this book trades.

        `self.universe` is empty on a book that has never persisted state, and
        an empty universe used to mean "adopt everything". On a Binance testnet
        account pre-seeded with several hundred balances that made the bot
        believe it held 487 positions and submit 469 orders in one cycle on
        2026-09-22. The universe is resolved FIRST so the restriction is real.
        DECISIONS.md#testnet-live
        """
        from bot.verify import reconcile
        if not self.universe:
            try:
                self.refresh_universe(dt.datetime.now(dt.UTC))
            except Exception as exc:                      # noqa: BLE001
                self.journal.write("errors", {"event": "universe_refresh_failed_before_adopt",
                                              "error": repr(exc)})
                return
        try:
            wallet = self.client.balance()
        except Exception as exc:
            self.journal.write("errors", {"event": "wallet_read_failed",
                                          "error": repr(exc)})
            return
        if not self.universe:
            self.journal.write("errors", {"event": "adopt_skipped_no_universe"})
            return
        live, cash = wallet_positions(wallet, universe=set(self.universe))
        check = reconcile(self.holdings, live, tolerance=1e-6)
        from bot.state import holdings_ignored
        self.journal.write("reconcile", {"event": "startup", **check,
                                         "cash_local": round(self.cash, 2),
                                         "cash_venue": round(cash, 2),
                                         "wallet_entries_outside_universe":
                                             len(holdings_ignored)})
        self.holdings = live
        self.cash = cash
        self.state = {s: True for s in live}

    def persist(self) -> None:
        self.store.save({
            "config_sha": self.s.config_sha256,
            "state": self.state, "holdings": self.holdings, "cash": self.cash,
            "universe": self.universe,
            "universe_at": (self.universe_at.isoformat()
                            if self.universe_at else None),
            "equity_curve": self.equity_curve[-5000:],
            "last_bar": str(self.last_bar) if self.last_bar is not None else None,
            "skim_refs": {k: round(v, 10) for k, v in self.skim_refs.items()},
            "skims": self.skims})

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

    def compute_target(self, channels: dict, derisk: float,
                       prices: dict[str, float]) -> dict[str, float]:
        return portfolio.target_weights(channels, self.s, derisk)

    def target_from_channels(self) -> bool:
        """True when compute_target reads `channels`, which only a bar close fills.

        Such a book must carry its holdings forward between bar closes or it
        would read an empty channel set as an instruction to flatten. A bot that
        computes its own target from its own state every cycle, like
        bot/scalper_run.py, returns False and is always asked afresh, or booking
        would silently disable its intrabar stops and targets.
        """
        return True

    def trades_every_cycle(self) -> bool:
        """False for a bar-close book; True for a signal with intrabar exits.

        Booking is an intrabar exit: a position can reach its next skim step at
        any time, so a booking bot must be allowed to trade between bar closes.
        """
        return bool(self.s.booking.get("enabled"))

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

    def fit_to_cash(self, plan: dict, cash: float) -> dict:
        """Shrink a buy so notional plus fee fits the cash available, or skip it.

        A full-deployment book targets 1/n of equity per name, so its last buy
        plus the fee exceeds the cash left. The paper fill then silently did not
        happen while the order journal recorded it, so the book believed it held
        a name it did not, and a venue would reject the same order outright.
        DECISIONS.md#lowtf-paper-bots
        """
        fee = FEE_RATE.get(plan["type"], 0.001)
        cap = max(0.0, cash) / (1.0 + fee)
        if plan["notional"] <= cap:
            return plan
        spec = self.executor.spec(plan["symbol"])
        qty = spec.round_qty(cap / plan["price"] * (1.0 - 1e-9)) if spec else 0.0
        if qty <= 0 or spec is None or qty * plan["price"] < spec.min_order:
            return {"skipped": "insufficient_cash", "symbol": plan["symbol"], "pair": plan.get("pair"),
                    "notional": plan["notional"], "cash": round(cash, 4)}
        return {**plan, "quantity": qty, "notional": round(qty * plan["price"], 4),
                "cash_capped_from": plan["notional"]}

    def apply_dry_fill(self, plan: dict) -> bool:
        if plan.get("skipped") or not self.s.dry_run:
            return False
        qty, px = plan["quantity"], plan["price"]
        if plan.get("wide_tick"):
            # A paper fill at our own passive price on a one-tick book that is
            # wider than max_spread_bps would book the whole tick as profit on
            # every round trip. Charge the far side instead, which is what the
            # backtest's paid-spread arm assumed. DECISIONS.md#live-validation-2026-09-23
            px = float(plan["ref_ask"] if plan["side"] == "BUY" else plan["ref_bid"])
        sym = plan["symbol"]
        fee = FEE_RATE.get(plan["type"], 0.0010)
        if plan["side"] == "BUY":
            cost = qty * px * (1 + fee)
            if cost > self.cash + 1e-9:
                return False
            self.cash -= cost
            self.holdings[sym] = self.holdings.get(sym, 0.0) + qty
        else:
            have = self.holdings.get(sym, 0.0)
            qty = min(qty, have)
            if qty <= 0:
                return False
            self.cash += qty * px * (1 - fee)
            self.holdings[sym] = have - qty
            if self.holdings[sym] <= 1e-12:
                self.holdings.pop(sym, None)
        return True

    def cycle(self) -> dict:
        now = dt.datetime.now(dt.timezone.utc)
        self.refresh_universe(now)

        need = max(self.s.entry_bars, self.s.exit_bars) + 5
        frames = feed.bar_frame(self.universe, self.s.interval, max(need + 20, REPLAY_BARS))
        matrix = feed.close_matrix(frames)
        quotes = feed.roostoo_quotes(self.client)
        ticker_time = getattr(self.client, "last_ticker_server_time_ms", None)
        ticker_age_s = (float("inf") if ticker_time is None else
                        max(0.0, (self.client._timestamp() - ticker_time) / 1000.0))
        equity, prices = self.mark(quotes)
        self.equity_curve.append(equity)

        if self.s.mirror_reference == "none":
            mirror, worst = [], None
        else:
            mirror = feed.mirror_check(quotes, self.specs, self.universe)
            material = [m for m in mirror if m.get("material")]
            raw_worst = (max((abs(m["deviation_bps"]) for m in material), default=0.0)
                         if len(mirror) == len(self.universe) else float("inf"))
            if raw_worst >= self.s.mirror_max_deviation_bps:
                self.mirror_breaches += 1
            else:
                self.mirror_breaches = 0
            worst = (raw_worst if self.mirror_breaches >= 2 else
                     min(raw_worst, self.s.mirror_max_deviation_bps - 1e-9))
        guard = risk.gate(self.equity_curve, self.executor.error_rate(), ticker_age_s,
                          worst, self.s)
        derisk = risk.derisk_multiplier(now, self.s)

        fresh = self.bar_close_due(matrix)
        channels = replay_book(matrix, self.s) if fresh else {}
        ranking = {}
        if fresh:
            replayed = {s: c.held for s, c in channels.items()}
            drift = sorted(s for s in set(replayed) | set(self.state)
                           if replayed.get(s, False) != self.state.get(s, False)
                           and channels.get(s) is not None
                           and channels[s].action not in ("enter", "exit"))
            if drift:
                self.journal.write("signals", {
                    "event": "channel_state_resynced",
                    "bar": str(matrix.index[-1]),
                    "now_held": [s for s in drift if replayed.get(s)],
                    "now_flat": [s for s in drift if not replayed.get(s)],
                    "ref": "DECISIONS.md#live-validation-2026-09-23"})
            self.state = replayed
            selected, ranking = portfolio.rank_and_select(channels, matrix, self.s)
            channels = selected

        # Hook: a subclass with a different signal overrides compute_target and
        # trades_every_cycle rather than copying this cycle, so it inherits the
        # cold-start guard, drift band, kill switches, mirror check, markout
        # instrumentation and atomic state unchanged. See bot/scalper_run.py.
        current_w = portfolio.current_weights(self.holdings, prices, equity)
        if guard["halt"]:
            target = {}
        elif fresh or not self.s.booking.get("enabled") or not self.target_from_channels():
            target = self.compute_target(channels, derisk, prices)
        else:
            # Not a bar close, so `channels` is empty by construction and a
            # target computed from it would be empty too, which `deltas` would
            # read as "sell everything". A booking bot trades every cycle, so it
            # must carry the held book forward and let only the ladder move it.
            # This flattened three books on 2026-09-22 before it was caught.
            # DECISIONS.md#booking-flattened-the-book
            target = dict(current_w)
        # The skim ladder is a shared capability, not a property of one bot:
        # any config carrying a `booking` block gets it. bot/booking.py.
        target, skims = booking.apply(target, current_w, prices, self.skim_refs,
                                      equity, self.s.booking)
        if skims:
            self.skims += len(skims)
            self.journal.write("signals", {"event": "skim", "bar": str(matrix.index[-1])
                                           if len(matrix) else None,
                                           "step_pct": self.s.booking.get("step_pct"),
                                           "skim_fraction": self.s.booking.get("skim_fraction"),
                                           "skims": skims})
        # The gate defaults to always_on, which returns `target` unmodified, so
        # a bot that does not declare regime_gate behaves exactly as before.
        target, gate = regime.apply(target, self.s.regime_gate,
                                    held=set(self.holdings),
                                    min_cushion_pct=self.s.min_cushion_pct)
        current = current_w
        orders = (portfolio.deltas(target, current, equity, prices,
                                   force={e["symbol"] for e in skims})
                  if fresh or guard["halt"] or self.trades_every_cycle() else [])

        suppressed = []
        if fresh and self.cold_start and not guard["halt"]:
            keep = []
            for o in orders:
                opening = o["side"] == "BUY" and o["symbol"] not in self.holdings
                (suppressed if opening else keep).append(o)
            orders = keep
            if suppressed:
                self.journal.write("orders", {
                    "event": "cold_start_entry_suppressed",
                    "bar": str(matrix.index[-1]) if len(matrix) else None,
                    "reason": "first cycle of a process with no restored bar memory; "
                              "entering now would pay a price the backtest never modelled",
                    "symbols": sorted(o["symbol"] for o in suppressed),
                    "ref": "DECISIONS.md#cold-start-chases-the-bar"})
        if fresh:
            self.cold_start = False

        self.executor.refresh_pending()
        placed = []
        spendable = self.cash
        for o in sorted(orders, key=lambda o: o["side"] != "SELL"):
            plan = self.executor.prepare(o, quotes)
            if plan is None:
                continue
            if not plan.get("skipped") and plan["side"] == "BUY":
                plan = self.fit_to_cash(plan, spendable)
            rec = self.executor.send(plan)
            if not plan.get("skipped"):
                if self.s.dry_run:
                    if not self.apply_dry_fill(plan):
                        self.journal.write("orders", {"event": "dry_fill_refused",
                                                      "symbol": plan["symbol"], "side": plan["side"],
                                                      "notional": plan["notional"], "cash": round(self.cash, 4),
                                                      "ref": "DECISIONS.md#lowtf-paper-bots"})
                    spendable = self.cash
                elif plan["side"] == "BUY":
                    spendable -= plan["notional"] * (1.0 + FEE_RATE.get(plan["type"], 0.001))
            placed.append(rec)
        self.executor.sweep_unfilled()

        # Marks are journaled only for symbols a markout could need: what is held,
        # plus what was traded recently, so an EXIT still has forward marks after
        # the position is gone. Marking the whole universe every cycle would add
        # roughly 6 MB a day across the stack for data nothing reads.
        now_s = time.time()
        for pl in placed:
            if pl.get("symbol"):
                self.recent_symbols[pl["symbol"]] = now_s
        self.recent_symbols = {k: v for k, v in self.recent_symbols.items()
                               if now_s - v < MARKOUT_RETAIN_S}

        held_weights = portfolio.current_weights(self.holdings, prices, equity)
        snapshot = {
            "event": "cycle", "bar": str(matrix.index[-1]) if len(matrix) else None,
            "new_bar": fresh, "equity": round(equity, 2),
            "cash": round(self.cash, 2),
            "gross_exposure": round(sum(abs(w) for w in held_weights.values()), 4),
            "n_long": len(held_weights),
            "target_gross": round(sum(target.values()), 4) if fresh else None,
            "n_target": len(target) if fresh else None,
            "positions": {k: round(v, 5) for k, v in sorted(held_weights.items())},
            "marks": {k: float(v) for k, v in sorted(prices.items())
                      if k in held_weights or k in self.recent_symbols},
            "ranking": ranking or None,
            "n_universe": len(self.universe),
            "derisk": derisk, "halt": guard["halt"], "breaches": guard["breaches"],
            "drawdown": guard["drawdown"], "orders": len(placed),
            "cold_start_suppressed": len(suppressed) or None,
            "mirror_worst_bps": worst, "mirror_checked": len(mirror),
            "ticker_age_s": round(ticker_age_s, 3),
            "config_sha": self.s.config_sha256,
            "gate": gate,
        }
        if not self.s.dry_run:
            self.adopt_wallet()
        self.persist()
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
    bot = Bot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(a.cycles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
