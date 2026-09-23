"""Does checking the same exit level more often help?

Declared at config/exit_clock.yaml. Entry clock, channel and exit LEVEL are
held fixed at 4h; only the frequency of the comparison changes.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import yaml

from core.config import RESULTS, ROOT
from data import flow
from gates.concentration import context, rank_score, stats
from signals import exit_clock

warnings.filterwarnings("ignore")
POOL, FEE = 30, 0.0005


def declaration() -> dict:
    with (ROOT / "config" / "exit_clock.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def weights(pos_fast, sel, close_slow, qv, kind, fast_index):
    """Apply membership and the book's sizing rule to a fast-clock position.

    Ranking is deliberately taken from the SLOW clock and forward-filled: the
    declaration fixes re-ranking to 4h closes, so a name released early frees
    its slot but does not trigger a re-rank inside the bar.
    """
    # Both membership and ranking are slow-clock objects and must be carried
    # across on CLOSE times, not labels. A label-matched ffill leaks up to one
    # slow bar of future price into the ranking and inflates every fast arm.
    selF = exit_clock.to_fast(sel.astype(float), sel.index, fast_index).fillna(0.0) > 0.5
    live = (pos_fast > 0.5) & selF
    if kind == "top5_momentum":
        score = rank_score("momentum", close_slow, qv, None)
        rankF = exit_clock.to_fast(score, close_slow.index, fast_index)
        masked = rankF.where(live)
        chosen = (masked.rank(axis=1, ascending=False) <= 5) & live
        w = chosen.astype(float) / 5.0
    elif kind == "all_signals_div20":
        w = live.astype(float) / 20.0
    else:
        raise ValueError(kind)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def net_daily(w, close):
    ret = close.reindex(columns=w.columns).pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - (turn * FEE).shift(1).fillna(0.0)).fillna(0.0)
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna(), turn


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    fit, hold = tuple(m["fit_window"]), tuple(m["holdout_window"])
    close4, qv, sel, _ = context(POOL)
    # data.flow only caches 1h/4h/8h/12h/1d. 2h is built here by resampling
    # the 1h panel, which is the same construction flow itself uses.
    c1 = flow.panel("1h")["close"]
    panels = {"4h": close4, "1h": c1,
              "2h": c1.resample("2h").last().dropna(how="all")}
    results = []
    for kind in cfg["books"]:
        for clock in g["exit_clock"]:
            cf = panels[clock].reindex(columns=close4.columns)
            cf = cf[cf.index >= close4.index[0]]
            for eb in g["exit_bars"]:
                pos = exit_clock.position(close4, cf, 20, eb)
                w = weights(pos, sel, close4, qv, kind, cf.index)
                row = {"book": kind, "exit_clock": clock, "exit_bars": eb,
                       "baseline": clock == "4h" and eb == 10}
                for tag, win in (("fit", fit), ("hold", hold)):
                    ww = w.loc[win[0]:win[1]]
                    cc = cf.loc[win[0]:win[1]]
                    d, turn = net_daily(ww, cc)
                    s = stats(d)
                    yrs = max(len(ww) / (365 * (24 // int(clock[:-1]))), 1e-9)
                    s["annual_turnover"] = round(float(turn.sum() / yrs), 1)
                    s["annual_cost_drag"] = round(s["annual_turnover"] * FEE, 5)
                    s["mean_gross"] = round(float(ww.abs().sum(axis=1).mean()), 4)
                    s["mean_names"] = round(float((ww > 0).sum(axis=1).mean()), 3)
                    row[tag] = s
                results.append(row)
                h = row["hold"]
                print(f"{kind:18s} exit={clock:>3s} bars={eb:2d} "
                      f"{'BASE' if row['baseline'] else '    '} | "
                      f"S3={h['screen3']:+.3f} Sh={h['sharpe']:+.3f} "
                      f"maxDD={h['max_drawdown']*100:+6.1f}% "
                      f"P+={h['p_return_positive']:.3f} P5={h['p_clears_screen2']:.3f} "
                      f"turn={h['annual_turnover']:7.1f} drag={h['annual_cost_drag']*100:.2f}%",
                      flush=True)
    out = {"declaration": "config/exit_clock.yaml", "pool": POOL,
           "fit_window": list(fit), "holdout_window": list(hold),
           "configs": len(results), "results": results}
    (RESULTS / "exit_clock.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS / 'exit_clock.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
