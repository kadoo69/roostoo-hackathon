from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from data.binance import KLINE_COLUMNS, NUMERIC, REST
from venue.roostoo import PairSpec, RoostooClient

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-bot"})


class FeedError(RuntimeError):
    pass


def klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    r = SESSION.get(f"{REST}/klines",
                    params={"symbol": symbol, "interval": interval, "limit": limit},
                    timeout=20)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise FeedError(f"{symbol}:{interval}:empty")
    f = pd.DataFrame(rows, columns=KLINE_COLUMNS).drop(columns=["ignore"])
    for c in NUMERIC:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f["open_time"] = pd.to_datetime(f["open_time"], unit="ms", utc=True)
    f["close_time"] = pd.to_datetime(f["close_time"], unit="ms", utc=True)
    return f


def closed_bars(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    f = klines(symbol, interval, limit)
    now = dt.datetime.now(dt.timezone.utc)
    return f[f["close_time"] <= now].reset_index(drop=True)


def bar_frame(symbols: list[str], interval: str, limit: int) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        try:
            out[s] = closed_bars(s, interval, limit)
        except Exception:
            continue
    return out


def close_matrix(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {s: f.set_index("open_time")["close"] for s, f in frames.items() if len(f)}
    return pd.DataFrame(cols).sort_index()


def roostoo_quotes(client: RoostooClient) -> dict[str, dict]:
    return client.ticker()


def binance_prices(symbols: list[str]) -> dict[str, float]:
    r = SESSION.get(f"{REST}/ticker/price", timeout=20)
    r.raise_for_status()
    wanted = set(symbols)
    return {row["symbol"]: float(row["price"]) for row in r.json()
            if row["symbol"] in wanted}


def mirror_check(quotes: dict[str, dict], specs: dict[str, PairSpec],
                 symbols: list[str]) -> list[dict]:
    prices = binance_prices(symbols)
    rows = []
    for sym in symbols:
        pair = next((p for p, s in specs.items() if s.binance_symbol == sym), None)
        if pair is None or pair not in quotes or sym not in prices:
            continue
        rst = float(quotes[pair]["LastPrice"])
        bn = prices[sym]
        if rst <= 0 or bn <= 0:
            continue
        spec = specs[pair]
        dev = (rst / bn - 1.0) * 1e4
        tick_bps = spec.tick / rst * 1e4
        rows.append({"symbol": sym, "pair": pair, "roostoo": rst, "binance": bn,
                     "deviation_bps": round(dev, 3),
                     "tick_bps": round(tick_bps, 3),
                     "ticks": round(abs(dev) / tick_bps, 2) if tick_bps > 0 else None,
                     "material": bool(abs(dev) > 2.0 * tick_bps)})
    return rows
