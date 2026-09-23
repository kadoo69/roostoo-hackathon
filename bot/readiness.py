from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

import yaml

from bot.settings import ROOT


def inspect(state: dict, cfg: dict, now: dt.datetime) -> dict:
    failures = []
    rows = []
    stamp = state.get("last_cycle")
    age = (now - dt.datetime.fromisoformat(stamp)).total_seconds() if stamp else None
    if age is None or age < -5 or age > max(180, 3 * cfg["poll_seconds"]):
        failures.append("paper_cycle_missing_stale_or_future")
    candidates = {c["name"]: c for c in cfg["candidates"]}
    if set(state.get("books", {})) != set(candidates):
        failures.append("candidate_set_mismatch")
    for name, book in state.get("books", {}).items():
        issues = []
        cash = book.get("cash", float("nan"))
        holdings = book.get("holdings", {})
        marks = book.get("marks", {})
        pending = book.get("pending", [])
        fee = cfg["fee_bps"] / 1e4
        reserve = 0.0
        sell_reserve = {}
        symbols = []
        for order in pending:
            qty, price = order.get("quantity", 0), order.get("price", 0)
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (qty, price)):
                issues.append("invalid_pending_amount")
                continue
            symbol = order["symbol"]
            symbols.append(symbol)
            if order["side"] == "BUY":
                reserve += qty * price * (1 + fee)
            elif order["side"] == "SELL":
                sell_reserve[symbol] = sell_reserve.get(symbol, 0) + qty
            else:
                issues.append("invalid_pending_side")
        if len(symbols) != len(set(symbols)):
            issues.append("duplicate_pending_symbol")
        if not math.isfinite(cash) or cash < -1e-8 or reserve > cash + 1e-8:
            issues.append("cash_or_buy_reservation_invalid")
        if any(q > holdings.get(s, 0) + 1e-12 for s, q in sell_reserve.items()):
            issues.append("sell_inventory_overreserved")
        if any(not math.isfinite(q) or q <= 0 or s not in marks
               or not math.isfinite(marks[s]) or marks[s] <= 0 for s, q in holdings.items()):
            issues.append("invalid_inventory_or_marks")
        else:
            equity = cash + sum(q * marks[s] for s, q in holdings.items())
            history = book.get("nav", [])
            if not history or not math.isfinite(equity) or equity <= 0 or not math.isclose(
                    equity, history[-1]["equity"], rel_tol=1e-9, abs_tol=1e-6):
                issues.append("equity_reconciliation_failed")
        ledger = {}
        ledger_cash = cfg["initial_nav"]
        ledger_fees = 0.0
        for event in book.get("events", []):
            if event.get("event") != "fill":
                continue
            sign = 1 if event["side"] == "BUY" else -1
            ledger[event["symbol"]] = ledger.get(event["symbol"], 0) + sign * event["quantity"]
            ledger_cash -= sign * event["quantity"] * event["price"] + event["fee"]
            ledger_fees += event["fee"]
        if any(not math.isclose(ledger.get(s, 0), holdings.get(s, 0), rel_tol=1e-9, abs_tol=1e-10)
               for s in set(ledger) | set(holdings)):
            issues.append("fill_inventory_reconciliation_failed")
        if not math.isclose(ledger_cash, cash, rel_tol=1e-9, abs_tol=1e-6):
            issues.append("fill_cash_reconciliation_failed")
        if not math.isclose(ledger_fees, book.get("fees", -1), rel_tol=1e-9, abs_tol=1e-6):
            issues.append("fill_fee_reconciliation_failed")
        if book.get("halted"):
            issues.append("drawdown_halt_latched")
        failures.extend(f"{name}:{issue}" for issue in issues)
        rows.append({"name": name, "checks_pass": not issues, "issues": issues})
    return {"asof": now.isoformat(), "paper_last_cycle": stamp, "paper_age_seconds": age,
            "paper_accounting_healthy": not failures, "failures": failures, "books": rows,
            "competition_ready": False, "authenticated_trading_enabled": False,
            "deployment_blockers": ["restart_safe_authenticated_order_reconciliation_not_implemented",
                                    "venue_fee_partial_fill_and_rejection_paths_not_verified",
                                    "registered_statistical_and_risk_gates_not_passed"],
            "scope": "read_only_paper_snapshot_audit_not_a_live_venue_certification"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config/paper_lab_v2.yaml")
    parser.add_argument("--root", type=Path, default=ROOT / "live")
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    state = json.loads((args.root / cfg["meta"]["name"] / "state.json").read_text())
    report = inspect(state, cfg, dt.datetime.now(dt.timezone.utc))
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["paper_accounting_healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
