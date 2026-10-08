"""E2E check of DECISIONS.md#cash-ride-sleeve-2026-10-05.

Runs the real `CashSleeveRegimeBot` cycle (host `competition_r4` rule, guards and ladder, plus the sleeve) in
live mode against a simulated Roostoo wallet: public endpoints (prices, pair specs, server time) are the real
venue and Binance bars are real; balance, orders and fills are simulated, every order filling at its limit price
with a 0.1% fee. The host starts with the live book's coins and 7,289 USD cash. The sleeve's trigger is lowered
to 0.05% so it enters on the current bar. Phases: entry, steady state, host handover, exit, and a resting entry
that fills between the bot's pending-order and wallet reads (DECISIONS.md#pending-before-wallet-2026-10-06).
Checks every cycle: the reported equity equals the wallet's value at the marks, sleeve cash plus host cash equals
the wallet's cash, and the host never trades a sleeve coin. Writes only to temporary live/e2e_* and config files,
removed afterwards. No competition or TEST keys are read. Usage: python3 deploy/checks/cash_sleeve_e2e.py
"""
import itertools
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
NAME = "e2e_cash_sleeve"
HOST_W = {"AAVEUSDT": 0.095, "ADAUSDT": 0.502, "ENAUSDT": 0.244, "FILUSDT": 0.084}
EQUITY, CASH = 96_574.0, 40_000.0


def main() -> int:
    os.environ["ROOSTOO_DRY_RUN"] = "0"
    from bot import run
    from bot.cash_sleeve_run import CashSleeveRegimeBot
    from bot.regime_ls_run import RegimeLSBot
    from bot.settings import load
    from venue.roostoo import RoostooClient

    class Venue(RoostooClient):
        ids = itertools.count(1)

        def __init__(self):
            super().__init__(None, None)
            self.wallet: dict[str, float] = {}
            self.trades: list[dict] = []
            self.rest_buys = False
            self.resting: list[dict] = []
            self.locked = 0.0
            self.fill_after_balance = False

        def balance(self) -> dict:
            snap = {c: {"Free": q, "Lock": self.locked if c == "USD" else 0.0} for c, q in self.wallet.items()}
            if self.fill_after_balance:
                # The resting order fills right after this read, as FIL's did at 14:35 IST 2026-10-06.
                self.fill_after_balance = False
                for o in self.resting:
                    self.locked -= o["cost"]
                    self.wallet[o["coin"]] = self.wallet.get(o["coin"], 0.0) + o["qty"]
                self.resting = []
            return snap

        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            coin = pair.split("/")[0]
            q, p = float(quantity), float(price or self.ticker()[pair]["LastPrice"])
            if side == "BUY" and self.rest_buys:
                oid = next(self.ids)
                self.wallet["USD"] -= q * p * 1.001
                self.locked += q * p * 1.001
                self.resting.append({"id": oid, "pair": pair, "coin": coin, "qty": q, "price": p,
                                     "cost": q * p * 1.001, "ts": time.time()})
                self.trades.append({"pair": pair, "side": side, "qty": q, "price": p, "resting": True})
                return {"OrderDetail": {"OrderID": oid, "Status": "PENDING", "Role": "MAKER",
                                        "FilledQuantity": 0.0, "FilledAverPrice": 0.0, "CommissionPercent": 0.0005}}
            if side == "BUY":
                self.wallet["USD"] -= q * p * 1.001
                self.wallet[coin] = self.wallet.get(coin, 0.0) + q
            else:
                self.wallet[coin] = self.wallet.get(coin, 0.0) - q
                self.wallet["USD"] += q * p * 0.999
            self.trades.append({"pair": pair, "side": side, "qty": q, "price": p})
            return {"OrderDetail": {"OrderID": next(self.ids), "Status": "FILLED", "Role": "TAKER",
                                    "FilledQuantity": q, "FilledAverPrice": p, "CommissionPercent": 0.001}}

        def query_order(self, order_id=None, pair=None, pending_only=None):
            return {"Success": True, "OrderDetails": [
                {"OrderID": o["id"], "Pair": o["pair"], "Side": "BUY", "Type": "LIMIT", "Quantity": o["qty"],
                 "Price": o["price"], "FilledQuantity": 0.0, "Status": "PENDING",
                 "CreateTimestamp": o["ts"] * 1000.0} for o in self.resting]}

        def cancel_order(self, order_id=None, pair=None):
            return {"Success": True}

    venue = Venue()
    run.make_client = lambda settings: venue
    cfg = yaml.safe_load((ROOT / "config/competition_r4.yaml").read_text())
    cfg["meta"]["name"] = NAME
    cfg["cash_sleeve"]["ride"]["sigma_k"] = 0.05
    cfg["cash_sleeve"]["ride"].pop("trim_churn", None)
    cfg_path = ROOT / "config" / f"{NAME}.yaml"
    d = ROOT / "live" / NAME
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    failures = []

    def check(ok: bool, what: str) -> None:
        print(("  ok   " if ok else "  FAIL ") + what)
        if not ok:
            failures.append(what)

    try:
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        quotes = venue.ticker()
        px = {p.split("/")[0] + "USDT": float(q["LastPrice"]) for p, q in quotes.items()}
        units = {s: w * EQUITY / px[s] for s, w in HOST_W.items()}
        venue.wallet = {"USD": CASH, **{s[:-4]: u for s, u in units.items()}}
        bar30 = pd.Timestamp.now(tz="UTC").floor("30min") - pd.Timedelta(minutes=30)
        state = {"cash": CASH, "holdings": units, "shorts": {}, "equity_curve": [100_000.0, EQUITY],
                 "last_bar": str(bar30), "last_decision_bar": str(bar30), "pending_bar": str(bar30),
                 "pending_entries": {}, "skim_refs": {s: px[s] for s in units}, "skims": 0, "lock_state": {},
                 "opened": {s: ["2026-10-05 12:00:00+00:00", 1] for s in units}, "last_marks": {}, "state": {},
                 "underfilled": [], "underfill_ref": {}}
        (d / "state.json").write_text(json.dumps(state))
        bot = CashSleeveRegimeBot(load(str(cfg_path)), mode="once")

        def wallet_value(marks: dict[str, float]) -> float:
            return venue.wallet["USD"] + venue.locked + sum(q * marks.get(c + "USDT", 0.0) for c, q in venue.wallet.items()
                                             if c != "USD")

        def cycle(label: str, slack: float = 0.0) -> dict:
            n0 = len(venue.trades)
            snap = bot.cycle()
            bot.adopt_wallet()
            led = bot.sleeve
            marks = {**bot.sleeve_px, **(snap.get("marks") or {})}
            new = venue.trades[n0:]
            print(f"{label}: equity {snap['equity']:.2f}, host cash {bot.cash:.2f}, sleeve "
                  f"{json.dumps(snap.get('cash_sleeve'))}, trades {new}")
            fees = sum(t["qty"] * t["price"] for t in new) * 0.001
            check(abs(snap["equity"] - wallet_value(marks)) < 2.0 + 1.5 * fees + slack,
                  f"reported equity {snap['equity']:.2f} = wallet value {wallet_value(marks):.2f}")
            check(venue.wallet["USD"] >= -1e-6, f"wallet cash never negative ({venue.wallet['USD']:.2f})")
            check(abs(bot.cash + led.cash - venue.wallet["USD"] - venue.locked) < 0.01,
                  f"host cash + sleeve cash = wallet cash {venue.wallet['USD'] + venue.locked:.2f}")
            check(not (set(bot.holdings) & led.owned()), "no coin is both host and sleeve")
            return {"snap": snap, "trades": new}

        print("phase 1: entry")
        r = cycle("cycle 1")
        led = bot.sleeve
        check(led is not None and abs(led.budget - 39800.0) < 1e-6, f"sleeve budget 7,000 + 32,800 top-up (got {led and led.budget})")
        check(led.top_ups == ["2026-10-06-churn"] and abs(bot.cash - 200.0) < 25.0, f"top-up applied once, host cash {bot.cash:.2f}")
        check(20 <= len(led.universe) <= 30, f"sleeve rides the host's universe ({len(led.universe)} coins)")
        check(all(abs(t["qty"] * t["price"] - 39800.0 / 2) < 600 for t in r["trades"] if t["side"] == "BUY"),
              f"each ride is half of the sleeve: {[round(t['qty'] * t['price']) for t in r['trades']]}")
        buys = [t for t in r["trades"] if t["side"] == "BUY"]
        check(len(buys) == 2, f"sleeve bought 2 rides on the forced trigger (got {len(buys)})")
        check(not any(t["pair"].split("/")[0] + "USDT" in units for t in r["trades"]),
              "no order on a host coin")
        r = cycle("cycle 2")
        pos = r["snap"]["positions"]
        check(set(pos) == set(units) | {t["pair"].split("/")[0] + "USDT" for t in buys}
              and abs(sum(pos.values()) + r["snap"]["cash"] / r["snap"]["equity"] - 1) < 0.002,
              f"reported positions cover host and sleeve coins and, with cash, sum to the account {pos}")
        check(all(abs(bot.holdings[s] - units[s]) < 1e-9 for s in units), "host holdings unchanged")
        check(len(led.units) == 2 and all(v > 0 for v in led.units.values()), "sleeve owns its 2 coins")
        check(r["trades"] == [], "steady state sends nothing")

        print("phase 2: host enters a sleeve coin")
        coin = sorted(led.units)[0]
        moved = led.units[coin]
        orig = RegimeLSBot.compute_target
        want_w = {"w": 0.04}

        def host_wants(self, channels, derisk, prices):
            return {**{s: w for s, w in HOST_W.items()}, coin: want_w["w"]}
        RegimeLSBot.compute_target = host_wants
        bot.last_bar = bar30 - pd.Timedelta(minutes=30)
        r = cycle("cycle 3a (host wants 0.04, less than the ride)")
        check(coin in led.owned() and abs(led.units[coin] - moved) < 1e-9, f"small host target leaves {coin} with the sleeve")
        check(not [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == coin], "host bought none of it")
        want_w["w"] = 0.40
        bot.last_bar = bar30 - pd.Timedelta(minutes=30)
        r = cycle("cycle 3b (host wants 0.20, more than the ride)")
        RegimeLSBot.compute_target = orig
        check(coin not in led.owned(), f"sleeve released {coin}")
        check(bot.holdings.get(coin, 0.0) >= moved - 1e-9, f"host holds the released {coin} units")
        host_buy = [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == coin and t["side"] == "BUY"]
        want = 0.40 * (r["snap"]["equity"] - led.equity(bot.sleeve_px))
        got = moved * bot.sleeve_px[coin] + sum(t["qty"] * t["price"] for t in host_buy)
        check(got <= want * 1.02, f"host never holds more than its 0.40 target ({got:.0f} vs {want:.0f})")

        print("phase 3: exit")
        bot.sleeve_cfg["ride"]["sigma_k"] = 500.0
        for s in led.held:
            led.held[s][0] = str(pd.Timestamp(led.held[s][0]) - pd.Timedelta(days=2))
            # In profit past the fee line, so the no-loss exit lets the hold expiry sell it
            # (DECISIONS.md#no-loss-net-of-fees-2026-10-06).
            led.held[s][1] = float(led.held[s][1]) * 0.99
        # The cost band also reads the fills (DECISIONS.md#no-sale-below-cost-anywhere-2026-10-06); put them at the
        # same 1% below, so the phase does not depend on where the market went since the entry.
        bot.entry_prices = lambda: {s: float(led.held[s][1]) for s in led.held}
        led.bar = None
        r = cycle("cycle 4 (hold expired)")
        sells = [t for t in r["trades"] if t["side"] == "SELL"]
        check(len(sells) == 1, f"sleeve sold its 1 remaining ride (got {len(sells)})")
        r = cycle("cycle 5")
        check(led.units == {} and led.owned() == set(), "sleeve flat after the exits")
        check(39500 < led.cash < 39800, f"sleeve cash after a round trip {led.cash:.2f}")
        print("phase 4: a resting entry fills between the bot's reads")
        fresh_coin = next(s for s in sorted(bot.universe) if s not in bot.holdings and s not in led.owned()
                          and s in bot.sleeve_px)

        def host_adds(self, channels, derisk, prices):
            return {**{s: w for s, w in HOST_W.items()}, fresh_coin: 0.05}
        RegimeLSBot.compute_target = host_adds
        bot.last_bar = bar30 - pd.Timedelta(minutes=30)
        venue.rest_buys = True
        venue.wallet["USD"] += 40_000.0  # host sells are held at cost (no-sale-below-cost), so fund the entry directly
        first = []
        for k in range(3):
            r = cycle(f"cycle 6.{k} (host enters {fresh_coin}, the order rests)")
            if k == 0:
                RegimeLSBot.compute_target = orig
            first += [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == fresh_coin and t["side"] == "BUY"]
            if venue.resting:
                break
        if not venue.resting:
            print("  events:", [json.loads(x).get("event") for f in d.glob("*-*.jsonl") for x in f.read_text().splitlines()][-30:])
        check(len(first) == 1 and venue.resting, f"one resting {fresh_coin} buy ({first})")
        venue.fill_after_balance = True
        # The cycle's equity is read before the fill and checked after it: allow the fee and the mark-to-limit gap.
        r = cycle("cycle 7 (it fills right after the wallet read)", slack=0.005 * first[0]["qty"] * first[0]["price"])
        again = [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == fresh_coin and t["side"] == "BUY"]
        check(again == [], f"no second {fresh_coin} buy while the first was filling ({again})")
        r = cycle("cycle 8")
        again = [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == fresh_coin and t["side"] == "BUY"]
        held_units = bot.holdings.get(fresh_coin, 0.0)
        check(again == [] and abs(held_units - first[0]["qty"]) < 1e-6,
              f"{fresh_coin} held once ({held_units} units for one {first[0]['qty']}-unit order), nothing re-sent")
        venue.rest_buys = False

        rows = [json.loads(x) for f in d.glob("orders-*.jsonl") for x in f.read_text().splitlines()]
        tagged = [o for o in rows if o.get("event") == "placed" and o.get("book") == "cash_sleeve"]
        check(len(tagged) == 3, f"sleeve orders are journaled with book: cash_sleeve ({len(tagged)})")
        errs = [json.loads(x) for f in d.glob("errors-*.jsonl") for x in f.read_text().splitlines()]
        check(not [e for e in errs if e.get("event") == "cash_sleeve_error"], "no cash_sleeve_error")
    finally:
        cfg_path.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)
    print("PASS" if not failures else f"FAIL: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
