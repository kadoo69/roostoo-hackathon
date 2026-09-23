"""Binance USD-M futures positioning: funding, open interest, taker and account ratios.

All keyless. These measure CROWDING, which is the one axis the price-covariance
work at DECISIONS.md#correlation-cap-outcome could not reach: that sweep found
no structure left in the correlation matrix, so a reweighting could not raise
effective bets above 1.32. Positioning is a different observable and is not
refuted by that null.

The REST endpoints here serve only the last 30 days of open interest and the
ratio series. That is a limit of this API, not of the data: data.binance.vision
archives the same fields at 5 minutes back to 2021-12, including delisted
contracts, and data/vision.py reads it. Use this module for live readings and
data/vision.py for anything that needs history. DECISIONS.md#positioning-history.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

FAPI = "https://fapi.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-bot"})
HIST_DAYS = {"openInterestHist": 30, "topLongShortAccountRatio": 30,
             "topLongShortPositionRatio": 30, "takerlongshortRatio": 30,
             "globalLongShortAccountRatio": 30, "fundingRate": 3650}


class FuturesError(RuntimeError):
    pass


def _get(path: str, params: dict, retries: int = 3) -> list | dict:
    for i in range(retries):
        try:
            r = SESSION.get(f"{FAPI}{path}", params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                time.sleep(2 ** i)
                continue
            raise FuturesError(f"{path}:{r.status_code}:{r.text[:120]}")
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)
    raise FuturesError(f"{path}:exhausted")


def funding(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Realised 8-hourly funding. Positive means longs pay shorts.

    Funding is the price of holding a leveraged long, so a persistently high
    rate is crowding that has already been paid for rather than sentiment.
    """
    rows = _get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["fundingTime"], unit="ms", utc=True)
    d["funding_rate"] = d["fundingRate"].astype(float)
    d["mark"] = pd.to_numeric(d.get("markPrice"), errors="coerce")
    return d[["ts", "funding_rate", "mark"]].set_index("ts").sort_index()


def open_interest(symbol: str, period: str = "4h", limit: int = 500) -> pd.DataFrame:
    """Contracts outstanding. Only the last ~30 days exist at any period."""
    rows = _get("/futures/data/openInterestHist",
                {"symbol": symbol, "period": period, "limit": min(limit, 500)})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    d["oi_base"] = d["sumOpenInterest"].astype(float)
    d["oi_usd"] = d["sumOpenInterestValue"].astype(float)
    return d[["ts", "oi_base", "oi_usd"]].set_index("ts").sort_index()


def taker_ratio(symbol: str, period: str = "4h", limit: int = 500) -> pd.DataFrame:
    """Futures taker buy/sell volume. The derivatives analogue of the spot
    aggressor share already used by signals.orderflow."""
    rows = _get("/futures/data/takerlongshortRatio",
                {"symbol": symbol, "period": period, "limit": min(limit, 500)})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    for c, s in (("taker_buy_sell", "buySellRatio"),
                 ("taker_buy_vol", "buyVol"), ("taker_sell_vol", "sellVol")):
        d[c] = d[s].astype(float)
    return d[["ts", "taker_buy_sell", "taker_buy_vol",
              "taker_sell_vol"]].set_index("ts").sort_index()


def account_ratio(symbol: str, period: str = "4h", limit: int = 500) -> pd.DataFrame:
    """Share of TOP accounts positioned long. Closest free proxy for
    where informed size sits, as distinct from where volume printed."""
    rows = _get("/futures/data/topLongShortAccountRatio",
                {"symbol": symbol, "period": period, "limit": min(limit, 500)})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    d["top_long_share"] = d["longAccount"].astype(float)
    d["top_long_short_ratio"] = d["longShortRatio"].astype(float)
    return d[["ts", "top_long_share",
              "top_long_short_ratio"]].set_index("ts").sort_index()


def crowding(symbol: str, period: str = "4h") -> dict:
    """One crowding snapshot per symbol, with every field allowed to be None.

    A missing field is reported as None rather than imputed. A crowding reading
    invented from an absent feed is worse than no reading, because a consumer
    cannot tell the difference.
    """
    out = {"symbol": symbol, "period": period}
    try:
        f = funding(symbol, limit=90)
        if len(f):
            out["funding_now"] = float(f["funding_rate"].iloc[-1])
            out["funding_mean_30d"] = float(f["funding_rate"].tail(90).mean())
            sd = float(f["funding_rate"].tail(90).std(ddof=1))
            out["funding_z"] = (round((out["funding_now"] - out["funding_mean_30d"]) / sd, 3)
                                if sd and sd == sd and sd > 0 else None)
            out["funding_ann_pct"] = round(out["funding_now"] * 3 * 365 * 100, 3)
    except Exception as exc:
        out["funding_error"] = repr(exc)[:120]
    try:
        oi = open_interest(symbol, period, limit=200)
        if len(oi) > 6:
            out["oi_usd"] = float(oi["oi_usd"].iloc[-1])
            out["oi_chg_6b_pct"] = round(float(oi["oi_usd"].iloc[-1] /
                                               oi["oi_usd"].iloc[-7] - 1) * 100, 3)
            m, s = oi["oi_usd"].mean(), oi["oi_usd"].std(ddof=1)
            out["oi_z"] = round(float((oi["oi_usd"].iloc[-1] - m) / s), 3) if s > 0 else None
    except Exception as exc:
        out["oi_error"] = repr(exc)[:120]
    try:
        t = taker_ratio(symbol, period, limit=200)
        if len(t):
            out["taker_buy_sell"] = float(t["taker_buy_sell"].iloc[-1])
    except Exception as exc:
        out["taker_error"] = repr(exc)[:120]
    try:
        a = account_ratio(symbol, period, limit=200)
        if len(a):
            out["top_long_share"] = float(a["top_long_share"].iloc[-1])
    except Exception as exc:
        out["account_error"] = repr(exc)[:120]
    return out
