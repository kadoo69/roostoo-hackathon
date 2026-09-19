from __future__ import annotations

import argparse
import json
import warnings

import numpy as np
import pandas as pd

from bot import feed, universe as bu
from bot.settings import load
from core.config import RESULTS
from signals import donchian
from venue.roostoo import RoostooClient

warnings.filterwarnings("ignore")
FEE = 0.0005


def per_coin_backtest(closes: pd.Series, entry: int, exit_lb: int,
                      bars_per_day: int) -> dict:
    df = closes.dropna().to_frame("c")
    pos = donchian.position(df, entry, "lowchannel", exit_lb)["c"]
    ret = df["c"].pct_change()
    turn = (pos - pos.shift(1)).abs()
    net = (pos.shift(1) * ret - turn.shift(1).fillna(0.0) * FEE).dropna()
    if len(net) < 30 or net.std() == 0:
        return {}
    eq = (1.0 + net).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    ppy = 365 * bars_per_day
    trades = float(turn.sum() / 2.0)
    return {"bars": int(len(net)),
            "total_return": round(float(eq.iloc[-1] - 1.0), 5),
            "sharpe": round(float(net.mean() / net.std() * np.sqrt(ppy)), 3),
            "max_drawdown": round(dd, 4),
            "trades": int(trades),
            "time_in_market": round(float(pos.mean()), 3),
            "win_bars": round(float((net[net != 0] > 0).mean()), 3)
            if (net != 0).any() else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/bot_a_4h.yaml")
    ap.add_argument("--bars", type=int, default=700)
    a = ap.parse_args()
    s = load(a.config)

    client = RoostooClient()
    specs = client.exchange_info()
    venue = bu.venue_symbols(specs)
    selected = set(bu.select(s, specs)["selected"])
    quotes = client.ticker()

    frames = feed.bar_frame(venue, s.interval, a.bars)
    matrix = feed.close_matrix(frames)
    need = max(s.entry_bars, s.exit_bars) + 1

    rows = []
    for sym in venue:
        if sym not in matrix.columns:
            rows.append({"symbol": sym, "status": "no_bars"})
            continue
        c = matrix[sym].dropna()
        if len(c) < need:
            rows.append({"symbol": sym, "status": f"short_history_{len(c)}"})
            continue
        prior = c.iloc[:-1]
        upper = float(prior.tail(s.entry_bars).max())
        floor = float(prior.tail(s.exit_bars).min())
        close = float(c.iloc[-1])
        pos = donchian.position(c.to_frame("c"), s.entry_bars, "lowchannel",
                                s.exit_bars)["c"]
        held = bool(pos.iloc[-1] > 0.5)
        spec = next((x for x in specs.values() if x.binance_symbol == sym), None)
        q = quotes.get(spec.pair) if spec else None
        row = {"symbol": sym, "status": "ok", "in_selected_pool": sym in selected,
               "held": held, "close": close, "upper_channel": round(upper, 8),
               "exit_floor": round(floor, 8),
               "pct_to_entry": round((upper / close - 1.0) * 100, 3),
               "pct_to_exit": round((close / floor - 1.0) * 100, 3),
               "bars": int(len(c))}
        if q:
            row["roostoo_last"] = q["LastPrice"]
            row["drift_since_bar_close_bps"] = round(
                (q["LastPrice"] / close - 1.0) * 1e4, 2)
            row["roostoo_spread_bps"] = round(
                (q["MinAsk"] / q["MaxBid"] - 1.0) * 1e4, 3)
        row.update(per_coin_backtest(c, s.entry_bars, s.exit_bars, s.bars_per_day))
        rows.append(row)

    out = {"config": a.config, "interval": s.interval,
           "entry_bars": s.entry_bars, "exit_bars": s.exit_bars,
           "roostoo_tradable": len(venue), "selected_pool": sorted(selected),
           "bars_fetched": a.bars, "coins": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "live_scan.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
