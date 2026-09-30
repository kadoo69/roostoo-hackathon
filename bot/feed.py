from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from data.binance import KLINE_COLUMNS, NUMERIC, rest_get
from venue.roostoo import PairSpec, RoostooClient

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-bot"})
FETCH_WORKERS = 8
SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=FETCH_WORKERS, pool_maxsize=FETCH_WORKERS * 2))


class FeedError(RuntimeError):
    pass


WEIGHT_SOFT_LIMIT = 4800
_GUARD = {"until": 0.0}


def binance_get(path: str, **kw):
    """Every Binance REST call goes through here. On 429 or 418 it records the Retry-After and
    raises; until then further calls fail at once without touching the network, because hammering
    a rate limit escalates Binance's ban from minutes to days. Near the weight limit it pauses so
    the fleet stays under it. DECISIONS.md#binance-rate-guard-2026-09-27"""
    import time

    now = time.time()
    if now < _GUARD["until"]:
        raise FeedError(f"binance backoff {(_GUARD['until'] - now):.0f}s")
    r = rest_get(path, session=SESSION, timeout=kw.pop("timeout", 20), **kw)
    if r.status_code in (418, 429):
        _GUARD["until"] = time.time() + float(r.headers.get("retry-after") or 60)
        raise FeedError(f"binance {r.status_code}, backing off {r.headers.get('retry-after')}s")
    used = int(r.headers.get("x-mbx-used-weight-1m") or 0)
    if used >= WEIGHT_SOFT_LIMIT:
        time.sleep(min(10.0, 60.0 - time.time() % 60 + 0.5))
    return r


def klines(symbol: str, interval: str, limit: int = 500, end_ms: int | None = None) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_ms is not None:
        params["endTime"] = end_ms
    r = binance_get("/klines", params=params)
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


def closed_bars(symbol: str, interval: str, limit: int = 500, asof: dt.datetime | None = None) -> pd.DataFrame:
    """Closed bars; more than Binance's 1,000 per request are paged backwards with `endTime`.
    DECISIONS.md#scalper-adaptive-declaration"""
    f = klines(symbol, interval, min(limit, 1000))
    while len(f) < limit:
        try:
            older = klines(symbol, interval, min(limit - len(f), 1000),
                           end_ms=int(f["open_time"].iloc[0].timestamp() * 1000) - 1)
        except FeedError:
            break
        f = pd.concat([older, f], ignore_index=True)
        if len(older) < 1000:
            break
    now = asof or dt.datetime.now(dt.timezone.utc)
    return f[f["close_time"] <= now].reset_index(drop=True)


def bar_frame(symbols: list[str], interval: str, limit: int, retries: int = 2) -> dict[str, pd.DataFrame]:
    """Closed bars per symbol. A failed request is retried with a short backoff; a symbol that
    still fails is left out, and callers that decide on the set must check `data_gaps`. Every symbol
    is cut at the same instant, so a bar that closes mid-download is either in all of them or none.
    A silent drop made the live books rank a partial universe. DECISIONS.md#live-audit-2026-09-24
    Symbols are fetched `FETCH_WORKERS` at a time, so a cycle waits for the slowest request
    rather than the sum of them. DECISIONS.md#parallel-fetch-2026-09-26
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    asof = dt.datetime.now(dt.timezone.utc)
    out = {}
    pending = list(symbols)

    def one(s: str) -> tuple[str, pd.DataFrame | None]:
        try:
            return s, closed_bars(s, interval, limit, asof=asof)
        except Exception:
            return s, None

    for attempt in range(retries + 1):
        failed = []
        with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, max(1, len(pending)))) as pool:
            for s, frame in pool.map(one, pending):
                if frame is None:
                    failed.append(s)
                else:
                    out[s] = frame
        if not failed:
            break
        pending = failed
        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))
    return out


def data_gaps(symbols: list[str], frames: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Symbols with no bars, and symbols whose last closed bar is older than the newest bar any
    symbol has. Either means a decision on this matrix would rank a partial universe."""
    missing = sorted(s for s in symbols if s not in frames or frames[s].empty)
    have = {s: f["open_time"].iloc[-1] for s, f in frames.items() if s in symbols and not f.empty}
    newest = max(have.values()) if have else None
    stale = sorted(s for s, t in have.items() if newest is not None and t < newest)
    return {"missing": missing, "stale": stale}


def close_matrix(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {s: f.set_index("open_time")["close"] for s, f in frames.items() if len(f)}
    return pd.DataFrame(cols).sort_index()


def roostoo_quotes(client: RoostooClient) -> dict[str, dict]:
    return client.ticker()


def binance_prices(symbols: list[str]) -> dict[str, float]:
    r = binance_get("/ticker/price")
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


_PERPS: dict = {"at": 0.0, "listed": set()}


def perp_listing() -> set[str]:
    """Binance USD-M perpetual symbols, cached for six hours. DECISIONS.md#confirmations-and-residual-declaration"""
    import time

    from data.vision import FAPI
    if time.time() - _PERPS["at"] > 6 * 3600 or not _PERPS["listed"]:
        r = SESSION.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=20)
        r.raise_for_status()
        _PERPS["listed"] = {s["symbol"] for s in r.json()["symbols"]
                            if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"}
        _PERPS["at"] = time.time()
    return _PERPS["listed"]


def oi_frame(symbols: list[str], period: str, limit: int = 500) -> pd.DataFrame:
    """Perpetual open interest in USD per spot symbol, indexed by the observation time Binance stamps.
    A coin without a perpetual, or whose request fails, is left out. DECISIONS.md#confirmations-and-residual-declaration"""
    from concurrent.futures import ThreadPoolExecutor

    from data.vision import FAPI, perp_symbol
    listed = perp_listing()

    def one(s: str):
        p = perp_symbol(s, listed)
        if p is None:
            return s, None
        try:
            r = SESSION.get(f"{FAPI}/futures/data/openInterestHist",
                            params={"symbol": p, "period": period, "limit": min(limit, 500)}, timeout=20)
            r.raise_for_status()
            rows = r.json()
        except Exception:                                      # noqa: BLE001
            return s, None
        if not rows:
            return s, None
        return s, pd.Series({pd.Timestamp(x["timestamp"], unit="ms", tz="UTC"): float(x["sumOpenInterestValue"])
                             for x in rows})

    with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, max(1, len(symbols)))) as pool:
        got = dict(pool.map(one, symbols))
    return pd.DataFrame({s: v for s, v in got.items() if v is not None}).sort_index()
