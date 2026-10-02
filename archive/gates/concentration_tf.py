from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import daily, flow, universe as ru
from gates.concentration import net_daily, stats
from signals import donchian

warnings.filterwarnings("ignore")
A, B, END = "2023-01-01", "2025-01-01", "2026-09-19"
BPD = {"1h": 24, "4h": 6, "8h": 3, "12h": 2, "1d": 1}


def declaration():
    with (ROOT / "config" / "concentration_tf.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    pool_daily = ru.pit_top_n(pdl, base, top_n=g["pool"])
    trad = set(ru.tradable_symbols()) - ru.STABLES

    rows = []
    for iv in g["intervals"]:
        p = flow.panel(iv)
        close = p["close"]
        rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
        for s in sorted(trad & set(close.columns)):
            rmask[s] = True
        sel = pool_daily.reindex(close.index, method="ffill").fillna(False) & rmask
        pos = donchian.position(close, 20, "lowchannel", 10)
        live = pos.where(sel, 0.0) > 0.5
        for mb in g["momentum_bars"]:
            score = close / close.shift(mb) - 1.0
            rank = score.where(live).rank(axis=1, ascending=False)
            chosen = (rank <= g["n_positions"]) & live
            w = chosen.astype(float) / float(g["n_positions"])
            gr = w.abs().sum(axis=1)
            w = w.div(np.maximum(1.0, gr), axis=0)
            dr = net_daily(w, close)
            row = {"interval": iv, "momentum_bars": mb,
                   "lookback_days": round(mb / BPD[iv], 2),
                   "mean_names": round(float((w.abs() > 1e-12).sum(axis=1).mean()), 2),
                   "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            rows.append(row)

    f = pd.DataFrame(rows)
    rho = f["fit_screen3"].corr(f["hold_screen3"], method="spearman")
    out = {"declaration": "config/concentration_tf.yaml", "results": rows,
           "fit_vs_hold_spearman": round(float(rho), 4),
           "best_on_fit": f.loc[f.fit_screen3.idxmax()].to_dict(),
           "best_on_hold": f.loc[f.hold_screen3.idxmax()].to_dict()}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "concentration_tf.json").write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
