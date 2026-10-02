from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from core import artifacts
from core.config import RESULTS, gate_config
from data import daily, flow, universe as ru
from archive.gates.gate08_regime import net_returns, stats, to_daily

warnings.filterwarnings("ignore")
INTERVAL = "4h"
POOL = 30
ENTRY_GRID = (12, 16, 20, 24, 28)
EXIT_GRID = (6, 8, 10, 12, 14)
CENTRE = (20, 10)
IS_END = "2023-01-01"


def context():
    p = flow.panel(INTERVAL)
    close = p["close"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(
        pdl["close"].index).fillna(False)
    members = ru.pit_top_n(pdl, base, top_n=POOL).reindex(
        close.index, method="ffill").fillna(False)
    return close, members


def run_one(close, members, entry, exit_lb, start=None, end=None) -> pd.Series:
    from signals import donchian
    pos = donchian.position(close, entry, "lowchannel", exit_lb)
    w = pos.where(members, 0.0) / 20.0
    g = w.abs().sum(axis=1)
    w = w.div(np.maximum(1.0, g), axis=0)
    seg = slice(start, end)
    return to_daily(net_returns(w.loc[seg], close.loc[seg]))


def sensitivity(close, members) -> dict:
    cfg = gate_config("g2_parameter_sensitivity")
    grid = {}
    for e in ENTRY_GRID:
        for x in EXIT_GRID:
            s = stats(run_one(close, members, e, x))
            grid[f"{e}/{x}"] = {"sharpe": s.get("sharpe"), "cagr": s.get("cagr"),
                                "max_drawdown": s.get("max_drawdown")}
    sharpes = {k: v["sharpe"] for k, v in grid.items() if v["sharpe"] is not None}
    centre = sharpes[f"{CENTRE[0]}/{CENTRE[1]}"]
    peak = max(sharpes.values())
    ei, xi = ENTRY_GRID.index(CENTRE[0]), EXIT_GRID.index(CENTRE[1])
    neigh = []
    for de, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-2, 0), (2, 0), (0, -2), (0, 2)):
        a, b = ei + de, xi + dx
        if 0 <= a < len(ENTRY_GRID) and 0 <= b < len(EXIT_GRID):
            neigh.append(sharpes[f"{ENTRY_GRID[a]}/{EXIT_GRID[b]}"])
    ratio = min(neigh) / peak if peak > 0 else 0.0
    isolation = (peak - float(np.median(list(sharpes.values())))) / peak if peak > 0 else 1.0
    passed = (ratio >= cfg["min_neighbour_sharpe_ratio_to_peak"]
              and isolation <= cfg["max_peak_isolation_score"])
    return {"grid": grid, "centre_sharpe": centre, "peak_sharpe": round(peak, 4),
            "centre_is_peak": bool(abs(centre - peak) < 1e-9),
            "n_configs": len(sharpes),
            "min_neighbour_sharpe": round(min(neigh), 4),
            "neighbour_ratio_to_peak": round(ratio, 4),
            "threshold_min_ratio": cfg["min_neighbour_sharpe_ratio_to_peak"],
            "peak_isolation_score": round(isolation, 4),
            "threshold_max_isolation": cfg["max_peak_isolation_score"],
            "all_positive": bool(min(sharpes.values()) > 0),
            "worst_sharpe": round(min(sharpes.values()), 4),
            "passed": bool(passed)}


def walk_forward(close, members) -> dict:
    cfg = gate_config("g6_walk_forward")
    years = pd.date_range("2019-01-01", "2026-01-01", freq="YS", tz="UTC")
    rows = []
    for i in range(len(years) - 1):
        a, b = years[i], years[i + 1]
        is_seg = run_one(close, members, *CENTRE, end=str(a.date()))
        oos_seg = run_one(close, members, *CENTRE, start=str(a.date()),
                          end=str(b.date()))
        si, so = stats(is_seg), stats(oos_seg)
        if si.get("sharpe") is None or so.get("sharpe") is None:
            continue
        rows.append({"oos_year": int(a.year), "is_sharpe": si["sharpe"],
                     "oos_sharpe": so["sharpe"], "oos_cagr": so["cagr"],
                     "oos_max_drawdown": so["max_drawdown"],
                     "ratio": round(so["sharpe"] / si["sharpe"], 4)
                     if si["sharpe"] > 0 else None})
    ratios = [r["ratio"] for r in rows if r["ratio"] is not None]
    positive = sum(1 for r in rows if r["oos_sharpe"] > 0)
    median_ratio = float(np.median(ratios)) if ratios else 0.0
    passed = median_ratio >= cfg["min_oos_to_is_sharpe_ratio"]
    return {"mode": "anchored", "folds": rows, "n_folds": len(rows),
            "folds_positive_oos": positive,
            "median_oos_to_is_ratio": round(median_ratio, 4),
            "threshold": cfg["min_oos_to_is_sharpe_ratio"],
            "passed": bool(passed)}


def main() -> int:
    close, members = context()
    sens = sensitivity(close, members)
    wf = walk_forward(close, members)
    artifacts.write("g2_parameter_sensitivity", sens["passed"],
                    {"strategy": "donchian_4h_20_10", **sens})
    artifacts.write("g6_walk_forward", wf["passed"],
                    {"strategy": "donchian_4h_20_10", **wf})
    (RESULTS / "g2_g6_donchian.json").write_text(
        json.dumps({"sensitivity": sens, "walk_forward": wf}, indent=2))
    return 0 if (sens["passed"] and wf["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
