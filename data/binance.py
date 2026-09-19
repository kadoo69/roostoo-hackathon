from __future__ import annotations

import datetime as dt
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests

from core.config import CACHE

BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
VISION = "https://data.binance.vision"
REST = "https://api.binance.com/api/v3"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
ARCHIVE_WORKERS = 16

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]
NUMERIC = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
           "taker_buy_base", "taker_buy_quote"]


class BinanceDataError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "roostoo-hackathon-research"})
    return s


SESSION = _session()


def listed_symbols_ever(quote: str = "USDT") -> list[str]:
    cache = CACHE / f"symbols_ever_{quote}.txt"
    if cache.exists():
        return cache.read_text().split()

    symbols: list[str] = []
    marker = ""
    while True:
        url = (
            f"{BUCKET}?delimiter=/&prefix=data/spot/monthly/klines/"
            f"&max-keys=1000&marker={marker}"
        )
        root = ElementTree.fromstring(SESSION.get(url, timeout=60).content)
        prefixes = [
            p.findtext(f"{NS}Prefix").rstrip("/").rsplit("/", 1)[-1]
            for p in root.findall(f"{NS}CommonPrefixes")
        ]
        symbols += [s for s in prefixes if s.endswith(quote)]
        if root.findtext(f"{NS}IsTruncated") != "true":
            break
        marker = root.findtext(f"{NS}NextMarker") or prefixes[-1]

    symbols = sorted(set(symbols))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(symbols))
    return symbols


def currently_trading(quote: str = "USDT") -> set[str]:
    info = SESSION.get(f"{REST}/exchangeInfo", params={"permissions": "SPOT"}, timeout=60).json()
    return {
        s["symbol"] for s in info["symbols"]
        if s["quoteAsset"] == quote and s["status"] == "TRADING"
    }


def _parse_zip(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name)
    head = raw[:64].decode("utf-8", "ignore")
    header = 0 if head.lstrip().lower().startswith("open_time") else None
    frame = pd.read_csv(io.BytesIO(raw), header=header, names=KLINE_COLUMNS)
    return frame


def _fetch_archive(symbol: str, interval: str, period: str, daily: bool) -> pd.DataFrame | None:
    scope = "daily" if daily else "monthly"
    url = f"{VISION}/data/spot/{scope}/klines/{symbol}/{interval}/{symbol}-{interval}-{period}.zip"
    r = SESSION.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return _parse_zip(r.content)


def archive_periods(symbol: str, interval: str, daily: bool) -> list[str]:
    scope = "daily" if daily else "monthly"
    prefix = f"data/spot/{scope}/klines/{symbol}/{interval}/"
    periods, marker = [], ""
    while True:
        url = f"{BUCKET}?prefix={prefix}&max-keys=1000&marker={marker}"
        root = ElementTree.fromstring(SESSION.get(url, timeout=60).content)
        keys = [c.findtext(f"{NS}Key") for c in root.findall(f"{NS}Contents")]
        periods += [
            k.rsplit("/", 1)[-1][len(f"{symbol}-{interval}-"):-4]
            for k in keys if k.endswith(".zip")
        ]
        if root.findtext(f"{NS}IsTruncated") != "true":
            break
        marker = keys[-1]
    return sorted(periods)


def _to_utc(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    micros = values > 1e14
    values = values.mask(micros, values // 1000)
    return pd.to_datetime(values, unit="ms", utc=True)


def _rest_klines(symbol: str, interval: str, start_ms: int) -> pd.DataFrame:
    frames, cursor = [], start_ms
    while True:
        r = SESSION.get(
            f"{REST}/klines",
            params={"symbol": symbol, "interval": interval,
                    "startTime": cursor, "limit": 1000},
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        frames.append(pd.DataFrame(rows, columns=KLINE_COLUMNS))
        if len(rows) < 1000:
            break
        cursor = int(rows[-1][0]) + 1
    return pd.concat(frames) if frames else pd.DataFrame(columns=KLINE_COLUMNS)


def klines(symbol: str, interval: str = "1h", start: dt.date | None = None,
           refresh: bool = False) -> pd.DataFrame:
    cache = CACHE / interval / f"{symbol}.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)

    floor = f"{start:%Y-%m}" if start else ""
    jobs = [(p, False) for p in archive_periods(symbol, interval, daily=False)
            if p >= floor]
    covered = {p for p, _ in jobs}
    jobs += [(p, True) for p in archive_periods(symbol, interval, daily=True)
             if p[:7] not in covered]

    with ThreadPoolExecutor(max_workers=ARCHIVE_WORKERS) as pool:
        fetched = list(pool.map(
            lambda j: _fetch_archive(symbol, interval, j[0], j[1]), jobs))
    parts = [f for f in fetched if f is not None]

    if not parts:
        raise BinanceDataError(f"{symbol}:{interval}:no_archive_data")

    frame = pd.concat(parts, ignore_index=True)
    frame["open_time"] = _to_utc(frame["open_time"])
    frame["close_time"] = _to_utc(frame["close_time"])

    tail_from = int(frame["open_time"].max().timestamp() * 1000) + 1
    rest = _rest_klines(symbol, interval, tail_from)
    if len(rest):
        rest["open_time"] = _to_utc(rest["open_time"])
        rest["close_time"] = _to_utc(rest["close_time"])
        frame = pd.concat([frame, rest], ignore_index=True)

    frame = frame.drop(columns=["ignore"])
    for col in NUMERIC:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = (
        frame.drop_duplicates(subset="open_time")
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    frame.insert(0, "symbol", symbol)

    cache.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache, index=False)
    return frame


def klines_many(symbols: list[str], interval: str = "1h", workers: int = 8,
                start: dt.date | None = None) -> dict[str, pd.DataFrame]:
    def one(sym: str) -> tuple[str, pd.DataFrame | None]:
        try:
            return sym, klines(sym, interval, start)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, symbols))
    return {s: f for s, f in results if f is not None and len(f)}
