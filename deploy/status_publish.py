"""Publish the live book's status to an unlisted ntfy.sh topic, for monitors that cannot reach the instance.

Run on the EC2 instance by `deploy/roostoo-status.timer` every 10 minutes. It reads the live book's own
files only (never calls Roostoo, never writes to a book) and posts one compact JSON status to
`https://ntfy.sh/<topic>`; on a change worth a human's attention (a trade, a sleeve ride, an error, a skipped
signal, the unit down, a halt) it also posts a high-priority plain-text alert. The topic name is read from
`STATUS_NTFY_TOPIC` in the instance's `.env` and is never committed. Two checks recompute the rules from raw
Binance bars: a +2%/15m trigger on a coin outside the host book that the cash sleeve did not take, and a new
long in the rule's latest 30m target with no BUY and no journaled reason.
DECISIONS.md#status-feed-2026-10-06
Usage: python3 deploy/status_publish.py [--book competition_r4] [--dry]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "run" / "status_publish_state.json"


def rows(book: str, stream: str, n: int = 2) -> list[dict]:
    out = []
    for f in sorted((ROOT / "live" / book).glob(f"{stream}-*.jsonl"))[-n:]:
        for line in f.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def checks(book: str, holdings: set[str], led: dict) -> dict:
    import pandas as pd

    from bot import feed
    st = json.loads((ROOT / "live" / book / "state.json").read_text())
    uni = st.get("universe") or []
    fr = feed.bar_frame(uni, "5m", 20)
    c = pd.DataFrame({s: f.set_index("open_time")["close"] for s, f in fr.items() if len(f)}).sort_index()
    r3 = (c / c.shift(3) - 1).iloc[-6:]
    missed = []
    for t, row in r3.iterrows():
        for s, v in row.items():
            if v >= 0.02 and s not in holdings and led and str(t) <= str(led.get("bar")):
                took = s in led["held"] or led["last"].get(s) == str(t) or s in led["units"]
                if not took and len(led["held"]) < 3 and not led["stopped"] and led["cash"] > 5:
                    missed.append(f"{s}@{t:%H:%M}Z {v * 100:.2f}%")
    out = {"sleeve_missed": missed, "best_15m_pct": round(float(r3.max().max()) * 100, 2)}
    con = [x for x in rows(book, "signals", 1) if x.get("event") == "contenders"]
    if con:
        last = con[-1]
        want = [s for s, w in last["target"].items() if w > 0 and s not in holdings]
        after = str(pd.Timestamp(last["bar"]) + pd.Timedelta(minutes=30))[:19].replace(" ", "T")
        bought = {o.get("symbol") for o in rows(book, "orders", 1) if o.get("side") == "BUY" and o.get("ts_utc", "") >= after}
        explained = {s for x in rows(book, "signals", 1) if x.get("bar") == last["bar"] for s in (x.get("symbols") or [])}
        age = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(last["bar"]) - pd.Timedelta(minutes=30)).total_seconds()
        gap = [s for s in want if s not in bought and s not in explained]
        out.update({"rule_bar": last["bar"], "regime": last.get("regime"), "rule_target": last["target"],
                    "host_missed": gap if age > 120 else []})
    return out


def status(book: str) -> dict:
    now = dt.datetime.now(dt.UTC)
    active = subprocess.run(["systemctl", "is-active", f"roostoo-live@{book}"], capture_output=True, text=True).stdout.strip()
    cyc = rows(book, "cycles", 1)
    last = cyc[-1] if cyc else {}
    age = (now - dt.datetime.fromisoformat(last["ts_utc"])).total_seconds() if last else None
    since = (now - dt.timedelta(hours=6)).isoformat()[:19]
    orders = [{k: o.get(k) for k in ("ts_utc", "side", "symbol", "price", "quantity", "status", "book", "event")}
              for o in rows(book, "orders") if o.get("ts_utc", "") >= since and o.get("event") in ("placed", "cash_sleeve_fill")]
    errors = [{k: e.get(k) for k in ("ts_utc", "event", "error")} for e in rows(book, "errors")
              if e.get("ts_utc", "") >= since and e.get("event") != "config_changed_mid_run"]
    led_path = ROOT / "live" / book / "cash_sleeve.json"
    led = json.loads(led_path.read_text()) if led_path.exists() else {}
    holdings = {s for s, w in (last.get("positions") or {}).items() if w > 0} - set(led.get("units") or {})
    s = {"t": now.isoformat()[:19] + "Z", "book": book, "unit": active, "cycle_age_s": round(age) if age is not None else None,
         "equity": last.get("equity"), "cash": last.get("cash"), "host_cash": last.get("host_cash"),
         "positions": last.get("positions"), "halt": last.get("halt"), "freeze": last.get("freeze"),
         "drawdown": last.get("drawdown"), "sleeve": last.get("cash_sleeve"),
         "orders_6h": orders[-8:], "errors_6h": errors[-5:]}
    try:
        s["checks"] = checks(book, holdings, led)
    except Exception as exc:                                      # noqa: BLE001
        s["checks"] = {"error": repr(exc)[:200]}
    return s


def alerts(s: dict, prev: dict) -> list[str]:
    out = []
    if s["unit"] != "active":
        out.append(f"unit {s['unit']}")
    if s["cycle_age_s"] is not None and s["cycle_age_s"] > 300:
        out.append(f"no cycle for {s['cycle_age_s']} s")
    if s.get("halt") or s.get("freeze"):
        out.append(f"halt {s.get('halt')} freeze {s.get('freeze')}")
    seen = set(prev.get("orders") or [])
    for o in s["orders_6h"]:
        key = f"{o['ts_utc']}|{o['symbol']}|{o['side']}"
        if o.get("event") == "placed" and key not in seen:
            out.append(f"{'sleeve' if o.get('book') else 'rule'} {o['side']} {o['symbol']} {o['quantity']} @ {o['price']}")
    old_err = set(prev.get("errors") or [])
    out += [f"error {e['event']}" for e in s["errors_6h"] if f"{e['ts_utc']}|{e['event']}" not in old_err]
    ck = s.get("checks") or {}
    if ck.get("sleeve_missed"):
        out.append(f"SLEEVE MISSED {ck['sleeve_missed']}")
    if ck.get("host_missed") and ck.get("rule_bar") != prev.get("host_missed_bar"):
        out.append(f"RULE MISSED {ck['host_missed']} at {ck.get('rule_bar')}")
    if ck.get("error"):
        out.append(f"check error {ck['error']}")
    eq, peq = s.get("equity"), prev.get("equity")
    for line in (95_000, 98_000, 99_900, 101_000):
        if eq and peq and (eq - line) * (peq - line) < 0:
            out.append(f"equity crossed {line:,} ({eq:,.0f})")
    return out


def env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None


def post(topic: str, body: str, title: str | None = None, priority: str = "default") -> None:
    import requests
    headers = {"Priority": priority}
    if title:
        headers["Title"] = title
    requests.post(f"https://ntfy.sh/{topic}", data=body.encode(), headers=headers, timeout=20).raise_for_status()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="competition_r4")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    topic = os.environ.get("STATUS_NTFY_TOPIC") or env_value(ROOT / ".env", "STATUS_NTFY_TOPIC")
    s = status(a.book)
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    al = alerts(s, prev)
    body = json.dumps(s, separators=(",", ":"), default=str)
    if len(body) > 3900:
        s["orders_6h"] = s["orders_6h"][-3:]
        s["errors_6h"] = s["errors_6h"][-2:]
        body = json.dumps(s, separators=(",", ":"), default=str)[:3900]
    if a.dry or not topic:
        print(body)
        print("ALERTS", al)
        return 0
    post(topic, body, title=f"status {s['equity']}")
    if al:
        post(topic, f"{s['t']} equity {s['equity']}: " + "; ".join(al), title="Roostoo ALERT", priority="high")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"equity": s["equity"],
                                 "orders": [f"{o['ts_utc']}|{o['symbol']}|{o['side']}" for o in s["orders_6h"]],
                                 "errors": [f"{e['ts_utc']}|{e['event']}" for e in s["errors_6h"]],
                                 "host_missed_bar": (s.get("checks") or {}).get("rule_bar") if (s.get("checks") or {}).get("host_missed") else prev.get("host_missed_bar")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
