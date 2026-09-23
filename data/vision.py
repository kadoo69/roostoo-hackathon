"""Historical Binance USD-M positioning from data.binance.vision, which the REST API does not serve.

The REST endpoints for open interest and long/short ratios keep about 30 days.
The bulk archive keeps the same fields at 5-minute resolution back to 2021-12,
including delisted contracts, which is what makes positioning backtestable here.
DECISIONS.md#positioning-history.

Three datasets, each stored as one hourly parquet per perpetual:

    metrics    open interest, top-trader and all-account long/short, taker vol ratio
    funding    realised funding, snapped to the hour it settled
    premium    hourly premium index klines, the perp's premium over the index

Spot names map to perps through `perp_symbol`, because meme contracts list as
`1000PEPEUSDT` and friends. The earlier funding panel was keyed on spot names
and silently had no row for any of those.
"""
from __future__ import annotations

import datetime as dt
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from core.config import ROOT

BASE = "https://data.binance.vision/data/futures/um"
FAPI = "https://fapi.binance.com"
CACHE = ROOT / "data" / "cache" / "vision"
METRICS_START = dt.date(2021, 12, 1)
PREFIXES = ("", "1000", "1000000", "1M")
METRIC_COLS = {"sum_open_interest_value": "oi_usd",
               "count_toptrader_long_short_ratio": "top_account_ls",
               "sum_toptrader_long_short_ratio": "top_position_ls",
               "count_long_short_ratio": "global_account_ls",
               "sum_taker_long_short_vol_ratio": "taker_ls"}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-research"})


def perp_symbol(spot: str, listed: set[str]) -> str | None:
    for p in PREFIXES:
        if p + spot in listed:
            return p + spot
    return None


def _rest(path: str, params: dict, retries: int = 5):
    for i in range(retries):
        try:
            r = SESSION.get(f"{FAPI}{path}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2.0 * (i + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (418, 429, 500, 502, 503, 504):
            time.sleep(2.0 * (i + 1))
            continue
        return None
    raise RuntimeError(f"rest_fetch_failed:{path}:{params.get('symbol')}")


def listed_perps() -> set[str]:
    info = SESSION.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=30).json()
    return {s["symbol"] for s in info["symbols"] if s.get("contractType") == "PERPETUAL"}


def _zip_csv(url: str, retries: int = 4) -> pd.DataFrame | None:
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(1.5 * (i + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            time.sleep(1.5 * (i + 1))
            continue
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(z.namelist()[0]) as fh:
                raw = fh.read()
        first = raw.split(b"\n", 1)[0]
        header = 0 if any(c.isalpha() for c in first.decode(errors="ignore")) else None
        return pd.read_csv(io.BytesIO(raw), header=header)
    raise RuntimeError(f"vision_fetch_failed:{url}")


def _months(start: dt.date, end: dt.date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _metrics_day(perp: str, day: dt.date) -> pd.DataFrame | None:
    d = _zip_csv(f"{BASE}/daily/metrics/{perp}/{perp}-metrics-{day:%Y-%m-%d}.zip")
    if d is None or d.empty:
        return None
    d["ts"] = pd.to_datetime(d["create_time"], utc=True)
    keep = d.set_index("ts")[list(METRIC_COLS)].rename(columns=METRIC_COLS)
    return keep.apply(pd.to_numeric, errors="coerce")


def hourly_last(raw: pd.DataFrame) -> pd.DataFrame:
    return raw.sort_index().resample("1h", label="right", closed="left").last().dropna(how="all")


def metrics(perp: str, end: dt.date, workers: int = 16) -> pd.DataFrame:
    """Hourly, stamped at the END of the hour: the last reading CREATED strictly before it.

    The bucket is [13:00, 14:00) and it is stamped 14:00, so the 13:55 row is
    what a bar closing at 14:00 sees and the 14:00 row is not. Two reasons, both
    measured against the REST API on 2026-09-21: the taker ratio's create_time is
    the START of a 5-minute volume bucket, so the row created at 14:00 covers
    14:00-14:05 and is five minutes of future flow; and the REST series stamped
    14:00 for open interest and both long/short ratios equals the archive row
    created at 13:55. A right-closed bucket leaked the first and misaligned the
    rest. DECISIONS.md#positioning-history.
    """
    path = CACHE / "metrics" / f"{perp}.parquet"
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if len(old) and old.attrs.get("bucket") != "left_closed":
        old = pd.DataFrame()
    start = METRICS_START if old.empty else (old.index.max() - pd.Timedelta(hours=1)).date()
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        parts = [p for p in ex.map(lambda d: _metrics_day(perp, d), days) if p is not None]
    if not parts and old.empty:
        return old
    raw = pd.concat(parts).sort_index() if parts else pd.DataFrame()
    fresh = hourly_last(raw) if len(raw) else raw
    out = pd.concat([old, fresh])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.attrs["bucket"] = "left_closed"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path)
    return out


def funding(perp: str, end: dt.date) -> pd.DataFrame:
    """Realised funding snapped DOWN to the hour it settled, so millisecond
    jitter on `calc_time` cannot break an as-of join."""
    path = CACHE / "funding" / f"{perp}.parquet"
    parts = []
    for m in _months(dt.date(2020, 1, 1), end):
        d = _zip_csv(f"{BASE}/monthly/fundingRate/{perp}/{perp}-fundingRate-{m}.zip")
        if d is None or d.empty:
            continue
        if "calc_time" not in d.columns:
            d.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][:len(d.columns)]
        d["ts"] = pd.to_datetime(d["calc_time"], unit="ms", utc=True).dt.floor("1h")
        parts.append(d.set_index("ts")[["last_funding_rate"]].rename(
            columns={"last_funding_rate": "funding"}).astype(float))
    tail = _funding_rest(perp, parts[-1].index.max() if parts else None)
    if tail is not None:
        parts.append(tail)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path)
    return out


def _funding_rest(perp: str, after) -> pd.DataFrame | None:
    params = {"symbol": perp, "limit": 1000}
    if after is not None:
        params["startTime"] = int(after.timestamp() * 1000) + 1
    rows = _rest("/fapi/v1/fundingRate", params)
    if not rows:
        return None
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["fundingTime"], unit="ms", utc=True).dt.floor("1h")
    return d.set_index("ts")[["fundingRate"]].rename(columns={"fundingRate": "funding"}).astype(float)


def premium(perp: str, end: dt.date) -> pd.DataFrame:
    """Hourly premium index close, stamped at the bar's CLOSE time, not its open."""
    path = CACHE / "premium" / f"{perp}.parquet"
    parts = []
    for m in _months(dt.date(2020, 1, 1), end):
        d = _zip_csv(f"{BASE}/monthly/premiumIndexKlines/{perp}/1h/{perp}-1h-{m}.zip")
        if d is None or d.empty:
            continue
        d = d.iloc[:, :5]
        d.columns = ["open_time", "open", "high", "low", "close"]
        d = d[pd.to_numeric(d["open_time"], errors="coerce").notna()]
        d["ts"] = pd.to_datetime(d["open_time"].astype("int64"), unit="ms", utc=True) + pd.Timedelta(hours=1)
        parts.append(d.set_index("ts")[["close"]].rename(columns={"close": "premium"}).astype(float))
    tail = _premium_rest(perp, parts[-1].index.max() if parts else None)
    if tail is not None:
        parts.append(tail)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path)
    return out


def _premium_rest(perp: str, after) -> pd.DataFrame | None:
    """The archive publishes a month only after it ends; the REST endpoint fills the gap."""
    rows, start = [], int(after.timestamp() * 1000) if after is not None else None
    while True:
        params = {"symbol": perp, "interval": "1h", "limit": 1500}
        if start is not None:
            params["startTime"] = start
        batch = _rest("/fapi/v1/premiumIndexKlines", params)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1500 or start is None:
            break
        start = int(batch[-1][0]) + 3_600_000
    if not rows:
        return None
    d = pd.DataFrame([r[:5] for r in rows], columns=["open_time", "open", "high", "low", "close"])
    d["ts"] = pd.to_datetime(d["open_time"].astype("int64"), unit="ms", utc=True) + pd.Timedelta(hours=1)
    now = pd.Timestamp.now(tz="UTC")
    d = d[d["ts"] <= now]
    return d.set_index("ts")[["close"]].rename(columns={"close": "premium"}).astype(float)


def panel(dataset: str, field: str, spots: list[str], perp_map: dict[str, str]) -> pd.DataFrame:
    """Wide hourly frame keyed by SPOT name, so it joins straight onto the price panel.

    The archive writes 0.0 where no reading was recorded (BTC and ETH open
    interest read zero for hours on 2022-03-07). Every metrics field is a level
    or a ratio of positives, so a non-positive value is missing, never a reading;
    left in, its log is -inf and it poisons every rolling z-score downstream.
    """
    cols = {}
    for s in spots:
        p = perp_map.get(s)
        f = CACHE / dataset / f"{p}.parquet" if p else None
        if f is None or not f.exists():
            continue
        d = pd.read_parquet(f)
        if field in d.columns:
            cols[s] = d[field].where(d[field] > 0) if dataset == "metrics" else d[field]
    return pd.DataFrame(cols).sort_index()


def asof(hourly: pd.DataFrame, bar_close: pd.DatetimeIndex, max_age_hours: float) -> pd.DataFrame:
    """Last value known at each bar CLOSE, and nothing older than `max_age_hours`.

    Binance bars are labelled by OPEN time; pass the CLOSE times here. This is
    the join the funding panel needed and did not have.
    """
    h = hourly.sort_index()
    stamp = pd.DataFrame(h.index.to_numpy(), index=h.index, columns=["_t"])
    idx = pd.DatetimeIndex(bar_close)
    val = h.reindex(h.index.union(idx)).ffill().reindex(idx)
    age = stamp.reindex(stamp.index.union(idx)).ffill().reindex(idx)["_t"]
    stale = (idx.to_series() - pd.to_datetime(age)).dt.total_seconds().to_numpy() / 3600 > max_age_hours
    val[stale] = float("nan")
    return val


def build(spots: list[str], end: dt.date | None = None, datasets=("metrics", "funding", "premium")) -> dict:
    end = end or (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1))
    listed = listed_perps()
    pmap = {s: perp_symbol(s, listed) for s in spots}
    report = {}
    for s, p in pmap.items():
        if p is None:
            report[s] = "no_perp"
            continue
        row = {}
        for ds in datasets:
            fn = {"metrics": metrics, "funding": funding, "premium": premium}[ds]
            d = fn(p, end)
            row[ds] = (str(d.index.min()), str(d.index.max()), len(d)) if len(d) else None
        report[s] = row
        print(s, p, row, flush=True)
    (CACHE / "perp_map.json").parent.mkdir(parents=True, exist_ok=True)
    pd.Series(pmap).to_json(CACHE / "perp_map.json")
    return report


if __name__ == "__main__":
    import sys

    from data import universe as ru
    names = sys.argv[1:] or sorted(ru.tradable_symbols())
    build(names)
