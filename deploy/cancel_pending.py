"""CLI: list, and with --cancel cancel by id, the resting orders on a key set, for a live unit switch.

A stopped unit can leave a limit order resting on the venue; the unit that replaces it does not know
the order and would count its later fill as a wallet change it never decided. Run only after the old
unit is stopped and before the new one starts. DECISIONS.md#competition-r4-2026-10-05

Usage: python3 deploy/cancel_pending.py comp [--cancel]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.settings import credentials  # noqa: E402
from venue.roostoo import RoostooClient  # noqa: E402


def pending(client: RoostooClient) -> list[dict]:
    return list(client.query_order(pending_only=True).get("OrderDetails") or [])


def journal(book: str, order_id: int) -> None:
    """Record a cancel made outside the bot in the book's order journal, so `bot.blotter` does not read
    the venue's FilledQuantity = Quantity on the unfilled order as a fill. DECISIONS.md#guard-crowding-fix-2026-10-05"""
    now = dt.datetime.now(dt.UTC)
    d = Path(__file__).resolve().parent.parent / "live" / book
    with (d / f"orders-{now:%Y-%m-%d}.jsonl").open("a") as fh:
        fh.write(json.dumps({"event": "cancelled_external", "order_id": order_id, "ts_utc": now.isoformat(),
                             "ref": "DECISIONS.md#guard-crowding-fix-2026-10-05"}) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keyset", choices=("test", "comp"))
    ap.add_argument("--cancel", action="store_true")
    ap.add_argument("--book", help="journal each cancel into live/<book>/orders as cancelled_external")
    ap.add_argument("--record", type=int, nargs="*", default=[], help="order ids already cancelled, to journal only")
    a = ap.parse_args(argv)
    if a.book and a.record:
        for oid in a.record:
            journal(a.book, oid)
        return 0
    key, secret = credentials(a.keyset)
    client = RoostooClient(key, secret)
    client.sync_time()
    rows = pending(client)
    print(json.dumps({"pending": [{k: r.get(k) for k in ("OrderID", "Pair", "Side", "Type", "Price", "Quantity",
                                                         "FilledQuantity", "Status")} for r in rows]}))
    if a.cancel:
        for r in rows:
            print(json.dumps({"cancel": r.get("OrderID"), "result": client.cancel_order(order_id=r["OrderID"])}))
            if a.book:
                journal(a.book, r["OrderID"])
        left = pending(client)
        print(json.dumps({"pending_after": len(left)}))
        return 1 if left else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
