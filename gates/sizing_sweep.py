from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import daily, flow, universe as ru
from signals import donchian

warnings.filterwarnings("ignore")
FEE = 0.0005
A, B, END = "2023-01-01", "2025-01-01", "2026-09-19"
WINDOW, SCREEN2 = 14, 0.05


def declaration():
    with (ROOT / "config" / "sizing_sweep.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def context():
    p = flow.panel("4h")
    close = p["close"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    trad = sorted(set(ru.tradable_symbols()) & set(close.columns) - ru.STABLES)
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    rmask[trad] = True
    pos = donchian.position(close, 20, "lowchannel", 10)
    return close, pdl, base, rmask, pos


def book(pos, close, pdl, base, rmask, pool, divisor, max_gross):
    sel = ru.pit_top_n(pdl, base, top_n=pool).reindex(
        close.index, method="ffill").fillna(False) & rmask
    w = pos.where(sel, 0.0) / float(divisor)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g / max_gross), axis=0)


def net_daily(w, close):
    ret = close.pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - (turn * FEE).shift(1).fillna(0.0)).fillna(0.0)
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna()


def stats(dr):
    dr = dr.dropna()
    if len(dr) < 60 or dr.std() == 0:
        return {}
    eq = (1.0 + dr).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    cagr = float(eq.iloc[-1]) ** (365.0 / len(dr)) - 1.0
    down = float(np.sqrt((dr.clip(upper=0.0) ** 2).mean()) * np.sqrt(365))
    sh = float(dr.mean() / dr.std() * np.sqrt(365))
    so = float(dr.mean() * 365 / down) if down > 0 else 0.0
    cm = cagr / abs(dd) if dd < 0 else 0.0
    cap = lambda v: float(np.clip(v, -5, 5))
    n = len(dr) - WINDOW + 1
    m = np.stack([dr.to_numpy()[i:i + WINDOW] for i in range(n)])
    e14 = np.cumprod(1.0 + m, axis=1)
    r14 = e14[:, -1] - 1.0
    return {"cagr": round(cagr, 5), "sharpe": round(sh, 4), "sortino": round(so, 4),
            "calmar": round(cm, 4), "max_drawdown": round(dd, 5),
            "screen3": round(0.4 * cap(so) + 0.3 * cap(sh) + 0.3 * cap(cm), 4),
            "p_return_positive": round(float((r14 > 0).mean()), 4),
            "p_clears_screen2": round(float((r14 > SCREEN2).mean()), 4)}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    close, pdl, base, rmask, pos = context()
    rows = []
    for pool in g["top_n_pool"]:
        for div in g["weight_divisor"]:
            w = book(pos, close, pdl, base, rmask, pool, div, g["max_gross_primary"])
            dr = net_daily(w, close)
            row = {"pool": pool, "divisor": div, "max_gross": g["max_gross_primary"],
                   "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4),
                   "mean_names": round(float((w.abs() > 1e-12).sum(axis=1).mean()), 2)}
            for tag, seg in (("fit", dr.loc[A:B]), ("holdout", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            rows.append(row)

    f = pd.DataFrame(rows)
    best_fit = f.loc[f["fit_screen3"].idxmax()]
    best_hold = f.loc[f["holdout_screen3"].idxmax()]
    extra = []
    for mg in g["max_gross_secondary"]:
        w = book(pos, close, pdl, base, rmask, int(best_fit["pool"]),
                 int(best_fit["divisor"]), mg)
        dr = net_daily(w, close)
        row = {"pool": int(best_fit["pool"]), "divisor": int(best_fit["divisor"]),
               "max_gross": mg,
               "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4),
               "mean_names": round(float((w.abs() > 1e-12).sum(axis=1).mean()), 2)}
        for tag, seg in (("fit", dr.loc[A:B]), ("holdout", dr.loc[B:END])):
            for k, v in stats(seg).items():
                row[f"{tag}_{k}"] = v
        extra.append(row)

    rho = f["fit_screen3"].corr(f["holdout_screen3"], method="spearman")
    out = {"declaration": "config/sizing_sweep.yaml",
           "primary": rows, "gross_variants": extra,
           "best_on_fit": {k: best_fit[k] for k in
                           ("pool", "divisor", "fit_screen3", "holdout_screen3")},
           "best_on_holdout": {k: best_hold[k] for k in
                               ("pool", "divisor", "fit_screen3", "holdout_screen3")},
           "fit_vs_holdout_spearman": round(float(rho), 4),
           "incumbent_pool30_div20": {
               k: float(f[(f["pool"] == 30) & (f["divisor"] == 20)][k].iloc[0])
               for k in ("fit_screen3", "holdout_screen3", "fit_sharpe",
                         "holdout_sharpe")}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "sizing_sweep.json").write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
