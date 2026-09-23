"""Market-level series with real history: implied volatility, stablecoin supply, US spot premium.

Each is a single market-wide reading, never a per-coin selector, and each is
stamped at the moment it became knowable so an as-of join cannot leak.

    dvol              Deribit DVOL, 30-day implied vol index for BTC and ETH, hourly from 2021-03
    stablecoin_supply DefiLlama total circulating USD stablecoins, daily from 2017
    coinbase_premium  Coinbase BTC-USD over Binance BTCUSDT, hourly, the US-buyer demand proxy

DECISIONS.md#positioning-history.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from core.config import ROOT

CACHE = ROOT / "data" / "cache" / "macro"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-research"})


def _json(url: str, params: dict | None = None, retries: int = 5):
    for i in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429, 500, 502, 503):
                time.sleep(2.0 * (i + 1))
                continue
            raise RuntimeError(f"{url}:{r.status_code}:{r.text[:120]}")
        except requests.RequestException:
            time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"{url}:exhausted")


def dvol(currency: str = "BTC", start: str = "2021-03-01") -> pd.Series:
    """Hourly DVOL close, stamped at the hour's CLOSE."""
    end_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows, cur = [], end_ms
    while cur > start_ms:
        res = _json("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                    {"currency": currency, "start_timestamp": start_ms,
                     "end_timestamp": cur, "resolution": 3600})["result"]
        if not res["data"]:
            break
        rows.extend(res["data"])
        nxt = res.get("continuation")
        if not nxt or nxt >= cur:
            break
        cur = nxt
    d = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close"]).drop_duplicates("t")
    s = pd.Series(d["close"].astype(float).to_numpy(),
                  index=pd.to_datetime(d["t"], unit="ms", utc=True) + pd.Timedelta(hours=1))
    s = s.sort_index().rename(f"dvol_{currency.lower()}")
    CACHE.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(CACHE / f"dvol_{currency.lower()}.parquet")
    return s


def stablecoin_supply() -> pd.Series:
    """Daily total, stamped at the END of the UTC day it describes."""
    rows = _json("https://stablecoins.llama.fi/stablecoincharts/all")
    s = pd.Series({pd.Timestamp(int(r["date"]), unit="s", tz="UTC") + pd.Timedelta(days=1):
                   float(r["totalCirculatingUSD"].get("peggedUSD", 0.0)) for r in rows})
    s = s.sort_index().rename("stable_usd")
    CACHE.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(CACHE / "stablecoin_supply.parquet")
    return s


def coinbase_hourly(product: str = "BTC-USD", start: str = "2021-01-01") -> pd.Series:
    """Hourly close, stamped at CLOSE. Coinbase serves 300 bars per call."""
    t0 = pd.Timestamp(start, tz="UTC")
    now = pd.Timestamp.now(tz="UTC").floor("1h")
    rows = []
    while t0 < now:
        t1 = min(t0 + pd.Timedelta(hours=300), now)
        batch = _json(f"https://api.exchange.coinbase.com/products/{product}/candles",
                      {"granularity": 3600, "start": t0.isoformat(), "end": t1.isoformat()})
        rows.extend(batch)
        t0 = t1
        time.sleep(0.12)
    d = pd.DataFrame(rows, columns=["t", "low", "high", "open", "close", "volume"]).drop_duplicates("t")
    return pd.Series(d["close"].astype(float).to_numpy(),
                     index=pd.to_datetime(d["t"], unit="s", utc=True) + pd.Timedelta(hours=1)).sort_index()


def coinbase_premium(binance_hourly_close: pd.Series) -> pd.Series:
    """(Coinbase USD - Binance USDT) / Binance, on CLOSE-stamped hourly bars.

    USDT's own drift against USD sits inside this number. It is a level shift
    that a z-score over a trailing window removes; the raw level is not read.
    """
    cb = coinbase_hourly()
    bn = binance_hourly_close.copy()
    j = pd.concat([cb.rename("cb"), bn.rename("bn")], axis=1, join="inner").dropna()
    s = ((j["cb"] - j["bn"]) / j["bn"]).rename("cb_premium")
    CACHE.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(CACHE / "coinbase_premium.parquet")
    return s


def etf_flows() -> pd.Series:
    """Daily net flow across US spot Bitcoin ETFs, from TFTC's published dataset.

    Stamped when it is KNOWN, not when it happened: issuers report a session's
    creations after the US close and aggregators publish overnight, so session d is
    stamped at 14:00 UTC on d+1, the next US pre-open. Weekends and holidays have
    no session and no row.
    """
    d = _json("https://www.tftc.io/bitcoin-etf-flows/data.json")
    rows = {pd.Timestamp(r["date"], tz="UTC") + pd.Timedelta(days=1, hours=14): float(r["netFlowUsd"])
            for r in d["days"] if r.get("netFlowUsd") is not None}
    s = pd.Series(rows).sort_index().rename("etf_net_flow_usd")
    CACHE.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(CACHE / "etf_flows.parquet")
    return s


def load(name: str) -> pd.Series:
    return pd.read_parquet(CACHE / f"{name}.parquet").iloc[:, 0]
