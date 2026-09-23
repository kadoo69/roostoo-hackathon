"""config/scalper_v1.yaml. Judged on the pre-registered per-trade floor.

Sharpe is deliberately not the criterion: DECISIONS.md#scalp-meanrev-outcome
established that net Sharpe at this horizon ranks configurations by turnover
rather than by edge (fit/holdout rank correlation +0.968 on Sharpe, -0.108 on
per-trade edge).
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from signals import orderflow, scalper

warnings.filterwarnings("ignore")
A, B = "2023-01-01", "2025-01-01"


def declaration():
    with (ROOT / "config" / "scalper_v1.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def summarise(t: pd.DataFrame, tag: str) -> dict:
    if not len(t):
        return {f"{tag}_n": 0}
    net = t["net_bps"]
    return {f"{tag}_n": int(len(t)),
            f"{tag}_median_bps": round(float(net.median()), 3),
            f"{tag}_mean_bps": round(float(net.mean()), 3),
            f"{tag}_win_rate": round(float((net > 0).mean()), 4),
            f"{tag}_gross_mean_bps": round(float(t["gross_bps"].mean()), 3),
            f"{tag}_total_bps": round(float(net.sum()), 1),
            f"{tag}_stop_share": round(float((t["reason"] == "stop").mean()), 3)}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    rt = g["round_trip_bps"]

    panels, feats = {}, {}
    for iv in g["intervals"]:
        panels[iv] = {s: orderflow.bars(f"data/cache/5m/{s}.parquet", iv)
                      for s in g["symbols"]}
        feats[iv] = {s: orderflow.features(d, g["lookback"])
                     for s, d in panels[iv].items()}

    def run(iv, arm, spec, rng=None, rate=None):
        fit, hold = [], []
        for s in g["symbols"]:
            t = scalper.trades(panels[iv][s], feats[iv][s], arm=arm,
                               round_trip_bps=rt, cooldown_bars=g["cooldown_bars"],
                               max_per_day=g["max_trades_per_day_per_symbol"],
                               rng=rng, random_rate=rate, **spec)
            if not len(t):
                continue
            t = t.set_index("ts")
            fit.append(t.loc[A:B])
            hold.append(t.loc[B:])
        f = pd.concat(fit) if fit else pd.DataFrame()
        h = pd.concat(hold) if hold else pd.DataFrame()
        return {**summarise(f, "fit"), **summarise(h, "hold")}

    rows = []
    keys = ["ret_thresh", "ofi_thresh", "target_atr", "stop_atr",
            "time_stop_bars", "cost_gate_multiple"]
    for iv in g["intervals"]:
        for combo in itertools.product(*[g[k] for k in keys]):
            spec = dict(zip(keys, combo))
            rows.append({"interval": iv, "arm": "divergence", **spec,
                         **run(iv, "divergence", spec)})

    best = max((r for r in rows if r.get("hold_n", 0) >= 50),
               key=lambda r: r.get("hold_median_bps", -1e9), default=None)
    if best:
        spec = {k: best[k] for k in keys}
        iv = best["interval"]
        for arm in ("sign_flip", "no_flow_gate"):
            rows.append({"interval": iv, "arm": arm, **spec, **run(iv, arm, spec)})
        n_real = best.get("hold_n", 0) + best.get("fit_n", 0)
        total_bars = sum(len(panels[iv][s]) for s in g["symbols"])
        rate = min(1.0, n_real / max(1, total_bars))
        rows.append({"interval": iv, "arm": "random", **spec, "random_rate": round(rate, 6),
                     **run(iv, "random", spec, np.random.default_rng(5), rate)})

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scalper_v1.json").write_text(
        json.dumps({"declaration": "config/scalper_v1.yaml", "results": rows},
                   indent=2, default=str))

    print(f"{'iv':>6s} {'arm':12s} {'ret':>6s} {'ofi':>4s} {'tgt':>5s} {'ts':>3s} {'cg':>4s} "
          f"{'holdN':>6s} {'med':>8s} {'mean':>8s} {'win':>6s} {'stop%':>6s}")
    for r in sorted(rows, key=lambda x: -x.get("hold_median_bps", -1e9))[:24]:
        print(f"{r['interval']:>6s} {r['arm']:12s} {r['ret_thresh']:6.3f} {r['ofi_thresh']:4.1f} "
              f"{r['target_atr']:5.2f} {r['time_stop_bars']:3d} {r['cost_gate_multiple']:4.1f} "
              f"{r.get('hold_n',0):6d} {r.get('hold_median_bps',float('nan')):8.2f} "
              f"{r.get('hold_mean_bps',float('nan')):8.2f} {r.get('hold_win_rate',float('nan')):6.3f} "
              f"{r.get('hold_stop_share',float('nan')):6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
