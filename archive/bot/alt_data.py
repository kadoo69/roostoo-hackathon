"""Alternate-data collector: positioning and option data logged in the backtest's own definitions.

Two kinds of series live here and they must not be confused.

Deribit option open interest is a SNAPSHOT with no history anywhere, so dealer
gamma can only be collected forward. Positioning (open interest, long/short
ratios, taker ratio, funding, premium) DOES have history - the REST API keeps
30 days but data.binance.vision archives it back to 2021-12 - and every feature
below was scored against the deployed book in gates/positioning_edges.py and
failed the pre-declared rule. DECISIONS.md#positioning-edges-outcome.

So nothing here decides a trade. `positioning` computes each feature with the
exact definition the gate used, so a forward log from the competition window can
be laid next to the backtest tables without a translation step.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import threading
import time
import urllib.error
import urllib.request

FAPI = "https://fapi.binance.com"
TIMEOUT = 20


def _get(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "roostoo-hackathon-bot"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return None


def open_interest(symbol: str, period: str = "4h") -> dict | None:
    d = _get(f"{FAPI}/futures/data/openInterestHist?symbol={symbol}&period={period}&limit=30")
    if not isinstance(d, list) or len(d) < 2:
        return None
    last, prior = d[-1], d[-8] if len(d) >= 8 else d[0]
    try:
        now_v = float(last["sumOpenInterestValue"])
        then_v = float(prior["sumOpenInterestValue"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"oi_usd": round(now_v, 2),
            "oi_change_pct": round((now_v / then_v - 1.0) * 100, 3) if then_v else None,
            "bars": len(d)}


def long_short(symbol: str, period: str = "4h") -> dict | None:
    d = _get(f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol={symbol}&period={period}&limit=2")
    if not isinstance(d, list) or not d:
        return None
    try:
        return {"long_short_ratio": round(float(d[-1]["longShortRatio"]), 4)}
    except (KeyError, TypeError, ValueError):
        return None


def funding(symbol: str) -> dict | None:
    d = _get(f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}")
    if not isinstance(d, dict):
        return None
    try:
        return {"funding_rate": float(d["lastFundingRate"])}
    except (KeyError, TypeError, ValueError):
        return None


DERIBIT = "https://www.deribit.com/api/v2/public"
COINBASE = "https://api.exchange.coinbase.com"
SPOT = "https://api.binance.com"
PERP_PREFIXES = ("", "1000", "1000000", "1M")


def _series(url: str, field: str) -> list[float]:
    d = _get(url)
    if not isinstance(d, list):
        return []
    out = []
    for row in d:
        try:
            v = float(row[field]) if isinstance(row, dict) else float(row[field])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if v > 0 or field == "fundingRate" or field == 4:
            out.append(v)
    return out


def _log_change(xs: list[float], lag: int) -> float | None:
    if len(xs) <= lag or xs[-1] <= 0 or xs[-1 - lag] <= 0:
        return None
    return round(math.log(xs[-1] / xs[-1 - lag]), 6)


def funding_per_8h(perp: str, hours: int, end_ms: int | None = None) -> float | None:
    """Sum of settlements in the trailing window over (hours / 8), as gates.positioning_edges does.

    The gate's rolling window is right-closed and left-open on settlement hours,
    so a settlement exactly `hours` before `end` is excluded here too.
    """
    end = end_ms or int(time.time() * 1000)
    start = end - hours * 3_600_000 + 3_600_000
    xs = _series(f"{FAPI}/fapi/v1/fundingRate?symbol={perp}&startTime={start}&endTime={end}&limit=100",
                 "fundingRate")
    return round(sum(xs) / (hours / 8.0), 8) if xs else None


def perp_for(spot: str, listed: set[str]) -> str | None:
    for p in PERP_PREFIXES:
        if p + spot in listed:
            return p + spot
    return None


def listed_perps() -> set[str]:
    d = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    if not isinstance(d, dict):
        return set()
    return {x["symbol"] for x in d.get("symbols", []) if x.get("contractType") == "PERPETUAL"}


def hour_end_taker(perp: str, end_ms: int | None = None) -> list[float]:
    """The 5-minute taker ratio whose bucket ENDS on each hour, last 24 hours.

    REST `period=1h` returns an hourly aggregate, which is not what the archive
    holds and not what the gate scored. The archive's hourly value is the 5-minute
    bucket stamped :55, so that is what is taken here, and only buckets that have
    finished by `end_ms`.
    """
    end = end_ms or int(time.time() * 1000)
    d = _get(f"{FAPI}/futures/data/takerlongshortRatio?symbol={perp}&period=5m&limit=320&endTime={end}")
    if not isinstance(d, list):
        return []
    out = []
    for row in d:
        try:
            t, v = int(row["timestamp"]), float(row["buySellRatio"])
        except (KeyError, TypeError, ValueError):
            continue
        if (t // 60_000) % 60 == 55 and t + 300_000 <= end and v > 0:
            out.append(v)
    return out[-24:]


def positioning(perp: str, end_ms: int | None = None) -> dict:
    """Per-coin features, named and defined exactly as config/positioning_edges.yaml features.per_coin.

    `end_ms` pins the reading to a past hour so tests/test_positioning.py can check
    parity against the archive; live calls leave it unset.
    """
    base = f"{FAPI}/futures/data"
    e = f"&endTime={end_ms}" if end_ms else ""
    oi = _series(f"{base}/openInterestHist?symbol={perp}&period=1h&limit=80{e}", "sumOpenInterestValue")
    top = _series(f"{base}/topLongShortPositionRatio?symbol={perp}&period=1h&limit=26{e}", "longShortRatio")
    glo = _series(f"{base}/globalLongShortAccountRatio?symbol={perp}&period=1h&limit=26{e}", "longShortRatio")
    tak = hour_end_taker(perp, end_ms)
    kl = f"&endTime={end_ms - 1}" if end_ms else ""
    prem = _series(f"{FAPI}/fapi/v1/premiumIndexKlines?symbol={perp}&interval=1h&limit=25{kl}", 4)
    prem = prem[-24:] if end_ms else prem[:-1]
    tv = _log_change(top, 24)
    gv = _log_change(glo, 24)
    return {"perp": perp,
            "oi_usd": round(oi[-1], 2) if oi else None,
            "oi_chg_24h": _log_change(oi, 24),
            "oi_chg_3d": _log_change(oi, 72),
            "funding_3d": funding_per_8h(perp, 72, end_ms),
            "premium_24h": round(sum(prem) / len(prem), 8) if len(prem) >= 20 else None,
            "top_vs_global_24h": round(tv - gv, 6) if tv is not None and gv is not None else None,
            "taker_ls_24h": (round(sum(math.log(x) for x in tak) / len(tak), 6)
                             if len(tak) >= 20 else None)}


def market() -> dict:
    """Market features, as config/positioning_edges.yaml features.market, minus the 180-day z-scores.

    The z-scores need six months of history the REST API does not keep; they are
    recomputed offline from the archive, so only their raw inputs are logged here.
    """
    oi = {c: _series(f"{FAPI}/futures/data/openInterestHist?symbol={c}&period=1h&limit=200",
                     "sumOpenInterestValue") for c in ("BTCUSDT", "ETHUSDT")}
    agg = None
    if all(len(v) > 168 for v in oi.values()):
        now_v = oi["BTCUSDT"][-1] + oi["ETHUSDT"][-1]
        then_v = oi["BTCUSDT"][-169] + oi["ETHUSDT"][-169]
        agg = round(math.log(now_v / then_v), 6) if then_v > 0 else None
    fs = [funding_per_8h(c, 168) for c in ("BTCUSDT", "ETHUSDT")]
    out = {"agg_oi_chg_7d": agg,
           "agg_funding_7d": round(sum(fs) / 2, 8) if all(f is not None for f in fs) else None}
    end = int(time.time() * 1000)
    dv = _get(f"{DERIBIT}/get_volatility_index_data?currency=BTC&resolution=3600"
              f"&start_timestamp={end - 80 * 3_600_000}&end_timestamp={end}")
    rows = (dv or {}).get("result", {}).get("data", []) if isinstance(dv, dict) else []
    if rows:
        out["dvol_btc"] = float(rows[-1][4])
        out["dvol_chg_3d"] = round(float(rows[-1][4]) - float(rows[-73][4]), 3) if len(rows) >= 73 else None
    cb = _get(f"{COINBASE}/products/BTC-USD/ticker")
    bn = _get(f"{SPOT}/api/v3/ticker/price?symbol=BTCUSDT")
    try:
        c, b = float(cb["price"]), float(bn["price"])
        out["cb_premium"] = round((c - b) / b, 6)
    except (TypeError, KeyError, ValueError):
        out["cb_premium"] = None
    return out


class Collector:
    """Throttled snapshot collector that never blocks or raises into the trading loop.

    One collection makes about six HTTP calls per symbol plus the market reads,
    each with a 20-second timeout, so a slow venue could stall a cycle for
    minutes. Collection therefore runs on a daemon thread; `collect` starts one
    when due and returns the newest FINISHED snapshot exactly once, so the bot
    journals every snapshot and never waits for one.
    """

    def __init__(self, cfg: dict):
        self.enabled = bool(cfg.get("enabled"))
        self.every = float(cfg.get("refresh_seconds", 900))
        self.currencies = tuple(
            (cfg.get("sources", {}).get("deribit_gex", {}) or {}).get("currencies", ("BTC",)))
        self.last = 0.0
        self.latest: dict = {}
        self.perps: set[str] = set()
        self._ready: dict | None = None
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def due(self) -> bool:
        return self.enabled and (time.time() - self.last) >= self.every

    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def collect(self, symbols: list[str]) -> dict | None:
        if self.due() and not self.busy():
            self.last = time.time()
            self._worker = threading.Thread(target=self._run, args=(list(symbols),), daemon=True)
            self._worker.start()
        with self._lock:
            out, self._ready = self._ready, None
        return out

    def _run(self, symbols: list[str]) -> None:
        try:
            snap = self.snapshot(symbols)
        except Exception as err:
            snap = {"utc": dt.datetime.now(dt.UTC).isoformat(), "error": repr(err)[:200]}
        with self._lock:
            self._ready = snap
            self.latest = snap

    def snapshot(self, symbols: list[str]) -> dict:
        snap = {"utc": dt.datetime.now(dt.UTC).isoformat(), "gex": {}, "perp": {}}
        try:
            from archive.data import options
            for c in self.currencies:
                try:
                    e = options.exposure(c)
                    snap["gex"][c] = {k: e.get(k) for k in
                                      ("spot", "net_gex_usd_per_1pct", "net_gex_ratio",
                                       "gamma_flip_strike", "spot_above_flip", "regime",
                                       "instruments_used")}
                except options.OptionsError as err:
                    snap["gex"][c] = {"error": str(err)[:120]}
        except ImportError as err:
            snap["gex"] = {"error": str(err)[:120]}
        if not self.perps:
            self.perps = listed_perps()
        for s in symbols[:12]:
            p = perp_for(s, self.perps)
            snap["perp"][s] = positioning(p) if p else {"perp": None}
        snap["market"] = market()
        return snap
