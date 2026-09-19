from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT, prereg
from costs.model import CostModel
from data import daily, flow, intraday, universe
from portfolio.backtest import PERIODS_PER_YEAR, evaluate, run
from portfolio.construct import holding_period_days
from signals.volume import REGISTRY, book

warnings.filterwarnings("ignore")

IS_END = "2023-01-01"
WINDOW = 14
SCREEN2 = 0.05


def declaration() -> dict:
    with (ROOT / "config" / "volume_family.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("volume_family:not_declared")
    return cfg


def screen3(d: dict) -> float:
    w = prereg()["objective"]["weights"]
    cap = prereg()["objective"]["calmar_cap"]
    def g(k):
        v = d[k]
        return 0.0 if v is None or not np.isfinite(v) else min(v, cap)
    return float(w["sortino"] * g("sortino") + w["sharpe"] * g("sharpe")
                 + w["calmar"] * g("calmar"))


def daily_returns(net: pd.Series, ppy: int) -> pd.Series:
    if ppy == 365:
        return net
    return (1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0


def window_metrics(dr: pd.Series, hold: pd.Series) -> dict:
    j = pd.concat([dr.rename("s"), hold.rename("h")], axis=1).dropna()
    v, hv = j["s"].to_numpy(), j["h"].to_numpy()
    n = len(v) - WINDOW + 1
    if n <= 0:
        return {}
    def stats(a):
        m = np.stack([a[i:i + WINDOW] for i in range(n)])
        eq = np.cumprod(1.0 + m, axis=1)
        ret = eq[:, -1] - 1.0
        dd = (eq / np.maximum.accumulate(eq, axis=1) - 1.0).min(axis=1)
        mu, sd = m.mean(axis=1), m.std(axis=1)
        dn = np.sqrt((np.clip(m, None, 0.0) ** 2).mean(axis=1))
        sh = np.where(sd > 0, mu / np.where(sd > 0, sd, 1.0) * np.sqrt(365.0), 0.0)
        so = np.where(dn > 0, mu * 365.0 / np.where(dn > 0, dn, 1.0), 0.0)
        cg = np.where(ret > -1.0, (1.0 + ret) ** (365.0 / WINDOW) - 1.0, -1.0)
        cm = np.where(dd < 0, cg / np.abs(np.where(dd < 0, dd, 1.0)), 0.0)
        w = prereg()["objective"]["weights"]
        c = 5.0
        comp = (w["sortino"] * np.clip(so, -c, c) + w["sharpe"] * np.clip(sh, -c, c)
                + w["calmar"] * np.clip(cm, -c, c))
        return ret, comp
    r, c = stats(v)
    rh, ch = stats(hv)
    return {
        "n_windows": int(n),
        "p_return_positive": round(float((r > 0).mean()), 4),
        "p_clears_screen2": round(float((r > SCREEN2).mean()), 4),
        "median_return_14d": round(float(np.median(r)), 5),
        "median_screen3_14d": round(float(np.median(c)), 4),
        "p_beats_hold_screen3": round(float((c > ch).mean()), 4),
        "p_qualifies_and_beats_screen3": round(float(((r > SCREEN2) & (c > ch)).mean()), 4),
    }


def main() -> int:
    cfg = declaration()
    costs = CostModel.from_prereg()
    p_daily = daily.build()
    btc_daily = p_daily["close"]["BTCUSDT"].pct_change().loc[IS_END:].dropna()

    rows = []
    for interval in cfg["data"]["intervals"]:
        p = flow.panel(interval)
        close = p["close"]
        members = intraday.members_at(interval, close.index)
        spreads = daily.half_spread_bps(close, floor=daily.venue_tick_floor())
        ppy = PERIODS_PER_YEAR[interval]
        for name, fn in REGISTRY.items():
            score = fn(p)
            w = book(score, members, cfg["construction"]["quantile"])
            net, perf, gross = run(w.loc[IS_END:], close.loc[IS_END:],
                                   spreads.loc[IS_END:], costs, "LIMIT", ppy)
            d = perf.as_dict()
            dr = daily_returns(net, ppy)
            row = {
                "feature": name, "interval": interval,
                "annual_return": d["annual_return"], "sharpe": d["sharpe"],
                "sortino": d["sortino"], "calmar": d["calmar"],
                "max_drawdown": d["max_drawdown"], "screen3": round(screen3(d), 4),
                "gross_sharpe": gross.as_dict()["sharpe"],
                "annual_turnover": d["annual_turnover"],
                "annual_cost_drag": d["annual_cost_drag"],
                "holding_period_bars": round(holding_period_days(w.loc[IS_END:]), 2),
                "obs": d["days"],
            }
            row.update(window_metrics(dr, btc_daily))
            rows.append(row)

    z = pd.Series(0.0, index=btc_daily.index)
    hd = evaluate(btc_daily, btc_daily, z, z, pd.Series(1.0, index=btc_daily.index)).as_dict()
    bench = {"feature": "btc_hold", "interval": "1d", "annual_return": hd["annual_return"],
             "sharpe": hd["sharpe"], "sortino": hd["sortino"], "calmar": hd["calmar"],
             "max_drawdown": hd["max_drawdown"], "screen3": round(screen3(hd), 4)}
    bench.update(window_metrics(btc_daily, btc_daily))
    rows.append(bench)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "volume_sweep.json").write_text(json.dumps({
        "declaration": "config/volume_family.yaml",
        "oos_start": IS_END,
        "configs": len(rows) - 1,
        "results": rows,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
