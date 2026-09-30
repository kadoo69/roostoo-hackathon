"""Point-in-time features for source research, separate from execution bots.

Historical features use only readings available at the 4h decision CLOSE.
Forward snapshots are stamped when fetched, not backdated to their vendor's
period label. Missing readings remain missing; no source is silently imputed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import CACHE, ROOT
from data import macro, vision
from data.hyperliquid import DEFAULT_COINS, OUT as HYPER_FUNDING

FOUR_HOURS = pd.Timedelta(hours=4)
FORWARD_OUT = ROOT / "results" / "source_features_forward.parquet"


def window_at(series: pd.Series, grid: pd.DatetimeIndex, hours: int,
              minimum: int, max_age_hours: int, mean: bool = False) -> pd.Series:
    """Window ending at each decision, using exact vendor timestamps.

    Values stamped even one millisecond after a decision are unavailable. A
    short gap may be tolerated, but stale latest readings return NaN.
    """
    s = series.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = np.full(len(grid), np.nan)
    if s.empty:
        return pd.Series(out, index=grid)
    ticks = s.index.asi8
    g = grid.asi8
    right = np.searchsorted(ticks, g, side="right")
    left = np.searchsorted(ticks, g - pd.Timedelta(hours=hours).value, side="right")
    values = s.to_numpy(dtype=float)
    cumul = np.r_[0.0, np.cumsum(values)]
    counts = right - left
    last = np.maximum(right - 1, 0)
    age = g - ticks[last]
    good = (counts >= minimum) & (right > 0) & (age <= pd.Timedelta(hours=max_age_hours).value)
    out[good] = (cumul[right[good]] - cumul[left[good]]) / (counts[good] if mean else 1)
    return pd.Series(out, index=grid)


def asof(series: pd.Series, grid: pd.DatetimeIndex, max_age_hours: int) -> pd.Series:
    s = series.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(grid, method="ffill", tolerance=pd.Timedelta(hours=max_age_hours))


def historical(grid: pd.DatetimeIndex, symbols: list[str]) -> dict[str, pd.DataFrame | pd.Series]:
    """Hyperliquid and Binance perps plus already-cached market-wide context."""
    if grid.tz is None:
        raise ValueError("decision grid must be timezone-aware UTC")
    grid = grid.tz_convert("UTC")
    names = [s for s in symbols if s.endswith("USDT") and s[:-4] in DEFAULT_COINS]
    pmap = json.loads((vision.CACHE / "perp_map.json").read_text())
    bn_fund = vision.panel("funding", "funding", names, pmap)
    bn_prem = vision.panel("premium", "premium", names, pmap)
    fields = {k: pd.DataFrame(index=grid, columns=symbols, dtype=float) for k in
              ("hl_funding_3d", "bn_funding_3d", "funding_diff_3d",
               "hl_premium_24h", "bn_premium_24h", "premium_diff_24h")}
    for sym in names:
        coin = sym[:-4]
        path = HYPER_FUNDING / f"{coin}.parquet"
        if not path.exists():
            continue
        hl = pd.read_parquet(path).sort_index()
        hf = window_at(hl["funding_rate"], grid, 72, 60, 2) / 9.0
        hp = window_at(hl["premium"], grid, 24, 20, 2, mean=True)
        bf = window_at(bn_fund[sym], grid, 72, 7, 9) / 9.0 if sym in bn_fund else pd.Series(np.nan, index=grid)
        bp = window_at(bn_prem[sym], grid, 24, 20, 2, mean=True) if sym in bn_prem else pd.Series(np.nan, index=grid)
        fields["hl_funding_3d"][sym] = hf
        fields["bn_funding_3d"][sym] = bf
        fields["funding_diff_3d"][sym] = hf - bf
        fields["hl_premium_24h"][sym] = hp
        fields["bn_premium_24h"][sym] = bp
        fields["premium_diff_24h"][sym] = hp - bp
    st = macro.load("stablecoin_supply")
    for days in (7, 30):
        impulse = np.log(st / st.shift(days))
        fields[f"stable_impulse_{days}d"] = asof(impulse, grid, 48)
    dv = macro.load("dvol_btc")
    fields["dvol_btc"] = asof(dv, grid, 3)
    return fields


def _jsonl(pattern: str) -> list[dict]:
    rows = []
    for path in sorted(ROOT.glob(pattern)):
        with path.open() as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _lagged(group: pd.DataFrame, column: str, hours: int,
            tolerance_hours: int = 1) -> pd.Series:
    """Last sample at or before t-hours; reject a gap beyond tolerance."""
    t = pd.DatetimeIndex(group["available_at"])
    target = t - pd.Timedelta(hours=hours)
    loc = t.get_indexer(target, method="pad", tolerance=pd.Timedelta(hours=tolerance_hours))
    value = pd.to_numeric(group[column], errors="coerce").to_numpy(dtype=float)
    old = np.full(len(group), np.nan)
    valid = loc >= 0
    old[valid] = value[loc[valid]]
    return pd.Series(old, index=group.index)


def forward() -> pd.DataFrame:
    """Tidy, availability-stamped observations for forward-only data.

    Each row is one source/symbol/sample. It can later be joined to order or
    return outcomes by an as-of join on ``available_at`` with a freshness cap.
    """
    rows = []
    for sample in _jsonl("live/source_hub/observations-*.jsonl"):
        for source, rec in sample.get("sources", {}).items():
            if source == "DefiLlama" or rec.get("status") != "ok":
                continue  # DefiLlama and Stablecoin data are one upstream read
            ts = rec.get("fetched_at")
            if not ts:
                continue
            if source == "Hyperliquid":
                for coin, values in rec.get("coins", {}).items():
                    rows.append({"available_at": ts, "source": source, "symbol": coin + "USDT",
                                 "source_time": rec.get("source_time"),
                                 "funding_hourly": values.get("funding_hourly"),
                                 "oi_usd": values.get("open_interest_usd"),
                                 "premium": values.get("premium"),
                                 "volume_24h_usd": values.get("volume_24h_usd")})
            elif source == "Deribit options":
                for coin, values in rec.get("coins", {}).items():
                    if "error" in values:
                        continue
                    spot, flip = values.get("spot"), values.get("gamma_flip_strike")
                    rows.append({"available_at": ts, "source": source, "symbol": coin + "USDT",
                                 "source_time": rec.get("source_time"),
                                 "gex_ratio": values.get("net_gex_ratio"),
                                 "gex_usd_per_1pct": values.get("net_gex_usd_per_1pct"),
                                 "flip_distance_pct": 100 * (spot / flip - 1) if spot and flip else None})
            elif source == "Stablecoin data":
                rows.append({"available_at": ts, "source": source, "symbol": "MARKET",
                             "source_time": rec.get("source_time"),
                             "stable_supply_usd": rec.get("total_usd"),
                             "stable_change_7d_pct": rec.get("change_7d_pct")})
    for sample in _jsonl("live/scanner/enriched-*.jsonl"):
        ts = sample.get("ts_utc")
        for symbol, raw in sample.get("enriched", {}).items():
            c, b, t = (raw.get(k) or {} for k in ("crowding", "book", "trades"))
            rows.append({"available_at": ts, "source": "Binance scanner", "symbol": symbol,
                         "source_time": ts,
                         "funding_z": c.get("funding_z"), "oi_z": c.get("oi_z"),
                         "taker_buy_sell": c.get("taker_buy_sell"),
                         "book_imbalance": b.get("imbalance"), "spread_bps": b.get("spread_bps"),
                         "depth_10bps_usd": b.get("depth_10bps_usd"),
                         "top5pct_notional_share": t.get("top5pct_notional_share"),
                         "big_trade_aggressor": t.get("big_trade_aggressor")})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["available_at"] = pd.to_datetime(out["available_at"], utc=True, format="ISO8601")
    out["source_time"] = pd.to_datetime(out["source_time"], utc=True, format="ISO8601")
    out = out.drop_duplicates(["available_at", "source", "symbol"], keep="last")
    out = out.sort_values(["source", "symbol", "available_at"]).reset_index(drop=True)
    out["feature_version"] = 1
    out["oi_log_change_24h"] = np.nan
    out["gex_ratio_change_24h"] = np.nan
    for (source, _symbol), group in out.groupby(["source", "symbol"], sort=False):
        if source == "Hyperliquid":
            old = _lagged(group, "oi_usd", 24)
            current = pd.to_numeric(group["oi_usd"], errors="coerce")
            out.loc[group.index, "oi_log_change_24h"] = np.log(current.where(current > 0) /
                                                                 old.where(old > 0))
        elif source == "Deribit options":
            old = _lagged(group, "gex_ratio", 24)
            out.loc[group.index, "gex_ratio_change_24h"] = (
                pd.to_numeric(group["gex_ratio"], errors="coerce") - old)
    def numeric(name: str) -> pd.Series:
        return pd.to_numeric(out.get(name, pd.Series(np.nan, index=out.index)), errors="coerce")

    out["large_trade_pressure"] = numeric("top5pct_notional_share") * numeric("big_trade_aggressor")
    out["book_flow_interaction"] = numeric("book_imbalance") * (numeric("taker_buy_sell") - 1.0)
    return out.sort_values("available_at")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forward", action="store_true", help="materialise current forward snapshots")
    args = ap.parse_args()
    if not args.forward:
        ap.error("pass --forward; historical features are used by source_edges.py")
    out = forward()
    FORWARD_OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(FORWARD_OUT, index=False)
    print(f"{len(out)} observations -> {FORWARD_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
