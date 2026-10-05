"""Paper tick scalper on the live Roostoo ticker: rest a buy at the bid and a sell at the entry's ask, filled
from the venue LastPrice, PEPE (23.5 bps tick) as the arm and ARB (tick below the 10 bps maker round trip) as
the control that should not pay, under a touch and a trade-through fill rule. Keyless, no orders: it
measures how often both legs fill and what a round trip nets after fees, for the desk.
DECISIONS.md#tick-scalp-paper-2026-10-05
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import requests
import yaml

from bot.settings import ROOT

URL = "https://mock-api.roostoo.com/v3/ticker"
MAKER, TAKER = 0.0005, 0.001


class Book:
    def __init__(self, rule: str, unit: float, max_inv: int):
        self.rule, self.unit, self.max_inv = rule, unit, max_inv
        self.cash, self.lots, self.buy, self.fees = 0.0, [], None, 0.0
        self.trips, self.taker_fills, self.maker_fills = 0, 0, 0

    def hit_buy(self, last: float, px: float) -> bool:
        return last <= px if self.rule == "touch" else last < px

    def hit_sell(self, last: float, px: float) -> bool:
        return last >= px if self.rule == "touch" else last > px

    def fill_buy(self, px: float, fee: float) -> None:
        q = self.unit / px
        self.cash -= q * px
        self.fees += self.unit * fee
        self.lots.append({"q": q, "entry": px, "sell": None})

    def step(self, bid: float, ask: float, last: float, tick: float) -> list[dict]:
        events = []
        for lot in list(self.lots):
            if lot["sell"] is not None and self.hit_sell(last, lot["sell"]):
                self.cash += lot["q"] * lot["sell"]
                self.fees += lot["q"] * lot["sell"] * MAKER
                self.lots.remove(lot)
                self.trips += 1
                self.maker_fills += 1
                events.append({"side": "SELL", "px": lot["sell"], "entry": lot["entry"]})
        if self.buy is not None and self.hit_buy(last, self.buy):
            self.fill_buy(self.buy, MAKER)
            self.maker_fills += 1
            events.append({"side": "BUY", "px": self.buy, "kind": "maker"})
            self.buy = None
        if self.buy is not None and abs(self.buy - bid) > tick * 0.5:
            self.buy = None
        if self.buy is None and len(self.lots) < self.max_inv:
            if last <= bid:
                self.fill_buy(bid, TAKER)
                self.taker_fills += 1
                events.append({"side": "BUY", "px": bid, "kind": "taker"})
            else:
                self.buy = bid
        for lot in self.lots:
            if lot["sell"] is None:
                lot["sell"] = max(ask, lot["entry"] + tick)
        return events

    def pnl(self, bid: float) -> float:
        return self.cash + sum(lot["q"] * bid for lot in self.lots) - self.fees

    def view(self, bid: float) -> dict:
        return {"net_pnl_usd": round(self.pnl(bid), 2), "fees_usd": round(self.fees, 2), "round_trips": self.trips,
                "maker_fills": self.maker_fills, "taker_fills": self.taker_fills, "open_lots": len(self.lots),
                "open_entry": self.lots[0]["entry"] if self.lots else None, "resting_buy": self.buy,
                "net_bps_of_unit": round(self.pnl(bid) / self.unit * 1e4, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config" / "tick_scalp_pepe.yaml"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())
    t = cfg["test"]
    out_dir = ROOT / "live" / cfg["meta"]["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = [t["arm"]] + list(t["controls"])
    books = {(p, r): Book(r, float(t["unit_usd"]), int(t["max_inventory"])) for p in pairs for r in t["fill_rules"]}
    started = dt.datetime.now(dt.UTC).isoformat()
    polls = errors = 0
    flips = {p: 0 for p in pairs}
    last_seen: dict[str, float] = {}
    quotes: dict[str, dict] = {}
    while True:
        try:
            d = requests.get(URL, params={"timestamp": int(time.time() * 1000)}, timeout=8).json()["Data"]
        except Exception:                                     # noqa: BLE001
            errors += 1
            time.sleep(float(t["poll_seconds"]))
            continue
        polls += 1
        now = dt.datetime.now(dt.UTC).isoformat()
        for p in pairs:
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
            quotes[p] = {"bid": bid, "ask": ask, "last": last, "tick_bps": round((ask / bid - 1) * 1e4, 2)}
            for r in t["fill_rules"]:
                for ev in books[(p, r)].step(bid, ask, last, tick):
                    with (out_dir / f"fills-{now[:10]}.jsonl").open("a") as fh:
                        fh.write(json.dumps({"ts_utc": now, "pair": p, "rule": r, **ev}) + "\n")
        state = {"ref": cfg["meta"]["declared_ref"], "started": started, "updated": now, "polls": polls,
                 "errors": errors, "poll_seconds": t["poll_seconds"], "unit_usd": t["unit_usd"], "arm": t["arm"],
                 "flips": flips, "quotes": quotes,
                 "books": {f"{p}|{r}": b.view(quotes.get(p, {}).get("bid", 0.0)) for (p, r), b in books.items()}}
        tmp = out_dir / "state.json.tmp"
        tmp.write_text(json.dumps(state))
        tmp.replace(out_dir / "state.json")
        time.sleep(float(t["poll_seconds"]))


if __name__ == "__main__":
    raise SystemExit(main())
