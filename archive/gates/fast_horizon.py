from __future__ import annotations

import glob
import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from signals import donchian

warnings.filterwarnings("ignore")
RULE = {"5m": None, "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}
BARS_PER_DAY = {"5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last",
       "quote_volume": "sum"}


def declaration() -> dict:
    with (ROOT / "config" / "fast_horizon.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def load_panel(symbols, interval) -> pd.DataFrame:
    cols = {}
    for s in symbols:
        p = f"data/cache/5m/{s}.parquet"
        if not glob.glob(p):
            continue
        d = pd.read_parquet(p, columns=["open_time", "open", "high", "low",
                                        "close", "quote_volume"])
        d = d.set_index("open_time").sort_index()
        if RULE[interval] is not None:
            d = d.resample(RULE[interval]).agg(AGG).dropna(subset=["close"])
        cols[s] = d["close"]
    return pd.DataFrame(cols).sort_index()


def simulate(close, entry, exit_lb, divisor, fee_bps, max_gross=1.0):
    pos = donchian.position(close, entry, "lowchannel", exit_lb)
    w = pos / float(divisor)
    g = w.abs().sum(axis=1)
    w = w.div(np.maximum(1.0, g / max_gross), axis=0)
    ret = close.pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    cost = turn * fee_bps / 1e4
    net = (gross - cost.shift(1).fillna(0.0)).fillna(0.0)
    return net, gross, turn, cost, w


def to_daily(x):
    return ((1.0 + x.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def stats(dr):
    dr = dr.dropna()
    if len(dr) < 60 or dr.std() == 0:
        return {}
    eq = (1.0 + dr).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    years = len(dr) / 365.0
    cagr = float(eq.iloc[-1]) ** (1 / years) - 1.0
    down = float(np.sqrt((dr.clip(upper=0.0) ** 2).mean()) * np.sqrt(365))
    sh = float(dr.mean() / dr.std() * np.sqrt(365))
    so = float(dr.mean() * 365 / down) if down > 0 else 0.0
    cm = cagr / abs(dd) if dd < 0 else 0.0
    def cap(v):
        return float(np.clip(v, -5, 5))

    return {"cagr": round(cagr, 5), "sharpe": round(sh, 4),
            "sortino": round(so, 4), "calmar": round(cm, 4),
            "max_drawdown": round(dd, 5),
            "screen3": round(0.4 * cap(so) + 0.3 * cap(sh) + 0.3 * cap(cm), 4)}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    syms = g["universe"]
    rows = []
    edge = []
    for iv in g["intervals"]:
        close = load_panel(syms, iv).loc[cfg["evaluation"]["is_end"]:]
        if close.empty:
            continue
        r = close.pct_change()
        edge.append({"interval": iv,
                     "mean_abs_bar_return_bps": round(float(r.abs().mean().mean() * 1e4), 3),
                     "median_abs_bar_return_bps": round(float(r.abs().stack().median() * 1e4), 3),
                     "bars": int(len(close))})
        for fee in g["fee_bps_per_side_grid"]:
            net, gross, turn, cost, w = simulate(
                close, g["entry_bars"], g["exit_bars"], g["weight_divisor"], fee,
                g["max_gross"])
            dnet, dgross = to_daily(net), to_daily(gross)
            sn, sg = stats(dnet), stats(dgross)
            bpd = BARS_PER_DAY[iv]
            changes = float(((w - w.shift(1)).abs() > 1e-12).sum().sum())
            rows.append({
                "interval": iv, "fee_bps": fee,
                "net_sharpe": sn.get("sharpe"), "gross_sharpe": sg.get("sharpe"),
                "net_cagr": sn.get("cagr"), "gross_cagr": sg.get("cagr"),
                "net_sortino": sn.get("sortino"), "net_calmar": sn.get("calmar"),
                "max_drawdown": sn.get("max_drawdown"), "screen3": sn.get("screen3"),
                "annual_turnover": round(float(turn.mean() * 365 * bpd), 1),
                "annual_cost_drag": round(float(cost.mean() * 365 * bpd), 4),
                "trades_per_day": round(changes / 2.0 / (len(close) / bpd), 2),
                "mean_gross_exposure": round(float(w.abs().sum(axis=1).mean()), 4)})

    bh = load_panel(syms, "1h").loc[cfg["evaluation"]["is_end"]:]
    hold = to_daily(bh.pct_change().mean(axis=1))
    out = {"declaration": "config/fast_horizon.yaml", "universe": syms,
           "bar_edge_vs_cost": edge, "results": rows,
           "benchmark_equal_weight_hold": stats(hold)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "fast_horizon.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
