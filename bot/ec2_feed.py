"""State of the live books on the EC2 instance, for the desk.

While `run/LIVE_HOST_EC2` exists the live books run on EC2 and the Mac's own logs for them are stale.
A background thread pulls one JSON line from the instance every `REFRESH_S` through a Session Manager
session (`bot.ec2_session`) and caches it; the desk reads the cache. Returns are measured from each
book's first recorded equity (the venue wallet, never the 100,000 placeholder).
DECISIONS.md#ec2-cutover-2026-10-02
"""
from __future__ import annotations

import json
import threading
import time

from bot.settings import ROOT

MARKER = ROOT / "run" / "LIVE_HOST_EC2"
CACHE = ROOT / "run" / "ec2_state.json"
REFRESH_S = 180
LIVE = ("competition_z25", "competition_z3", "competition_ride", "competition_wf", "competition_split", "competition_rehearsal")
PAPER = ("wf_live", "ride_5m", "ride_z3_5m", "sleeves_z3_5m", "split_tilt_5m", "regime_ls_30m", "ride_z25_5m", "ride_z25_swap_5m", "ride_z25_zrank_5m", "ride_z25_churn_5m")
BOOKS = LIVE + PAPER
_LOCK = threading.Lock()
_STATE: dict = {"ts": 0.0, "data": None, "error": None}

REMOTE = r'''
cd /opt/roostoo-hackathon
sudo .venv/bin/python - <<'PY'
import json, subprocess, datetime as dt
from pathlib import Path
out = {"books": {}, "commit": subprocess.run(["git", "-C", ".", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
       "host_time": dt.datetime.now(dt.UTC).isoformat()}
day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
for b in BOOKS:
    d = Path("live") / b
    unit = ("roostoo-paper@" if b in PAPER else "roostoo-live@") + b
    rec = {"active": subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip(),
           "since": subprocess.run(["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit], capture_output=True, text=True).stdout.strip()}
    try:
        s = json.loads((d / "state.json").read_text())
        curve = s.get("equity_curve") or []
        marks = s.get("last_marks") or {}
        eq = curve[-1] if curve else None
        rec.update({"start_equity": curve[0] if curve else None, "equity": eq, "peak": max(curve) if curve else None,
                    "cash": s.get("cash"), "last_bar": s.get("last_bar"),
                    "curve": curve[-288:][::4],
                    "positions": {k[:-4] if k.endswith("USDT") else k: round(q * marks.get(k, 0) / eq, 4)
                                  for k, q in (s.get("holdings") or {}).items() if eq and q * marks.get(k, 0) / eq > 0.005}})
    except (OSError, ValueError):
        pass
    for kind in ("cycles", "waiting"):
        f = d / f"{kind}-{day}.jsonl"
        if f.exists():
            lines = f.read_text().splitlines()
            if lines:
                last = json.loads(lines[-1])
                rec["last_" + kind] = {k: last.get(k) for k in ("ts_utc", "event", "equity", "halt", "freeze", "drawdown")}
    orders = sorted((d).glob("orders-*.jsonl"))
    rows = []
    for f in orders[-2:]:
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("event") in ("placed", "filled", "cancelled_stale", "rejected"):
                rows.append({k: r.get(k) for k in ("ts_utc", "event", "side", "pair", "status", "price", "quantity", "filled_quantity")})
    rec["orders"] = rows[-6:]
    buys = {}
    for f in orders[-2:]:
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("event") == "placed" and r.get("side") == "BUY" and r.get("symbol"):
                buys[r["symbol"]] = r.get("price")
    try:
        held_q = json.loads((d / "state.json").read_text()).get("holdings") or {}
    except (OSError, ValueError):
        held_q = {}
    rec["entries"] = {k[:-4] if k.endswith("USDT") else k: {"qty": q, "entry": buys.get(k)}
                      for k, q in held_q.items() if q and buys.get(k)}
    errs = sorted(d.glob("errors-*.jsonl"))
    rows = [json.loads(x) for x in errs[-1].read_text().splitlines()] if errs and day in errs[-1].name else []
    rec["errors_today_rows"] = [{"event": r.get("event"), "error": str(r.get("error", ""))[:160]} for r in rows[-200:]]
    if b != "competition_rehearsal" and b not in PAPER and rec.get("active") == "active":
        # The detail panel of the desk, for the live competition unit only. DECISIONS.md#desk-revamp-2026-10-05
        try:
            st = json.loads((d / "state.json").read_text())
            rec["skim_refs"] = st.get("skim_refs") or {}
            rec["universe"] = st.get("universe") or []
            rec["cash"] = st.get("cash")
        except (OSError, ValueError):
            pass
        try:
            rec["ride"] = next(iter(json.loads((d / "ride_state.json").read_text()).values())).get("after")
        except (OSError, ValueError, StopIteration, AttributeError):
            rec["ride"] = None
        series, seen = [], set()
        for f in sorted(d.glob("cycles-*.jsonl"))[-3:]:
            for line in f.read_text().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("event") != "cycle" or r.get("equity") is None:
                    continue
                key = r["ts_utc"][:15]  # one point per 10 minutes
                if key in seen:
                    series[-1] = [r["ts_utc"], round(r["equity"], 2)]
                    continue
                seen.add(key)
                series.append([r["ts_utc"], round(r["equity"], 2)])
        rec["eq_series"] = series[-600:]
        try:
            from bot.blotter import build
            bl = build(b)
            rec["closed"] = bl.get("closed") or []
            rec["open_lots"] = bl.get("open") or []
            rec["blotter"] = bl.get("stats") or {}
        except Exception as exc:  # noqa: BLE001
            rec["closed"], rec["blotter"] = [], {"error": repr(exc)[:200]}
        try:
            rec["monitor"] = json.loads(Path("live/monitor/latest.json").read_text())
        except (OSError, ValueError):
            rec["monitor"] = None
    out["books"][b] = rec
try:
    from gates.wf_report import summary
    out["wf"] = summary("wf_live")
except Exception as exc:  # noqa: BLE001
    out["wf"] = {"error": repr(exc)[:200]}
try:
    out["progress"] = {r["book"]: r for r in json.loads(Path("results/progress/latest.json").read_text()).get("books", [])}
except (OSError, ValueError):
    out["progress"] = {}
print("EC2JSON " + json.dumps(out, default=str))
PY
'''.replace("BOOKS", repr(BOOKS)).replace("PAPER", repr(PAPER))


def error_counts(b: dict) -> dict:
    """Faults and notes from a book's error journal today: config changes, deferred data gaps and recovered
    network blips are notes, not faults (`bot.dashboard.transient`). DECISIONS.md#live-audit-2026-09-24"""
    from bot.dashboard import transient
    rows = b.get("errors_today_rows")
    if rows is None:
        return {"errors_today": b.get("errors_today", 0), "notes_today": 0}
    notes = sum(1 for r in rows if transient(r))
    return {"errors_today": len(rows) - notes, "notes_today": notes}


def fetch() -> dict:
    from bot.ec2_session import run_script
    rc, text = run_script(REMOTE, timeout=120)
    for line in text.splitlines():
        if line.startswith("EC2JSON "):
            return json.loads(line[len("EC2JSON "):])
    raise RuntimeError(f"no EC2JSON line (rc={rc}): {text[-300:]}")


def fetch_isolated(timeout: float = 240) -> dict:
    """`fetch()` in a child process, so a long-running desk always reads the current AWS sign-in from disk:
    an in-process boto3 session kept failing as expired after `deploy/aws_login.py` had renewed it,
    while fresh processes succeeded (2026-10-04, HANDOVER.md lessons)."""
    import subprocess
    import sys
    code = "import json; from bot.ec2_feed import fetch; print('EC2FEED ' + json.dumps(fetch()))"
    p = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    for line in p.stdout.splitlines():
        if line.startswith("EC2FEED "):
            return json.loads(line[len("EC2FEED "):])
    raise RuntimeError(f"fetch child rc={p.returncode}: {(p.stderr or p.stdout)[-300:]}")


def refresh_once() -> None:
    try:
        data = fetch_isolated()
        with _LOCK:
            _STATE.update({"ts": time.time(), "data": data, "error": None})
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"fetched": time.time(), "data": data}))
    except Exception as exc:                                  # noqa: BLE001
        msg = repr(exc)
        if any(k in msg for k in ("ExpiredToken", "RequestExpired", "UnrecognizedClient", "Forbidden", "(403)",
                                  "InvalidClientTokenId", "NoCredentials", "ProfileNotFound")) or "credentials" in msg.lower():
            msg = "AWS sign-in expired: run python3 deploy/aws_login.py and approve in the browser"
        with _LOCK:
            _STATE.update({"error": msg[:300]})


def refresh_loop() -> None:
    if CACHE.exists() and _STATE["data"] is None:
        try:
            c = json.loads(CACHE.read_text())
            _STATE.update({"ts": c["fetched"], "data": c["data"]})
        except (OSError, ValueError, KeyError):
            pass
    while True:
        if MARKER.exists():
            refresh_once()
        time.sleep(REFRESH_S)


def competition_context() -> tuple[list[str], dict[str, str], set[str]]:
    """Universe, last entry bars and held symbols of the active competition unit, for the trigger radar."""
    with _LOCK:
        data = _STATE["data"] or {}
    for name in LIVE:
        b = (data.get("books") or {}).get(name) or {}
        if name != "competition_rehearsal" and b.get("active") == "active" and b.get("universe"):
            ride = b.get("ride") or {}
            return list(b["universe"]), dict(ride.get("last") or {}), set(ride.get("held") or {})
    return [], {}, set()


def active() -> bool:
    return MARKER.exists()


def payload() -> dict | None:
    if not MARKER.exists():
        return None
    with _LOCK:
        st = dict(_STATE)
    data = st["data"] or {}
    books = []
    for name in BOOKS:
        b = (data.get("books") or {}).get(name) or {}
        start, eq = b.get("start_equity"), b.get("equity")
        waiting = bool(b.get("last_waiting")) and not b.get("last_cycles")
        if not b and name in PAPER:
            continue
        books.append({"bot": name, "paper": name in PAPER, "active": b.get("active"), "since": b.get("since"), "waiting": waiting,
                      "last_poll": (b.get("last_waiting") or {}).get("ts_utc"),
                      "last_cycle": (b.get("last_cycles") or {}).get("ts_utc"),
                      "halt": (b.get("last_cycles") or {}).get("halt"), "freeze": (b.get("last_cycles") or {}).get("freeze"),
                      "start_equity": start, "equity": eq, "net": round(eq - start, 2) if start and eq else None,
                      "ret_pct": round((eq / start - 1) * 100, 2) if start and eq else None,
                      "peak": b.get("peak"), "positions": b.get("positions") or {}, "entries": b.get("entries") or {},
                      "curve": b.get("curve") or [], "orders": b.get("orders") or [], **error_counts(b),
                      **{k: b[k] for k in ("skim_refs", "universe", "cash", "ride", "eq_series", "closed", "open_lots", "blotter",
                                           "monitor") if k in b}})
    return {"host": MARKER.read_text().strip(), "commit": data.get("commit"), "wf": data.get("wf"),
            "progress": data.get("progress") or {}, "fetched_age_s":
            round(time.time() - st["ts"]) if st["ts"] else None, "error": st["error"], "books": books}
