"""Live regime book with a cash ride sleeve (`bot.cash_sleeve`).

The host is `RegimeLSBot` unchanged: its rule, guards, ladder and kill switches see a wallet from which
the sleeve's coins and cash are removed. After the host's cycle the sleeve decides once per closed 5m bar
and sends its orders through the same executor, tagged `book: cash_sleeve`. The drawdown kill switch and
the reported equity count the whole account (`Bot.book_offset`).
DECISIONS.md#cash-ride-sleeve-2026-10-05
"""
from __future__ import annotations

import argparse
import json
import time

import pandas as pd
import yaml

from bot import cash_sleeve
from bot.regime_ls_run import RegimeLSBot
from bot.entry_guard import NO_LOSS_FEE_BUFFER
from bot.run import venue_quote
from bot.scalper_adaptive_run import bars_needed, load_clock
from bot.settings import ROOT, load

STEP = pd.Timedelta(minutes=5)
SLEEVE_TIME_BUDGET_S = 20.0


class CashSleeveRegimeBot(RegimeLSBot):
    def __init__(self, settings, mode: str = "continuous"):
        raw = yaml.safe_load((ROOT / "config" / f"{settings.name}.yaml").read_text())
        self.sleeve_cfg = raw["cash_sleeve"]
        self.sleeve_path = ROOT / "live" / settings.name / "cash_sleeve.json"
        self.sleeve = cash_sleeve.Ledger.load(self.sleeve_path)
        self.sleeve_px: dict[str, float] = {}
        self.sleeve_quotes: dict = {}
        self.wallet_cash = 0.0
        self.host_target: set[str] = set()
        self.host_target_w: dict[str, float] = {}
        self.sleeve_universe: list[str] = []
        self.sleeve_universe_at = 0.0
        super().__init__(settings, mode=mode)

    def adopt_wallet(self) -> None:
        led = self.sleeve
        owned = led.owned() if led else set()
        view = {**self.holdings, **{s: (led.units.get(s, 0.0) if led else 0.0) for s in owned}}
        self.holdings = view
        super().adopt_wallet()
        read = self.holdings is not view
        wallet = {s: self.holdings.pop(s, 0.0) for s in owned}
        if not read:
            return
        self.wallet_cash = self.cash
        if led is None:
            budget = float(self.sleeve_cfg["budget_usd"])
            reserve = float(self.sleeve_cfg.get("host_reserve_usd", 0.0))
            cash = max(0.0, min(budget, self.cash - reserve))
            led = self.sleeve = cash_sleeve.Ledger(cash=cash, budget=cash)
            led.save(self.sleeve_path)
            self.journal.write("lifecycle", {"event": "cash_sleeve_start", "budget": round(cash, 2),
                                             "wallet_cash": round(self.cash, 2),
                                             "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
        fills = cash_sleeve.reconcile(led, wallet, self.sleeve_px)
        if fills:
            led.save(self.sleeve_path)
            self.journal.write("orders", {"event": "cash_sleeve_fill", "book": "cash_sleeve", "fills": fills,
                                          "sleeve_cash": round(led.cash, 2),
                                          "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
        self.cash = self.cash - led.cash
        self.state = {s: True for s in self.holdings}
        self.lend_to_host(led)
        tag = self.sleeve_cfg.get("top_up_tag")
        if tag and tag not in led.top_ups:
            want = float(self.sleeve_cfg.get("top_up_usd", 0.0))
            amount = min(want, max(0.0, self.cash - float(self.sleeve_cfg.get("host_reserve_usd", 0.0))))
            added = cash_sleeve.top_up(led, amount, tag, self.sleeve_px)
            if added:
                self.cash -= added
                led.save(self.sleeve_path)
                self.journal.write("lifecycle", {"event": "cash_sleeve_top_up", "tag": tag, "added": round(added, 2),
                                                 "budget": round(led.budget, 2), "host_cash": round(self.cash, 2),
                                                 "held_weights": {k: round(float(v[3]), 4) for k, v in led.held.items()},
                                                 "ref": "DECISIONS.md#sleeve-wide-ride-2026-10-06"})

    def lend_to_host(self, led: cash_sleeve.Ledger) -> None:
        """Fund the host's fresh entries that venue cash cut short (`underfilled`) from the sleeve's cash while
        the sleeve has a free slot: the shortfall is each such name's target weight of the host book less what it
        holds, valued at the mark. The host completes the entry under its own 1% chase cap.
        DECISIONS.md#sleeve-lends-to-host-2026-10-06"""
        if not self.sleeve_cfg.get("lend_to_host") or not self.underfilled or not self.host_target_w:
            return
        px = self.sleeve_px
        n = int(self.sleeve_cfg["ride"].get("n", 2))
        light = set(self.sleeve_cfg.get("weightless_rides") or [])
        used = sum(float(v[3]) for k, v in led.held.items() if k not in light and len(v) > 3)
        if int((1.0 - used + 1e-9) * n) < 1:
            return
        host_eq = self.cash + sum(q * px.get(s, 0.0) for s, q in self.holdings.items())
        need = sum(max(0.0, self.host_target_w.get(s, 0.0) * host_eq - self.holdings.get(s, 0.0) * px.get(s, 0.0))
                   for s in self.underfilled if s in px)
        need -= max(0.0, self.cash)
        if need < 50.0:
            return
        lent = cash_sleeve.lend(led, need)
        if lent > 0:
            self.cash += lent
            led.save(self.sleeve_path)
            self.journal.write("lifecycle", {"event": "cash_sleeve_lend", "lent": round(lent, 2),
                                             "for": sorted(self.underfilled), "host_cash": round(self.cash, 2),
                                             "sleeve_cash": round(led.cash, 2),
                                             "ref": "DECISIONS.md#sleeve-lends-to-host-2026-10-06"})

    def exit_band(self, symbol: str) -> tuple[float, float] | None:
        """A sleeve ride with `no_loss_exit` is never sold below the higher of its entry close and its average
        fill, plus a round trip of fees, at any depth; host coins take the host guard's band.
        DECISIONS.md#no-loss-escalation-2026-10-06, DECISIONS.md#no-sale-below-cost-anywhere-2026-10-06"""
        led = self.sleeve
        if led is not None and symbol in led.owned():
            rec = led.held.get(symbol)
            if not self.sleeve_cfg.get("no_loss_exit") or not rec:
                return None
            cost = max(float(rec[1]), self.entry_prices().get(symbol, 0.0))
            return 0.0, cost * (1.0 + NO_LOSS_FEE_BUFFER)
        return super().exit_band(symbol)

    def mark(self, quotes: dict) -> tuple[float, dict[str, float]]:
        self.sleeve_quotes = quotes
        names = set(self.universe) | set(self.sleeve_universe) | (self.sleeve.owned() if self.sleeve else set())
        for s in names:
            spec = self.executor.spec(s)
            if spec and spec.pair in quotes and float(quotes[spec.pair].get("LastPrice") or 0.0) > 0:
                self.sleeve_px[s] = float(quotes[spec.pair]["LastPrice"])
        return super().mark(quotes)

    def book_offset(self) -> float:
        return self.sleeve.equity(self.sleeve_px) if self.sleeve else 0.0

    def snapshot_extra(self) -> dict:
        """The cycle record shows the whole account, so the desk and the watch see the sleeve's coins: positions
        as weights of the account equity, marks for every held or recently traded coin, cash as the wallet's;
        `host_cash` keeps the host's own part."""
        led = self.sleeve
        if led is None:
            return {}
        px = {**self.last_marks, **self.sleeve_px}
        account = self.equity_curve[-1] if self.equity_curve else 0.0
        held = {**{s: q for s, q in self.holdings.items()}, **led.units}
        pos = {s: round(q * px.get(s, 0.0) / account, 5) for s, q in sorted(held.items())
               if account > 0 and q * px.get(s, 0.0) >= cash_sleeve.DUST_USD}
        marks = {s: px[s] for s in set(held) | set(self.recent_symbols) if s in px}
        return {"positions": pos, "marks": dict(sorted(marks.items())), "cash": round(self.cash + led.cash, 2),
                "host_cash": round(self.cash, 2),
                "cash_sleeve": {"equity": round(led.equity(self.sleeve_px), 2), "cash": round(led.cash, 2),
                                "budget": round(led.budget, 2), "stopped": led.stopped,
                                "value": {s: round(u * self.sleeve_px.get(s, 0.0), 2) for s, u in led.units.items()},
                                "riding": sorted(led.held)}}

    def compute_target(self, channels: dict, derisk: float, prices: dict[str, float]) -> dict[str, float]:
        target = super().compute_target(channels, derisk, prices)
        self.host_target = {s for s, v in target.items() if v > 0}
        self.host_target_w = {s: float(v) for s, v in target.items() if v > 0}
        led = self.sleeve
        if led is None:
            return target
        equity = self.cash + sum(q * prices.get(s, 0.0) for s, q in self.holdings.items())
        for s in sorted(self.host_target & led.owned()):
            p = prices.get(s) or self.sleeve_px.get(s)
            if not p:
                continue
            if led.units.get(s, 0.0) * p > target[s] * equity:
                target[s] = 0.0
                self.journal.write("signals", {"event": "cash_sleeve_kept", "symbol": s, "units": led.units.get(s, 0.0),
                                               "host_target": round(float(target[s]), 5),
                                               "ref": "DECISIONS.md#sleeve-wide-ride-2026-10-06"})
                continue
            u = cash_sleeve.release(led, s, p)
            self.holdings[s] = self.holdings.get(s, 0.0) + u
            self.cash -= u * p
            moved = u * p / equity if equity > 0 else 0.0
            target[s] = max(0.0, target[s] - moved)
            self.journal.write("signals", {"event": "cash_sleeve_handover", "symbol": s, "units": u, "price": p,
                                           "host_target_left": round(target[s], 5),
                                           "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
            led.save(self.sleeve_path)
        return target

    def cycle(self) -> dict:
        snap = super().cycle()
        try:
            self.sleeve_step()
        except Exception as exc:                                  # noqa: BLE001
            self.journal.write("errors", {"event": "cash_sleeve_error", "error": repr(exc)[:300],
                                          "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
        return snap

    def sleeve_step(self) -> None:
        led = self.sleeve
        if led is None or self.s.dry_run or not self.wallet_ok:
            return
        started = getattr(self, "_cycle_started", None)
        if started is not None and time.monotonic() - started > SLEEVE_TIME_BUDGET_S:
            return
        cfg = self.sleeve_cfg
        px = self.sleeve_px
        uni = self.refresh_sleeve_universe()
        led.universe = uni
        last_closed = pd.Timestamp.now(tz="UTC").floor("5min") - STEP
        if led.bar is None or pd.Timestamp(led.bar) < last_closed:
            host = {s for s, q in self.holdings.items() if q * px.get(s, 0.0) >= cash_sleeve.DUST_USD}
            d5 = load_clock(uni, "5m", bars_needed({"cc": cfg["ride"]}), False)
            close, high = d5["close"], d5["high"]
            if len(close) > 3 and close.index[-1] == last_closed:
                ev = cash_sleeve.decide(led, close, high, cfg["ride"], px, host | self.host_target,
                                        float(cfg["stop_equity_frac"]), cfg["ladder"],
                                        no_loss_exit=bool(cfg.get("no_loss_exit")),
                                        weightless=set(cfg.get("weightless_rides") or []),
                                        paused=self.entries_paused() is not None)
                led.save(self.sleeve_path)
                if ev["entered"] or ev["exited"] or ev["skimmed"] or ev["loss_kept"]:
                    self.journal.write("signals", {"event": "cash_sleeve_decision", **ev,
                                                   "target": {s: round(v, 8) for s, v in led.target.items()},
                                                   "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
        orders, closed = cash_sleeve.plan_orders(led, px, last_closed, STEP, int(cfg["entry_window_bars"]),
                                                 float(cfg["entry_chase_max"]))
        if closed:
            self.journal.write("signals", {"event": "cash_sleeve_entry_closed", "symbols": closed,
                                           "units": {s: led.units.get(s, 0.0) for s in closed},
                                           "ref": "DECISIONS.md#cash-ride-sleeve-2026-10-05"})
        if self.entries_paused() is not None:
            orders = [o for o in orders if o["side"] != "BUY"]
        spendable = self.free_cash(led) if any(o["side"] == "BUY" for o in orders) else 0.0
        for o in orders:
            plan = self.executor.prepare(o, self.sleeve_quotes)
            if plan is None:
                continue
            if not plan.get("skipped") and plan["side"] == "BUY":
                plan = self.fit_to_cash(plan, spendable)
                if not plan.get("skipped"):
                    spendable -= plan["notional"] * (1.0 + cash_sleeve.FEE)
            self.executor.send({**plan, "book": "cash_sleeve"})
        led.save(self.sleeve_path)

    def refresh_sleeve_universe(self) -> list[str]:
        """The host's universe, or with `universe_mode: venue_all` every tradable Roostoo crypto pair that
        prints Binance bars (`bot.universe.select`), refreshed daily. DECISIONS.md#sleeve-wide-ride-2026-10-06"""
        mode = self.sleeve_cfg.get("universe_mode")
        if not mode:
            return sorted(self.universe)
        if not self.sleeve_universe or time.time() - self.sleeve_universe_at > 86_400:
            from types import SimpleNamespace

            from bot import universe
            sel = universe.select(SimpleNamespace(universe_mode=mode), self.specs)["selected"]
            if sel:
                self.sleeve_universe, self.sleeve_universe_at = sorted(sel), time.time()
                self.journal.write("universe", {"event": "cash_sleeve_universe", "mode": mode, "n": len(sel),
                                                "ref": "DECISIONS.md#sleeve-wide-ride-2026-10-06"})
        return self.sleeve_universe or sorted(self.universe)

    def free_cash(self, led: cash_sleeve.Ledger) -> float:
        """What a sleeve buy may spend: its own cash, but never more than the wallet's free cash, which is
        lower while a host order locks cash or after a handover lent the host the sleeve's cash."""
        try:
            wallet = self.client.balance()
        except Exception as exc:                                  # noqa: BLE001
            self.journal.write("errors", {"event": "cash_sleeve_balance_failed", "error": repr(exc)[:200]})
            return 0.0
        row = (wallet.get("Coins", wallet) or {}).get(venue_quote(self.specs)) or {}
        free = float(row.get("Free", 0.0)) if isinstance(row, dict) else float(row)
        return max(0.0, min(led.cash, free))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    bot = CashSleeveRegimeBot(load(a.config), mode="once" if a.once else "continuous")
    if a.once:
        print(json.dumps(bot.cycle(), indent=2, default=str))
        return 0
    bot.loop(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
