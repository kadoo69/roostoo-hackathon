from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT, prereg
from costs.model import CostModel
from data import daily, flow
from archive.data import intraday
from portfolio.backtest import PERIODS_PER_YEAR, evaluate, run
from signals import donchian

warnings.filterwarnings("ignore")

IS_END = "2023-01-01"
PUBLISHED = "2025-04-01"
WINDOW = 14
SCREEN2 = 0.05
BARS_PER_DAY = {"1h": 24, "4h": 6, "8h": 3, "12h": 2, "1d": 1}


def declaration() -> dict:
    with (ROOT / "config" / "donchian_lowtf.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("donchian_lowtf:not_declared")
    return cfg


def screen3(d: dict) -> float:
    w = prereg()["objective"]["weights"]
    cap = prereg()["objective"]["calmar_cap"]
    def g(k):
        v = d[k]
        return 0.0 if v is None or not np.isfinite(v) else min(v, cap)
    return float(w["sortino"] * g("sortino") + w["sharpe"] * g("sharpe")
                 + w["calmar"] * g("calmar"))


def to_daily(net: pd.Series, ppy: int) -> pd.Series:
    if ppy == 365:
        return net.dropna()
    return ((1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def _window_arrays(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(a) - WINDOW + 1
    m = np.stack([a[i:i + WINDOW] for i in range(n)])
    eq = np.cumprod(1.0 + m, axis=1)
    ret = eq[:, -1] - 1.0
    dd = (eq / np.maximum(1.0, np.maximum.accumulate(eq, axis=1)) - 1.0).min(axis=1)
    mu, sd = m.mean(axis=1), m.std(axis=1, ddof=1)
    dn = np.sqrt((np.clip(m, None, 0.0) ** 2).mean(axis=1)) * np.sqrt(365.0)
    sh = np.where(sd > 0, mu / np.where(sd > 0, sd, 1.0) * np.sqrt(365.0), 0.0)
    so = np.where(dn > 0, mu * 365.0 / np.where(dn > 0, dn, 1.0), 0.0)
    cg = np.where(ret > -1.0, (1.0 + ret) ** (365.0 / WINDOW) - 1.0, -1.0)
    cm = np.where(dd < 0, cg / np.abs(np.where(dd < 0, dd, 1.0)), 0.0)
    w = prereg()["objective"]["weights"]
    c = 5.0
    comp = (w["sortino"] * np.clip(so, -c, c) + w["sharpe"] * np.clip(sh, -c, c)
            + w["calmar"] * np.clip(cm, -c, c))
    return ret, comp


def competition(dr: pd.Series, hold: pd.Series) -> dict:
    j = pd.concat([dr.rename("s"), hold.rename("h")], axis=1).dropna()
    if len(j) < WINDOW + 1:
        return {}
    r, c = _window_arrays(j["s"].to_numpy())
    rh, ch = _window_arrays(j["h"].to_numpy())
    return {
        "n_windows": int(len(r)),
        "p_return_positive": round(float((r > 0).mean()), 4),
        "p_clears_screen2": round(float((r > SCREEN2).mean()), 4),
        "p_clears_10pct": round(float((r > 0.10).mean()), 4),
        "median_return_14d": round(float(np.median(r)), 5),
        "p95_return_14d": round(float(np.quantile(r, 0.95)), 5),
        "worst_return_14d": round(float(r.min()), 5),
        "median_screen3_14d": round(float(np.median(c)), 4),
        "p_beats_hold_screen3": round(float((c > ch).mean()), 4),
        "p_qualifies_and_beats_screen3": round(float(((r > SCREEN2) & (c > ch)).mean()), 4),
    }


def evaluate_book(w, close, spreads, costs, ppy, hold, interval) -> dict:
    net, perf, gross = run(w.loc[IS_END:], close.loc[IS_END:],
                           spreads.loc[IS_END:], costs, "LIMIT", ppy)
    d = perf.as_dict()
    seg = w.loc[IS_END:]
    traded = (seg - seg.shift(1)).abs() > 1e-12
    bpd = BARS_PER_DAY[interval]
    days_active = float(traded.any(axis=1).groupby(
        traded.index.floor("1D")).any().mean())
    row = {
        "annual_return": d["annual_return"], "sharpe": d["sharpe"],
        "sortino": d["sortino"], "calmar": d["calmar"],
        "max_drawdown": d["max_drawdown"], "screen3": round(screen3(d), 4),
        "gross_sharpe": gross.as_dict()["sharpe"],
        "annual_turnover": d["annual_turnover"],
        "annual_cost_drag": d["annual_cost_drag"],
        "mean_gross_exposure": d["mean_gross_exposure"],
        "frac_days_with_a_trade": round(days_active, 4),
        "expected_trade_days_in_14": round(days_active * 14, 1),
        "bars_per_day": bpd,
    }
    dr = to_daily(net, ppy)
    z = pd.Series(0.0, index=dr.index)
    dd = evaluate(dr, dr, z, z, pd.Series(1.0, index=dr.index)).as_dict()
    row["daily_sharpe"] = dd["sharpe"]
    row["daily_sortino"] = dd["sortino"]
    row["daily_calmar"] = dd["calmar"]
    row["daily_max_drawdown"] = dd["max_drawdown"]
    row["daily_screen3"] = round(screen3(dd), 4)
    row.update(competition(dr, hold))
    pp = to_daily(net.loc[PUBLISHED:], ppy)
    if len(pp) > 40:
        z = pd.Series(0.0, index=pp.index)
        dp = evaluate(pp, pp, z, z, pd.Series(1.0, index=pp.index)).as_dict()
        row["postpub_sharpe"] = dp["sharpe"]
        row["postpub_screen3"] = round(screen3(dp), 4)
    return row


def main() -> int:
    cfg = declaration()
    costs = CostModel.from_prereg()
    p_daily = daily.build()
    hold = p_daily["close"]["BTCUSDT"].pct_change().loc[IS_END:].dropna()

    rows = []
    for interval in cfg["grid"]["intervals"]:
        p = flow.panel(interval)
        close = p["close"]
        members = intraday.members_at(interval, close.index)
        spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())
        ppy = PERIODS_PER_YEAR[interval]
        bpd = BARS_PER_DAY[interval]
        for mode, entry in (("bars", cfg["grid"]["entry_bars"]),
                            ("calendar", cfg["grid"]["entry_days"] * bpd)):
            for exit_mode in cfg["grid"]["exit_modes"]:
                exit_lb = max(2, entry // 2) if exit_mode == "lowchannel" else None
                w = donchian.book(close, members, entry, exit_mode, exit_lb)
                row = {"interval": interval, "mode": mode, "entry_bars": entry,
                       "exit": exit_mode}
                row.update(evaluate_book(w, close, spreads, costs, ppy, hold, interval))
                rows.append(row)

    z = pd.Series(0.0, index=hold.index)
    hd = evaluate(hold, hold, z, z, pd.Series(1.0, index=hold.index)).as_dict()
    bench = {"interval": "1d", "mode": "benchmark", "entry_bars": 0, "exit": "none",
             "annual_return": hd["annual_return"], "sharpe": hd["sharpe"],
             "sortino": hd["sortino"], "calmar": hd["calmar"],
             "max_drawdown": hd["max_drawdown"], "screen3": round(screen3(hd), 4),
             "daily_sharpe": hd["sharpe"], "daily_sortino": hd["sortino"],
             "daily_calmar": hd["calmar"], "daily_max_drawdown": hd["max_drawdown"],
             "daily_screen3": round(screen3(hd), 4)}
    bench.update(competition(hold, hold))
    rows.append(bench)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "donchian_lowtf.json").write_text(json.dumps({
        "declaration": "config/donchian_lowtf.yaml",
        "oos_start": IS_END, "configs": len(rows) - 1, "results": rows,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
