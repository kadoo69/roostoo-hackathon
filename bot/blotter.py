from __future__ import annotations

import argparse
import json
from collections import deque

import pandas as pd

from bot.journal import Journal
from bot.settings import ROOT

FILLED_EVENTS = ("placed", "dry_run")


def _fill(o: dict) -> dict | None:
    if o.get("event") not in FILLED_EVENTS or o.get("skipped"):
        return None
    qty = o.get("filled_quantity")
    px = o.get("filled_average_price")
    if qty in (None, 0) or px in (None, 0):
        qty, px = o.get("quantity"), o.get("price")
    if not qty or not px:
        return None
    fee_rate = o.get("commission_percent")
    if fee_rate is None:
        fee_rate = 0.0005 if o.get("type") == "LIMIT" else 0.0010
    return {"ts": o["ts_utc"], "symbol": o["symbol"], "side": o["side"],
            "qty": float(qty), "price": float(px), "fee_rate": float(fee_rate),
            "fee": float(qty) * float(px) * float(fee_rate),
            "order_id": o.get("order_id"), "event": o["event"],
            "role": o.get("role")}


# A round trip below this notional cannot move any value-weighted statistic but
# gets a full vote in every count-weighted one. It is a rounding residue, not a
# position. Stated in absolute terms because the books run a fixed 100k NAV.
DUST_NOTIONAL = 50.0


def build(bot: str) -> dict:
    orders = Journal(bot).read("orders")
    fills = [f for f in (_fill(o) for o in orders) if f]
    fills.sort(key=lambda x: x["ts"])

    lots: dict[str, deque] = {}
    closed, skipped, errors = [], 0, 0
    for o in orders:
        if o.get("event") == "skipped":
            skipped += 1
        if o.get("event") in ("error", "cancel_error", "query_error"):
            errors += 1

    for f in fills:
        q = lots.setdefault(f["symbol"], deque())
        if f["side"] == "BUY":
            q.append(dict(f, remaining=f["qty"]))
            continue
        to_sell = f["qty"]
        while to_sell > 1e-12 and q:
            lot = q[0]
            take = min(lot["remaining"], to_sell)
            entry_fee = lot["fee"] * (take / lot["qty"])
            exit_fee = f["fee"] * (take / f["qty"])
            gross = (f["price"] - lot["price"]) * take
            closed.append({
                "symbol": f["symbol"],
                "entry_ts": lot["ts"], "exit_ts": f["ts"],
                "qty": round(take, 10),
                "entry_price": lot["price"], "exit_price": f["price"],
                "gross_pnl": gross, "fees": entry_fee + exit_fee,
                "net_pnl": gross - entry_fee - exit_fee,
                "return_pct": (f["price"] / lot["price"] - 1.0) * 100.0,
                "net_return_pct": ((gross - entry_fee - exit_fee)
                                   / (lot["price"] * take) * 100.0),
                "hold_hours": round((pd.Timestamp(f["ts"])
                                     - pd.Timestamp(lot["ts"])).total_seconds()
                                    / 3600.0, 3),
                "entry_event": lot["event"], "exit_event": f["event"],
                "entry_role": lot.get("role"), "exit_role": f.get("role")})
            lot["remaining"] -= take
            to_sell -= take
            if lot["remaining"] <= 1e-12:
                q.popleft()

    open_lots = [{"symbol": s, "entry_ts": lot["ts"], "qty": round(lot["remaining"], 10),
                  "entry_price": lot["price"],
                  "cost_basis": round(lot["remaining"] * lot["price"], 4)}
                 for s, q in lots.items() for lot in q if lot["remaining"] > 1e-12]

    t = pd.DataFrame(closed)
    stats = {"closed_trades": len(t), "open_lots": len(open_lots),
             "fills": len(fills), "skipped_orders": skipped,
             "order_errors": errors}
    if len(t):
        # Count-based statistics give a $5 rounding residue the same vote as a
        # $20,000 position. On 2026-09-20 three of donchian_1h's eleven "closed
        # trades" were TRX round trips of $3 to $19 whose net P&L was under a
        # cent, which alone produced a payoff ratio of 2,156 and moved win rate
        # by 9 points. DECISIONS.md#dust-trades-distort-count-statistics
        #
        # The floor is a REPORTING threshold and changes no trading decision.
        # Both sets are always returned so it cannot hide anything.
        t = t.assign(notional=(t.qty.abs() * t.entry_price).round(6))
        material = t[t.notional >= DUST_NOTIONAL]
        dust = t[t.notional < DUST_NOTIONAL]
        stats.update({
            "dust_trades": int(len(dust)),
            "dust_notional_floor": DUST_NOTIONAL,
            "material_trades": int(len(material)),
            "dust_net_pnl": round(float(dust.net_pnl.sum()), 4) if len(dust) else 0.0,
            "win_rate_all_trades": round(float((t.net_pnl > 0).mean()), 4),
        })
        if len(material):
            t = material
        wins = t[t.net_pnl > 0]
        losses = t[t.net_pnl <= 0]
        stats.update({
            "net_pnl": round(float(t.net_pnl.sum()), 4),
            "gross_pnl": round(float(t.gross_pnl.sum()), 4),
            "total_fees": round(float(t.fees.sum()), 4),
            "fees_pct_of_gross": (round(float(t.fees.sum() / abs(t.gross_pnl.sum())
                                              * 100), 2)
                                  if t.gross_pnl.sum() else None),
            "win_rate": round(float(len(wins) / len(t)), 4),
            "avg_win": round(float(wins.net_pnl.mean()), 4) if len(wins) else None,
            "avg_loss": round(float(losses.net_pnl.mean()), 4) if len(losses) else None,
            "payoff_ratio": (round(float(wins.net_pnl.mean() / abs(losses.net_pnl.mean())), 3)
                             if len(wins) and len(losses) and losses.net_pnl.mean() else None),
            "profit_factor": (round(float(wins.net_pnl.sum() / abs(losses.net_pnl.sum())), 3)
                              if len(losses) and losses.net_pnl.sum() else None),
            "median_hold_hours": round(float(t.hold_hours.median()), 2),
            "best_trade": round(float(t.net_pnl.max()), 4),
            "worst_trade": round(float(t.net_pnl.min()), 4),
            "expectancy_per_trade": round(float(t.net_pnl.mean()), 4)})
    return {"bot": bot, "stats": stats, "closed": closed, "open": open_lots}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bots", nargs="*",
                    default=["donchian_4h", "donchian_4h_cushion", "donchian_1h",
                             "momentum_top5_4h", "momentum_top5_cushion"])
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    out = []
    for b in (a.bots or ["donchian_4h", "donchian_4h_cushion", "donchian_1h",
                             "momentum_top5_4h", "momentum_top5_cushion"]):
        r = build(b)
        out.append(r)
        if a.csv:
            d = ROOT / "live" / b
            d.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(r["closed"]).to_csv(d / "trades_closed.csv", index=False)
            pd.DataFrame(r["open"]).to_csv(d / "trades_open.csv", index=False)
    print(json.dumps([{"bot": r["bot"], "stats": r["stats"]} for r in out],
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
