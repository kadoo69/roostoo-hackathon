from __future__ import annotations

import glob

import pandas as pd

from core.config import CACHE

RULE = {"1h": None, "4h": "4h", "8h": "8h", "12h": "12h", "1d": "1D"}
FIELDS = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
          "taker_buy_base", "taker_buy_quote"]
AGG = {"open": "first", "high": "max", "low": "min", "close": "last",
       "volume": "sum", "quote_volume": "sum", "trades": "sum",
       "taker_buy_base": "sum", "taker_buy_quote": "sum"}


def _stacked(interval: str) -> pd.DataFrame:
    path = CACHE / f"flow_{interval}.parquet"
    if path.exists():
        return pd.read_parquet(path)

    parts = []
    for f in sorted(glob.glob(str(CACHE / "1h" / "*.parquet"))):
        d = pd.read_parquet(f, columns=["symbol", "open_time"] + FIELDS)
        rule = RULE[interval]
        if rule is not None:
            d = (d.set_index("open_time").resample(rule).agg(AGG)
                 .dropna(subset=["close"]).reset_index())
            d["symbol"] = f.rsplit("/", 1)[-1][:-8]
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(path, index=False)
    return out


def panel(interval: str) -> dict[str, pd.DataFrame]:
    s = _stacked(interval)
    return {f: s.pivot(index="open_time", columns="symbol", values=f) for f in FIELDS}
