"""Forward labels for source snapshots. Observational research; no bot imports this.

Feature availability, price entry, and outcome are separate timestamps. A label
is written only after its target hourly bar has closed. Price cache is append
only by timestamp so daily runs can retain data beyond the REST window.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np
import pandas as pd
import yaml

from bot.feed import closed_bars
from core.config import CACHE, ROOT
from ml_research.source_features import forward

CONFIG = ROOT / "config" / "source_forward_validation.yaml"
PRICE_DIR = CACHE / "source_forward_prices"
OUT = ROOT / "results" / "source_forward_outcomes.parquet"
REPORT = ROOT / "results" / "source_forward_validation.json"
SHORT_OUT = ROOT / "results" / "source_short_outcomes.parquet"
SHORT_REPORT = ROOT / "results" / "source_short_validation.json"
HOUR = pd.Timedelta(hours=1)


def collect_prices(symbols: list[str], *, fetch: bool = True) -> tuple[dict[str, pd.Series], dict[str, str]]:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    out, errors = {}, {}
    for symbol in sorted(set(symbols)):
        path = PRICE_DIR / f"{symbol}.parquet"
        cached = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if fetch:
            try:
                bars = closed_bars(symbol, "1h", limit=1000)
                fresh = bars[["close_time", "close"]].copy()
                fresh["close"] = pd.to_numeric(fresh["close"], errors="coerce")
                cached = pd.concat([cached, fresh], ignore_index=True)
                cached["close_time"] = pd.to_datetime(cached["close_time"], utc=True)
                cached = (cached.dropna().drop_duplicates("close_time", keep="last")
                          .sort_values("close_time"))
                cached.to_parquet(path, index=False)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        if not cached.empty:
            cached["close_time"] = pd.to_datetime(cached["close_time"], utc=True)
            out[symbol] = (cached.drop_duplicates("close_time", keep="last")
                           .set_index("close_time")["close"].sort_index())
    return out, errors


def label_samples(features: pd.DataFrame, prices: dict[str, pd.Series],
                  now: pd.Timestamp, horizons: tuple[int, ...] = (24, 72),
                  sample_freq: str = "1D") -> pd.DataFrame:
    """One earliest sample per source/symbol/bucket; no incomplete future labels."""
    if features.empty:
        return pd.DataFrame()
    f = features.copy()
    f["available_at"] = pd.to_datetime(f["available_at"], utc=True)
    f["price_symbol"] = f["symbol"].replace({"MARKET": "BTCUSDT"})
    f["sample_day"] = f["available_at"].dt.floor("D")
    f["sample_bucket"] = f["available_at"].dt.floor(sample_freq)
    f = (f.sort_values("available_at")
         .drop_duplicates(["source", "symbol", "sample_bucket"], keep="first"))
    for horizon in horizons:
        f[f"entry_at_{horizon}h"] = pd.Series(pd.NaT, index=f.index, dtype="datetime64[ns, UTC]")
        f[f"outcome_at_{horizon}h"] = pd.Series(pd.NaT, index=f.index, dtype="datetime64[ns, UTC]")
        f[f"return_{horizon}h"] = np.nan
    now = pd.Timestamp(now).tz_convert("UTC")
    for symbol, group in f.groupby("price_symbol"):
        series = prices.get(symbol)
        if series is None or series.empty:
            continue
        series = series.dropna().sort_index()
        ix = series.index
        for row_id, row in group.iterrows():
            pos = ix.searchsorted(row["available_at"], side="right")
            if pos == len(ix):
                continue
            entry_at = ix[pos]
            if entry_at > now:
                continue
            for horizon in horizons:
                if horizon == 72 and row["sample_day"].dayofyear % 3 != 0:
                    continue
                if sample_freq == "1h" and horizon == 4 and row["sample_bucket"].hour % 4 != 0:
                    continue
                target = entry_at + horizon * HOUR
                if target > now:
                    continue
                target_pos = ix.searchsorted(target, side="left")
                if target_pos == len(ix) or ix[target_pos] != target:
                    continue
                f.at[row_id, f"entry_at_{horizon}h"] = entry_at
                f.at[row_id, f"outcome_at_{horizon}h"] = target
                f.at[row_id, f"return_{horizon}h"] = float(series.iloc[target_pos] / series.iloc[pos] - 1)
    for horizon in horizons:
        f[f"entry_at_{horizon}h"] = pd.to_datetime(f[f"entry_at_{horizon}h"], utc=True)
        f[f"outcome_at_{horizon}h"] = pd.to_datetime(f[f"outcome_at_{horizon}h"], utc=True)
    return f.reset_index(drop=True)


def summarize(labels: pd.DataFrame, cfg: dict, errors: dict[str, str],
              horizons: tuple[int, ...] | None = None) -> dict:
    horizons = horizons or tuple(cfg["meta"]["horizons_hours"])
    result = {"generated_at": dt.datetime.now(dt.UTC).isoformat(),
              "declaration": str(CONFIG.relative_to(ROOT)), "price_errors": errors,
              "sources": {}, "feature_checks": [], "promotable": False}
    if labels.empty:
        return result
    exploratory_days = cfg["meta"]["exploratory_min_distinct_days"]
    promotion_days = cfg["meta"]["promotion_min_distinct_days"]
    for source, group in labels.groupby("source"):
        observed_hours = pd.DatetimeIndex(group["available_at"].dt.floor("h").unique()).sort_values()
        span_hours = int((observed_hours[-1] - observed_hours[0]) / HOUR) + 1
        max_gap = float((observed_hours[1:] - observed_hours[:-1]).max() / HOUR) if len(observed_hours) > 1 else 0.0
        result["sources"][source] = {"observations": len(group),
            "days": group["sample_day"].nunique(),
            "observed_hours": len(observed_hours),
            "hour_coverage_fraction": round(len(observed_hours) / span_hours, 3),
            "max_observation_gap_hours": round(max_gap, 1),
            **{f"matured_{h}h": int(group[f"return_{h}h"].notna().sum())
               for h in horizons}}
    feature_map = {"Hyperliquid": cfg["features"]["hyperliquid"],
                   "Deribit options": cfg["features"]["deribit_options"],
                   "Binance scanner": cfg["features"]["binance_scanner"],
                   "Stablecoin data": cfg["features"]["stablecoins"]}
    for source, names in feature_map.items():
        group = labels[labels["source"] == source]
        for name in names:
            if name not in group:
                continue
            for h in horizons:
                pair = group[["sample_day", name, f"return_{h}h"]].dropna()
                days = int(pair["sample_day"].nunique())
                row = {"source": source, "feature": name, "horizon_hours": h,
                       "matured_observations": len(pair), "distinct_days": days,
                       "status": "insufficient" if days < exploratory_days else
                                 "exploratory" if days < promotion_days else "needs_paper_replication"}
                if days >= exploratory_days and pair[name].nunique() > 1:
                    row["spearman_ic"] = round(float(pair[name].corr(pair[f"return_{h}h"], method="spearman")), 4)
                    mid = pair["sample_day"].sort_values().iloc[len(pair) // 2]
                    row["first_half_ic"] = round(float(pair.loc[pair["sample_day"] <= mid, name].corr(
                        pair.loc[pair["sample_day"] <= mid, f"return_{h}h"], method="spearman")), 4)
                    row["second_half_ic"] = round(float(pair.loc[pair["sample_day"] > mid, name].corr(
                        pair.loc[pair["sample_day"] > mid, f"return_{h}h"], method="spearman")), 4)
                result["feature_checks"].append(row)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use cached prices only")
    args = ap.parse_args()
    cfg = yaml.safe_load(CONFIG.read_text())
    features = forward()
    symbols = [] if features.empty else features["symbol"].replace({"MARKET": "BTCUSDT"}).unique().tolist()
    prices, errors = collect_prices(symbols, fetch=not args.offline)
    labels = label_samples(features, prices, pd.Timestamp.now(tz="UTC"),
                           tuple(cfg["meta"]["horizons_hours"]))
    short = label_samples(features, prices, pd.Timestamp.now(tz="UTC"),
                          tuple(cfg["meta"]["short_horizons_hours"]), sample_freq="1h")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(OUT, index=False)
    short.to_parquet(SHORT_OUT, index=False)
    report = summarize(labels, cfg, errors)
    REPORT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    short_report = summarize(short, cfg, errors, tuple(cfg["meta"]["short_horizons_hours"]))
    SHORT_REPORT.write_text(json.dumps(short_report, indent=2, default=str) + "\n")
    print(f"{len(labels)} daily samples; {len(short)} hourly samples; "
          f"{sum(x['matured_1h'] for x in short_report['sources'].values())} matured 1h; {SHORT_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
