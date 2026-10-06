from __future__ import annotations

import math
import time
from collections import deque

from bot.journal import Journal
from bot.settings import Settings
from venue.roostoo import AmbiguousOrderError, PairSpec, RoostooClient, RoostooError


NORMAL_SPREAD_TICKS = 2
SPOT_SIDES = {"BUY", "SELL"}
SHORT_SIDES = {"SHORT_OPEN", "SHORT_CLOSE"}
SHORT_FEE = 0.001
ERROR_WINDOW = 40
ERROR_MIN_CALLS = 8



def venue_filled_qty(o: dict) -> float:
    """The quantity an order has really filled. Roostoo reports `FilledQuantity` equal to the whole order even
    when nothing filled (a cancelled LTC sell on 2026-10-05: Quantity 227.588, FilledQuantity 227.588,
    FilledAverPrice 0, CoinChange 0), so the coin actually moved (`CoinChange`) is the fill, and a zero average
    price means nothing filled; only without either field is `FilledQuantity` trusted (Binance testnet shape).
    This made every exit escalation compute a zero rest and skip since 2026-10-02.
    DECISIONS.md#escalation-fill-field-2026-10-05"""
    if o.get("CoinChange") is not None:
        return abs(float(o.get("CoinChange") or 0.0))
    if o.get("FilledAverPrice") is not None and float(o.get("FilledAverPrice") or 0.0) == 0.0:
        return 0.0
    return float(o.get("FilledQuantity") or 0.0)

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
        self.submission_blocked = False
        self.intents = None
        self.pending_pairs: set[str] = set()
        self.calls: deque[bool] = deque(maxlen=ERROR_WINDOW)
        self.sent_at: dict[str, float] = {}
        # symbol -> (lo, hi) price band in which a stale exit must not be market-sold, from the book's
        # no-loss guard. DECISIONS.md#no-loss-escalation-2026-10-06
        self.exit_band = None
        self.quotes: dict = {}
        # True only in a cycle whose drawdown kill switch fired: the one case a sale inside the band may go.
        self.allow_loss_exits = False

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
        if not spec.can_trade or spec.asset_type == "stock":
            return {"skipped": "pair_not_tradable", "symbol": order["symbol"], "pair": spec.pair}
        if order.get("side") not in SPOT_SIDES | SHORT_SIDES:
            return {"skipped": "invalid_side", "symbol": order["symbol"], "pair": spec.pair}
        short = order["side"] in SHORT_SIDES
        if order["side"] == "SHORT_OPEN" and not self.settings.shorts_enabled:
            return {"skipped": "shorts_not_enabled", "symbol": order["symbol"], "pair": spec.pair}
        if short and not hasattr(self.client, "short_open"):
            return {"skipped": "venue_has_no_shorts", "symbol": order["symbol"], "pair": spec.pair}
        self.quotes = quotes
        q = quotes[spec.pair]
        try:
            bid, ask, last = (float(q[k]) for k in ("MaxBid", "MinAsk", "LastPrice"))
            quantity = float(order["quantity"])
        except (KeyError, TypeError, ValueError):
            return {"skipped": "invalid_quote_or_quantity", "symbol": order["symbol"], "pair": spec.pair}
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask, last, quantity)) or bid > ask:
            return {"skipped": "invalid_quote_or_quantity", "symbol": order["symbol"], "pair": spec.pair}
        spread_bps = (ask / bid - 1.0) * 1e4
        normal = (ask - bid) <= NORMAL_SPREAD_TICKS * spec.tick * (1.0 + 1e-6)
        # Up to two ticks is a normal quote, whatever it is in bps: its
        # half-spread is the one tick per side every backtest already charges.
        # Refusing it idled a ranked slot (PEPE at one tick, ARB at two) while
        # the backtest held the name. Wider than that is still refused above
        # max_spread_bps. DECISIONS.md#execution-gaps-2026-09-23
        if spread_bps > self.settings.max_spread_bps and not normal:
            return {"skipped": "spread_exceeds_limit", "symbol": order["symbol"],
                    "pair": spec.pair, "spread_bps": round(spread_bps, 4),
                    "max_spread_bps": self.settings.max_spread_bps}
        wide_tick = spread_bps > self.settings.max_spread_bps
        if short:
            return self._prepare_short(order, spec, bid, ask, quantity, spread_bps, wide_tick)
        qty = spec.round_qty(quantity)
        if qty <= 0:
            return None
        px = (self.limit_price(spec, order["side"], q)
              if self.settings.execution == "LIMIT" else float(q["LastPrice"]))
        if not math.isfinite(px) or px <= 0:
            return {"skipped": "invalid_limit_price", "symbol": order["symbol"], "pair": spec.pair}
        if qty * px < spec.min_order:
            return {"skipped": "below_min_order", "symbol": order["symbol"],
                    "pair": spec.pair, "quantity": qty, "price": px,
                    "min_order": spec.min_order}
        # The reference quote at submission is recorded because post-fill markout,
        # which is the only direct measure of the adverse selection that
        # DECISIONS.md#passive-fill-adverse-selection shows the backtest prices at
        # zero, cannot be reconstructed afterwards from price alone.
        return {"symbol": order["symbol"], "pair": spec.pair, "side": order["side"],
                "quantity": qty, "price": px,
                "type": self.settings.execution,
                "notional": round(qty * px, 4),
                "ref_bid": bid, "ref_ask": ask, "ref_mid": round((bid + ask) / 2.0, 10),
                "ref_spread_bps": round(spread_bps, 4),
                "wide_tick": wide_tick}

    def _prepare_short(self, order: dict, spec: PairSpec, bid: float, ask: float,
                       quantity: float, spread_bps: float, wide_tick: bool) -> dict | None:
        """A venue short leg. Both legs are MARKET: an open fills at the bid, a close at the ask.

        A LIMIT short open pays its 0.1% fee on acceptance, filled or not, and a close is
        always market at the venue, so a passive short saves nothing and risks paying twice.
        DECISIONS.md#plan-correction-shorting, DECISIONS.md#short-paper-books
        """
        side = order["side"]
        px = bid if side == "SHORT_OPEN" else ask
        qty = spec.round_qty(quantity)
        if qty <= 0:
            return None
        notional = qty * px
        if notional < max(1.0, spec.min_order) and not order.get("close_all"):
            return {"skipped": "below_min_order", "symbol": order["symbol"], "pair": spec.pair,
                    "quantity": qty, "price": px, "min_order": spec.min_order}
        return {"symbol": order["symbol"], "pair": spec.pair, "side": side,
                "quantity": qty, "price": px, "type": "MARKET",
                "notional": round(notional, 4),
                "collateral": round(notional, 2) if side == "SHORT_OPEN" else None,
                "close_all": bool(order.get("close_all")),
                "ref_bid": bid, "ref_ask": ask, "ref_mid": round((bid + ask) / 2.0, 10),
                "ref_spread_bps": round(spread_bps, 4), "wide_tick": wide_tick}

    def refresh_pending(self) -> set[str]:
        """Pairs that already have a resting order at the venue.

        A resting LIMIT order locks the asset, and `holdings` does not reflect
        an order that has not filled, so without this the bot re-submits the
        same sell every cycle and the venue answers -2010 insufficient balance
        until the error-rate kill switch halts it. A dry run never shows this
        because `apply_dry_fill` settles instantly.
        DECISIONS.md#testnet-live
        """
        if self.settings.dry_run:
            self.pending_pairs = set()
            return self.pending_pairs
        try:
            resp = self.client.query_order(pending_only=True)
        except RoostooError:
            self.calls.append(True)
            now = time.time()
            self.pending_pairs = self.pending_pairs | {p for p, t in self.sent_at.items()
                                                       if now - t < self.settings.limit_timeout_s}
            return self.pending_pairs
        self.calls.append(False)
        self.pending_pairs = {str(o.get("Pair") or "").replace("/", "")
                              for o in (resp.get("OrderDetails") or [])}
        return self.pending_pairs

    def below_cost(self, plan: dict) -> dict | None:
        """The no-loss band check every SELL passes before it is sent, whatever produced it: the rule's exit,
        a skim, a guard's resize, an escalation or a sleeve exit. Inside the symbol's band (`exit_band`, from
        the book's no-loss guard) the order is not sent; a MARKET sale is judged at the bid, a LIMIT at its
        price, and a sale with no price to judge is held. Only a drawdown halt (`allow_loss_exits`) passes.
        DECISIONS.md#no-sale-below-cost-anywhere-2026-10-06"""
        if plan.get("side") != "SELL" or not self.exit_band or self.allow_loss_exits:
            return None
        band = self.exit_band(plan.get("symbol"))
        if not band:
            return None
        if plan.get("type") == "LIMIT" and plan.get("price"):
            px = float(plan["price"])
        else:
            px = float((self.quotes.get(plan.get("pair")) or {}).get("MaxBid") or 0.0)
        lo, hi = band
        if px and not lo <= px < hi:
            return None
        return {"skipped": "below_cost_hold", "judged_px": px or None,
                "band": [round(lo, 10), round(hi, 10)], "ref": "DECISIONS.md#no-sale-below-cost-anywhere-2026-10-06"}

    def send(self, plan: dict) -> dict:
        if plan.get("skipped"):
            return self.journal.write("orders", {"event": "skipped", **plan})
        held = self.below_cost(plan)
        if held:
            return self.journal.write("orders", {"event": "skipped", **plan, **held})
        if (plan.get("symbol") in self.pending_pairs
                or str(plan.get("pair") or "").replace("/", "") in self.pending_pairs):
            return self.journal.write("orders", {"event": "skipped",
                                                 "skipped": "order_already_pending", **plan})
        if self.submission_blocked:
            raise AmbiguousOrderError("submission_blocked_pending_reconciliation")
        self.attempts += 1
        if self.settings.dry_run:
            return self.journal.write("orders", {"event": "dry_run", **plan})
        # The intent is written and fsynced BEFORE the call. If the process dies
        # here the order may exist at the venue and only this record proves a
        # request was ever made. bot/intents.py
        intent_id = self.intents.open_intent(plan) if self.intents else None
        try:
            if plan["side"] == "SHORT_OPEN":
                resp = self.client.short_open(plan["pair"], plan["collateral"])
            elif plan["side"] == "SHORT_CLOSE":
                resp = self.client.short_close(plan["pair"],
                                               None if plan.get("close_all") else plan["quantity"])
            else:
                price = plan["price"] if plan["type"] == "LIMIT" else None
                resp = self.client.place_order(plan["pair"], plan["side"],
                                               plan["quantity"], price,
                                               client_order_id=intent_id)
        except AmbiguousOrderError as exc:
            self.errors += 1
            self.calls.append(True)
            self.submission_blocked = True
            self.journal.write("orders", {"event": "submission_unknown", "error": str(exc),
                                          "intent_id": intent_id, **plan})
            raise
        except RoostooError as exc:
            self.errors += 1
            self.calls.append(True)
            if self.intents and intent_id:
                self.intents.resolve(intent_id, "rejected", {"error": str(exc)})
            return self.journal.write("orders", {"event": "error", "error": str(exc),
                                                 "intent_id": intent_id, **plan})
        self.calls.append(False)
        self.sent_at[str(plan.get("pair") or "").replace("/", "")] = time.time()
        if plan["side"] in SHORT_SIDES:
            return self._record_short(plan, resp, intent_id)
        detail = resp.get("OrderDetail", resp)
        if self.intents and intent_id:
            self.intents.resolve(intent_id, "placed", {"order_id": detail.get("OrderID"),
                                                       "status": detail.get("Status")})
        return self.journal.write("orders", {
            "event": "placed", "intent_id": intent_id, **plan,
            "order_id": detail.get("OrderID"),
            "status": detail.get("Status"),
            "role": detail.get("Role"),
            "commission_percent": detail.get("CommissionPercent"),
            "filled_quantity": detail.get("FilledQuantity"),
            "filled_average_price": detail.get("FilledAverPrice"),
        })

    def _record_short(self, plan: dict, resp: dict, intent_id: str | None) -> dict:
        """Journal a venue short in the spot order's shape; a missing field reads as zero."""
        opened = plan["side"] == "SHORT_OPEN"
        qty = float(resp.get("ShortQty" if opened else "ClosedQty") or 0.0)
        px = float(resp.get("EntryPrice" if opened else "ClosePrice") or 0.0)
        if self.intents and intent_id:
            self.intents.resolve(intent_id, "placed", {"order_id": resp.get("ID"),
                                                       "status": resp.get("Status")})
        return self.journal.write("orders", {
            "event": "placed", "intent_id": intent_id, **plan,
            "order_id": resp.get("ID"), "status": resp.get("Status") or (
                "FILLED" if not opened else None),
            "commission_percent": SHORT_FEE,
            "filled_quantity": qty, "filled_average_price": px,
            "realized_pnl": resp.get("RealizedPNL"), "return_amount": resp.get("ReturnAmount"),
            "fully_closed": resp.get("FullyClosed")})

    def sweep_unfilled(self) -> list[dict]:
        if self.settings.dry_run:
            return []
        out = []
        try:
            pending = self.client.query_order(pending_only=True)
        except RoostooError as exc:
            self.errors += 1
            self.calls.append(True)
            return [self.journal.write("orders", {"event": "query_error",
                                                  "error": str(exc)})]
        self.calls.append(False)
        for o in pending.get("OrderDetails", []) or []:
            age = time.time() - float(o.get("CreateTimestamp", 0)) / 1000.0
            if age < self.timeout_for(o):
                continue
            try:
                # Binance requires `symbol` on a cancel and Roostoo does not.
                # Passing the pair satisfies both; omitting it produced
                # -1105 "Parameter 'symbol' was empty" on every sweep and walked
                # the error rate toward the kill switch.
                # DECISIONS.md#testnet-live
                self.client.cancel_order(order_id=o["OrderID"], pair=o.get("Pair"))
                self.calls.append(False)
                out.append(self.journal.write("orders", {
                    "event": "cancelled_stale", "order_id": o["OrderID"],
                    "pair": o.get("Pair"), "age_s": round(age, 1)}))
                if self.settings.exit_escalation and str(o.get("Side", "")).upper() == "SELL":
                    esc = self.escalate_exit(o)
                    if esc:
                        out.append(esc)
            except RoostooError as exc:
                self.errors += 1
                self.calls.append(True)
                out.append(self.journal.write("orders", {
                    "event": "cancel_error", "error": str(exc),
                    "order_id": o.get("OrderID")}))
        return out

    def timeout_for(self, o: dict) -> float:
        """How long a resting order may wait: `exit_timeout_s` for a SELL when exits escalate and it is set,
        else `limit_timeout_s`. A falling coin left a resting exit five minutes behind the market before the
        market order (ADA, ENA, ETH, AAVE on 2026-10-06, about 0.2-0.3% each).
        DECISIONS.md#exit-timeout-2026-10-06"""
        quick = getattr(self.settings, "exit_timeout_s", 0)
        if quick and self.settings.exit_escalation and str(o.get("Side", "")).upper() == "SELL":
            return float(quick)
        return float(self.settings.limit_timeout_s)

    def escalate_exit(self, o: dict) -> dict | None:
        """Re-send the unfilled rest of a cancelled stale SELL at MARKET.

        A LIMIT exit that rests past `limit_timeout_s` was cancelled and never re-sent, so the book
        kept a position its rule had left (PEPE on the rehearsal, 2026-10-02 12:00Z). Exits must
        complete; entries are never chased, so a stale BUY is only cancelled.
        DECISIONS.md#exit-escalation-2026-10-02
        The market sale passes `below_cost` in `send` like every SELL: inside a held name's no-loss band it is
        not sent (an exit placed above cost escalated to a -0.52% market sale of AAVE at 10:35 IST 2026-10-06).
        DECISIONS.md#no-loss-escalation-2026-10-06
        """
        pair = o.get("Pair")
        spec = self.specs.get(pair)
        if spec is None:
            return None
        rest = spec.round_qty(float(o.get("Quantity") or 0) - venue_filled_qty(o))
        price = float(o.get("Price") or 0)
        if rest <= 0 or rest * price < spec.min_order:
            return self.journal.write("orders", {"event": "escalation_skipped", "pair": pair,
                                                 "order_id": o.get("OrderID"), "rest": rest})
        self.pending_pairs.discard(pair.replace("/", ""))
        self.pending_pairs.discard(spec.binance_symbol)
        return self.send({"pair": pair, "symbol": spec.binance_symbol, "side": "SELL", "type": "MARKET",
                          "quantity": rest, "reason": "exit_escalation", "escalated_from": o.get("OrderID")})

    def error_rate(self) -> float:
        """Failed share of the last ERROR_WINDOW venue calls (orders, queries and cancels alike), or
        0 before ERROR_MIN_CALLS. A lifetime ratio of order errors to order attempts let one failed
        query after a handful of orders halt a book, and never fell again once the book was flat.
        DECISIONS.md#live-faults-2026-10-01"""
        if len(self.calls) < ERROR_MIN_CALLS:
            return 0.0
        return sum(self.calls) / len(self.calls)
