from __future__ import annotations


import pandas as pd

from core import artifacts
from core.config import gate_config, prereg
from data import binance, universe
from venue.roostoo import RoostooClient

GATE = "g1_data_integrity"


def timestamp_audit(panel: pd.DataFrame, interval_hours: int = 1) -> dict:
    grouped = panel.groupby("symbol")["open_time"]
    duplicated = int(panel.duplicated(subset=["symbol", "open_time"]).sum())
    non_monotonic = int(
        sum(not g.is_monotonic_increasing for _, g in grouped)
    )
    step = pd.Timedelta(hours=interval_hours)
    gaps = []
    for symbol, series in grouped:
        deltas = series.diff().dropna()
        missing = int(((deltas / step) - 1).clip(lower=0).sum())
        if missing:
            gaps.append({"symbol": symbol, "missing_bars": missing})
    gaps.sort(key=lambda r: -r["missing_bars"])
    tz_naive = int(panel["open_time"].dt.tz is None)
    return {
        "duplicated_rows": duplicated,
        "non_monotonic_symbols": non_monotonic,
        "timezone_naive": tz_naive,
        "symbols_with_gaps": len(gaps),
        "total_missing_bars": sum(g["missing_bars"] for g in gaps),
        "worst_gaps": gaps[:10],
    }


def survivorship_audit(panel: pd.DataFrame) -> dict:
    trading = binance.currently_trading("USDT")
    windows = universe.listing_windows(panel)
    present = set(windows["symbol"])
    delisted = sorted(present - trading)
    return {
        "symbols_in_panel": len(present),
        "currently_trading": len(present & trading),
        "delisted_retained": len(delisted),
        "delisted_fraction": round(len(delisted) / max(len(present), 1), 4),
        "naive_universe_would_drop": len(delisted),
        "sample_delisted": delisted[:10],
    }


def lookahead_audit(panel: pd.DataFrame) -> dict:
    cfg = prereg()["data"]
    members = universe.membership(panel)
    windows = universe.listing_windows(panel).set_index("symbol")

    violations = []
    for symbol in members.columns:
        active = members.index[members[symbol]]
        if not len(active):
            continue
        if active.min() <= windows.loc[symbol, "first_bar"]:
            violations.append({
                "symbol": symbol,
                "first_membership": str(active.min()),
                "first_bar": str(windows.loc[symbol, "first_bar"]),
            })

    close_vs_open = panel["close_time"] > panel["open_time"]
    _ = close_vs_open
    return {
        "membership_before_first_bar": len(violations),
        "violations": violations[:10],
        "close_time_after_open_time_always": bool(close_vs_open.all()),
        "label_horizon_bars": cfg["label_horizon_bars"],
        "embargo_bars": cfg["embargo_bars"],
        "embargo_at_least_label_horizon":
            cfg["embargo_bars"] >= cfg["label_horizon_bars"],
        "membership_matrix_shape": list(members.shape),
        "mean_daily_members": round(float(members.sum(axis=1).mean()), 2),
    }


def price_source_audit(sample: int = 40) -> dict:
    client = RoostooClient()
    client.sync_time()
    specs = client.exchange_info()
    roostoo = client.ticker()
    book = {
        d["symbol"]: d for d in
        binance.SESSION.get(
            "https://api.binance.com/api/v3/ticker/bookTicker", timeout=60
        ).json()
    }
    deviations = []
    for pair, spec in specs.items():
        quote = roostoo.get(pair)
        ref = book.get(spec.binance_symbol)
        if not quote or not ref:
            continue
        rmid = (quote["MaxBid"] + quote["MinAsk"]) / 2
        bmid = (float(ref["bidPrice"]) + float(ref["askPrice"])) / 2
        if bmid <= 0:
            continue
        deviations.append(abs(rmid - bmid) / bmid * 1e4)
    series = pd.Series(deviations)
    return {
        "pairs_compared": int(series.size),
        "pairs_unmatched": len(specs) - int(series.size),
        "median_deviation_bps": round(float(series.median()), 4),
        "p95_deviation_bps": round(float(series.quantile(0.95)), 4),
        "max_deviation_bps": round(float(series.max()), 4),
    }


def repair_audit(interval: str = "1h") -> list[dict]:
    from core.config import CACHE

    path = CACHE / f"repairs_{interval}.json"
    if not path.exists():
        return []
    return pd.read_json(path).to_dict(orient="records")


def main() -> int:
    cfg = gate_config(GATE)
    panel = universe.load_panel("1h")
    applied = repair_audit("1h")

    timestamps = timestamp_audit(panel)
    survivorship = survivorship_audit(panel)
    lookahead = lookahead_audit(panel)
    price_source = price_source_audit()

    lookahead_violations = lookahead["membership_before_first_bar"]
    survivorship_violations = 0 if survivorship["delisted_retained"] > 0 else 1

    passed = (
        lookahead_violations <= cfg["max_lookahead_violations"]
        and survivorship_violations <= cfg["max_survivorship_violations"]
        and timestamps["non_monotonic_symbols"] == 0
        and timestamps["duplicated_rows"] == 0
        and lookahead["close_time_after_open_time_always"]
        and lookahead["embargo_at_least_label_horizon"]
    )

    artifacts.write(GATE, passed, {
        "panel_rows": int(len(panel)),
        "panel_span": [str(panel["open_time"].min()), str(panel["open_time"].max())],
        "timestamps": timestamps,
        "survivorship": survivorship,
        "lookahead": lookahead,
        "price_source": price_source,
        "repairs_applied": applied,
        "costs_confirmed": prereg()["costs"]["confirmed"],
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
