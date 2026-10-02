"""Does adding Roostoo's bStocks to the pool help the rule, the ride and the 50/50 sleeves, judged on the
two latest 14-day windows of live Binance bars.

Declared in config/bstocks_pool.yaml before any number was computed.
DECISIONS.md#bstocks-pool-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.scalper_adaptive_run import build_variants, variant_weights
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe

STEP = {"5m": "5min", "30m": "30min", "4h": "4h"}


def frames(syms: list[str], iv: str, start: pd.Timestamp) -> dict:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(STEP[iv])) + 10
    fr = feed.bar_frame(syms, iv, n)
    col = lambda k: pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()  # noqa: E731
    return {"close": col("close"), "qv": col("quote_volume"), "high": col("high"), "taker": col("taker_buy_quote")}


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    return {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
            "max_dd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 2)}


def stock_share(w: pd.DataFrame, stocks: set[str]) -> float:
    cols = [c for c in w.columns if c in stocks]
    tot = float(w.abs().sum(axis=1).sum())
    return round(float(w[cols].abs().sum(axis=1).sum()) / tot, 3) if cols and tot else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="2026-09-05")
    ap.add_argument("--w2", default="2026-09-19")
    a = ap.parse_args(argv)
    w1, w2 = pd.Timestamp(a.w1, tz="UTC"), pd.Timestamp(a.w2, tz="UTC")
    warm = w1 - pd.Timedelta(days=30)
    specs = ru.roostoo_specs()
    by_bin = {s.binance_symbol: s for s in specs.values() if s.can_trade}
    stocks = {b for b, s in by_bin.items() if s.asset_type == "stock"}
    base = universe("momentum_top3_30m")
    arms = {"A0": base, "A1": base + sorted({"SNDKBUSDT", "CRCLBUSDT"} & stocks), "A2": base + sorted(stocks)}
    every = sorted(set(arms["A2"]))
    d30, d5, d4 = frames(every, "30m", warm), frames(every, "5m", w1 - pd.Timedelta(days=2)), frames(every, "4h", warm)
    tick = pd.Series({s: by_bin[s].tick for s in every if s in by_bin})
    rule = build_variants({"clocks": {"30m": "competition"}})["30m"]
    ride_cfg = next(iter(yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    ride = {"type": "burst", "cc": ride_cfg}
    windows = {"W1": (w1, w2), "W2": (w2, pd.Timestamp.now(tz="UTC"))}
    out = {"windows": {k: [str(s), str(e)] for k, (s, e) in windows.items()},
           "arms": {k: len(v) for k, v in arms.items()}, "stocks_with_bars": sorted(set(d5["close"].columns) & stocks),
           "results": {}, "ref": "DECISIONS.md#bstocks-pool-declaration"}
    for arm, syms in arms.items():
        cols30 = [s for s in syms if s in d30["close"].columns]
        cols5 = [s for s in syms if s in d5["close"].columns]
        sub = lambda d, cols: {k: v[cols] for k, v in d.items()}  # noqa: E731
        wr = variant_weights(rule, sub(d30, cols30), d4["close"][[c for c in cols30 if c in d4["close"].columns]])
        wr = wr.reindex_like(d30["close"][cols30]).fillna(0.0)
        wd = variant_weights(ride, sub(d5, cols5), None).reindex_like(d5["close"][cols5]).fillna(0.0)
        res = {}
        for wn, (s, e) in windows.items():
            c30, c5 = d30["close"][cols30].loc[s:e], d5["close"][cols5].loc[s:e]
            nr, _ = lwr.simulate(c30, wr.loc[s:e], tick, True)
            nd, _ = lwr.simulate(c5, wd.loc[s:e], tick, True)
            r_rule = np.log1p(nr).groupby((nr.index + pd.Timedelta("30min")).floor("30min")).sum()
            r_ride = np.log1p(nd).groupby((nd.index + pd.Timedelta("5min")).ceil("30min")).sum()
            grid = r_rule.index.union(r_ride.index)
            mix = 0.5 * np.expm1(r_rule.reindex(grid).fillna(0.0)) + 0.5 * np.expm1(r_ride.reindex(grid).fillna(0.0))
            res[wn] = {"rule": stats(nr), "ride": stats(nd), "sleeves": stats(mix),
                       "rule_stock_weight_share": stock_share(wr.loc[s:e], stocks),
                       "ride_stock_weight_share": stock_share(wd.loc[s:e], stocks)}
        out["results"][arm] = res
    a0 = out["results"]["A0"]
    out["verdict"] = {}
    for arm in ("A1", "A2"):
        r = out["results"][arm]
        beats = all(r[w]["sleeves"]["total_pct"] > a0[w]["sleeves"]["total_pct"] for w in windows)
        dd_ok = all(r[w]["sleeves"]["max_dd_pct"] >= a0[w]["sleeves"]["max_dd_pct"] - 2.0 for w in windows)
        out["verdict"][arm] = {"sleeves_gain_pp": {w: round(r[w]["sleeves"]["total_pct"] - a0[w]["sleeves"]["total_pct"], 2)
                                                   for w in windows},
                               "dd_ok": dd_ok, "recommended": bool(beats and dd_ok)}
    (RESULTS / "bstocks_pool.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
