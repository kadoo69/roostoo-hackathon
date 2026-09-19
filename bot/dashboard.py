from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd

from bot.blotter import build as build_blotter
from bot.journal import Journal
from bot.report import from_equity
from bot.insights import breadth, derive
from bot.settings import ROOT, load

BOTS = {"bot_a_4h": "config/bot_a_4h.yaml",
        "bot_b_1h": "config/bot_b_1h.yaml",
        "bot_c_5names": "config/bot_c_5names.yaml"}
EXPECTED_DRAG = {"bot_a_4h": 0.051, "bot_b_1h": 0.193, "bot_c_5names": 0.075}
_BREADTH = {"data": None, "updated": None}


def _breadth_loop():
    while True:
        try:
            _BREADTH["data"] = breadth(load("config/bot_a_4h.yaml"))
            _BREADTH["updated"] = pd.Timestamp.now(tz="UTC").isoformat()
        except Exception as exc:
            _BREADTH["data"] = {"error": str(exc)[:160]}
        time.sleep(240)


def bot_state(name: str, cfg: str) -> dict:
    j = Journal(name)
    cycles = j.read("cycles")
    errors = j.read("errors")
    life = j.read("lifecycle")
    try:
        s = load(cfg)
        meta = {"interval": s.interval, "entry": s.entry_bars, "exit": s.exit_bars,
                "divisor": s.weight_divisor, "max_gross": s.max_gross,
                "venue": s.venue, "dry_run": s.dry_run, "sha": s.config_sha256}
    except Exception:
        meta = {}
    bl = build_blotter(name)
    if not cycles:
        return {"bot": name, "meta": meta, "live": False, "cycles": 0,
                "blotter": bl["stats"], "closed": [], "open": bl["open"],
                "equity_series": []}

    f = pd.DataFrame(cycles)
    f["ts"] = pd.to_datetime(f["ts_utc"], utc=True)
    f = f.sort_values("ts")
    last = f.iloc[-1]
    age = (pd.Timestamp.now(tz="UTC") - f["ts"].iloc[-1]).total_seconds()
    eq = f.set_index("ts")["equity"].astype(float)
    daily = eq.resample("1D").last().dropna()
    gaps = f["ts"].diff().dt.total_seconds().dropna()
    series = [{"t": t.isoformat(), "e": round(float(v), 2)}
              for t, v in eq.tail(400).items()]

    start = float(eq.iloc[0])
    cur = float(eq.iloc[-1])
    peak = float(eq.cummax().iloc[-1])
    return {
        "bot": name, "meta": meta, "live": age < 300, "seconds_since_cycle": round(age, 1),
        "cycles": int(len(f)),
        "first_cycle": str(f["ts"].iloc[0]), "last_cycle": str(f["ts"].iloc[-1]),
        "distinct_days": int(f["ts"].dt.date.nunique()),
        "wall_hours": round((f["ts"].iloc[-1] - f["ts"].iloc[0]).total_seconds() / 3600, 2),
        "restarts": sum(1 for l in life if l.get("event") == "resumed"),
        "halts": int(f.get("halt", pd.Series(dtype=bool)).fillna(False).sum()),
        "errors": len(errors),
        "max_gap_s": round(float(gaps.max()), 1) if len(gaps) else None,
        "equity": round(cur, 2), "equity_start": round(start, 2),
        "pnl": round(cur - start, 2),
        "pnl_pct": round((cur / start - 1) * 100, 4) if start else 0.0,
        "drawdown_pct": round((cur / peak - 1) * 100, 4) if peak else 0.0,
        "cash": round(float(last.get("cash", 0)), 2),
        "gross": float(last.get("gross_exposure", 0) or 0),
        "n_long": int(last.get("n_long", 0) or 0),
        "n_universe": int(last.get("n_universe", 0) or 0),
        "mirror_bps": last.get("mirror_worst_bps"),
        "positions": last.get("positions") or {},
        "performance": from_equity(daily) if len(daily) >= 3 else None,
        "blotter": bl["stats"],
        "closed": sorted(bl["closed"], key=lambda t: t["exit_ts"], reverse=True)[:60],
        "open": bl["open"],
        "equity_series": series,
    }


def snapshot() -> dict:
    bots = []
    for n, c in BOTS.items():
        st = bot_state(n, c)
        st["insights"] = derive(st, EXPECTED_DRAG.get(n, 0.05))
        bots.append(st)
    return {"generated": pd.Timestamp.now(tz="UTC").isoformat(),
            "breadth": _BREADTH["data"], "breadth_updated": _BREADTH["updated"],
            "bots": bots}


HTML = (Path(__file__).parent / "dashboard.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def do_GET(self):
        if self.path.startswith("/api/state"):
            body = json.dumps(snapshot(), default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = HTML.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    threading.Thread(target=_breadth_loop, daemon=True).start()
    srv = HTTPServer((a.host, a.port), Handler)
    print(f"dashboard: http://{a.host}:{a.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
