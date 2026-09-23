"""Cross-sectional reversal, split by liquidity sleeve and by sign.

Declared at config/meanrev_xs.yaml. The headline is not any single number, it
is whether the liquidity contrast runs the way the literature says it must:
short-horizon reversal on illiquid coins, short-horizon momentum on liquid
ones. A reversal result on the liquid sleeve would contradict the paper this
was built from and is treated as a construction fault, not a discovery.
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import daily as dly
from data import universe as ru
from gates.scalp_meanrev import stats

warnings.filterwarnings("ignore")


def declaration() -> dict:
    with (ROOT / "config" / "meanrev_xs.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def context():
    """Daily closes plus a point-in-time liquidity rank, lagged one day."""
    p = dly.build()
    close, qv = p["close"], p["quote_volume"]
    trad = sorted(set(ru.tradable_symbols()) & set(close.columns) - ru.STABLES)
    close, qv = close[trad], qv[trad]
    adv = qv.rolling(180, min_periods=60).median().shift(1)
    rank = adv.rank(axis=1, ascending=False)        # 1 = most liquid
    return close, adv, rank


def sleeve_mask(rank: pd.DataFrame, sleeve: str) -> pd.DataFrame:
    if sleeve == "liquid":
        return rank <= 30
    if sleeve == "illiquid":
        return (rank > 30) & (rank <= 66)
    raise ValueError(sleeve)


def weights(close, rank, sleeve, formation, holding, direction, n=5):
    """Equal-weight the n most extreme names, rebalanced every `holding` days.

    The formation return ends on the prior day and selection is held fixed for
    the whole holding period, so nothing is chosen using a price the book could
    not have seen.
    """
    ret = (close / close.shift(formation) - 1.0).shift(1)
    elig = sleeve_mask(rank, sleeve) & ret.notna() & close.notna()
    scored = ret.where(elig)
    asc = direction == "reversal"                   # reversal buys the losers
    r = scored.rank(axis=1, ascending=asc)
    chosen = (r <= n) & elig
    w = chosen.astype(float) / float(n)
    if holding > 1:                                 # rebalance every k days
        keep = pd.Series(np.arange(len(w)) % holding == 0, index=w.index)
        w = w.where(keep).ffill()
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0).fillna(0.0)


def score(w, close, fee_bps, win):
    ww, cc = w.loc[win[0]:win[1]], close.loc[win[0]:win[1]]
    ret = cc.reindex(columns=ww.columns).pct_change(fill_method=None)
    gross = (ww.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (ww - ww.shift(1)).abs().sum(axis=1)
    net = (gross - (turn * fee_bps / 1e4).shift(1).fillna(0.0)).fillna(0.0)
    s = stats(net.dropna())
    if not s:
        return {}
    yrs = max(len(ww) / 365.0, 1e-9)
    s["annual_turnover"] = round(float(turn.sum() / yrs), 1)
    s["annual_cost_drag"] = round(s["annual_turnover"] * fee_bps / 1e4, 5)
    s["mean_gross"] = round(float(ww.abs().sum(axis=1).mean()), 4)
    s["gross_sharpe"] = (stats(gross.dropna()) or {}).get("sharpe")
    return s


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    close, adv, rank = context()
    fit, hold = tuple(m["fit_window"]), tuple(m["holdout_window"])
    fees = [float(x) for x in m["fee_bps"]]
    results = []
    for sleeve, f, h, d in itertools.product(
            g["sleeve"], g["formation_days"], g["holding_days"], g["direction"]):
        w = weights(close, rank, sleeve, f, h, d, g["n_positions"])
        row = {"sleeve": sleeve, "formation_days": f, "holding_days": h,
               "direction": d}
        for tag, win in (("fit", fit), ("hold", hold)):
            row[tag] = {f"fee{int(x)}": score(w, close, x, win) for x in fees}
        results.append(row)
        hh = row["hold"]["fee5"]
        print(f"{sleeve:9s} form={f:3d}d hold={h}d {d:9s} | "
              f"S3={hh.get('screen3', float('nan')):+7.3f} "
              f"Sh={hh.get('sharpe', float('nan')):+6.2f} "
              f"turn={hh.get('annual_turnover', 0):7.1f} "
              f"drag={100*(hh.get('annual_cost_drag') or 0):5.1f}% "
              f"P(+)={hh.get('p_return_positive', float('nan')):.3f}", flush=True)

    # the declared test: reversal minus momentum, per sleeve and horizon
    contrast = []
    for sleeve, f, h in itertools.product(g["sleeve"], g["formation_days"], g["holding_days"]):
        pick = {r["direction"]: r for r in results
                if r["sleeve"] == sleeve and r["formation_days"] == f and r["holding_days"] == h}
        if len(pick) != 2:
            continue
        row = {"sleeve": sleeve, "formation_days": f, "holding_days": h}
        for tag in ("fit", "hold"):
            rv = pick["reversal"][tag]["fee5"].get("screen3")
            mo = pick["momentum"][tag]["fee5"].get("screen3")
            row[f"{tag}_rev_minus_mom"] = (round(rv - mo, 3)
                                           if rv is not None and mo is not None else None)
        contrast.append(row)

    out = {"declaration": "config/meanrev_xs.yaml", "configs": len(results),
           "results": results, "contrast_reversal_minus_momentum": contrast}
    (RESULTS / "meanrev_xs.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'meanrev_xs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
