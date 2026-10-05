"""Real-order micro-test of tick scalping on the Roostoo TEST account: one small resting buy at the bid, and
once it fills a resting sell one tick higher, repeated for `--minutes`; every order, fill and round trip is
journaled with the venue's own status and prices. It settles whether real resting orders fill on a touch or
only on a trade-through (the two fill rules of `bot.tick_scalper`). TEST keys only; flat at the end.
Runs on EC2: sudo -u roostoo .venv/bin/python deploy/checks/scalp_micro_test.py --pair 1000CHEEMS/USD
DECISIONS.md#scalp-micro-test-2026-10-05
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bot.settings import credentials  # noqa: E402
from venue.roostoo import RoostooClient  # noqa: E402

MAKER = 0.0005
OUT = Path(__file__).resolve().parent.parent.parent / "live" / "scalp_micro"


def detail(resp: dict) -> dict:
    d = resp.get("OrderDetail")
    if d:
        return d
    rows = resp.get("OrderDetails") or []
    return rows[0] if rows else {}


def quote(client: RoostooClient, pair: str) -> tuple[float, float, float]:
    data = client.ticker(pair)
    q = data.get(pair) or data.get("Data", {}).get(pair) or next(iter(data.values()))
    return float(q["MaxBid"]), float(q["MinAsk"]), float(q["LastPrice"])


def log(rec: dict) -> None:
    rec = {"ts_utc": dt.datetime.now(dt.UTC).isoformat(), **rec}
    with (OUT / "events.jsonl").open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="1000CHEEMS/USD")
    ap.add_argument("--notional", type=float, default=1000.0)
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--poll", type=float, default=10.0)
    ap.add_argument("--reprice_s", type=float, default=60.0)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    client = RoostooClient(*credentials("test"))
    client.sync_time()
    client._spec_cache = client.exchange_info()
    spec = client._spec_cache[a.pair]
    state, oid, placed_at, entry, qty = "idle", None, 0.0, 0.0, 0.0
    trips, pnl, fees, buys_placed, reprices = 0, 0.0, 0.0, 0, 0
    end = time.time() + a.minutes * 60
    log({"event": "start", "pair": a.pair, "notional": a.notional, "tick": spec.tick, "minutes": a.minutes})
    try:
        while time.time() < end:
            bid, ask, last = quote(client, a.pair)
            if state == "idle":
                qty = spec.round_qty(a.notional / bid)
                r = detail(client.place_order(a.pair, "BUY", qty, price=bid))
                oid, placed_at, state, entry = r.get("OrderID"), time.time(), "buying", bid
                buys_placed += 1
                log({"event": "buy_placed", "order_id": oid, "price": bid, "qty": qty, "status": r.get("Status"),
                     "bid": bid, "ask": ask, "last": last})
            else:
                r = detail(client.query_order(order_id=oid))
                status = str(r.get("Status", "")).upper()
                if status == "FILLED" and state == "buying":
                    log({"event": "buy_filled", "order_id": oid, "price": entry, "after_s": round(time.time() - placed_at, 1),
                         "bid": bid, "ask": ask, "last": last})
                    fees += entry * qty * MAKER
                    sell_px = max(ask, entry + spec.tick)
                    r2 = detail(client.place_order(a.pair, "SELL", qty, price=sell_px))
                    oid, placed_at, state = r2.get("OrderID"), time.time(), "selling"
                    log({"event": "sell_placed", "order_id": oid, "price": sell_px, "status": r2.get("Status")})
                    entry_sell = sell_px
                elif status == "FILLED" and state == "selling":
                    gain = (entry_sell - entry) * qty
                    fees += entry_sell * qty * MAKER
                    pnl += gain
                    trips += 1
                    log({"event": "sell_filled", "order_id": oid, "price": entry_sell, "after_s": round(time.time() - placed_at, 1),
                         "trip_gross": round(gain, 4), "trips": trips, "bid": bid, "ask": ask, "last": last})
                    state = "idle"
                elif state == "buying" and bid > entry and time.time() - placed_at > a.reprice_s:
                    client.cancel_order(order_id=oid)
                    reprices += 1
                    log({"event": "buy_repriced", "order_id": oid, "old": entry, "bid": bid})
                    state = "idle"
            summary = {"pair": a.pair, "trips": trips, "gross_usd": round(pnl, 4), "fees_usd": round(fees, 4),
                       "net_usd": round(pnl - fees, 4), "buys_placed": buys_placed, "reprices": reprices, "state": state,
                       "updated": dt.datetime.now(dt.UTC).isoformat()}
            (OUT / "summary.json").write_text(json.dumps(summary))
            time.sleep(a.poll)
    finally:
        if oid and state in ("buying", "selling"):
            try:
                client.cancel_order(order_id=oid)
                log({"event": "final_cancel", "order_id": oid, "state": state})
            except Exception as exc:                          # noqa: BLE001
                log({"event": "final_cancel_failed", "error": repr(exc)[:200]})
            if state == "selling":
                bid, _, _ = quote(client, a.pair)
                r = detail(client.place_order(a.pair, "SELL", qty, price=bid))
                log({"event": "flatten", "price": bid, "qty": qty, "status": r.get("Status"),
                     "open_loss_gross": round((bid - entry) * qty, 4)})
        log({"event": "end", "trips": trips, "net_usd": round(pnl - fees, 4)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
