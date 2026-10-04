"""Live venue quotes for the desk: the Roostoo ticker (keyless, one call for every pair) every
`REFRESH_S`, so positions and equity on the page move at venue speed instead of the EC2 pull's
minutes. Runs on the Mac from its own IP, separate from the bot's calls on EC2; read-only.
DECISIONS.md#desk-live-quotes-2026-10-05
"""
from __future__ import annotations

import threading
import time

REFRESH_S = 3.0
_LOCK = threading.Lock()
_STATE: dict = {"quotes": {}, "server_ms": None, "ts": 0.0, "error": None, "calls": 0}


def parse(data: dict) -> dict[str, dict]:
    """`{"PUMP/USD": {...}}` -> `{"PUMP": {"last", "bid", "ask", "chg_24h_pct"}}` for USD pairs."""
    out = {}
    for pair, q in data.items():
        base, _, quote = pair.partition("/")
        if quote != "USD":
            continue
        out[base] = {"last": q.get("LastPrice"), "bid": q.get("MaxBid"), "ask": q.get("MinAsk"),
                     "chg_24h_pct": round(float(q["Change"]) * 100, 3) if q.get("Change") is not None else None}
    return out


def refresh_loop() -> None:
    from venue.roostoo import RoostooClient
    client = RoostooClient(max_retries=1, timeout=5.0)
    while True:
        try:
            data = client.ticker()
            with _LOCK:
                _STATE.update({"quotes": parse(data), "server_ms": client.last_ticker_server_time_ms,
                               "ts": time.time(), "error": None, "calls": _STATE["calls"] + 1})
        except Exception as exc:                                  # noqa: BLE001
            with _LOCK:
                _STATE["error"] = repr(exc)[:200]
        time.sleep(REFRESH_S)


def payload() -> dict:
    with _LOCK:
        st = dict(_STATE)
    return {"quotes": st["quotes"], "server_ms": st["server_ms"], "error": st["error"],
            "age_s": round(time.time() - st["ts"], 1) if st["ts"] else None, "refresh_s": REFRESH_S}
