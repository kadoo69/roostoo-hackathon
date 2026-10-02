"""What makes a 15-minute +2% burst continue: an event study on recent live-market 5m bars.

Declared in config/burst_drivers.yaml before any number was computed.
DECISIONS.md#burst-drivers-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from core.config import RESULTS

COST = 0.10
FEATURES = ["vol_x", "taker_share", "btc_15m", "breadth_15m", "prior_4h", "dist_hi24", "trade_size_x", "burst_pct"]


def pivots(k: pd.DataFrame) -> dict[str, pd.DataFrame]:
    k = k.drop_duplicates(["symbol", "open_time"])
    return {f: k.pivot(index="open_time", columns="symbol", values=f).sort_index()
            for f in ("close", "high", "low", "quote_volume", "taker_buy_quote", "trades") if f in k}


def events(p: dict[str, pd.DataFrame], thresh: float = 0.02, cooldown_bars: int = 12) -> pd.DataFrame:
    c, h, qv, tb, tr = p["close"], p["high"], p["quote_volume"], p["taker_buy_quote"], p["trades"]
    r15 = c / c.shift(3) - 1.0
    qv15 = qv.rolling(3).sum()
    vol_x = qv15 / qv15.shift(3).rolling(288, min_periods=144).median()
    taker = tb.rolling(3).sum() / qv15
    size = qv / tr.replace(0, np.nan)
    size15 = qv15 / tr.rolling(3).sum().replace(0, np.nan)
    size_x = size15 / size.shift(3).rolling(288, min_periods=144).median()
    btc = r15["BTCUSDT"] if "BTCUSDT" in r15 else pd.Series(0.0, index=c.index)
    up = (r15 > 0.005).astype(float)
    breadth = (up.sum(axis=1).to_numpy()[:, None] - up.to_numpy()) / (up.shape[1] - 1)
    breadth = pd.DataFrame(breadth, index=c.index, columns=c.columns)
    prior4 = c.shift(3) / c.shift(3 + 48) - 1.0
    hi24 = h.shift(1).rolling(288, min_periods=144).max()
    dist = c / hi24 - 1.0
    fwd = {n: c.shift(-b) / c - 1.0 for n, b in (("f15m", 3), ("f1h", 12), ("f4h", 48))}
    runup = h[::-1].rolling(48, min_periods=1).max()[::-1].shift(-1) / c - 1.0
    rows = []
    for sym in c.columns:
        if sym == "BTCUSDT":
            continue
        hit = r15[sym] >= thresh
        last = -10**9
        for i in np.flatnonzero(hit.to_numpy()):
            if i - last < cooldown_bars or i < 300 or i + 48 >= len(c):
                continue
            last = i
            t = c.index[i]
            rows.append({"symbol": sym, "t": t, "burst_pct": r15[sym].iat[i] * 100, "vol_x": vol_x[sym].iat[i],
                         "taker_share": taker[sym].iat[i], "btc_15m": btc.iat[i] * 100,
                         "breadth_15m": breadth[sym].iat[i], "prior_4h": prior4[sym].iat[i] * 100,
                         "dist_hi24": dist[sym].iat[i] * 100, "trade_size_x": size_x[sym].iat[i],
                         **{n: v[sym].iat[i] * 100 - COST for n, v in fwd.items()},
                         "runup_4h": runup[sym].iat[i] * 100})
    return pd.DataFrame(rows).dropna()


def exit_trade(c: np.ndarray, h: np.ndarray, lo: np.ndarray, i: int, tp: float, stop: float | None,
               horizon: int = 48) -> float:
    """Net % of a long bought at close i: resting take-profit `tp`, optional stop, else the close
    `horizon` bars later; a bar touching both counts as the stop. DECISIONS.md#burst-drivers-outcome"""
    entry = c[i]
    for j in range(i + 1, min(i + horizon, len(c) - 1) + 1):
        if stop is not None and lo[j] <= entry * (1 - stop / 100):
            return -stop - 0.15
        if h[j] >= entry * (1 + tp / 100):
            return tp - COST
    return (c[min(i + horizon, len(c) - 1)] / entry - 1) * 100 - COST


def exit_grid(p: dict[str, pd.DataFrame], ev: pd.DataFrame, rng: np.random.Generator) -> dict:
    idx = {t: n for n, t in enumerate(p["close"].index)}
    arr = {f: p[f] for f in ("close", "high", "low")}
    out = {}
    for tp in (1.0, 1.5, 2.0, 3.0, 5.0):
        for stop in (None, 1.5):
            key = f"tp{tp}_stop{stop or 'none'}"
            real, ctrl = [], []
            for _, e in ev.iterrows():
                c, h, lo = (arr[f][e["symbol"]].to_numpy() for f in ("close", "high", "low"))
                i = idx[e["t"]]
                real.append(exit_trade(c, h, lo, i, tp, stop))
                r = int(rng.integers(300, len(c) - 49))
                ctrl.append(exit_trade(c, h, lo, r, tp, stop))
            real, ctrl = np.array(real), np.array(ctrl)
            out[key] = {"mean": round(float(real.mean()), 3), "t": round(float(real.mean() / (real.std(ddof=1) / np.sqrt(len(real)))), 2),
                        "hit": round(float((real > 0).mean()), 3), "random_mean": round(float(ctrl.mean()), 3)}
    return out


def tercile_spread(ev: pd.DataFrame, feat: str, out: str) -> dict:
    q = ev[feat].rank(pct=True)
    top, bot = ev.loc[q > 2 / 3, out], ev.loc[q <= 1 / 3, out]
    d = top.mean() - bot.mean()
    se = np.sqrt(top.var(ddof=1) / len(top) + bot.var(ddof=1) / len(bot))
    return {"top": round(float(top.mean()), 3), "bottom": round(float(bot.mean()), 3),
            "spread": round(float(d), 3), "t": round(float(d / se), 2) if se > 0 else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    a = ap.parse_args()
    k = pd.read_parquet(a.cache)
    k["open_time"] = pd.to_datetime(k["open_time"], utc=True)
    ev = events(pivots(k))
    mid = ev["t"].min() + (ev["t"].max() - ev["t"].min()) / 2
    halves = {"discovery": ev[ev["t"] < mid], "validation": ev[ev["t"] >= mid]}
    res = {"n_events": {h: len(e) for h, e in halves.items()}, "split_at": str(mid), "baseline": {}, "drivers": {}}
    for h, e in halves.items():
        res["baseline"][h] = {o: {"mean": round(float(e[o].mean()), 3), "t": round(float(e[o].mean() / (e[o].std() / np.sqrt(len(e)))), 2),
                                  "hit": round(float((e[o] > 0).mean()), 3)} for o in ("f15m", "f1h", "f4h", "runup_4h")}
    for f in FEATURES:
        res["drivers"][f] = {h: {o: tercile_spread(e, f, o) for o in ("f1h", "f4h")} for h, e in halves.items()}
        d, v = res["drivers"][f]["discovery"], res["drivers"][f]["validation"]
        res["drivers"][f]["real"] = all(np.sign(d[o]["spread"]) == np.sign(v[o]["spread"]) and abs(d[o]["t"]) >= 2
                                        and abs(v[o]["t"]) >= 2 for o in ("f1h", "f4h"))
    p = pivots(k)
    rng = np.random.default_rng(5)
    res["exits"] = {h: exit_grid(p, e.reset_index(drop=True), rng) for h, e in halves.items()}
    res["exits_real"] = [key for key, v in res["exits"]["validation"].items()
                         if v["mean"] > 0 and v["t"] >= 2 and res["exits"]["discovery"][key]["mean"] > 0]
    (RESULTS / "burst_drivers.json").write_text(json.dumps(res, indent=1, default=str))
    ev.to_parquet(RESULTS / "burst_drivers_events.parquet")
    print(json.dumps({"n_events": res["n_events"], "split_at": res["split_at"], "baseline": res["baseline"]}, indent=1))
    print(f"\n{'driver':14s} {'half':11s} {'+1h top/bot (spread, t)':34s} {'+4h top/bot (spread, t)':34s} real")
    for f, r in res["drivers"].items():
        for h in ("discovery", "validation"):
            x, y = r[h]["f1h"], r[h]["f4h"]
            print(f"{f:14s} {h:11s} {x['top']:+6.2f}/{x['bottom']:+6.2f} ({x['spread']:+5.2f}, {x['t']:+5.2f})     "
                  f"{y['top']:+6.2f}/{y['bottom']:+6.2f} ({y['spread']:+5.2f}, {y['t']:+5.2f})     {r['real'] if h == 'validation' else ''}")
    print(f"\n{'exit':20s} {'discovery mean/t/hit (random)':34s} {'validation mean/t/hit (random)':34s}")
    for key in res["exits"]["discovery"]:
        d, v = res["exits"]["discovery"][key], res["exits"]["validation"][key]
        print(f"{key:20s} {d['mean']:+6.3f} {d['t']:+5.2f} {d['hit']:.2f} ({d['random_mean']:+6.3f})      "
              f"{v['mean']:+6.3f} {v['t']:+5.2f} {v['hit']:.2f} ({v['random_mean']:+6.3f})")
    print("REAL:", res["exits_real"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
