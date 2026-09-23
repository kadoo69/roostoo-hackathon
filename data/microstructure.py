"""L2 depth imbalance and trade-size distribution from Binance spot.

These exist to close a limitation measured at DECISIONS.md#flow-scalp-outcome.
That sweep found a real divergence effect - fit +9.26 bps against holdout
+11.42, dose-responding to the flow threshold - that failed only because
bar-aggregated `taker_buy_quote` cannot separate one sweep from many small
orders and says nothing about resting liquidity.

Depth is a SNAPSHOT endpoint: there is no history behind it. Anything built on
book imbalance can therefore only be validated forward, never backtested, and
that asymmetry is the reason it is published by the scanner rather than fed to
a sweep.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

REST = "https://api.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "roostoo-hackathon-bot"})


class MicroError(RuntimeError):
    pass


def _get(path: str, params: dict) -> list | dict:
    r = SESSION.get(f"{REST}{path}", params=params, timeout=20)
    if r.status_code != 200:
        raise MicroError(f"{path}:{r.status_code}:{r.text[:120]}")
    return r.json()


def book(symbol: str, limit: int = 100) -> dict:
    """Depth-weighted book imbalance and the cost of crossing it.

    `imbalance` is (bid_value - ask_value) / total within the top `limit`
    levels, in [-1, +1]. Unlike a taker share it measures liquidity that is
    RESTING rather than volume that already traded, so a thin ask stack shows
    up before the print does.
    """
    d = _get("/api/v3/depth", {"symbol": symbol, "limit": limit})
    bids = np.array(d["bids"], dtype=float)
    asks = np.array(d["asks"], dtype=float)
    if not len(bids) or not len(asks):
        raise MicroError(f"{symbol}:empty_book")
    bid_v = float((bids[:, 0] * bids[:, 1]).sum())
    ask_v = float((asks[:, 0] * asks[:, 1]).sum())
    best_bid, best_ask = float(bids[0, 0]), float(asks[0, 0])
    mid = (best_bid + best_ask) / 2.0
    tot = bid_v + ask_v
    return {
        "symbol": symbol, "levels": int(min(len(bids), len(asks))),
        "mid": mid,
        "spread_bps": round((best_ask / best_bid - 1.0) * 1e4, 4),
        "bid_value_usd": round(bid_v, 2), "ask_value_usd": round(ask_v, 2),
        "imbalance": round((bid_v - ask_v) / tot, 4) if tot > 0 else None,
        # depth within 10 bps of mid: what a market order would actually eat
        "depth_10bps_usd": round(float(
            (bids[bids[:, 0] >= mid * 0.999][:, 0] * bids[bids[:, 0] >= mid * 0.999][:, 1]).sum()
            + (asks[asks[:, 0] <= mid * 1.001][:, 0] * asks[asks[:, 0] <= mid * 1.001][:, 1]).sum()), 2),
    }


def trade_profile(symbol: str, limit: int = 1000) -> dict:
    """Trade-size distribution from aggTrades: one whale or many retail.

    `m` is true when the BUYER was the maker, i.e. the aggressor sold. The
    large-trade share is the quantity a bar-level taker ratio destroys, and it
    is the other half of the flow-scalp limitation.
    """
    rows = _get("/api/v3/aggTrades", {"symbol": symbol, "limit": min(limit, 1000)})
    if not rows:
        raise MicroError(f"{symbol}:no_trades")
    d = pd.DataFrame(rows)
    px = d["p"].astype(float)
    qty = d["q"].astype(float)
    notional = px * qty
    sell_agg = d["m"].astype(bool)          # buyer was maker => seller crossed
    buy_notional = float(notional[~sell_agg].sum())
    sell_notional = float(notional[sell_agg].sum())
    tot = buy_notional + sell_notional
    big = notional >= notional.quantile(0.95)
    span_s = (int(d["T"].max()) - int(d["T"].min())) / 1000.0
    return {
        "symbol": symbol, "n_trades": int(len(d)),
        "window_s": round(span_s, 1),
        "trades_per_s": round(len(d) / span_s, 2) if span_s > 0 else None,
        "notional_usd": round(float(tot), 2),
        "aggressor_imbalance": round((buy_notional - sell_notional) / tot, 4) if tot > 0 else None,
        "mean_trade_usd": round(float(notional.mean()), 2),
        "median_trade_usd": round(float(notional.median()), 2),
        # share of notional done by the top 5% of trades: high means one hand
        "top5pct_notional_share": round(float(notional[big].sum() / tot), 4) if tot > 0 else None,
        "big_trade_aggressor": round(float(
            (notional[big & ~sell_agg].sum() - notional[big & sell_agg].sum())
            / notional[big].sum()), 4) if float(notional[big].sum()) > 0 else None,
    }
