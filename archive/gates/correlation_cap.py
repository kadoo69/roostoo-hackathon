"""Does correlation awareness help, beyond the effect of holding less?

Declared at config/correlation_cap.yaml. Every arm that changes gross exposure
is scored against a beta-matched control, because
DECISIONS.md#beta-is-the-only-screen3-lever established that any exposure
reduction moves Screen 3 up and qualification probability down on its own.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import yaml

from core.config import RESULTS, ROOT
from gates.concentration import context, net_daily, rank_score, stats
from archive.signals import correlation

warnings.filterwarnings("ignore")
POOL = 30


def declaration() -> dict:
    with (ROOT / "config" / "correlation_cap.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def book(close, qv, sel, pos, kind):
    """The two live configurations, rebuilt: bot_c_5names and bot_a_4h."""
    live = pos.where(sel, 0.0) > 0.5
    if kind == "top5_momentum":
        score = rank_score("momentum", close, qv, pos)
        masked = score.where(live)
        chosen = (masked.rank(axis=1, ascending=False) <= 5) & live
        w = chosen.astype(float) / 5.0
    elif kind == "all_signals_div20":
        score = rank_score("liquidity", close, qv, pos)
        masked = score.where(live)
        w = live.astype(float) / 20.0
    else:
        raise ValueError(kind)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0), masked


def score(w, close, eff, win):
    d = net_daily(w.loc[win[0]:win[1]], close.loc[win[0]:win[1]])
    s = stats(d)
    ww = w.loc[win[0]:win[1]]
    s["mean_gross"] = round(float(ww.abs().sum(axis=1).mean()), 4)
    s["mean_names"] = round(float((ww > 0).sum(axis=1).mean()), 3)
    s["mean_eff_bets"] = round(float(eff.loc[win[0]:win[1]].mean()), 3)
    s["annual_turnover"] = round(float(
        (ww - ww.shift(1)).abs().sum(axis=1).sum() / max(len(ww) / (365 * 6), 1e-9)), 1)
    return s


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    fit, hold = tuple(m["fit_window"]), tuple(m["holdout_window"])
    close, qv, sel, pos = context(POOL)

    specs = []
    for cb in g["corr_bars"]:
        for e in g["scale_exponent"]:
            specs.append(dict(rule="scale", bars=cb, exponent=e))
        for sh in g["reweight_shrinkage"]:
            specs.append(dict(rule="reweight", bars=cb, shrinkage=sh))
    for th in g["cluster_threshold"]:
        for mp in g["max_per_cluster"]:
            specs.append(dict(rule="cluster_cap", bars=g["corr_bars"][-1],
                              threshold=th, max_per_cluster=mp))

    results = []
    for kind in cfg["books"]:
        w0, rank = book(close, qv, sel, pos, kind)
        _, eff0 = correlation.apply(w0, close, "baseline", g["corr_bars"][-1])
        base = {t: score(w0, close, eff0, win)
                for t, win in (("fit", fit), ("hold", hold))}
        results.append({"book": kind, "arm": "baseline", "params": {},
                        "fit": base["fit"], "hold": base["hold"]})
        for sp in specs:
            w1, eff1 = correlation.apply(w0, close, rank=rank, **sp)
            row = {"book": kind, "arm": sp["rule"], "params": sp}
            for t, win in (("fit", fit), ("hold", hold)):
                s = score(w1, close, eff1, win)
                row[t] = s
                if s["mean_gross"] < base[t]["mean_gross"] - 1e-6:
                    wc = correlation.beta_match(
                        w0.loc[win[0]:win[1]], s["mean_gross"])
                    row[t + "_control"] = score(wc, close, eff0, win)
                else:
                    row[t + "_control"] = None
            results.append(row)
            h, hc = row["hold"], row["hold_control"]
            ref = hc or base["hold"]
            print(f"{kind:18s} {sp['rule']:12s} {str({k: v for k, v in sp.items() if k != 'rule'}):46s} "
                  f"gross={h['mean_gross']:.3f} eff={h['mean_eff_bets']:.2f} "
                  f"S3={h['screen3']:+.3f} vs ctrl {ref['screen3']:+.3f} "
                  f"P+={h['p_return_positive']:.3f} vs {ref['p_return_positive']:.3f}", flush=True)

    out = {"declaration": "config/correlation_cap.yaml", "pool": POOL,
           "fit_window": list(fit), "holdout_window": list(hold),
           "configs": len([r for r in results if r["arm"] != "baseline"]),
           "results": results}
    (RESULTS / "correlation_cap.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS / 'correlation_cap.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
