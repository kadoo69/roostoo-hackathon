"""Read-only pre-flight for a live host: clock, venue, keys, market data. Places no order.

Exit code 0 only when every check a live book depends on passes; a competition key that is
not yet active is reported but does not fail, because the book waits for it by design.
The competition key is only checked for presence: Screen 1 rejects any trace of a manually called
API on the competition account, so only the bot itself calls Roostoo with it. Set PREFLIGHT_COMP=1
to read its wallet anyway (before activation only). DECISIONS.md#roostoo-keys-2026-09-30,
DECISIONS.md#comp-key-bot-only-2026-10-02
"""
from __future__ import annotations

import json
import os
import sys
import time

from bot.settings import credentials
from data.binance import REST, REST_MIRROR, rest_get
from venue.roostoo import RoostooClient, RoostooError


def check(name: str, fn) -> dict:
    t0 = time.time()
    try:
        detail = fn()
        return {"check": name, "ok": True, "ms": round((time.time() - t0) * 1000), "detail": detail}
    except Exception as exc:
        return {"check": name, "ok": False, "ms": round((time.time() - t0) * 1000), "detail": str(exc)[:200]}


def run() -> list[dict]:
    out = []
    pub = RoostooClient()
    out.append(check("roostoo_clock_offset_ms", lambda: pub.sync_time()))
    out.append(check("roostoo_pairs", lambda: len(pub.exchange_info())))
    out.append(check("roostoo_ticker", lambda: len(pub.ticker())))
    for host in (REST, REST_MIRROR):
        def klines(host=host):
            import requests
            r = requests.get(f"{host}/klines", params={"symbol": "BTCUSDT", "interval": "30m", "limit": 2}, timeout=10)
            r.raise_for_status()
            return f"{r.status_code} {len(r.json())} bars"
        out.append(check(f"binance_klines {host.split('/')[2]}", klines))
    out.append(check("binance_failover_path", lambda: rest_get("/ping", timeout=10).status_code))
    for keyset in ("test", "comp"):
        key, secret = credentials(keyset)
        if keyset == "comp" and os.environ.get("PREFLIGHT_COMP") != "1":
            out.append({"check": "roostoo_keys_comp", "ok": bool(key and secret), "ms": 0,
                        "detail": "present, not called (bot-only key)" if key and secret else "missing keys in .env"})
            continue

        def wallet(key=key, secret=secret):
            if not key or not secret:
                raise RoostooError("missing keys in .env")
            c = RoostooClient(key, secret)
            c.sync_time()
            w = c.balance()
            return {k: v for k, v in w.items() if (v.get("Free") or v.get("Lock"))}
        row = check(f"roostoo_wallet_{keyset}", wallet)
        if not row["ok"] and "not yet a member" in row["detail"]:
            row.update(ok=True, note="competition account not active yet; the book waits for it")
        out.append(row)
    return out


if __name__ == "__main__":
    rows = run()
    for r in rows:
        print(json.dumps(r))
    bad = [r["check"] for r in rows if not r["ok"]]
    print("PREFLIGHT", "PASS" if not bad else f"FAIL {bad}")
    sys.exit(1 if bad else 0)
