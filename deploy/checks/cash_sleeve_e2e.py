"""E2E check of DECISIONS.md#cash-ride-sleeve-2026-10-05.

Runs the real `CashSleeveRegimeBot` cycle (host `competition_r4` rule, guards and ladder, plus the sleeve) in
live mode against a simulated Roostoo wallet: public endpoints (prices, pair specs, server time) are the real
venue and Binance bars are real; balance, orders and fills are simulated, every order filling at its limit price
with a 0.1% fee. The host starts with the live book's coins and 7,289 USD cash. The sleeve's trigger is lowered
to 0.05% so it enters on the current bar. Four phases: entry, steady state, host handover, exit.
Checks every cycle: the reported equity equals the wallet's value at the marks, sleeve cash plus host cash equals
the wallet's cash, and the host never trades a sleeve coin. Writes only to temporary live/e2e_* and config files,
removed afterwards. No competition or TEST keys are read. Usage: python3 deploy/checks/cash_sleeve_e2e.py
"""
import itertools
import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
NAME = "e2e_cash_sleeve"
HOST_W = {"AAVEUSDT": 0.095, "ADAUSDT": 0.502, "ENAUSDT": 0.244, "FILUSDT": 0.084}
EQUITY, CASH = 96_574.0, 7_289.41


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

        def balance(self) -> dict:
            return {c: {"Free": q, "Lock": 0.0} for c, q in self.wallet.items()}

        def place_order(self, pair, side, quantity, price=None, client_order_id=None):
            coin = pair.split("/")[0]
            q, p = float(quantity), float(price or self.ticker()[pair]["LastPrice"])
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
            return {"Success": True, "OrderDetails": []}

        def cancel_order(self, order_id=None, pair=None):
            return {"Success": True}

    venue = Venue()
    run.make_client = lambda settings: venue
    cfg = yaml.safe_load((ROOT / "config/competition_r4.yaml").read_text())
    cfg["meta"]["name"] = NAME
    cfg["cash_sleeve"]["ride"]["thresh_pct"] = 0.05
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
            return venue.wallet["USD"] + sum(q * marks.get(c + "USDT", 0.0) for c, q in venue.wallet.items()
                                             if c != "USD")

        def cycle(label: str) -> dict:
            n0 = len(venue.trades)
            snap = bot.cycle()
            bot.adopt_wallet()
            led = bot.sleeve
            marks = {**bot.sleeve_px, **(snap.get("marks") or {})}
            new = venue.trades[n0:]
            print(f"{label}: equity {snap['equity']:.2f}, host cash {bot.cash:.2f}, sleeve "
                  f"{json.dumps(snap.get('cash_sleeve'))}, trades {new}")
            fees = sum(t["qty"] * t["price"] for t in new) * 0.001
            check(abs(snap["equity"] - wallet_value(marks)) < 2.0 + 1.5 * fees,
                  f"reported equity {snap['equity']:.2f} = wallet value {wallet_value(marks):.2f}")
            check(venue.wallet["USD"] >= -1e-6, f"wallet cash never negative ({venue.wallet['USD']:.2f})")
            check(abs(bot.cash + led.cash - venue.wallet["USD"]) < 0.01,
                  f"host cash + sleeve cash = wallet cash {venue.wallet['USD']:.2f}")
            check(not (set(bot.holdings) & led.owned()), "no coin is both host and sleeve")
            return {"snap": snap, "trades": new}

        print("phase 1: entry")
        r = cycle("cycle 1")
        led = bot.sleeve
        check(led is not None and abs(led.budget - 7000.0) < 1e-6, f"sleeve budget 7,000 (got {led and led.budget})")
        buys = [t for t in r["trades"] if t["side"] == "BUY"]
        check(len(buys) == 3, f"sleeve bought 3 rides on the forced trigger (got {len(buys)})")
        check(not any(t["pair"].split("/")[0] + "USDT" in units for t in r["trades"]),
              "no order on a host coin")
        r = cycle("cycle 2")
        pos = r["snap"]["positions"]
        check(set(pos) == set(units) | {t["pair"].split("/")[0] + "USDT" for t in buys}
              and abs(sum(pos.values()) + r["snap"]["cash"] / r["snap"]["equity"] - 1) < 0.002,
              f"reported positions cover host and sleeve coins and, with cash, sum to the account {pos}")
        check(all(abs(bot.holdings[s] - units[s]) < 1e-9 for s in units), "host holdings unchanged")
        check(len(led.units) == 3 and all(v > 0 for v in led.units.values()), "sleeve owns its 3 coins")
        check(r["trades"] == [], "steady state sends nothing")

        print("phase 2: handover")
        coin = sorted(led.units)[0]
        moved = led.units[coin]
        orig = RegimeLSBot.compute_target

        def host_wants(self, channels, derisk, prices):
            return {**{s: w for s, w in HOST_W.items()}, coin: 0.04}
        RegimeLSBot.compute_target = host_wants
        bot.last_bar = bar30 - pd.Timedelta(minutes=30)
        r = cycle("cycle 3 (host enters a sleeve coin)")
        RegimeLSBot.compute_target = orig
        check(coin not in led.owned(), f"sleeve released {coin}")
        check(bot.holdings.get(coin, 0.0) >= moved - 1e-9, f"host holds the released {coin} units")
        host_buy = [t for t in r["trades"] if t["pair"].split("/")[0] + "USDT" == coin and t["side"] == "BUY"]
        want = 0.04 * (r["snap"]["equity"] - led.equity(bot.sleeve_px))
        got = moved * bot.sleeve_px[coin] + sum(t["qty"] * t["price"] for t in host_buy)
        check(got <= want * 1.02, f"host never holds more than its 0.04 target ({got:.0f} vs {want:.0f})")

        print("phase 3: exit")
        bot.sleeve_cfg["ride"]["thresh_pct"] = 50.0
        for s in led.held:
            led.held[s][0] = str(pd.Timestamp(led.held[s][0]) - pd.Timedelta(days=2))
        led.bar = None
        r = cycle("cycle 4 (hold expired)")
        sells = [t for t in r["trades"] if t["side"] == "SELL"]
        check(len(sells) == 2, f"sleeve sold its 2 remaining rides (got {len(sells)})")
        r = cycle("cycle 5")
        check(led.units == {} and led.owned() == set(), "sleeve flat after the exits")
        check(6950 < led.cash < 7000, f"sleeve cash after a round trip {led.cash:.2f}")
        rows = [json.loads(x) for f in d.glob("orders-*.jsonl") for x in f.read_text().splitlines()]
        tagged = [o for o in rows if o.get("event") == "placed" and o.get("book") == "cash_sleeve"]
        check(len(tagged) == 5, f"sleeve orders are journaled with book: cash_sleeve ({len(tagged)})")
        errs = [json.loads(x) for f in d.glob("errors-*.jsonl") for x in f.read_text().splitlines()]
        check(not [e for e in errs if e.get("event") == "cash_sleeve_error"], "no cash_sleeve_error")
    finally:
        cfg_path.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)
    print("PASS" if not failures else f"FAIL: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
