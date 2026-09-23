"""Fit/holdout sweep for the mean-reversion scalper declared at
config/scalp_meanrev.yaml. Reports both ends of the unconfirmed fee schedule.
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from signals import meanrev

warnings.filterwarnings("ignore")
WINDOW, SCREEN2 = 14, 0.05


def declaration() -> dict:
    with (ROOT / "config" / "scalp_meanrev.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def to_daily(x: pd.Series) -> pd.Series:
    return ((1.0 + x.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def stats(dr: pd.Series) -> dict:
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
    def cap(v):
        return float(np.clip(v, -5, 5))
    k = len(dr) - WINDOW + 1
    if k > 0:
        m = np.stack([dr.to_numpy()[i:i + WINDOW] for i in range(k)])
        r14 = np.cumprod(1.0 + m, axis=1)[:, -1] - 1.0
        p_pos, p_s2 = float((r14 > 0).mean()), float((r14 > SCREEN2).mean())
    else:
        p_pos = p_s2 = float("nan")
    return {"cagr": round(cagr, 5), "sharpe": round(sh, 4), "sortino": round(so, 4),
            "calmar": round(cm, 4), "max_drawdown": round(dd, 5),
            "skew": round(float(dr.skew()), 4),
            "screen3": round(0.4 * cap(so) + 0.3 * cap(sh) + 0.3 * cap(cm), 4),
            "p_return_positive": round(p_pos, 4),
            "p_clears_screen2": round(p_s2, 4), "days": int(len(dr))}


def run_one(panels: dict, p: meanrev.Params, interval: str, win: tuple,
            weight: float, max_conc: int, fees: list[float]) -> dict:
    per, index = {}, None
    for sym, d in panels.items():
        w = d.loc[win[0]:win[1]]
        if len(w) < p.lookback_bars * 3:
            continue
        per[sym] = meanrev.trades(w, p)
        index = w.index if index is None else index.union(w.index)
    if index is None or not per:
        return {}
    allt = pd.concat([t for t in per.values() if not t.empty]) if any(
        not t.empty for t in per.values()) else pd.DataFrame()
    if allt.empty:
        return {"trades": 0}
    days = max((index[-1] - index[0]).days, 1)
    base = {
        "trades": int(len(allt)),
        "trades_per_day": round(len(allt) / days, 3),
        "win_rate": round(float((allt.gross_ret > 0).mean()), 4),
        "mean_gross_bps": round(float(allt.gross_ret.mean() * 1e4), 3),
        "median_gross_bps": round(float(allt.gross_ret.median() * 1e4), 3),
        "mean_bars_held": round(float(allt.bars_held.mean()), 2),
        "pct_target": round(float((allt.reason == "target").mean()), 4),
        "pct_stop": round(float((allt.reason == "stop").mean()), 4),
        "pct_time": round(float((allt.reason == "time").mean()), 4),
    }
    for fee in fees:
        net, gross, cost = meanrev.book_returns(per, index, weight, max_conc, fee)
        s_net = stats(to_daily(net))
        s_gro = stats(to_daily(gross))
        base[f"fee{int(fee)}"] = {
            **{f"net_{k}": v for k, v in s_net.items()},
            "gross_sharpe": s_gro.get("sharpe"),
            "annual_cost_drag": round(float(to_daily(cost).sum() / max(days / 365.0, 1e-9)), 5),
            "round_trip_bps": 2 * fee,
            "edge_minus_cost_bps": round(base["mean_gross_bps"] - 2 * fee, 3),
        }
    return base


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    syms = cfg["universe"]["symbols"]
    fees = [float(f) for f in m["fee_bps"]]
    results = []
    for interval in g["interval"]:
        panels = {s: meanrev.bars(f"data/cache/5m/{s}.parquet", interval)
                  for s in syms}
        for ez, tp, sl in itertools.product(g["entry_z"], g["tp_atr"], g["sl_atr"]):
            p = meanrev.Params(entry_z=float(ez), tp_atr=float(tp), sl_atr=float(sl),
                               lookback_bars=g["lookback_bars"],
                               atr_bars=g["atr_bars"],
                               max_hold_bars=g["max_hold_bars"])
            row = {"interval": interval, "entry_z": ez, "tp_atr": tp, "sl_atr": sl}
            for tag, win in (("fit", m["fit_window"]), ("hold", m["holdout_window"])):
                r = run_one(panels, p, interval, tuple(win),
                            g["weight_per_position"], g["max_concurrent"], fees)
                row[tag] = r
            results.append(row)
            f5 = row["hold"].get("fee5", {})
            print(f"{interval:>4s} z{ez} tp{tp} sl{sl} | hold trades={row['hold'].get('trades',0):5d} "
                  f"edge={row['hold'].get('mean_gross_bps',float('nan')):7.2f}bps "
                  f"net_sharpe@5={f5.get('net_sharpe')} screen3={f5.get('net_screen3')}",
                  flush=True)
    out = {"declaration": "config/scalp_meanrev.yaml",
           "universe": syms, "fit_window": m["fit_window"],
           "holdout_window": m["holdout_window"], "fee_bps": fees,
           "configs": len(results), "results": results}
    (RESULTS / "scalp_meanrev.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS / 'scalp_meanrev.json'}  configs={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
