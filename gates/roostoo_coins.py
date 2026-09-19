from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from core.config import RESULTS, prereg
from costs.model import CostModel
from data import daily, flow, universe
from portfolio.backtest import PERIODS_PER_YEAR, evaluate, run
from signals import donchian

warnings.filterwarnings("ignore")

INTERVAL = "4h"
ENTRY = 20
EXIT_LB = 10
SPLIT_A = "2023-01-01"
SPLIT_B = "2025-01-01"
END = "2026-09-19"
MIN_BARS = 1080
WINDOW = 14
SCREEN2 = 0.05


def screen3(d: dict) -> float:
    w = prereg()["objective"]["weights"]
    cap = prereg()["objective"]["calmar_cap"]
    def g(k):
        v = d[k]
        return 0.0 if v is None or not np.isfinite(v) else min(v, cap)
    return float(w["sortino"] * g("sortino") + w["sharpe"] * g("sharpe")
                 + w["calmar"] * g("calmar"))


def to_daily(net: pd.Series) -> pd.Series:
    return ((1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def metrics(dr: pd.Series) -> dict:
    dr = dr.dropna()
    if len(dr) < 60 or dr.std() == 0:
        return {}
    z = pd.Series(0.0, index=dr.index)
    d = evaluate(dr, dr, z, z, pd.Series(1.0, index=dr.index)).as_dict()
    return {"annual_return": d["annual_return"], "sharpe": d["sharpe"],
            "sortino": d["sortino"], "calmar": d["calmar"],
            "max_drawdown": d["max_drawdown"], "screen3": round(screen3(d), 4),
            "days": d["days"]}


def window_stats(dr: pd.Series) -> dict:
    a = dr.dropna().to_numpy()
    n = len(a) - WINDOW + 1
    if n <= 0:
        return {}
    m = np.stack([a[i:i + WINDOW] for i in range(n)])
    eq = np.cumprod(1.0 + m, axis=1)
    r = eq[:, -1] - 1.0
    return {"p_return_positive": round(float((r > 0).mean()), 4),
            "p_clears_screen2": round(float((r > SCREEN2).mean()), 4),
            "median_return_14d": round(float(np.median(r)), 5)}


def main() -> int:
    costs = CostModel.from_prereg()
    p = flow.panel(INTERVAL)
    close = p["close"]
    spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())
    ppy = PERIODS_PER_YEAR[INTERVAL]

    tradable = sorted(set(universe.tradable_symbols()) & set(close.columns)
                      - universe.STABLES)
    pos = donchian.position(close[tradable], ENTRY, "lowchannel", EXIT_LB)

    qv = p["quote_volume"][tradable]
    ret = close[tradable].pct_change()

    rows = []
    for sym in tradable:
        c = close[[sym]].dropna()
        if len(c) < MIN_BARS:
            continue
        w = pos[[sym]].reindex(c.index).fillna(0.0)
        net, _, gross = run(w, c, spreads[[sym]].reindex(c.index), costs, "LIMIT", ppy)
        dr = to_daily(net)
        row = {"symbol": sym, "first_bar": str(c.index.min().date()),
               "bars": int(len(c))}
        for tag, seg in (("A", dr.loc[SPLIT_A:SPLIT_B]), ("B", dr.loc[SPLIT_B:END]),
                         ("all", dr.loc[SPLIT_A:END])):
            m = metrics(seg)
            for k, v in m.items():
                row[f"{tag}_{k}"] = v
            if tag == "B":
                row.update({f"B_{k}": v for k, v in window_stats(seg).items()})
        sl = slice(SPLIT_A, SPLIT_B)
        row["A_ann_vol"] = round(float(ret[sym].loc[sl].std() * np.sqrt(365 * 6)), 4)
        row["A_median_daily_qv_musd"] = round(
            float(qv[sym].loc[sl].resample("1D").sum().median() / 1e6), 3)
        row["A_time_in_market"] = round(float(pos[sym].loc[sl].mean()), 4)
        row["A_autocorr_1d"] = round(float(
            ret[sym].loc[sl].resample("1D").sum().autocorr(1) or 0.0), 4)
        rows.append(row)

    f = pd.DataFrame(rows)
    both = f.dropna(subset=["A_sharpe", "B_sharpe"])
    persistence = {}
    for metric in ("sharpe", "screen3", "annual_return"):
        x, y = both[f"A_{metric}"], both[f"B_{metric}"]
        rho, pv = stats.spearmanr(x, y)
        persistence[metric] = {
            "n_coins": int(len(both)), "spearman_rho": round(float(rho), 4),
            "p_value": round(float(pv), 4),
            "top10_A_mean_B": round(float(
                both.nlargest(10, f"A_{metric}")[f"B_{metric}"].mean()), 4),
            "bottom10_A_mean_B": round(float(
                both.nsmallest(10, f"A_{metric}")[f"B_{metric}"].mean()), 4),
            "all_mean_B": round(float(y.mean()), 4),
        }

    drivers = {}
    for prop in ("A_ann_vol", "A_median_daily_qv_musd", "A_time_in_market",
                 "A_autocorr_1d", "bars"):
        sub = f.dropna(subset=[prop, "B_sharpe"])
        rho, pv = stats.spearmanr(sub[prop], sub["B_sharpe"])
        drivers[prop] = {"spearman_rho_vs_B_sharpe": round(float(rho), 4),
                         "p_value": round(float(pv), 4), "n": int(len(sub))}

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "roostoo_coins.json").write_text(json.dumps({
        "interval": INTERVAL, "entry_bars": ENTRY, "exit_low_bars": EXIT_LB,
        "roostoo_tradable_crypto": len(tradable),
        "evaluated": int(len(f)),
        "period_A": [SPLIT_A, SPLIT_B], "period_B": [SPLIT_B, END],
        "rank_persistence": persistence,
        "property_drivers": drivers,
        "coins": f.to_dict(orient="records"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
