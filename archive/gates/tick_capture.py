"""Forward paper test of tick capture on Roostoo: rest a buy at the bid and a sell at the entry's ask, filled from the
live Roostoo LastPrice, PEPE (23.5 bps tick) against 4-5 bps controls, under a touch and a trade-through fill rule.

Declared in config/tick_capture.yaml.
DECISIONS.md#tick-capture-declaration
"""
from __future__ import annotations

import argparse
import json
import time

import requests

from core.config import RESULTS

URL = "https://mock-api.roostoo.com/v3/ticker"
PAIRS = ("PEPE/USD", "ARB/USD", "TRUMP/USD", "ENA/USD", "XLM/USD")
MAKER, TAKER, UNIT, MAX_INV = 0.0005, 0.001, 10_000.0, 2


class Book:
    def __init__(self, rule: str):
        self.rule = rule
        self.cash, self.lots, self.buy, self.fees = 0.0, [], None, 0.0
        self.trips, self.taker_fills, self.maker_fills = 0, 0, 0

    def hit_buy(self, last: float, px: float) -> bool:
        return last <= px if self.rule == "touch" else last < px

    def hit_sell(self, last: float, px: float) -> bool:
        return last >= px if self.rule == "touch" else last > px

    def fill_buy(self, px: float, fee: float) -> None:
        q = UNIT / px
        self.cash -= q * px
        self.fees += UNIT * fee
        self.lots.append({"q": q, "entry": px, "sell": None})

    def step(self, bid: float, ask: float, last: float, tick: float) -> None:
        for lot in list(self.lots):
            if lot["sell"] is not None and self.hit_sell(last, lot["sell"]):
                self.cash += lot["q"] * lot["sell"]
                self.fees += lot["q"] * lot["sell"] * MAKER
                self.lots.remove(lot)
                self.trips += 1
                self.maker_fills += 1
        if self.buy is not None and self.hit_buy(last, self.buy):
            self.fill_buy(self.buy, MAKER)
            self.maker_fills += 1
            self.buy = None
        if self.buy is not None and abs(self.buy - bid) > tick * 0.5:
            self.buy = None
        if self.buy is None and len(self.lots) < MAX_INV:
            if last <= bid:
                self.fill_buy(bid, TAKER)
                self.taker_fills += 1
            else:
                self.buy = bid
        for lot in self.lots:
            if lot["sell"] is None:
                lot["sell"] = max(ask, lot["entry"] + tick)

    def pnl(self, bid: float) -> float:
        return self.cash + sum(lot["q"] * bid for lot in self.lots) - self.fees


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=40)
    ap.add_argument("--every", type=float, default=6)
    a = ap.parse_args(argv)
    books = {(p, r): Book(r) for p in PAIRS for r in ("touch", "through")}
    last_seen, flips, polls, errors = {}, {p: 0 for p in PAIRS}, 0, 0
    quotes = {}
    end = time.time() + a.minutes * 60
    while time.time() < end:
        try:
            d = requests.get(URL, params={"timestamp": int(time.time() * 1000)}, timeout=8).json()["Data"]
        except Exception:
            errors += 1
            time.sleep(a.every)
            continue
        polls += 1
        for p in PAIRS:
            q = d.get(p)
            if not q:
                continue
            bid, ask, last = float(q["MaxBid"]), float(q["MinAsk"]), float(q["LastPrice"])
            tick = ask - bid if ask > bid else 0.0
            if tick <= 0:
                continue
            if p in last_seen and last != last_seen[p]:
                flips[p] += 1
            last_seen[p] = last
            quotes[p] = {"bid": bid, "ask": ask, "last": last, "spread_bps": round((ask / bid - 1) * 1e4, 2)}
            for r in ("touch", "through"):
                books[(p, r)].step(bid, ask, last, tick)
        time.sleep(a.every)
    out = {"ref": "DECISIONS.md#tick-capture-declaration", "minutes": a.minutes, "polls": polls, "errors": errors,
           "flips": flips, "quotes_last": quotes, "books": {}}
    for (p, r), b in books.items():
        bid = quotes.get(p, {}).get("bid", 0.0)
        out["books"][f"{p}|{r}"] = {"net_pnl_usd": round(b.pnl(bid), 2), "fees_usd": round(b.fees, 2),
                                   "round_trips": b.trips, "maker_fills": b.maker_fills, "taker_fills": b.taker_fills,
                                   "open_lots": len(b.lots),
                                   "net_bps_of_unit": round(b.pnl(bid) / UNIT * 1e4, 1)}
    (RESULTS / "tick_capture.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
