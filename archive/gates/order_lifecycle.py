from __future__ import annotations

import json
import time
import warnings

from bot.settings import credentials
from core.config import RESULTS
from venue.roostoo import RoostooError

warnings.filterwarnings("ignore")
SYMBOL = "BTC/USDT"
NOTIONAL = 200.0


def client():
    credentials()
    from venue.binance_testnet import BinanceTestnetClient
    c = BinanceTestnetClient()
    c.sync_time()
    c.exchange_info()
    return c


def run() -> dict:
    c = client()
    spec = c._specs[SYMBOL]
    q = c.ticker()[SYMBOL]
    bid, ask = q["MaxBid"], q["MinAsk"]
    steps = []

    def rec(name, **kw):
        steps.append({"step": name, **kw})
        return steps[-1]

    rec("spec", price_precision=spec.price_precision,
        amount_precision=spec.amount_precision, min_order=spec.min_order,
        bid=bid, ask=ask, spread_bps=round((ask / bid - 1) * 1e4, 3))

    resting_px = round(bid * 0.90, spec.price_precision)
    qty = spec.round_qty(NOTIONAL / resting_px)
    try:
        r = c.place_order(SYMBOL, "BUY", qty, resting_px)
        d = r["OrderDetail"]
        oid = d["OrderID"]
        rec("place_resting_limit", ok=True, order_id=oid, status=d["Status"],
            price=resting_px, qty=qty, notional=round(qty * resting_px, 2),
            filled=d["FilledQuantity"])
    except RoostooError as e:
        return {"fatal": f"place_resting_limit:{e}", "steps": steps}

    try:
        pend = c.query_order(pending_only=True)["OrderDetails"]
        rec("query_pending", ok=True, count=len(pend),
            contains_ours=any(o["OrderID"] == oid for o in pend))
    except RoostooError as e:
        rec("query_pending", ok=False, error=str(e))

    try:
        c.cancel_order(order_id=oid, pair=SYMBOL)
        pend2 = c.query_order(pending_only=True)["OrderDetails"]
        rec("cancel", ok=True,
            gone=not any(o["OrderID"] == oid for o in pend2))
    except RoostooError as e:
        rec("cancel", ok=False, error=str(e))

    try:
        tiny = spec.round_qty(1.0 / ask)
        c.place_order(SYMBOL, "BUY", tiny, round(ask, spec.price_precision))
        rec("min_notional_rejected", ok=False,
            note="venue ACCEPTED an order below minNotional")
    except RoostooError as e:
        rec("min_notional_rejected", ok=True, error=str(e)[:160])

    marketable = round(ask * 1.001, spec.price_precision)
    mqty = spec.round_qty(NOTIONAL / marketable)
    try:
        r = c.place_order(SYMBOL, "BUY", mqty, marketable)
        d = r["OrderDetail"]
        slip = ((d["FilledAverPrice"] / ask - 1) * 1e4
                if d["FilledAverPrice"] else None)
        rec("marketable_limit_buy", ok=True, status=d["Status"],
            role=d["Role"], commission_percent=d["CommissionPercent"],
            filled=d["FilledQuantity"], avg_price=d["FilledAverPrice"],
            quoted_ask=ask, slippage_vs_ask_bps=round(slip, 3) if slip else None)
    except RoostooError as e:
        rec("marketable_limit_buy", ok=False, error=str(e)[:200])

    touch_px = round(bid * (1 + 1.0 / 1e4), spec.price_precision)
    tqty = spec.round_qty(NOTIONAL / touch_px)
    try:
        r = c.place_order(SYMBOL, "BUY", tqty, touch_px)
        d = r["OrderDetail"]
        oid2 = d["OrderID"]
        time.sleep(20)
        det = c.query_order(order_id=oid2, pair=SYMBOL)["OrderDetails"][0]
        filled = float(det.get("executedQty", 0) or 0)
        rec("bot_style_limit_at_touch", ok=True, order_id=oid2,
            price=touch_px, status_after_20s=det.get("status"),
            filled_qty=filled, fill_fraction=round(filled / tqty, 4) if tqty else None)
        if det.get("status") not in ("FILLED",):
            c.cancel_order(order_id=oid2, pair=SYMBOL)
            rec("cleanup_cancel", ok=True)
    except RoostooError as e:
        rec("bot_style_limit_at_touch", ok=False, error=str(e)[:200])

    return {"symbol": SYMBOL, "steps": steps}


if __name__ == "__main__":
    out = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "order_lifecycle_testnet.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
