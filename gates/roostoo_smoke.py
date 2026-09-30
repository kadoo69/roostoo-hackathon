"""Order lifecycle on the Roostoo TEST account: the fields and fees the live bot relies on.

Uses ROOSTOO_TEST_* only; the competition keys are never read here, because a trade
placed by hand on the competition account breaks the no-manual-trading rule.
DECISIONS.md#roostoo-keys-2026-09-30
"""
from __future__ import annotations

import json
import os
import time

from bot.settings import credentials
from bot.state import wallet_positions
from core.config import RESULTS
from venue.roostoo import RoostooClient, RoostooError

PAIR = "BTC/USD"
NOTIONAL = 200.0
SHORT_COLLATERAL = 100.0


def client() -> RoostooClient:
    credentials()
    c = RoostooClient(os.environ["ROOSTOO_TEST_API_KEY"], os.environ["ROOSTOO_TEST_SECRET_KEY"])
    c.sync_time()
    c.exchange_info()
    return c


def run() -> dict:
    c = client()
    spec = c._spec_cache[PAIR]
    steps: list[dict] = []

    def rec(name: str, **kw) -> dict:
        steps.append({"step": name, "t": time.strftime("%H:%M:%S", time.gmtime()), **kw})
        print(json.dumps(steps[-1]))
        return steps[-1]

    def attempt(name: str, fn):
        try:
            return fn()
        except RoostooError as exc:
            rec(name, ok=False, error=str(exc)[:240])
            return None

    q = c.ticker(PAIR)[PAIR]
    bid, ask = q["MaxBid"], q["MinAsk"]
    wallet = c.balance()
    holdings, cash = wallet_positions(wallet, quote="USD")
    rec("start", offset_ms=c.time_offset_ms, bid=bid, ask=ask, cash=cash, holdings=holdings,
        price_precision=spec.price_precision, amount_precision=spec.amount_precision,
        min_order=spec.min_order)

    rest_px = round(bid * 0.90, spec.price_precision)
    r = attempt("resting_limit", lambda: c.place_order(PAIR, "BUY",
                                                       spec.round_qty(NOTIONAL / rest_px), rest_px))
    if r:
        d = r["OrderDetail"]
        oid = d["OrderID"]
        rec("resting_limit", ok=True, detail=d)
        pend = attempt("query_pending", lambda: c.query_order(pending_only=True))
        if pend is not None:
            rec("query_pending", ok=True, count=len(pend.get("OrderDetails") or []),
                contains_ours=any(o["OrderID"] == oid for o in pend.get("OrderDetails") or []))
        by_id = attempt("query_by_id", lambda: c.query_order(order_id=oid))
        if by_id is not None:
            rec("query_by_id", ok=True, detail=(by_id.get("OrderDetails") or [None])[0])
        cx = attempt("cancel", lambda: c.cancel_order(order_id=oid))
        if cx is not None:
            rec("cancel", ok=True, response=cx)
        after = attempt("query_pending_after_cancel", lambda: c.query_order(pending_only=True))
        if after is not None:
            rec("query_pending_after_cancel", ok=True,
                gone=not any(o["OrderID"] == oid for o in after.get("OrderDetails") or []))

    attempt("below_min_order", lambda: c.place_order(PAIR, "BUY", spec.round_qty(0.5 / ask), None))
    if steps[-1]["step"] != "below_min_order":
        rec("below_min_order", ok=False, note="venue accepted a sub-1 USD market order")

    qty = spec.round_qty(NOTIONAL / ask)
    r = attempt("market_buy", lambda: c.place_order(PAIR, "BUY", qty, None))
    if r:
        d = r["OrderDetail"]
        rec("market_buy", ok=True, detail=d, quoted_ask=ask,
            slip_bps=round((d["FilledAverPrice"] / ask - 1) * 1e4, 3) if d.get("FilledAverPrice") else None)
        time.sleep(1)
        held = wallet_positions(c.balance(), quote="USD")
        rec("wallet_after_buy", holdings=held[0], cash=held[1])
        q = c.ticker(PAIR)[PAIR]
        sell_qty = spec.round_qty(held[0].get("BTCUSDT", qty))
        r = attempt("market_sell", lambda: c.place_order(PAIR, "SELL", sell_qty, None))
        if r:
            d = r["OrderDetail"]
            rec("market_sell", ok=True, detail=d, quoted_bid=q["MaxBid"])

    q = c.ticker(PAIR)[PAIR]
    touch = round(q["MaxBid"], spec.price_precision)
    r = attempt("limit_at_bid", lambda: c.place_order(PAIR, "BUY", spec.round_qty(NOTIONAL / touch), touch))
    if r:
        d = r["OrderDetail"]
        rec("limit_at_bid", ok=True, detail=d)
        if d.get("Status") != "FILLED":
            time.sleep(30)
            det = attempt("limit_at_bid_30s", lambda: c.query_order(order_id=d["OrderID"]))
            if det is not None:
                row = (det.get("OrderDetails") or [{}])[0]
                rec("limit_at_bid_30s", ok=True, detail=row)
                if row.get("Status") not in ("FILLED",):
                    attempt("limit_at_bid_cancel", lambda: c.cancel_order(order_id=d["OrderID"]))
        held = wallet_positions(c.balance(), quote="USD")[0]
        if held.get("BTCUSDT"):
            r = attempt("limit_flatten", lambda: c.place_order(PAIR, "SELL", spec.round_qty(held["BTCUSDT"]), None))
            if r:
                rec("limit_flatten", ok=True, detail=r["OrderDetail"])

    r = attempt("short_open", lambda: c.short_open(PAIR, SHORT_COLLATERAL))
    if r:
        rec("short_open", ok=True, response=r)
        time.sleep(1)
        pos = attempt("short_positions", c.short_positions)
        if pos is not None:
            rec("short_positions", ok=True, rows=pos)
        raw = c._request("GET", "/v3/balance", signed=True)
        rec("balance_with_short", raw=raw)
        cl = attempt("short_close", lambda: c.short_close(PAIR))
        if cl:
            rec("short_close", ok=True, response=cl)

    raw = c._request("GET", "/v3/balance", signed=True)
    rec("end", raw=raw)
    return {"pair": PAIR, "steps": steps}


if __name__ == "__main__":
    out = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "roostoo_smoke_test.json").write_text(json.dumps(out, indent=2))
