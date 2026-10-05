"""CLI: list, and with --cancel cancel by id, the resting orders on a key set, for a live unit switch.

A stopped unit can leave a limit order resting on the venue; the unit that replaces it does not know
the order and would count its later fill as a wallet change it never decided. Run only after the old
unit is stopped and before the new one starts. DECISIONS.md#competition-r4-2026-10-05

Usage: python3 deploy/cancel_pending.py comp [--cancel]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.settings import credentials  # noqa: E402
from venue.roostoo import RoostooClient  # noqa: E402


def pending(client: RoostooClient) -> list[dict]:
    return list(client.query_order(pending_only=True).get("OrderDetails") or [])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keyset", choices=("test", "comp"))
    ap.add_argument("--cancel", action="store_true")
    a = ap.parse_args(argv)
    key, secret = credentials(a.keyset)
    client = RoostooClient(key, secret)
    client.sync_time()
    rows = pending(client)
    print(json.dumps({"pending": [{k: r.get(k) for k in ("OrderID", "Pair", "Side", "Type", "Price", "Quantity",
                                                         "FilledQuantity", "Status")} for r in rows]}))
    if a.cancel:
        for r in rows:
            print(json.dumps({"cancel": r.get("OrderID"), "result": client.cancel_order(order_id=r["OrderID"])}))
        left = pending(client)
        print(json.dumps({"pending_after": len(left)}))
        return 1 if left else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
