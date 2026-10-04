"""Read-only status snapshot of the competition account, written on the EC2 instance itself every 5 minutes.

Monitoring from the Mac went blind three times on 2026-10-04 (AWS sign-in expiry, a stalled desk feed, the
battery). A systemd timer on the instance (`deploy/roostoo-monitor.timer`) runs this module, which reads the live
book's own files and appends one line to `live/monitor/status-<day>.jsonl` and rewrites `live/monitor/latest.json`.
It never calls Roostoo and never writes to a book. DECISIONS.md#ec2-monitor-2026-10-05
Usage: python3 deploy/ec2_monitor.py [--root /opt/roostoo-hackathon]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

UNITS = ("competition_z25", "competition_z3", "competition_ride", "competition_wf", "competition_split")
STALE_CYCLE_S = 300
DRAWDOWN_ALERT = 0.05


def unit_active(book: str) -> bool:
    try:
        out = subprocess.run(["systemctl", "is-active", f"roostoo-live@{book}"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return out == "active"


def last_line(path: Path) -> dict | None:
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def position(sym: str, weight: float, marks: dict, held: dict) -> dict:
    rec = held.get(sym) or []
    return {"weight": round(weight, 4), "mark": marks.get(sym),
            "entry": rec[1] if len(rec) > 1 else None, "target_pct": round(rec[2] * 100, 2) if len(rec) > 2 else None}


def snapshot(root: Path, book: str | None, now: dt.datetime) -> dict:
    """One status record for `book` (the active competition unit) from its journal and state files."""
    day = now.strftime("%Y-%m-%d")
    out: dict = {"ts_utc": now.isoformat(), "book": book, "alerts": []}
    if book is None:
        out["alerts"].append("no competition unit active")
        return out
    d = root / "live" / book
    cyc = last_line(d / f"cycles-{day}.jsonl")
    state = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
    ride = json.loads((d / "ride_state.json").read_text()) if (d / "ride_state.json").exists() else {}
    held = next(iter(ride.values()), {}).get("after", {}).get("held", {}) if ride else {}
    curve = state.get("equity_curve") or []
    if cyc:
        age = (now - dt.datetime.fromisoformat(cyc["ts_utc"])).total_seconds()
        marks = cyc.get("marks") or {}
        out.update({"equity": round(cyc["equity"], 2), "cash": round(cyc["cash"], 2), "cycle_age_s": round(age),
                    "halt": cyc.get("halt"), "freeze": cyc.get("freeze"),
                    "positions": {s: position(s, w, marks, held) for s, w in (cyc.get("positions") or {}).items()}})
        if age > STALE_CYCLE_S:
            out["alerts"].append(f"last cycle {round(age)} s old")
        if cyc.get("halt") or cyc.get("freeze"):
            out["alerts"].append("halt or freeze")
    else:
        out["alerts"].append("no cycle today")
    if curve:
        peak = max(curve)
        out["peak"] = round(peak, 2)
        if out.get("equity") and out["equity"] < peak * (1 - DRAWDOWN_ALERT):
            out["alerts"].append(f"drawdown {round((out['equity'] / peak - 1) * 100, 2)}% from peak")
    errs = d / f"errors-{day}.jsonl"
    rows = [json.loads(x) for x in errs.read_text().splitlines()] if errs.exists() else []
    out["faults_today"] = sum(1 for r in rows if r.get("event") != "config_changed_mid_run")
    orders = d / f"orders-{day}.jsonl"
    placed = [json.loads(x) for x in orders.read_text().splitlines()] if orders.exists() else []
    out["orders_today"] = sum(1 for r in placed if r.get("event") == "placed")
    out["last_order"] = next(({k: r.get(k) for k in ("ts_utc", "side", "symbol", "price", "quantity", "status")}
                              for r in reversed(placed) if r.get("event") == "placed"), None)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/opt/roostoo-hackathon")
    a = ap.parse_args(argv)
    root = Path(a.root)
    now = dt.datetime.now(dt.timezone.utc)
    book = next((b for b in UNITS if unit_active(b)), None)
    rec = snapshot(root, book, now)
    mon = root / "live" / "monitor"
    mon.mkdir(parents=True, exist_ok=True)
    with (mon / f"status-{now.strftime('%Y-%m-%d')}.jsonl").open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    (mon / "latest.json").write_text(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
