"""Research-only Hyperliquid realised funding history.

The public ``fundingHistory`` endpoint returns hourly settlements, up to 500
rows per page. Keep the API's millisecond timestamp: a settlement a few
milliseconds after a bar close was not known at that close.
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
from pathlib import Path

import pandas as pd
import requests

from core.config import CACHE

URL = "https://api.hyperliquid.xyz/info"
OUT = CACHE / "hyperliquid" / "funding"
DEFAULT_COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "AVAX", "SUI", "LINK", "ADA")


def _page(session: requests.Session, coin: str, start_ms: int, end_ms: int) -> list[dict]:
    body = {"type": "fundingHistory", "coin": coin, "startTime": start_ms,
            "endTime": end_ms}
    for attempt in range(5):
        try:
            res = session.post(URL, json=body, timeout=25)
            if res.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(16, 2 ** attempt))
                continue
            res.raise_for_status()
            rows = res.json()
            if not isinstance(rows, list):
                raise ValueError(f"{coin}: invalid fundingHistory response")
            return rows
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(min(16, 2 ** attempt))
    raise RuntimeError(f"{coin}: exhausted retries")


def fetch(coin: str, start: pd.Timestamp, end: pd.Timestamp,
          session: requests.Session | None = None, out: Path = OUT,
          pause_s: float = 0.12) -> pd.DataFrame:
    """Incrementally fill [start, end], preserving past parquet on API failure."""
    coin = coin.upper()
    if coin not in DEFAULT_COINS:
        raise ValueError(f"unconfigured Hyperliquid coin: {coin}")
    session = session or requests.Session()
    start = pd.Timestamp(start).tz_convert("UTC")
    end = pd.Timestamp(end).tz_convert("UTC")
    path = out / f"{coin}.parquet"
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    first = int(start.timestamp() * 1000)
    stop = int(end.timestamp() * 1000)
    ranges = [(first, stop)] if old.empty else [
        (first, min(stop, int(old.index.min().timestamp() * 1000) - 1)),
        (max(first, int(old.index.max().timestamp() * 1000) + 1), stop),
    ]
    chunks = []
    for cursor, range_end in ranges:
        while cursor <= range_end:
            rows = _page(session, coin, cursor, range_end)
            if not rows:
                break
            d = pd.DataFrame(rows)
            required = {"time", "fundingRate", "premium"}
            if not required.issubset(d.columns):
                raise ValueError(f"{coin}: missing {required - set(d.columns)}")
            d["ts"] = pd.to_datetime(d["time"], unit="ms", utc=True)
            d["funding_rate"] = pd.to_numeric(d["fundingRate"], errors="coerce")
            d["premium"] = pd.to_numeric(d["premium"], errors="coerce")
            d = d.set_index("ts")[["funding_rate", "premium"]].dropna(subset=["funding_rate"])
            if d.empty:
                break
            chunks.append(d)
            nxt = int(d.index.max().timestamp() * 1000) + 1
            if nxt <= cursor:
                raise ValueError(f"{coin}: fundingHistory cursor did not advance")
            cursor = nxt
            if len(rows) < 500:
                break
            time.sleep(pause_s)
    frames = ([old] if len(old) else []) + chunks
    if not frames:
        return pd.DataFrame(columns=["funding_rate", "premium"])
    result = pd.concat(frames).sort_index()
    result = result[~result.index.duplicated(keep="last")]
    out.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".parquet.tmp")
    result.to_parquet(temp)
    temp.replace(path)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill public Hyperliquid funding history")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default=dt.datetime.now(dt.UTC).date().isoformat())
    ap.add_argument("--coins", nargs="+", default=list(DEFAULT_COINS))
    args = ap.parse_args()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    with requests.Session() as session:
        session.headers.update({"User-Agent": "roostoo-hackathon-research"})
        for coin in args.coins:
            d = fetch(coin, start, end, session)
            print(f"{coin}: {len(d)} settlements, {d.index.min()} to {d.index.max()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
