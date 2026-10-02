"""Replay of inverse-volatility entry sizing on the rule, the ride and the 50/50 sleeves over the two
latest 14-day windows; information beside the forward paper book `sleeves_ivol_5m`.
DECISIONS.md#sleeves-ivol-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from bot.scalper_adaptive_run import build_variants, variant_weights
from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from archive.gates.bstocks_pool import frames, stats
from gates.missed_replay import universe


def entry_scaled(w: pd.DataFrame, close: pd.DataFrame, lookback: int, lo: float, hi: float) -> pd.DataFrame:
    """Each holding spell keeps the multiplier known at its entry bar, as the live sleeves do."""
    v = np.log(close).diff().rolling(lookback, min_periods=lookback // 2).std()
    k = (v.median(axis=1).to_numpy()[:, None] / v).clip(lo, hi).fillna(1.0)
    on = w > 0
    start = on & ~on.shift(fill_value=False)
    kk = k.where(start).ffill().where(on).fillna(1.0)
    return w * kk


def mix(nr: pd.Series, nd: pd.Series) -> pd.Series:
    r1 = np.log1p(nr).groupby((nr.index + pd.Timedelta("30min")).floor("30min")).sum()
    r2 = np.log1p(nd).groupby((nd.index + pd.Timedelta("5min")).ceil("30min")).sum()
    g = r1.index.union(r2.index)
    return 0.5 * np.expm1(r1.reindex(g).fillna(0.0)) + 0.5 * np.expm1(r2.reindex(g).fillna(0.0))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="2026-09-05")
    ap.add_argument("--w2", default="2026-09-19")
    a = ap.parse_args(argv)
    w1, w2 = pd.Timestamp(a.w1, tz="UTC"), pd.Timestamp(a.w2, tz="UTC")
    iv = yaml.safe_load((ROOT / "config" / "sleeves_ivol_5m.yaml").read_text())["sleeves"]["inverse_vol"]
    syms = universe("momentum_top3_30m")
    specs = ru.tradable_symbols()
    d30, d4 = frames(syms, "30m", w1 - pd.Timedelta(days=30)), frames(syms, "4h", w1 - pd.Timedelta(days=30))
    d5 = frames(syms, "5m", w1 - pd.Timedelta(days=2))
    tick = pd.Series({s: specs[s].tick for s in syms if s in specs})
    rule = build_variants({"clocks": {"30m": "competition"}})["30m"]
    ride_cfg = next(iter(yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"].values()))
    wr = variant_weights(rule, d30, d4["close"]).reindex_like(d30["close"]).fillna(0.0)
    wd = variant_weights({"type": "burst", "cc": ride_cfg}, d5, None).reindex_like(d5["close"]).fillna(0.0)
    arms = {"base": (wr, wd),
            "ivol": (entry_scaled(wr, d30["close"], int(iv["lookback_bars"]) // 6, iv["min"], iv["max"]),
                     entry_scaled(wd, d5["close"], int(iv["lookback_bars"]), iv["min"], iv["max"]))}
    out = {"inverse_vol": iv, "results": {}, "ref": "DECISIONS.md#sleeves-ivol-declaration"}
    for arm, (r, d) in arms.items():
        res = {}
        for wn, (s, e) in {"W1": (w1, w2), "W2": (w2, pd.Timestamp.now(tz="UTC"))}.items():
            nr, _ = lwr.simulate(d30["close"].loc[s:e], r.loc[s:e], tick, True)
            nd, _ = lwr.simulate(d5["close"].loc[s:e], d.loc[s:e], tick, True)
            m = mix(nr, nd)
            sd = m.std() * np.sqrt(48 * 365)
            res[wn] = {"rule": stats(nr), "ride": stats(nd), "sleeves": stats(m),
                       "sleeves_ann_vol_pct": round(float(sd) * 100, 1),
                       "sleeves_sharpe": round(float(m.mean() * 48 * 365 / sd), 2) if sd > 0 else None,
                       "mean_gross": {"rule": round(float(r.loc[s:e].sum(axis=1).mean()), 3),
                                      "ride": round(float(d.loc[s:e].sum(axis=1).mean()), 3)}}
        out["results"][arm] = res
    (RESULTS / "ivol_sizing.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
