"""Asymmetric ratchet against its matched uniform-lookback control.

Declared at config/ratchet.yaml. The test is NOT whether a ratchet beats the
live baseline - a shorter stop can do that by accident. It is whether the
ratchet beats simply running that same short lookback on every position.
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import yaml

from core.config import RESULTS, ROOT
from gates.concentration import context, net_daily, rank_score, stats
from signals import ratchet

warnings.filterwarnings("ignore")
POOL = 30


def declaration() -> dict:
    with (ROOT / "config" / "ratchet.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def book(pos, close, qv, sel, kind):
    live = pos.where(sel, 0.0) > 0.5
    if kind == "donchian_4h":
        w = live.astype(float) / 20.0
    elif kind == "momentum_top5_4h":
        sc = rank_score("momentum", close, qv, pos).where(live)
        w = ((sc.rank(axis=1, ascending=False) <= 5) & live).astype(float) / 5.0
    else:
        raise ValueError(kind)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def kept_share(bookw, close) -> dict:
    """Mean share of each trade's peak that it actually realised.

    This is the quantity the rule targets. A configuration that lifts Screen 3
    without lifting this is working through some other channel, and the stated
    mechanism would be wrong.
    """
    arr = np.asarray(bookw > 0, dtype=bool)
    px = close.to_numpy(float)
    kept = []
    for j in range(arr.shape[1]):
        col, s = arr[:, j], px[:, j]
        i = 0
        while i < len(col):
            if not col[i]:
                i += 1
                continue
            k = i
            while k + 1 < len(col) and col[k + 1]:
                k += 1
            path = s[i:k + 1]
            if len(path) > 1 and np.isfinite(path).all() and path[0] > 0:
                peak = path.max() / path[0] - 1.0
                real = path[-1] / path[0] - 1.0
                # Only trades that actually built a meaningful peak. A ratio of
                # realised to a peak of +0.1% is arbitrarily large in either
                # direction and averaging those produced values like -37, which
                # is not a share of anything.
                if peak >= 0.02:
                    kept.append((real, peak))
            i = k + 1
    if not kept:
        return {"kept_share": float("nan"), "n_trades": 0}
    real = np.array([r for r, _ in kept])
    peak = np.array([p for _, p in kept])
    return {"kept_share": round(float(real.sum() / peak.sum()), 4),
            "mean_peak_pct": round(float(peak.mean() * 100), 2),
            "mean_realised_pct": round(float(real.mean() * 100), 2),
            "n_trades": int(len(kept))}


def score(w, close, win):
    ww, cc = w.loc[win[0]:win[1]], close.loc[win[0]:win[1]]
    dr = net_daily(ww, cc)
    s = stats(dr)
    if not s:
        return {}
    # gates.concentration.stats does not report skew, and skew is the declared
    # kill criterion here (take-profits died on it), so it is computed locally
    s["skew"] = round(float(dr.dropna().skew()), 4)
    yrs = max(len(ww) / (365 * 6), 1e-9)
    turn = (ww - ww.shift(1)).abs().sum(axis=1).sum()
    s["annual_turnover"] = round(float(turn / yrs), 1)
    s["annual_cost_drag"] = round(s["annual_turnover"] * 0.0005, 5)
    s["mean_gross"] = round(float(ww.abs().sum(axis=1).mean()), 4)
    s.update({f"peak_{k}": v for k, v in kept_share(ww, cc).items()})
    return s


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    fit, hold = tuple(m["fit_window"]), tuple(m["holdout_window"])
    close, qv, sel, _ = context(POOL)
    results = []

    for kind in g["books"]:
        # uniform controls first, so every ratchet has its match available
        for ub in g["uniform_controls"]:
            pos = ratchet.position(close, 20, ub, ub, 0.0)
            w = book(pos, close, qv, sel, kind)
            row = {"book": kind, "arm": "uniform", "bars": ub,
                   "fit": score(w, close, fit), "hold": score(w, close, hold)}
            results.append(row)
            h = row["hold"]
            print(f"{kind:18s} uniform bars={ub:2d}          | S3={h.get('screen3',0):+7.3f} "
                  f"skew={h.get('skew',0):+6.2f} maxDD={h.get('max_drawdown',0)*100:+6.1f}% "
                  f"kept={h.get('peak_kept_share',0):.3f} turn={h.get('annual_turnover',0):6.1f}",
                  flush=True)
        for tg, tb in itertools.product(g["trigger_gain"], g["tight_bars"]):
            pos = ratchet.position(close, 20, g["base_bars"], tb, float(tg))
            w = book(pos, close, qv, sel, kind)
            row = {"book": kind, "arm": "ratchet", "trigger_gain": tg,
                   "tight_bars": tb, "base_bars": g["base_bars"],
                   "fit": score(w, close, fit), "hold": score(w, close, hold)}
            results.append(row)
            h = row["hold"]
            print(f"{kind:18s} ratchet trig={tg:.2f} tight={tb:2d} | S3={h.get('screen3',0):+7.3f} "
                  f"skew={h.get('skew',0):+6.2f} maxDD={h.get('max_drawdown',0)*100:+6.1f}% "
                  f"kept={h.get('peak_kept_share',0):.3f} turn={h.get('annual_turnover',0):6.1f}",
                  flush=True)

    out = {"declaration": "config/ratchet.yaml", "configs": len(results),
           "results": results}
    (RESULTS / "ratchet.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'ratchet.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
