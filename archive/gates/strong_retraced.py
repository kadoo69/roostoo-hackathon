"""Strong-but-retraced entry, against a new-high control and a weak-retraced control.

Declared at config/strong_retraced.yaml. The hypothesis came from four coins
that were up on the day it was written, so it is tested on every name over the
full history and scored only against controls sharing its universe.
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates.concentration import context, net_daily, rank_score, stats

warnings.filterwarnings("ignore")
POOL, ENTRY, EXIT_LB = 30, 20, 10


def declaration() -> dict:
    with (ROOT / "config" / "strong_retraced.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def positions(close, arm, strong_bars, strong_thresh, retrace_max, max_hold):
    """Hold from a qualifying entry until the 10-bar low breaks or the hold caps.

    Entry and exit levels come from bars strictly before the current one, and
    the exit is the live channel floor so that any measured difference is
    attributable to the entry state alone.
    """
    upper = close.rolling(ENTRY).max().shift(1)
    floor = close.rolling(EXIT_LB).min().shift(1)
    strength = close / close.shift(strong_bars) - 1.0
    gap = upper / close - 1.0                       # >0 means below the high

    strong = strength >= strong_thresh
    if arm == "weak_retraced":
        strong = strength < strong_thresh
    if arm == "new_high":
        cond = (close > upper) & (strength >= strong_thresh)
    else:
        cond = strong & (gap > 0) & (gap <= retrace_max)

    c = cond.to_numpy(bool)
    px = close.to_numpy(float)
    fl = floor.to_numpy(float)
    rows, cols = px.shape
    out = np.zeros((rows, cols), dtype=float)
    held = np.zeros(cols, dtype=bool)
    age = np.zeros(cols, dtype=int)
    for i in range(rows):
        p, f = px[i], fl[i]
        ok = np.isfinite(p) & np.isfinite(f)
        exiting = held & ok & ((p < f) | (age >= max_hold))
        held &= ~exiting
        age = np.where(exiting, 0, age)
        entering = (~held) & ok & c[i]
        held |= entering
        age = np.where(entering, 0, age + held)
        held &= np.isfinite(p)
        out[i] = held
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def book(pos, close, qv, sel, kind):
    live = (pos > 0.5) & sel
    if kind == "donchian_4h":
        w = live.astype(float) / 20.0
    else:
        sc = rank_score("momentum", close, qv, pos).where(live)
        w = ((sc.rank(axis=1, ascending=False) <= 5) & live).astype(float) / 5.0
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def score(w, close, win):
    ww, cc = w.loc[win[0]:win[1]], close.loc[win[0]:win[1]]
    s = stats(net_daily(ww, cc))
    if not s:
        return {}
    dr = net_daily(ww, cc)
    s["skew"] = round(float(dr.dropna().skew()), 4)
    s["mean_gross"] = round(float(ww.abs().sum(axis=1).mean()), 4)
    s["n_entries"] = int(((ww > 0) & (ww.shift(1).fillna(0) == 0)).sum().sum())
    yrs = max(len(ww) / (365 * 6), 1e-9)
    s["annual_turnover"] = round(float((ww - ww.shift(1)).abs().sum(axis=1).sum() / yrs), 1)
    return s


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    fit, hold = tuple(m["fit_window"]), tuple(m["holdout_window"])
    close, qv, sel, _ = context(POOL)
    results = []
    for kind, st, rm, mh in itertools.product(
            g["books"], g["strong_thresh"], g["retrace_max"], g["max_hold_bars"]):
        row = {"book": kind, "strong_thresh": st, "retrace_max": rm, "max_hold_bars": mh}
        for arm in ("strong_retraced", "new_high", "weak_retraced"):
            pos = positions(close, arm, g["strong_bars"], st, rm, mh)
            w = book(pos, close, qv, sel, kind)
            row[arm] = {"fit": score(w, close, fit), "hold": score(w, close, hold)}
        h, nh, wr = row["strong_retraced"], row["new_high"], row["weak_retraced"]
        ok = (h["fit"].get("screen3", -9) > max(nh["fit"].get("screen3", -9), wr["fit"].get("screen3", -9))
              and h["hold"].get("screen3", -9) > max(nh["hold"].get("screen3", -9), wr["hold"].get("screen3", -9)))
        row["passes"] = bool(ok)
        results.append(row)
        print(f"{kind:17s} str>{st:.2f} ret<{rm:.2f} hold{mh:3d} | "
              f"S3 fit {h['fit'].get('screen3',0):+6.3f} hold {h['hold'].get('screen3',0):+6.3f} | "
              f"vs newhigh {nh['hold'].get('screen3',0):+6.3f} vs weakret {wr['hold'].get('screen3',0):+6.3f} "
              f"| n={h['hold'].get('n_entries',0):4d} {'PASS' if ok else ''}", flush=True)
    out = {"declaration": "config/strong_retraced.yaml", "configs": len(results),
           "passes": sum(r["passes"] for r in results), "results": results}
    (RESULTS / "strong_retraced.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\npassing both controls on both windows: {out['passes']} of {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
