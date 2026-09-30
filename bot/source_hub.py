"""Forward data collection for public sources that do not drive live orders.

Run ``python3 -m bot.source_hub --once`` for a sample, or without ``--once``
for a 15-minute loop. Every observation carries fetch time and source time.
Failed reads are recorded and never silently replaced with an old value.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from bot.settings import ROOT

OUT = ROOT / "live" / "source_hub"
HYPERLIQUID = "https://api.hyperliquid.xyz/info"
STABLECOINS = "https://stablecoins.llama.fi/stablecoincharts/all"
COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "AVAX", "SUI", "LINK", "ADA")
MAX_AGE_S = {"Hyperliquid": 1200, "Deribit options": 1200,
             "DefiLlama": 90000, "Stablecoin data": 90000}


def _utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _number(value: object) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def hyperliquid() -> dict:
    """One request for the default perp DEX; join metadata and contexts by index."""
    r = requests.post(HYPERLIQUID, json={"type": "metaAndAssetCtxs"}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("unexpected Hyperliquid response")
    universe = payload[0].get("universe")
    contexts = payload[1]
    if not isinstance(universe, list) or not isinstance(contexts, list) or len(universe) != len(contexts):
        raise ValueError("Hyperliquid metadata/context mismatch")
    wanted = set(COINS)
    coins = {}
    for meta, ctx in zip(universe, contexts):
        name = meta.get("name")
        if name not in wanted or not isinstance(ctx, dict):
            continue
        mark = _number(ctx.get("markPx"))
        oi = _number(ctx.get("openInterest"))
        if mark is None or mark <= 0:
            continue
        coins[name] = {
            "mark_usd": mark,
            "funding_hourly": _number(ctx.get("funding")),
            "open_interest_base": oi,
            "open_interest_usd": round(oi * mark, 2) if oi is not None else None,
            "volume_24h_usd": _number(ctx.get("dayNtlVlm")),
            "premium": _number(ctx.get("premium")),
        }
    if not coins:
        raise ValueError("Hyperliquid response has no configured coins")
    return {"source_time": None, "coverage": len(coins), "coins": coins}


def deribit() -> dict:
    from data.options import exposure

    coins = {}
    observed = []
    for name in ("BTC", "ETH"):
        try:
            e = exposure(name)
            if e.get("instruments_used", 0) > 0:
                observed.append(e["utc"])
                coins[name] = {k: e.get(k) for k in
                               ("spot", "net_gex_usd_per_1pct", "net_gex_ratio",
                                "gamma_flip_strike", "regime", "instruments_used")}
        except Exception as exc:  # preserve the other currency's reading
            coins[name] = {"error": repr(exc)[:160]}
    coverage = sum("error" not in v for v in coins.values())
    if not coverage:
        raise ValueError(f"Deribit unavailable: {coins}")
    return {"source_time": max(observed), "coverage": coverage, "coins": coins}


def stablecoins() -> dict:
    """Daily USD pegged supply; source date is distinct from the fetch time."""
    r = requests.get(STABLECOINS, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list):
        raise ValueError("unexpected DefiLlama response")
    rows = []
    for item in payload:
        try:
            day = dt.datetime.fromtimestamp(int(item["date"]), dt.UTC)
            value = _number(item["totalCirculatingUSD"].get("peggedUSD"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if value is not None and value > 0:
            rows.append((day, value))
    rows.sort(key=lambda p: p[0])
    if not rows:
        raise ValueError("DefiLlama response has no USD pegged supply")
    day, value = rows[-1]
    prev = next((v for d, v in reversed(rows[:-1]) if d <= day - dt.timedelta(days=7)), None)
    return {"source_time": day.isoformat(), "coverage": 1,
            "total_usd": round(value, 2),
            "change_7d_pct": round(100 * (value / prev - 1), 3) if prev else None}


SOURCES = {"Hyperliquid": hyperliquid, "Deribit options": deribit,
           "Stablecoin data": stablecoins}


def collect() -> dict:
    """Isolate source failures and publish one comparable health record per feed."""
    started = _utc()
    records = {}
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {pool.submit(fn): name for name, fn in SOURCES.items()}
        for future in as_completed(futures):
            name = futures[future]
            fetched = _utc()
            try:
                data = future.result()
                records[name] = {"status": "ok", "fetched_at": fetched,
                                 "source_time": data.pop("source_time"),
                                 "max_age_s": MAX_AGE_S[name], **data}
            except Exception as exc:
                records[name] = {"status": "error", "fetched_at": fetched,
                                 "source_time": None, "max_age_s": MAX_AGE_S[name],
                                 "coverage": 0, "error": repr(exc)[:200]}
    # DefiLlama is one upstream request exposed as two product datasets.
    records["DefiLlama"] = dict(records["Stablecoin data"])
    return {"schema": 1, "started_at": started, "completed_at": _utc(),
            "trades_on_it": False, "sources": records}


def publish(snapshot: dict, out: pathlib.Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f"state.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(snapshot, allow_nan=False, separators=(",", ":")) + "\n")
    os.replace(tmp, out / "state.json")
    day = snapshot["completed_at"][:10]
    with (out / f"observations-{day}.jsonl").open("a") as fh:
        fh.write(json.dumps(snapshot, allow_nan=False, separators=(",", ":")) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect public market context without trading")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--root", type=pathlib.Path)
    args = ap.parse_args()
    if args.root and args.root.resolve() != ROOT.resolve():
        ap.error("--root does not match this checkout")
    if args.interval < 60:
        ap.error("--interval must be at least 60 seconds")
    while True:
        snap = collect()
        publish(snap)
        print(f"{snap['completed_at']} " + " ".join(
            f"{name}={row['status']}:{row['coverage']}"
            for name, row in snap["sources"].items()), flush=True)
        if args.once:
            return 0 if any(r["status"] == "ok" for r in snap["sources"].values()) else 1
        time.sleep(max(0, args.interval - (
            dt.datetime.fromisoformat(snap["completed_at"]) -
            dt.datetime.fromisoformat(snap["started_at"])).total_seconds()))


if __name__ == "__main__":
    raise SystemExit(main())
