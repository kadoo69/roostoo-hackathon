from __future__ import annotations

import math
import time

from bot.journal import Journal
from bot.settings import Settings
from venue.roostoo import PairSpec, RoostooClient, RoostooError


class Executor:
    def __init__(self, client: RoostooClient, specs: dict[str, PairSpec],
                 settings: Settings, journal: Journal):
        self.client = client
        self.specs = specs
        self.settings = settings
        self.journal = journal
        self.by_symbol = {s.binance_symbol: s for s in specs.values()}
        self.errors = 0
        self.attempts = 0

    def spec(self, symbol: str) -> PairSpec | None:
        return self.by_symbol.get(symbol)

    def limit_price(self, spec: PairSpec, side: str, quote: dict) -> float:
        bid, ask = float(quote["MaxBid"]), float(quote["MinAsk"])
        off = self.settings.limit_offset_bps / 1e4
        step = spec.tick
        if side == "BUY":
            raw = min(bid * (1.0 + off), ask - step)
            px = math.floor((raw + step * 1e-9) / step) * step
        else:
            raw = max(ask * (1.0 - off), bid + step)
            px = math.ceil((raw - step * 1e-9) / step) * step
        return round(px, spec.price_precision)

    def prepare(self, order: dict, quotes: dict) -> dict | None:
        spec = self.spec(order["symbol"])
        if spec is None or spec.pair not in quotes:
            return None
        q = quotes[spec.pair]
        bid, ask = float(q["MaxBid"]), float(q["MinAsk"])
        spread_bps = (ask / bid - 1.0) * 1e4
        if spread_bps > self.settings.max_spread_bps:
            return {"skipped": "spread_exceeds_limit", "symbol": order["symbol"],
                    "pair": spec.pair, "spread_bps": round(spread_bps, 4),
                    "max_spread_bps": self.settings.max_spread_bps}
        qty = spec.round_qty(order["quantity"])
        if qty <= 0:
            return None
        px = (self.limit_price(spec, order["side"], q)
              if self.settings.execution == "LIMIT" else float(q["LastPrice"]))
        if qty * px < spec.min_order:
            return {"skipped": "below_min_order", "symbol": order["symbol"],
                    "pair": spec.pair, "quantity": qty, "price": px,
                    "min_order": spec.min_order}
        return {"symbol": order["symbol"], "pair": spec.pair, "side": order["side"],
                "quantity": qty, "price": px,
                "type": self.settings.execution,
                "notional": round(qty * px, 4)}

    def send(self, plan: dict) -> dict:
        if plan.get("skipped"):
            return self.journal.write("orders", {"event": "skipped", **plan})
        self.attempts += 1
        if self.settings.dry_run:
            return self.journal.write("orders", {"event": "dry_run", **plan})
        try:
            price = plan["price"] if plan["type"] == "LIMIT" else None
            resp = self.client.place_order(plan["pair"], plan["side"],
                                           plan["quantity"], price)
        except RoostooError as exc:
            self.errors += 1
            return self.journal.write("orders", {"event": "error", "error": str(exc),
                                                 **plan})
        detail = resp.get("OrderDetail", resp)
        return self.journal.write("orders", {
            "event": "placed", **plan,
            "order_id": detail.get("OrderID"),
            "status": detail.get("Status"),
            "role": detail.get("Role"),
            "commission_percent": detail.get("CommissionPercent"),
            "filled_quantity": detail.get("FilledQuantity"),
            "filled_average_price": detail.get("FilledAverPrice"),
        })

    def sweep_unfilled(self) -> list[dict]:
        if self.settings.dry_run:
            return []
        out = []
        try:
            pending = self.client.query_order(pending_only=True)
        except RoostooError as exc:
            self.errors += 1
            return [self.journal.write("orders", {"event": "query_error",
                                                  "error": str(exc)})]
        for o in pending.get("OrderDetails", []) or []:
            age = time.time() - float(o.get("CreateTimestamp", 0)) / 1000.0
            if age < self.settings.limit_timeout_s:
                continue
            try:
                self.client.cancel_order(order_id=o["OrderID"])
                out.append(self.journal.write("orders", {
                    "event": "cancelled_stale", "order_id": o["OrderID"],
                    "pair": o.get("Pair"), "age_s": round(age, 1)}))
            except RoostooError as exc:
                self.errors += 1
                out.append(self.journal.write("orders", {
                    "event": "cancel_error", "error": str(exc),
                    "order_id": o.get("OrderID")}))
        return out

    def error_rate(self) -> float:
        return self.errors / self.attempts if self.attempts else 0.0
