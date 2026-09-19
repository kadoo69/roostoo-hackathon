from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml
from scipy import stats as sps

from core.config import RESULTS, ROOT
from data import daily, flow, universe as ru
from gates.concentration import net_daily, stats
from signals import donchian

warnings.filterwarnings("ignore")
A, B, END = "2023-01-01", "2025-01-01", "2026-09-19"
ENTRY, EXIT, MOM, NPOS, POOL = 20, 10, 40, 5, 30


def declaration():
    with (ROOT / "config" / "take_profit.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def ranked_mask(close, sel):
    pos = donchian.position(close, ENTRY, "lowchannel", EXIT)
    live = pos.where(sel, 0.0) > 0.5
    score = close / close.shift(MOM) - 1.0
    rank = score.where(live).rank(axis=1, ascending=False)
    return (rank <= NPOS) & live


def apply_take_profit(chosen: pd.DataFrame, close: pd.DataFrame,
                      tp: float | None, mode: str) -> pd.DataFrame:
    if tp is None:
        return chosen.astype(float)
    px = close.to_numpy(dtype=float)
    ch = chosen.to_numpy(dtype=bool)
    rows, cols = px.shape
    out = np.zeros((rows, cols))
    entry = np.full(cols, np.nan)
    frac = np.zeros(cols)
    banked = np.zeros(cols, dtype=bool)
    for i in range(rows):
        p = px[i]
        newly = ch[i] & (frac == 0.0)
        entry = np.where(newly, p, entry)
        frac = np.where(newly, 1.0, frac)
        banked = np.where(newly, False, banked)
        gone = (~ch[i]) & (frac > 0.0)
        frac = np.where(gone, 0.0, frac)
        entry = np.where(gone, np.nan, entry)
        hit = (frac > 0.0) & np.isfinite(entry) & (p >= entry * (1.0 + tp)) & (~banked)
        if mode == "full":
            frac = np.where(hit, 0.0, frac)
            entry = np.where(hit, np.nan, entry)
        else:
            frac = np.where(hit, frac * 0.5, frac)
            banked = np.where(hit, True, banked)
        out[i] = frac
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    p = flow.panel("4h")
    close = p["close"]
    trad = set(ru.tradable_symbols()) - ru.STABLES
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    for s in sorted(trad & set(close.columns)):
        rmask[s] = True
    sel = ru.pit_top_n(pdl, base, top_n=POOL).reindex(
        close.index, method="ffill").fillna(False) & rmask
    chosen = ranked_mask(close, sel)

    rows = []
    for tp in g["take_profit_pct"]:
        modes = ["full"] if tp is None else ["full", "half"]
        for mode in modes:
            frac = apply_take_profit(chosen, close, None if tp is None else tp / 100.0, mode)
            w = frac / float(NPOS)
            gr = w.abs().sum(axis=1)
            w = w.div(np.maximum(1.0, gr), axis=0)
            dr = net_daily(w, close)
            active = (frac > 1e-12)
            flips = float(((active != active.shift(1)).sum().sum()) / 2.0)
            row = {"take_profit_pct": tp, "mode": "none" if tp is None else mode,
                   "mean_names": round(float(active.sum(axis=1).mean()), 2),
                   "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4),
                   "mean_hold_bars": round(float(active.sum().sum() / max(flips, 1)), 1),
                   "turnover_yr": round(float((w - w.shift(1)).abs().sum(axis=1).mean()
                                              * 365 * 6), 1)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                s = stats(seg)
                for k, v in s.items():
                    row[f"{tag}_{k}"] = v
                if len(seg.dropna()) > 30:
                    row[f"{tag}_skew"] = round(float(sps.skew(seg.dropna())), 3)
            rows.append(row)

    f = pd.DataFrame(rows)
    rho = f["fit_screen3"].corr(f["hold_screen3"], method="spearman")
    out = {"declaration": "config/take_profit.yaml", "results": rows,
           "fit_vs_hold_spearman": round(float(rho), 4),
           "baseline": f[f["mode"] == "none"].iloc[0].to_dict(),
           "best_on_fit": f.loc[f.fit_screen3.idxmax()].to_dict(),
           "best_on_hold": f.loc[f.hold_screen3.idxmax()].to_dict()}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "take_profit.json").write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
