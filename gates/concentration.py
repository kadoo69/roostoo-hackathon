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
    with (ROOT / "config" / "concentration.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def context(pool):
    p = flow.panel("4h")
    close = p["close"]
    qv = p["quote_volume"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    trad = sorted(set(ru.tradable_symbols()) & set(close.columns) - ru.STABLES)
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    rmask[trad] = True
    sel = ru.pit_top_n(pdl, base, top_n=pool).reindex(
        close.index, method="ffill").fillna(False) & rmask
    pos = donchian.position(close, 20, "lowchannel", 10)
    return close, qv, sel, pos


def rank_score(rule, close, qv, pos):
    if rule == "liquidity":
        return qv.rolling(180).median().shift(1)
    if rule == "breakout":
        upper = close.rolling(20).max().shift(1)
        return (close / upper - 1.0)
    if rule == "momentum":
        return close / close.shift(20) - 1.0
    if rule == "lowvol":
        return -close.pct_change().rolling(20).std().shift(1)
    raise ValueError(rule)


def build(close, qv, sel, pos, rule, n):
    score = rank_score(rule, close, qv, pos)
    live = pos.where(sel, 0.0) > 0.5
    masked = score.where(live)
    rank = masked.rank(axis=1, ascending=False)
    chosen = (rank <= n) & live
    w = chosen.astype(float) / float(n)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


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
    k = len(dr) - WINDOW + 1
    m = np.stack([dr.to_numpy()[i:i + WINDOW] for i in range(k)])
    r14 = np.cumprod(1.0 + m, axis=1)[:, -1] - 1.0
    return {"cagr": round(cagr, 5), "sharpe": round(sh, 4), "sortino": round(so, 4),
            "calmar": round(cm, 4), "max_drawdown": round(dd, 5),
            "screen3": round(0.4 * cap(so) + 0.3 * cap(sh) + 0.3 * cap(cm), 4),
            "p_return_positive": round(float((r14 > 0).mean()), 4),
            "p_clears_screen2": round(float((r14 > SCREEN2).mean()), 4)}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    close, qv, sel, pos = context(g["pool"])
    rows = []
    for rule in g["ranking_rules"]:
        for n in g["n_positions"]:
            w = build(close, qv, sel, pos, rule, n)
            dr = net_daily(w, close)
            row = {"rule": rule, "n": n,
                   "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4),
                   "mean_names": round(float((w.abs() > 1e-12).sum(axis=1).mean()), 2)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            rows.append(row)
    f = pd.DataFrame(rows)
    rho = f["fit_screen3"].corr(f["hold_screen3"], method="spearman")
    out = {"declaration": "config/concentration.yaml", "results": rows,
           "fit_vs_hold_spearman": round(float(rho), 4),
           "best_on_fit": f.loc[f.fit_screen3.idxmax()].to_dict(),
           "best_on_hold": f.loc[f.hold_screen3.idxmax()].to_dict()}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "concentration.json").write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
