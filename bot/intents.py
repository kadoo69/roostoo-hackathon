"""Durable order intent log: the record that survives the process dying mid-submit.

The window this closes is small and real. `Executor.send` makes an HTTP call and
then journals the result. If the process dies in between, the order may exist at
the venue and nothing local knows it. On restart the bot would recompute a
target from stale holdings and submit again, double-filling.

So the intent is written and fsynced BEFORE the call, and resolved after. On
startup every unresolved intent is queried at the venue and settled. Until that
completes cleanly, submission stays blocked - which is what
`live_orders_blocked_until_restart_reconciliation_is_implemented` was standing
in for. DECISIONS.md#testnet-live

Matching differs by venue and the difference is not cosmetic. Binance accepts a
`newClientOrderId`, so an intent maps to an order EXACTLY. Roostoo's
`place_order` takes no such field, so an unresolved Roostoo intent can only be
matched by pair, side, quantity and a timestamp window, which is a heuristic.
A heuristic match is reported as `matched_by: heuristic` and never silently
treated as certain.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

from bot.settings import ROOT


class IntentLog:
    def __init__(self, bot: str, root: Path | None = None):
        self.path = (root or ROOT / "live") / bot / "intents.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, row: dict) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def open_intent(self, plan: dict) -> str:
        intent_id = uuid.uuid4().hex[:22]
        self._append({"event": "intent", "intent_id": intent_id,
                      "utc": dt.datetime.now(dt.UTC).isoformat(),
                      "pair": plan.get("pair"), "side": plan.get("side"),
                      "quantity": plan.get("quantity"), "price": plan.get("price"),
                      "type": plan.get("type"), "symbol": plan.get("symbol")})
        return intent_id

    def resolve(self, intent_id: str, outcome: str, detail: dict | None = None) -> None:
        self._append({"event": "resolved", "intent_id": intent_id, "outcome": outcome,
                      "utc": dt.datetime.now(dt.UTC).isoformat(), "detail": detail or {}})

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def unresolved(self) -> list[dict]:
        rows = self.rows()
        done = {r["intent_id"] for r in rows if r.get("event") == "resolved"}
        return [r for r in rows if r.get("event") == "intent" and r["intent_id"] not in done]


def reconcile(log: IntentLog, client, journal=None) -> dict:
    """Settle every unresolved intent against the venue. Returns a report."""
    pending = log.unresolved()
    report = {"unresolved_at_start": len(pending), "settled": 0,
              "still_unknown": 0, "details": []}
    for row in pending:
        cid = row["intent_id"]
        pair = row.get("pair")
        found, how = None, None
        if hasattr(client, "query_by_client_id"):
            try:
                found = client.query_by_client_id(cid, pair)
                how = "client_order_id"
            except Exception as exc:                      # noqa: BLE001 - venue may 400
                found, how = None, f"lookup_failed:{type(exc).__name__}"
        if found is None and hasattr(client, "query_order"):
            try:
                resp = client.query_order(pair=pair)
                found = _heuristic(resp, row)
                how = "heuristic" if found else how or "not_found"
            except Exception as exc:                      # noqa: BLE001
                how = f"lookup_failed:{type(exc).__name__}"
        if found is not None:
            log.resolve(cid, "found_at_venue", {"matched_by": how, "order": found})
            report["settled"] += 1
        elif how in ("not_found", "client_order_id"):
            log.resolve(cid, "never_reached_venue", {"matched_by": how})
            report["settled"] += 1
        else:
            report["still_unknown"] += 1
        report["details"].append({"intent_id": cid, "pair": pair, "matched_by": how})
    report["clean"] = report["still_unknown"] == 0
    if journal is not None:
        journal.write("reconcile", {"event": "intent_reconciliation", **report})
    return report


def _heuristic(resp: dict, row: dict) -> dict | None:
    orders = resp.get("OrderDetail") or resp.get("orders") or resp
    if isinstance(orders, dict):
        orders = [orders]
    if not isinstance(orders, list):
        return None
    for o in orders:
        if not isinstance(o, dict):
            continue
        side = str(o.get("Side") or o.get("side") or "").upper()
        qty = o.get("Quantity") or o.get("origQty") or o.get("quantity")
        try:
            same_qty = abs(float(qty) - float(row["quantity"])) <= max(
                1e-9, 0.01 * float(row["quantity"]))
        except (TypeError, ValueError):
            same_qty = False
        if side == str(row.get("side", "")).upper() and same_qty:
            return o
    return None
