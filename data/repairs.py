from __future__ import annotations

import pandas as pd

BAR_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

REGISTRY = [
    {
        "id": "close_time_before_open_time",
        "reference": "DECISIONS.md#upstream-defects",
        "action": "rewrite_close_time_to_bar_end",
    }
]


def _bar_end(open_time: pd.Series, interval: str) -> pd.Series:
    return open_time + pd.Timedelta(seconds=BAR_SECONDS[interval]) - pd.Timedelta("1ms")


def apply(panel: pd.DataFrame, interval: str) -> tuple[pd.DataFrame, list[dict]]:
    panel = panel.copy()
    applied = []

    mask = panel["close_time"] <= panel["open_time"]
    if mask.any():
        affected = panel.loc[mask]
        panel.loc[mask, "close_time"] = _bar_end(affected["open_time"], interval)
        applied.append({
            **REGISTRY[0],
            "rows": int(mask.sum()),
            "symbols": int(affected["symbol"].nunique()),
            "bars": sorted({str(t) for t in affected["open_time"]}),
        })

    return panel, applied
