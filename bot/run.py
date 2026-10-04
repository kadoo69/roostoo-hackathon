from __future__ import annotations

import argparse
import datetime as dt
import json
import time

import pandas as pd

from bot import booking, feed, lock, portfolio, regime, risk, universe
from bot.execution import Executor
from bot.intents import IntentLog
from bot.intents import reconcile as reconcile_intents
from bot.journal import Journal
from bot.markout import HORIZONS_S
from bot.settings import Settings, load, make_client
from bot.state import Store, wallet_positions
from bot.strategy import (REGIME_SYMBOL, REPLAY_BARS, replay_book, replay_short_book,
                          short_bars_needed, short_regime)

INITIAL_NAV = 100_000.0


MARKOUT_RETAIN_S = max(HORIZONS_S) + 600
RETRY_MIN_CASH_FRAC = 0.01
WATCHDOG_S = 240.0
BAR_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "8h": 28800, "12h": 43200, "1d": 86400}
CLOSE_OFFSET_S = 2.0
STALE_SLEEP_S = 5.0
STALE_CYCLE_S = 300.0


def next_sleep(now_s: float, poll_s: float, bar_s: float, offset_s: float = CLOSE_OFFSET_S) -> float:
    """Seconds until the next cycle: the regular poll, or `offset_s` after the next bar close if
    that comes sooner, so a decision is made seconds after a close instead of up to a poll later.
    DECISIONS.md#bar-close-alignment-2026-09-27"""
    wake = (now_s // bar_s + 1) * bar_s + offset_s
    if now_s % bar_s < offset_s:
        wake = now_s // bar_s * bar_s + offset_s
    return max(0.5, min(poll_s, wake - now_s))


def ticker_age(client, stale_s: float) -> tuple[float, float | None]:
    """Age of the last ticker by the client's clock. When it reads stale, the client's server-time offset
    is synced again and the age read once more, so an offset left wrong by a host sleep or a clock step
    never freezes a book; a ticker that is really stale stays stale. Returns the age and, after a resync,
    the age it replaced. DECISIONS.md#clock-resync-2026-10-03"""
    t = getattr(client, "last_ticker_server_time_ms", None)
    if t is None:
        return float("inf"), None
    age = max(0.0, (client._timestamp() - t) / 1000.0)
    if age < stale_s or not hasattr(client, "sync_time"):
        return age, None
    try:
        client.sync_time()
    except Exception:
        return age, None
    return max(0.0, (client._timestamp() - t) / 1000.0), age


def stale_cycle(wall0: float, mono0: float, wall1: float, mono1: float,
                sleep_s: float = STALE_SLEEP_S, limit_s: float = STALE_CYCLE_S) -> bool:
    """True when the machine slept more than `sleep_s` since the cycle fetched its bars and quotes
    (the wall clock runs through sleep, the monotonic clock does not), or when the cycle has run
    longer than `limit_s` in all. DECISIONS.md#stale-cycle-guard"""
    wall = wall1 - wall0
    return wall - (mono1 - mono0) > sleep_s or wall > limit_s


def venue_quote(specs: dict) -> str:
    """The venue's cash asset, read from its own pair names (BTC/USD on Roostoo, BTC/USDT on Binance)."""
    quotes = [str(k).split("/")[-1].upper() for k in specs if "/" in str(k)]
    return max(set(quotes), key=quotes.count) if quotes else "USD"


def carry_target(current: dict[str, float], pending: dict[str, float],
                 cash_frac: float) -> dict[str, float]:
    """The held book carried between bar closes, plus entries the last close wanted and did not get.

    DECISIONS.md#execution-gaps-2026-09-23
    """
    target = dict(current)
    if cash_frac < RETRY_MIN_CASH_FRAC:
        return target
    for sym, w in pending.items():
        if current.get(sym, 0.0) <= 0.0:
            target[sym] = w
    return target


def next_pending(fresh: bool, halt: bool, target: dict[str, float], pending: dict[str, float],
                 holdings: dict[str, float], suppressed: set[str], cash_frac: float) -> dict[str, float]:
    """Entries still wanted and not held. A bar close replaces them; a halt clears them.

    DECISIONS.md#execution-gaps-2026-09-23
    """
    if halt:
        return {}
    base = target if fresh else pending
    return {s: w for s, w in base.items()
            if w > 1e-9 and holdings.get(s, 0.0) <= 0.0 and s not in suppressed}


MAX_DEFERRALS = 3
BLOCK_EXIT_CYCLES = 10


def incomplete_hold(gaps: dict, matrix: pd.DataFrame, state: dict) -> bool:
    """True while a bar close must wait for complete data. The same bar is deferred at most
    MAX_DEFERRALS cycles, so a symbol that is genuinely dead cannot freeze the book; after that
    the decision proceeds on what arrived and the journal says so. DECISIONS.md#live-audit-2026-09-24
    """
    if not (gaps["missing"] or gaps["stale"]) or matrix.empty:
        state.clear()
        return False
    bar = matrix.index[-1]
    if state.get("bar") != bar:
        state["bar"], state["count"] = bar, 0
    state["count"] += 1
    return state["count"] <= MAX_DEFERRALS


FEE_RATE = {"LIMIT": 0.0005, "MARKET": 0.0010}
SHORT_FEE = 0.0010
SELLS_FIRST = ("SELL", "SHORT_CLOSE")
OPENS = ("BUY", "SHORT_OPEN")
UNDERFILL_DONE = 0.25


class Bot:
    def __init__(self, settings: Settings, mode: str = "continuous"):
        self.mode = mode
        self.s = settings
        self.wallet_ok = settings.dry_run
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
        self.blocked_cycles = 0
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
        self.shorts = {k: {f: float(x) for f, x in v.items()}
                       for k, v in (saved.get("shorts") or {}).items()}
        self.short_pick: list[str] = []
        self.gap_state: dict = {}
        self.cash = float(saved.get("cash", INITIAL_NAV))
        self.universe = list(saved.get("universe", []))
        self.universe_at = (dt.datetime.fromisoformat(saved["universe_at"])
                            if saved.get("universe_at") else None)
        self.equity_curve = [float(x) for x in saved.get("equity_curve", [])]
        self.last_marks = {k: float(v) for k, v in (saved.get("last_marks") or {}).items()}
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
        self.lock_state = dict(saved.get("lock_state") or {})
        self.opened = {k: list(v) for k, v in (saved.get("opened") or {}).items()}
        self.last_decision_bar = saved.get("last_decision_bar")
        self.pending_entries = ({k: float(v) for k, v in (saved.get("pending_entries") or {}).items()}
                                if saved.get("pending_bar") == saved.get("last_bar") else {})
        self.underfilled = (set(saved["underfilled"]) if "underfilled" in saved
                            else self.capped_entries_held())
        self.journal.write("lifecycle", {
            "event": "resumed" if saved else "cold_start",
            # A one-shot diagnostic run resumes state exactly like a supervised
            # worker does, so without this the health counter reads a `--once`
            # invocation as a restart. See DECISIONS.md#restart-telemetry.
            "mode": mode,
            "config_sha": settings.config_sha256,
            "restored_positions": len(self.holdings),
            "restored_shorts": len(self.shorts),
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
            self.wallet_ok = False
            self.journal.write("errors", {"event": "wallet_read_failed",
                                          "error": repr(exc)})
            return
        if not self.universe:
            self.journal.write("errors", {"event": "adopt_skipped_no_universe"})
            return
        live, cash = wallet_positions(wallet, quote=venue_quote(self.specs),
                                      universe=set(self.universe) | set(self.holdings))
        check = reconcile(self.holdings, live, tolerance=1e-6)
        from bot.state import holdings_ignored
        self.journal.write("reconcile", {"event": "startup", **check,
                                         "cash_local": round(self.cash, 2),
                                         "cash_venue": round(cash, 2),
                                         "wallet_entries_outside_universe":
                                             len(holdings_ignored)})
        self.holdings = live
        self.cash = cash
        self.wallet_ok = True
        self.state = {s: True for s in live}
        if self.s.shorts_enabled:
            self.adopt_shorts()

    def adopt_shorts(self) -> None:
        """Venue short positions replace the local record, as the spot wallet does.

        Collateral has left the wallet while a short is open (the README's ReturnAmount
        returns it on close), so it is valued here and not in cash. That reading is
        checked with the test keys by gates/short_smoke.py. DECISIONS.md#short-paper-books
        """
        try:
            rows = self.client.short_positions()
        except Exception as exc:
            self.journal.write("errors", {"event": "short_positions_read_failed",
                                          "error": repr(exc)})
            return
        live = {}
        for r in rows:
            spec = self.specs.get(r.get("Pair"))
            if spec is None:
                continue
            live[spec.binance_symbol] = {"qty": float(r.get("ShortQty") or 0.0),
                                         "entry": float(r.get("EntryPrice") or 0.0),
                                         "collateral": float(r.get("Collateral") or 0.0)}
        if {k: round(v["qty"], 10) for k, v in live.items()} != {
                k: round(v["qty"], 10) for k, v in self.shorts.items()}:
            self.journal.write("reconcile", {"event": "shorts_adopted",
                                             "local": self.shorts, "venue": live})
        self.shorts = live

    def persist(self) -> None:
        self.store.save({
            "config_sha": self.s.config_sha256,
            "state": self.state, "holdings": self.holdings, "cash": self.cash,
            "shorts": self.shorts,
            "universe": self.universe,
            "universe_at": (self.universe_at.isoformat()
                            if self.universe_at else None),
            "equity_curve": self.equity_curve[-5000:],
            "last_bar": str(self.last_bar) if self.last_bar is not None else None,
            "skim_refs": {k: round(v, 10) for k, v in self.skim_refs.items()},
            "skims": self.skims,
            "lock_state": self.lock_state,
            "opened": self.opened,
            "last_decision_bar": self.last_decision_bar,
            "pending_entries": self.pending_entries,
            "underfilled": sorted(getattr(self, "underfilled", set())),
            "pending_bar": str(self.last_bar) if self.last_bar is not None else None,
            "last_marks": {k: round(v, 12) for k, v in getattr(self, "last_marks", {}).items()}})

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
        return portfolio.target_weights(channels, self.s, derisk, shorts=self.short_pick)

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
        """Prices for the universe and every position. A held coin missing from the ticker, or
        quoted at zero, keeps its last known mark instead of counting as worthless, which read as
        a phantom drawdown and tripped the halt. DECISIONS.md#live-faults-2026-10-01"""
        prices = {}
        for sym in set(self.universe) | set(self.holdings) | set(self.shorts):
            spec = self.executor.spec(sym)
            if spec and spec.pair in quotes and float(quotes[spec.pair].get("LastPrice") or 0.0) > 0:
                prices[sym] = float(quotes[spec.pair]["LastPrice"])
        if not hasattr(self, "last_marks"):
            self.last_marks = {}
        stale = sorted(s for s in set(self.holdings) | set(self.shorts)
                       if s not in prices and s in self.last_marks)
        for s in stale:
            prices[s] = self.last_marks[s]
        if stale and getattr(self, "journal", None) is not None:
            self.journal.write("errors", {"event": "mark_from_last_known", "symbols": stale,
                                          "ref": "DECISIONS.md#live-faults-2026-10-01"})
        self.last_marks.update({s: prices[s] for s in set(self.holdings) | set(self.shorts)
                                if s in prices and s not in stale})
        equity = self.cash + sum(q * prices.get(s, 0.0)
                                 for s, q in self.holdings.items())
        equity += sum(portfolio.short_value(pos, prices[s]) if s in prices
                      else float(pos["collateral"]) for s, pos in self.shorts.items())
        return equity, prices

    def fit_to_cash(self, plan: dict, cash: float) -> dict:
        """Shrink a buy so notional plus fee fits the cash available, or skip it.

        A full-deployment book targets 1/n of equity per name, so its last buy
        plus the fee exceeds the cash left. The paper fill then silently did not
        happen while the order journal recorded it, so the book believed it held
        a name it did not, and a venue would reject the same order outright.
        DECISIONS.md#lowtf-paper-bots
        """
        short = plan["side"] == "SHORT_OPEN"
        fee = SHORT_FEE if short else FEE_RATE.get(plan["type"], 0.001)
        cap = max(0.0, cash) / (1.0 + fee)
        if plan["notional"] <= cap:
            return plan
        spec = self.executor.spec(plan["symbol"])
        qty = spec.round_qty(cap / plan["price"] * (1.0 - 1e-9)) if spec else 0.0
        if qty <= 0 or spec is None or qty * plan["price"] < max(spec.min_order, 1.0 if short else 0.0):
            return {"skipped": "insufficient_cash", "symbol": plan["symbol"], "pair": plan.get("pair"),
                    "notional": plan["notional"], "cash": round(cash, 4)}
        out = {**plan, "quantity": qty, "notional": round(qty * plan["price"], 4),
               "cash_capped_from": plan["notional"]}
        if short:
            out["collateral"] = round(qty * plan["price"], 2)
        return out

    def capped_entries_held(self) -> set[str]:
        """Held symbols whose latest BUY was cut short by cash and which have not been sold since,
        read from the order journal, for state saved before `underfilled` existed.
        DECISIONS.md#underfilled-entry-2026-10-04"""
        last: dict[str, dict] = {}
        for f in sorted(self.journal.dir.glob("orders-*.jsonl"))[-2:]:
            for line in f.read_text().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("event") == "placed" and r.get("symbol") and r.get("side") in ("BUY", "SELL"):
                    last[r["symbol"]] = r
        return {s for s, r in last.items()
                if r["side"] == "BUY" and r.get("cash_capped_from") and self.holdings.get(s, 0.0) > 0}

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
        if plan["side"] in ("SHORT_OPEN", "SHORT_CLOSE"):
            return self.apply_dry_short(plan)
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

    def apply_dry_short(self, plan: dict) -> bool:
        """Paper fill of a venue short leg, on the venue's documented arithmetic.

        Open at the bid, collateral and a 0.1% fee leave cash, a repeat open merges at the
        quantity-weighted entry. Close at the ask returns the closed collateral plus P&L
        less 0.1% of the closed value, the loss capped at that collateral.
        DECISIONS.md#short-paper-books
        """
        sym, px = plan["symbol"], float(plan["price"])
        if plan["side"] == "SHORT_OPEN":
            qty = float(plan["quantity"])
            coll = qty * px
            cost = coll * (1.0 + SHORT_FEE)
            if qty <= 0 or cost > self.cash + 1e-9:
                return False
            self.cash -= cost
            pos = self.shorts.get(sym)
            if pos:
                q0 = pos["qty"]
                pos["entry"] = (q0 * pos["entry"] + qty * px) / (q0 + qty)
                pos["qty"] = q0 + qty
                pos["collateral"] += coll
            else:
                self.shorts[sym] = {"qty": qty, "entry": px, "collateral": coll}
            return True
        pos = self.shorts.get(sym)
        if not pos:
            return False
        qty = pos["qty"] if plan.get("close_all") else min(float(plan["quantity"]), pos["qty"])
        if qty <= 0:
            return False
        frac = qty / pos["qty"]
        coll = pos["collateral"] * frac
        pnl = max(qty * (pos["entry"] - px), -coll)
        self.cash += coll + pnl - qty * px * SHORT_FEE
        spec = self.executor.spec(sym)
        left = pos["qty"] - qty
        if frac >= 1.0 - 1e-12 or (spec is not None and spec.round_qty(left) <= 0):
            self.shorts.pop(sym, None)
        else:
            pos["qty"] = left
            pos["collateral"] -= coll
        return True

    def regime_closes(self, matrix: pd.DataFrame) -> pd.Series:
        """BTC closes for the short regime, fetched on their own when BTC is not in the pool,
        so the regime never adds BTC to what the book may trade."""
        if REGIME_SYMBOL in matrix.columns:
            return matrix[REGIME_SYMBOL]
        frames = feed.bar_frame([REGIME_SYMBOL], self.s.interval, short_bars_needed(self.s))
        return feed.close_matrix(frames).get(REGIME_SYMBOL, pd.Series(dtype=float))

    def cycle(self) -> dict:
        now = dt.datetime.now(dt.timezone.utc)
        wall0, mono0 = time.time(), time.monotonic()
        self.refresh_universe(now)

        need = max(self.s.entry_bars, self.s.exit_bars) + 5
        frames = feed.bar_frame(self.universe, self.s.interval,
                                max(need + 20, REPLAY_BARS, short_bars_needed(self.s)))
        matrix = feed.close_matrix(frames)
        gaps = feed.data_gaps(self.universe, frames)
        hold_bar = incomplete_hold(gaps, matrix, self.gap_state)
        if gaps["missing"] or gaps["stale"]:
            self.journal.write("errors", {"event": "data_incomplete", **gaps,
                                          "bar": str(matrix.index[-1]) if len(matrix) else None,
                                          "decision_deferred": hold_bar,
                                          "ref": "DECISIONS.md#live-audit-2026-09-24"})
        quotes = feed.roostoo_quotes(self.client)
        ticker_age_s, resynced = ticker_age(self.client, float(self.s.kill_stale_ticker_s))
        if resynced is not None:
            self.journal.write("lifecycle", {"event": "clock_resynced", "ticker_age_s": round(ticker_age_s, 3),
                                             "stale_before_s": round(resynced, 3),
                                             "ref": "DECISIONS.md#clock-resync-2026-10-03"})
        if not self.s.dry_run:
            self.settle_blocked_submission()
            self.adopt_wallet()
            if not self.wallet_ok:
                return self.journal.write("waiting", {
                    "event": "wallet_unavailable", "orders": 0,
                    "ref": "DECISIONS.md#roostoo-keys-2026-09-30"})
        equity, prices = self.mark(quotes)
        self.equity_curve.append(equity)

        if self.s.mirror_reference == "none":
            mirror, worst = [], None
        else:
            mirror = feed.mirror_check(quotes, self.specs, sorted(set(self.universe) | set(self.holdings)))
            material = [m for m in mirror if m.get("material")]
            unchecked_held = set(self.holdings) - {m["symbol"] for m in mirror}
            raw_worst = (float("inf") if unchecked_held else
                         max((abs(m["deviation_bps"]) for m in material), default=0.0))
            if raw_worst >= self.s.mirror_max_deviation_bps:
                self.mirror_breaches += 1
            else:
                self.mirror_breaches = 0
            worst = (raw_worst if self.mirror_breaches >= 2 else
                     min(raw_worst, self.s.mirror_max_deviation_bps - 1e-9))
        guard = risk.gate(self.equity_curve, self.executor.error_rate(), ticker_age_s,
                          worst, self.s)
        derisk = risk.derisk_multiplier(now, self.s)

        prev_last_bar, prev_cold = self.last_bar, self.cold_start
        saved_books = json.loads(json.dumps({"skim_refs": self.skim_refs, "skims": self.skims,
                                             "lock_state": self.lock_state, "opened": self.opened,
                                             "last_decision_bar": self.last_decision_bar}, default=str))
        fresh = False if hold_bar else self.bar_close_due(matrix)
        channels = replay_book(matrix, self.s) if fresh else {}
        ranking = {}
        short_info = None
        self.short_pick = []
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
            if self.s.shorts_enabled:
                regime_now = short_regime(self.regime_closes(matrix), self.s, matrix)
                self.short_pick, short_info = portfolio.select_shorts(
                    replay_short_book(matrix, self.s), channels, len(selected), matrix,
                    self.s, regime_now["on"])
                short_info["regime"] = regime_now
            channels = selected

        # Hook: a subclass with a different signal overrides compute_target and
        # trades_every_cycle rather than copying this cycle, so it inherits the
        # cold-start guard, drift band, kill switches, mirror check, markout
        # instrumentation and atomic state unchanged. See bot/scalper_run.py.
        current_w = portfolio.current_weights(self.holdings, prices, equity, self.shorts)
        cash_frac = self.cash / equity if equity > 0 else 0.0
        retrying = (not fresh and self.target_from_channels() and bool(self.pending_entries)
                    and cash_frac >= RETRY_MIN_CASH_FRAC)
        if guard["halt"]:
            target = {}
        elif guard.get("freeze"):
            target = dict(current_w)
        elif fresh or not self.target_from_channels():
            target = self.compute_target(channels, derisk, prices)
        elif not self.s.booking.get("enabled") and not retrying:
            target = self.compute_target(channels, derisk, prices)
        else:
            # Not a bar close, so `channels` is empty by construction and a
            # target computed from it would be empty too, which `deltas` would
            # read as "sell everything". A booking bot trades every cycle, so it
            # must carry the held book forward and let only the ladder move it.
            # This flattened three books on 2026-09-22 before it was caught.
            # DECISIONS.md#booking-flattened-the-book
            target = carry_target(current_w, self.pending_entries, cash_frac)
        if self.s.shorts_enabled:
            target = portfolio.hold_shorts(target, current_w)
        # The skim ladder is a shared capability, not a property of one bot:
        # any config carrying a `booking` block gets it. bot/booking.py.
        wanted = dict(target)
        target, skims = booking.apply(target, current_w, prices, self.skim_refs,
                                      equity, self.s.booking, grow=self.underfilled)
        if fresh:
            skimmed = {e["symbol"] for e in skims}
            self.underfilled = {s for s in self.underfilled
                                if s in wanted and s not in skimmed and current_w.get(s, 0.0) > 0
                                and current_w[s] < wanted[s] * (1.0 - UNDERFILL_DONE)}
        if skims:
            self.skims += len(skims)
            self.journal.write("signals", {"event": "skim", "bar": str(matrix.index[-1])
                                           if len(matrix) else None,
                                           "step_pct": self.s.booking.get("step_pct"),
                                           "skim_fraction": self.s.booking.get("skim_fraction"),
                                           "skims": skims})
        target, lock_event, lock_force = lock.apply(target, equity, self.lock_state,
                                                    self.s.target_lock, now)
        if lock_event:
            self.journal.write("signals", {**lock_event, "equity": round(equity, 2),
                                           "start_equity": self.lock_state.get("start_equity")})
        # The gate defaults to always_on, which returns `target` unmodified, so
        # a bot that does not declare regime_gate behaves exactly as before.
        target, gate = regime.apply(target, self.s.regime_gate,
                                    held=set(self.holdings) | set(self.shorts),
                                    min_cushion_pct=self.s.min_cushion_pct)
        current = current_w
        orders = (portfolio.deltas(target, current, equity, prices,
                                   force={e["symbol"] for e in skims} | lock_force)
                  if (fresh or guard["halt"] or self.trades_every_cycle() or retrying)
                  and not guard.get("freeze") else [])

        suppressed = []
        if fresh and self.cold_start and not guard["halt"]:
            keep = []
            for o in orders:
                opening = ((o["side"] == "BUY" and o["symbol"] not in self.holdings)
                           or (o["side"] == "SHORT_OPEN" and o["symbol"] not in self.shorts))
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
        aborted = None
        ordered = sorted(orders, key=lambda o: o["side"] not in SELLS_FIRST)
        for i, o in enumerate(ordered):
            if stale_cycle(wall0, mono0, time.time(), time.monotonic()):
                aborted = [x["symbol"] for x in ordered[i:]]
                break
            plan = self.executor.prepare(o, quotes)
            if plan is None:
                continue
            if not plan.get("skipped") and plan["side"] in OPENS:
                plan = self.fit_to_cash(plan, spendable)
                if plan.get("cash_capped_from") and plan["side"] == "BUY":
                    self.underfilled.add(plan["symbol"])
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
                elif plan["side"] == "SHORT_OPEN":
                    spendable -= plan["notional"] * (1.0 + SHORT_FEE)
            placed.append(rec)
        self.executor.sweep_unfilled()
        if aborted is not None:
            self.journal.write("orders", {
                "event": "stale_cycle_aborted", "bar": str(matrix.index[-1]) if len(matrix) else None,
                "started_utc": now.isoformat(),
                "age_s": round(time.time() - wall0, 1),
                "slept_s": round((time.time() - wall0) - (time.monotonic() - mono0), 1),
                "unsent": aborted, "sent": len(placed), "redecide_bar": fresh,
                "ref": "DECISIONS.md#stale-cycle-guard"})
            if fresh:
                self.last_bar, self.cold_start = prev_last_bar, prev_cold
            if not placed:
                self.skim_refs = saved_books["skim_refs"]
                self.skims = saved_books["skims"]
                self.lock_state = saved_books["lock_state"]
                self.opened = saved_books["opened"]
                self.last_decision_bar = saved_books["last_decision_bar"]
        elif self.target_from_channels():
            self.pending_entries = next_pending(
                fresh, guard["halt"] or bool(guard.get("freeze")), target, self.pending_entries,
                portfolio.current_weights(self.holdings, prices, equity),
                {o["symbol"] for o in suppressed}, cash_frac)

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

        held_weights = portfolio.current_weights(self.holdings, prices, equity, self.shorts)
        snapshot = {
            "event": "cycle", "bar": str(matrix.index[-1]) if len(matrix) else None,
            "new_bar": fresh, "equity": round(equity, 2),
            "cash": round(self.cash, 2),
            "gross_exposure": round(sum(abs(w) for w in held_weights.values()), 4),
            "n_long": sum(1 for w in held_weights.values() if w > 0),
            "n_short": sum(1 for w in held_weights.values() if w < 0),
            "target_gross": round(sum(abs(w) for w in target.values()), 4) if fresh else None,
            "n_target": len(target) if fresh else None,
            "positions": {k: round(v, 5) for k, v in sorted(held_weights.items())},
            "marks": {k: float(v) for k, v in sorted(prices.items())
                      if k in held_weights or k in self.recent_symbols},
            "ranking": ranking or None,
            "shorts": short_info,
            "n_universe": len(self.universe),
            "derisk": derisk, "halt": guard["halt"], "freeze": guard.get("freeze"), "breaches": guard["breaches"],
            "drawdown": guard["drawdown"], "orders": len(placed),
            "cold_start_suppressed": len(suppressed) or None,
            "mirror_worst_bps": worst, "mirror_checked": len(mirror),
            "ticker_age_s": round(ticker_age_s, 3),
            "config_sha": self.s.config_sha256,
            "gate": gate,
            "stale_aborted": aborted is not None or None,
        }
        if not self.s.dry_run:
            self.adopt_wallet()
        self.persist()
        self.journal.write("cycles", snapshot)
        if fresh and aborted is None:
            self.journal.write("signals", {
                "bar": str(matrix.index[-1]),
                "channels": {s: c.as_dict() for s, c in channels.items()},
                "target_weights": target})
        return snapshot

    def settle_blocked_submission(self) -> None:
        """Re-run intent reconciliation while an ambiguous submission blocks orders, and lift the
        block once every intent is settled; after BLOCK_EXIT_CYCLES unsettled cycles exit so the
        supervisor restarts the process and its startup reconciliation. One timed-out order used to
        block every later order, exits included, for the life of the process.
        DECISIONS.md#live-faults-2026-10-01"""
        import os

        ex = getattr(self, "executor", None)
        if ex is None or not ex.submission_blocked or getattr(self, "intents", None) is None:
            self.blocked_cycles = 0
            return
        report = reconcile_intents(self.intents, self.client, self.journal)
        if report["clean"]:
            self.executor.submission_blocked = False
            self.blocked_cycles = 0
            self.journal.write("lifecycle", {"event": "submission_unblocked", "settled": report["settled"],
                                             "ref": "DECISIONS.md#live-faults-2026-10-01"})
            return
        self.blocked_cycles += 1
        if self.blocked_cycles >= BLOCK_EXIT_CYCLES:
            self.journal.write("lifecycle", {"event": "exit_unsettled_submission", "cycles": self.blocked_cycles,
                                             "ref": "DECISIONS.md#live-faults-2026-10-01"})
            os._exit(4)

    def start_watchdog(self, limit_s: float = WATCHDOG_S) -> None:
        """Exit the process when one cycle has run longer than `limit_s` (monotonic clock, so
        machine sleep does not count); the supervisor respawns it from saved state. A worker was
        found alive but frozen for 33 minutes on 2026-09-27. DECISIONS.md#cycle-watchdog-2026-09-27"""
        import os
        import threading

        self._cycle_started = None

        def watch() -> None:
            while True:
                time.sleep(5)
                t0 = self._cycle_started
                if t0 is not None and time.monotonic() - t0 > limit_s:
                    try:
                        self.journal.write("lifecycle", {"event": "watchdog_exit",
                                                         "cycle_seconds": round(time.monotonic() - t0, 1),
                                                         "ref": "DECISIONS.md#cycle-watchdog-2026-09-27"})
                    finally:
                        os._exit(3)

        threading.Thread(target=watch, daemon=True, name="cycle-watchdog").start()

    def loop(self, cycles: int | None = None) -> None:
        n = 0
        if cycles is None:
            self.start_watchdog()
        while cycles is None or n < cycles:
            self._cycle_started = time.monotonic()
            try:
                self.cycle()
            except Exception as exc:
                self.journal.write("errors", {"event": "cycle_error",
                                              "error": repr(exc)})
            self._cycle_started = None
            n += 1
            if cycles is None or n < cycles:
                time.sleep(next_sleep(time.time(), self.s.poll_seconds,
                                      BAR_SECONDS.get(self.s.interval, self.s.poll_seconds)))


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
