"""Wide-tick names: what every gate assumed, what live can trade, and what paying their spread costs.

DECISIONS.md#live-validation-2026-09-23. Run: python3 -m gates.tick_universe
"""
import numpy as np
import pandas as pd
from data import universe as ru
from gates import positioning_edges as pe
from gates.concentration import context, rank_score, net_daily
specs = ru.tradable_symbols()
close, qv, sel, pos = context(30)
tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
tick_bps = (tick / close[tick.index]) * 1e4
ok = (tick_bps <= 5.0).reindex(columns=close.columns).fillna(False)
W = {"pre": ("2022-01-15", "2023-01-01"), "fit": ("2023-01-01", "2025-01-01"), "holdout": ("2025-01-01", "2026-09-19")}
print("share of selected name-bars removed by the tick filter:",
      {t: round(float((sel & ~ok).loc[a:b].sum().sum() / sel.loc[a:b].sum().sum()), 4) for t, (a, b) in W.items()})
print("names ever removed while selected (holdout):", sorted(c for c in close.columns if (sel & ~ok).loc["2025":, c].any()))
score = rank_score("momentum", close, qv, pos, 40)
for name, n, full in (("donchian_4h", None, False), ("momentum_top3_full", 3, True), ("momentum_top5_4h", 5, False)):
    for tag, s2 in (("current", sel), ("tick_filtered", sel & ok)):
        live = pos.where(s2, 0.0) > 0.5
        ch = (score.where(live).rank(axis=1, ascending=False) <= n) & live if n else live
        w = ch.astype(float)
        w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) if full else w / (n or 20)
        w = w.div(np.maximum(1.0, w.sum(axis=1)), axis=0)
        d = net_daily(w, close)
        row = " ".join(f"{t} {pe.describe(d, a, b)['median_pct']:+.2f}/{pe.describe(d, a, b)['p_gt5']:.3f}/w{pe.describe(d, a, b)['worst_pct']:+.1f}" for t, (a, b) in W.items())
        print(f"{name:20s} {tag:14s} {row}")
print("\n--- trade wide-tick names, charging each name's own spread ---")
ret = close.pct_change(fill_method=None)
tb = tick_bps.reindex(columns=close.columns).fillna(0.0) / 1e4
def net_cost(w, extra):
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    dw = (w - w.shift(1)).abs()
    cost = (dw * (0.0005 + extra)).sum(axis=1)
    net = (gross - cost.shift(1).fillna(0.0)).fillna(0.0)
    return ((1.0 + net).resample("1D").prod() - 1.0).dropna()
for name, n, full in (("momentum_top3_full", 3, True), ("momentum_top5_4h", 5, False), ("donchian_4h", None, False)):
    live = pos.where(sel, 0.0) > 0.5
    ch = (score.where(live).rank(axis=1, ascending=False) <= n) & live if n else live
    w = ch.astype(float)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) if full else w / (n or 20)
    w = w.div(np.maximum(1.0, w.sum(axis=1)), axis=0)
    for label, extra in (("fee only (what every gate assumed)", tb * 0), ("+ half tick per side", tb / 2), ("+ full tick per side", tb), ("+ 2 ticks per side", tb * 2)):
        d = net_cost(w, extra)
        row = " ".join(f"{t} {pe.describe(d, a, b)['median_pct']:+.2f}/{pe.describe(d, a, b)['p_gt5']:.3f}" for t, (a, b) in W.items())
        print(f"{name:20s} {label:36s} {row}")
print("\n--- what live does today: rank includes wide-tick names, their orders are refused, the slot idles in cash ---")
for name, n, full in (("momentum_top3_full", 3, True), ("momentum_top5_4h", 5, False), ("donchian_4h", None, False)):
    live = pos.where(sel, 0.0) > 0.5
    ch = (score.where(live).rank(axis=1, ascending=False) <= n) & live if n else live
    w = ch.astype(float)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) if full else w / (n or 20)
    w = w.div(np.maximum(1.0, w.sum(axis=1)), axis=0)
    w = w.where(ok, 0.0)
    d = net_daily(w, close)
    row = " ".join(f"{t} {pe.describe(d, a, b)['median_pct']:+.2f}/{pe.describe(d, a, b)['p_gt5']:.3f}" for t, (a, b) in W.items())
    print(f"{name:20s} {'live today':36s} {row}")
