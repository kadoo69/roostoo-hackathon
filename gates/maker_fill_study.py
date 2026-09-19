from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from bot import feed, universe as bu
from bot.settings import load
from core.config import RESULTS
from venue.roostoo import RoostooClient

warnings.filterwarnings("ignore")

OFFSET_BPS = 1.0
WINDOWS_MIN = (5, 15, 30, 60, 240)
LOOKBACK_MIN = 1000


def study_symbol(symbol: str) -> dict | None:
    try:
        k = feed.closed_bars(symbol, "1m", LOOKBACK_MIN)
    except Exception:
        return None
    if len(k) < 300:
        return None
    close = k["close"].to_numpy(dtype=float)
    low = k["low"].to_numpy(dtype=float)
    high = k["high"].to_numpy(dtype=float)
    n = len(close)
    out = {"symbol": symbol, "bars": n}
    for w in WINDOWS_MIN:
        buy_fill, sell_fill, k_ok = 0, 0, 0
        for i in range(n - w - 1):
            limit_buy = close[i] * (1.0 - OFFSET_BPS / 1e4)
            limit_sell = close[i] * (1.0 + OFFSET_BPS / 1e4)
            fwd_low = low[i + 1: i + 1 + w].min()
            fwd_high = high[i + 1: i + 1 + w].max()
            buy_fill += int(fwd_low <= limit_buy)
            sell_fill += int(fwd_high >= limit_sell)
            k_ok += 1
        out[f"buy_fill_{w}m"] = round(buy_fill / k_ok, 4)
        out[f"sell_fill_{w}m"] = round(sell_fill / k_ok, 4)
    return out


def main() -> int:
    s = load("config/bot_a_4h.yaml")
    client = RoostooClient()
    specs = client.exchange_info()
    sel = bu.select(s, specs)["selected"]
    rows = [r for r in (study_symbol(x) for x in sel) if r]
    f = pd.DataFrame(rows)

    summary = {"offset_bps": OFFSET_BPS, "symbols": len(f),
               "lookback_minutes": LOOKBACK_MIN, "per_window": {}}
    for w in WINDOWS_MIN:
        b, sl = f[f"buy_fill_{w}m"], f[f"sell_fill_{w}m"]
        both = pd.concat([b, sl])
        summary["per_window"][f"{w}m"] = {
            "median_fill_rate": round(float(both.median()), 4),
            "mean_fill_rate": round(float(both.mean()), 4),
            "worst_symbol_fill_rate": round(float(both.min()), 4),
            "p10_fill_rate": round(float(both.quantile(0.10)), 4),
            "buy_median": round(float(b.median()), 4),
            "sell_median": round(float(sl.median()), 4)}

    w = s.limit_timeout_s // 60
    key = min(WINDOWS_MIN, key=lambda x: abs(x - w))
    p = summary["per_window"][f"{key}m"]["median_fill_rate"]
    blended = p * 5.0 + (1 - p) * 10.0
    summary["bot_timeout_minutes"] = w
    summary["nearest_window"] = f"{key}m"
    summary["implied_maker_rate"] = p
    summary["blended_fee_bps_per_side"] = round(blended, 3)
    summary["blended_round_trip_bps"] = round(blended * 2, 3)
    summary["per_symbol"] = rows

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "maker_fill_study.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
