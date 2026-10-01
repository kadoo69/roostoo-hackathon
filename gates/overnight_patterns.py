"""Missed gains and minute-level patterns over a recent window: per-coin moves and best legs, the
live rule's replay against what the books did, and an event study of simple minute triggers
(jump, volume burst, range break, BTC lead) with forward returns net of a maker round trip.
Descriptive only: one window is in-sample, so nothing here is a validated edge.
DECISIONS.md#overnight-patterns-2026-10-01

`python3 -m gates.overnight_patterns --start 2026-09-30T20:00Z`
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from bot import feed
from core.config import RESULTS
from gates.missed_replay import universe

COST = 0.001
HORIZONS = (15, 60, 240)


def minute_frames(syms: list[str], start: pd.Timestamp) -> dict[str, pd.DataFrame]:
    n = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(minutes=1)) + 300
    fr = feed.bar_frame(syms, "1m", n)
    return {"close": feed.close_matrix(fr),
            "high": pd.DataFrame({s: f.set_index("open_time")["high"] for s, f in fr.items()}),
            "qv": pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in fr.items()}),
            "taker": pd.DataFrame({s: f.set_index("open_time")["taker_buy_quote"] for s, f in fr.items()})}


def best_leg(c: pd.Series) -> dict:
    lo_idx, best, leg = c.index[0], 0.0, (None, None)
    for t, p in c.items():
        if p < c[lo_idx]:
            lo_idx = t
        r = p / c[lo_idx] - 1.0
        if r > best:
            best, leg = r, (lo_idx, t)
    return {"best_leg_pct": round(best * 100, 2), "from": str(leg[0])[11:16], "to": str(leg[1])[11:16]}


def triggers(d: dict, w: slice) -> dict[str, pd.DataFrame]:
    c, qv, hi = d["close"], d["qv"], d["high"]
    r15 = c / c.shift(15) - 1.0
    v15 = qv.rolling(15).sum()
    vbase = v15.rolling(240, min_periods=120).median().shift(15)
    vz = v15 / vbase
    hi120 = hi.rolling(120).max().shift(1)
    share = (d["taker"].rolling(15).sum() / v15)
    btc = r15["BTCUSDT"] if "BTCUSDT" in r15 else pd.Series(0.0, index=c.index)
    out = {"jump_2pct_15m": r15 > 0.02,
           "jump_1pct_vol3x": (r15 > 0.01) & (vz > 3.0),
           "break_2h_high_vol2x": (c > hi120) & (vz > 2.0),
           "break_2h_high_buyers60": (c > hi120) & (share > 0.6),
           "idio_jump_1pct": r15.sub(btc, axis=0) > 0.01}
    return {k: v.loc[w] for k, v in out.items()}


def first_fires(mask: pd.DataFrame, gap: int = 60) -> list[tuple[pd.Timestamp, str]]:
    ev = []
    for s in mask.columns:
        last = None
        for t in mask.index[mask[s].fillna(False).to_numpy()]:
            if last is None or (t - last) >= pd.Timedelta(minutes=gap):
                ev.append((t, s))
            last = t
    return ev


def study(d: dict, mask: pd.DataFrame) -> dict:
    c = d["close"]
    rows = []
    for t, s in first_fires(mask):
        i = c.index.get_loc(t) + 1
        if i >= len(c):
            continue
        p0 = c[s].iloc[i]
        rec = {"t": str(t)[11:16], "symbol": s[:-4]}
        for h in HORIZONS:
            j = min(i + h, len(c) - 1)
            rec[f"f{h}"] = c[s].iloc[j] / p0 - 1.0 - COST if j - i >= h else np.nan
        seg = c[s].iloc[i:i + 240]
        rec["mfe240"] = seg.max() / p0 - 1.0
        rec["mae240"] = seg.min() / p0 - 1.0
        rows.append(rec)
    if not rows:
        return {"n": 0}
    f = pd.DataFrame(rows)
    out = {"n": int(len(f))}
    for h in HORIZONS:
        x = f[f"f{h}"].dropna()
        out[f"net_{h}m_mean_pct"] = round(float(x.mean()) * 100, 2) if len(x) else None
        out[f"hit_{h}m"] = round(float((x > 0).mean()), 2) if len(x) else None
    out["mfe240_median_pct"] = round(float(f["mfe240"].median()) * 100, 2)
    out["mae240_median_pct"] = round(float(f["mae240"].median()) * 100, 2)
    out["best"] = f.sort_values("f60", ascending=False).head(4)[["t", "symbol", "f60", "mfe240"]].round(4).to_dict("records")
    out["worst"] = f.sort_values("f60").head(3)[["t", "symbol", "f60", "mae240"]].round(4).to_dict("records")
    return out


def base_rate(d: dict, w: slice) -> dict:
    c = d["close"].loc[w]
    out = {}
    for h in HORIZONS:
        f = (c.shift(-h) / c - 1.0 - COST).stack()
        out[f"net_{h}m_mean_pct"] = round(float(f.mean()) * 100, 3)
        out[f"hit_{h}m"] = round(float((f > 0).mean()), 2)
    return out


def lead_lag(d: dict, w: slice) -> dict:
    r = d["close"].loc[w].pct_change()
    if "BTCUSDT" not in r:
        return {}
    btc = r["BTCUSDT"]
    alts = r.drop(columns="BTCUSDT")
    return {f"lag{k}m": round(float(alts.corrwith(btc.shift(k)).median()), 3) for k in (0, 1, 2, 5)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-30T20:00Z")
    a = ap.parse_args(argv)
    start = pd.Timestamp(a.start)
    syms = universe("momentum_top3_30m")
    d = minute_frames(syms, start)
    w = slice(start, None)
    c = d["close"].loc[w]
    moves = []
    for s in c.columns:
        moves.append({"symbol": s[:-4], "window_pct": round((c[s].iloc[-1] / c[s].iloc[0] - 1) * 100, 2), **best_leg(c[s].dropna())})
    moves.sort(key=lambda m: -m["best_leg_pct"])
    trig = triggers(d, w)
    res = {"window": [str(c.index[0]), str(c.index[-1])], "moves": moves,
           "base_rate": base_rate(d, w), "lead_lag_btc_to_alts": lead_lag(d, w),
           "triggers": {k: study(d, m) for k, m in trig.items()},
           "hour_of_best_legs": pd.Series([m["from"][:2] for m in moves[:10]]).value_counts().to_dict()}
    (RESULTS / "overnight_patterns.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "moves"}, indent=1, default=str))
    print("top legs:", [(m["symbol"], m["best_leg_pct"], m["from"], m["to"], m["window_pct"]) for m in moves[:10]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
