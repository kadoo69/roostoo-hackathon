from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from bot.settings import ROOT


def accounting(book: dict) -> dict:
    lots = {}
    realized = 0.0
    closed = []
    for event in book.get("events", []):
        if event.get("event") != "fill":
            continue
        symbol = event["symbol"]
        queue = lots.setdefault(symbol, deque())
        qty, price = event["quantity"], event["price"]
        fee_unit = event.get("fee", 0) / qty
        if event["side"] == "BUY":
            queue.append([qty, price, fee_unit, event["time"]])
            continue
        remaining = qty
        while remaining > 1e-12 and queue:
            lot = queue[0]
            matched = min(remaining, lot[0])
            pnl = matched * (price - lot[1] - fee_unit - lot[2])
            realized += pnl
            closed.append({"symbol": symbol, "quantity": matched, "entry_price": lot[1],
                           "exit_price": price, "pnl": pnl, "time": event["time"]})
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= 1e-12:
                queue.popleft()
        if remaining > 1e-8:
            raise ValueError(f"unmatched_sell:{symbol}")
    positions = []
    for symbol in sorted(set(lots) | set(book.get("holdings", {}))):
        queue = lots.get(symbol, [])
        qty = sum(l[0] for l in queue)
        held = book.get("holdings", {}).get(symbol, 0)
        if abs(qty - held) > max(1e-8, held * 1e-9):
            raise ValueError(f"inventory_mismatch:{symbol}")
        if qty > 1e-12:
            basis = sum(l[0] * (l[1] + l[2]) for l in queue)
            positions.append({"symbol": symbol, "quantity": held,
                              "average_entry": sum(l[0] * l[1] for l in queue) / qty,
                              "cost_basis": basis})
    return {"realized": realized, "positions": positions, "closed": closed[-100:][::-1]}


def snapshot(directory: Path, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    state = json.loads((directory / "state.json").read_text())
    last = state.get("last_cycle")
    age = max(0, (now - dt.datetime.fromisoformat(last)).total_seconds()) if last else None
    errors = []
    for path in sorted(directory.glob("errors-*.jsonl"))[-2:]:
        for line in path.read_text().splitlines()[-20:]:
            try:
                errors.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    bots = []
    for name, book in state["books"].items():
        history = book.get("nav", [])
        latest = history[-1] if history else {}
        equity = latest.get("equity", book["cash"])
        fills = [e for e in book.get("events", []) if e.get("event") == "fill"]
        initial = book["cash"] - sum((e["quantity"] * e["price"] * (1 if e["side"] == "SELL" else -1) - e.get("fee", 0)) for e in fills)
        ledger = accounting(book)
        stride = max(1, len(history) // 500)
        series = history[::stride]
        if history and series[-1] != history[-1]:
            series.append(history[-1])
        bots.append({"name": name, "equity": equity, "initial": initial,
                     "pnl": equity - initial, "return": equity / initial - 1 if initial else 0,
                     "cash": book["cash"], "gross": latest.get("gross", 0),
                     "drawdown": equity / book["peak"] - 1,
                     "fees": book["fees"], "halted": book["halted"], "fills": len(fills),
                     "turnover": book["turnover"], "pending": book["pending"],
                     "series": series, "events": book.get("events", [])[-300:][::-1],
                     "unrealized": equity - initial - ledger["realized"], **ledger})
    return {"generated": now.isoformat(), "asof": last, "age_seconds": age,
            "stale": age is None or age > 180, "started": state["started"],
            "sha": state["sha"], "universe": state.get("universe", {}).get("selected", []),
            "ranking_count": state.get("universe", {}).get("ranking_count", 0),
            "mirror_bps": state.get("mirror_worst_bps"), "errors": errors[-10:][::-1],
            "bots": bots}


class Handler(BaseHTTPRequestHandler):
    directory = ROOT / "live/paper_lab_v1"

    def log_message(self, *args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path
        status = 200
        if path == "/api/state":
            kind = "application/json"
            try:
                payload = snapshot(self.directory)
                body = json.dumps(payload, allow_nan=False).encode()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                status = 503
                body = json.dumps({"error": f"Paper snapshot unavailable: {type(exc).__name__}"}).encode()
        elif path == "/":
            kind = "text/html; charset=utf-8"
            body = Path(__file__).with_suffix(".html").read_bytes()
        else:
            status, kind, body = 404, "text/plain", b"Not found"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--directory", type=Path, default=Handler.directory)
    args = parser.parse_args()
    Handler.directory = args.directory
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Paper dashboard: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
