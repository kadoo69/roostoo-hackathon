"""Bar-level aggressor imbalance and the price-versus-flow divergence trigger.

Binance klines carry `taker_buy_quote`, the quote volume that traded against
the ask. Signed aggressor flow is therefore directly observable per bar without
any book reconstruction, which is what makes this testable on cached data.

It is a coarse proxy for true OFI: aggregation over a bar cannot separate one
sweep from many small orders and says nothing about resting depth. That
limitation is recorded in config/flow_scalp.yaml as the thing to blame first
if both arms come back empty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

AGG = {"open": "first", "high": "max", "low": "min", "close": "last",
       "volume": "sum", "quote_volume": "sum", "trades": "sum",
       "taker_buy_quote": "sum"}
RULE = {"5m": None, "15m": "15min", "30m": "30min", "1h": "1h"}
COLS = ["open_time", "open", "high", "low", "close", "volume",
        "quote_volume", "trades", "taker_buy_quote"]


def bars(path: str, interval: str) -> pd.DataFrame:
    d = pd.read_parquet(path, columns=COLS).set_index("open_time").sort_index()
    d = d[~d.index.duplicated(keep="last")]
    if RULE[interval] is not None:
        d = d.resample(RULE[interval]).agg(AGG).dropna(subset=["close"])
    return d


def ofi(d: pd.DataFrame) -> pd.Series:
    """Signed aggressor share in [-1, +1]. +1 is every trade lifting the offer.

    Bars with no quote volume are NaN rather than 0: an absent imbalance is not
    a balanced one, and treating it as balanced would let dead bars vote.
    """
    qv = d["quote_volume"].replace(0.0, np.nan)
    return (2.0 * d["taker_buy_quote"] / qv - 1.0).clip(-1.0, 1.0)


def _z(x: pd.Series, n: int) -> pd.Series:
    return (x - x.rolling(n).mean()) / x.rolling(n).std(ddof=1).replace(0.0, np.nan)


def features(d: pd.DataFrame, lookback: int) -> pd.DataFrame:
    f = pd.DataFrame(index=d.index)
    f["ofi"] = ofi(d)
    f["ofi_z"] = _z(f["ofi"], lookback)
    f["vol_z"] = _z(d["quote_volume"], lookback)
    f["trade_z"] = _z(d["trades"].astype(float), lookback)
    return f


def entry_mask(d: pd.DataFrame, f: pd.DataFrame, arm: str, k: int,
               ret_thresh: float, ofi_thresh: float,
               vol_min: float) -> np.ndarray:
    """Long-only trigger. `divergence` buys falls that flow did not confirm.

    Both arms demand the SAME positive flow condition; only the sign of the
    price leg differs, so the pair isolates whether the price move's direction
    matters at all once flow is positive.
    """
    ret = (d["close"] / d["close"].shift(k) - 1.0).to_numpy(float)
    oz = f["ofi_z"].to_numpy(float)
    vz = f["vol_z"].to_numpy(float)
    ok = np.isfinite(ret) & np.isfinite(oz) & np.isfinite(vz)
    flow = oz >= ofi_thresh
    liquid = vz >= vol_min
    price = (ret <= -ret_thresh) if arm == "divergence" else (ret >= ret_thresh)
    if arm not in ("divergence", "continuation"):
        raise ValueError(arm)
    return ok & flow & liquid & price
