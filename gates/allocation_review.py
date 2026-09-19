from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from bot.allocation import allocate
from bot.report import from_equity
from bot.settings import ROOT
from data import flow
from gates.concentration import context


def simulate(weights: pd.DataFrame, opens: pd.DataFrame, cost: float) -> pd.Series:
    w = weights.shift(1).fillna(0).to_numpy()
    p = opens.to_numpy()
    dollars = np.zeros(p.shape[1])
    cash = 1.0
    equity = []
    for i in range(len(p)):
        if i:
            held = dollars > 1e-15
            valid = np.isfinite(p[i]) & np.isfinite(p[i-1]) & (p[i-1] > 0)
            if np.any(held & ~valid):
                raise ValueError("missing_held_price")
            growth = np.divide(p[i], p[i-1], out=np.ones(p.shape[1]), where=valid)
            dollars *= growth
        before = cash + dollars.sum()
        target = w[i].copy()
        if np.any((target > 0) & (~np.isfinite(p[i]) | (p[i] <= 0))):
            raise ValueError("missing_entry_price")
        after = before
        for _ in range(12):
            after = before - cost * np.abs(target * after - dollars).sum()
        dollars = target * after
        cash = after - dollars.sum()
        if cash < -1e-10:
            raise ValueError("leverage")
        equity.append(after)
    return pd.Series(equity, index=opens.index)


def metrics(equity: pd.Series, start: str, end: str) -> dict:
    daily = equity.resample("1d").last()
    seg = daily[(daily.index >= start) & (daily.index < end)]
    before = daily[daily.index < start].tail(1)
    if len(before):
        seg = pd.concat([before, seg])
    return from_equity(seg)


def main():
    cfg = yaml.safe_load((ROOT / "config/allocation_review.yaml").read_text())
    if not cfg["meta"]["declared_before_test"]:
        raise ValueError("not_declared")
    close, _, members, pos = context(30)
    close = close.loc["2022-10-01":].sort_index(axis=1)
    members = members.reindex_like(close)
    live = (pos.reindex_like(close) > 0) & members
    score = (close / close.shift(cfg["momentum_bars"]) - 1).where(live)
    ret = close.pct_change(fill_method=None).to_numpy()
    opens = flow.panel("4h")["open"].reindex_like(close)
    policies = []
    for n in cfg["position_counts"]:
        for sizing in cfg["sizing"]:
            policies.append({"name": f"balanced_{n}_{sizing}", "n_positions": n, "sizing": sizing,
                             **{k: cfg[k] for k in ("max_gross", "max_single", "min_weight", "target_vol", "risk_bars", "momentum_bars")}})
    rows = []
    for policy in [{"name": "channel_4h"}, {"name": "ranked5_4h"}] + policies:
        if policy["name"] == "channel_4h":
            weights = live.astype(float) / 20
            weights = weights.div(weights.sum(axis=1).clip(lower=1), axis=0)
        elif policy["name"] == "ranked5_4h":
            weights = (score.rank(axis=1, method="first", ascending=False) <= 5).astype(float) / 5
        else:
            out = np.zeros(close.shape)
            scores = score.to_numpy()
            for i in range(cfg["risk_bars"], len(close)):
                out[i] = allocate(scores[i], ret[i-cfg["risk_bars"]+1:i+1], policy)
            weights = pd.DataFrame(out, index=close.index, columns=close.columns)
        for bps in cfg["cost_bps_per_side"]:
            eq = simulate(weights, opens, bps / 1e4)
            row = {"name": policy["name"], "policy": policy, "cost_bps": bps,
                   "mean_positions": float((weights > 0).sum(axis=1).mean()),
                   "mean_exposure": float(weights.sum(axis=1).mean()),
                   "fit": metrics(eq, "2023-01-01", "2025-01-01"),
                   "assessment": metrics(eq, "2025-01-01", "2026-09-20")}
            rows.append(row)
            print(json.dumps(row), flush=True)
    candidates = []
    for policy in policies:
        results = [r for r in rows if r["name"] == policy["name"]]
        passes = all(r["fit"].get("max_drawdown", -1) >= -0.25 and
                     all(r["fit"].get(k, 0) > 0 for k in ("sharpe", "sortino", "calmar")) for r in results)
        value = np.mean([min(5, r["fit"][k]) for r in results for k in ("sharpe", "sortino", "calmar")])
        if passes:
            candidates.append((float(value), policy["name"]))
    chosen = max(candidates)[1] if candidates else None
    result = {"declared": "config/allocation_review.yaml", "selected_on_fit": chosen,
              "edge_established": False, "execution": "next_bar_open_with_drift_and_one_way_cost",
              "caveat": "Current venue membership conditions history; later period is reused assessment; no order depth or fill queue model. No simulated drawdown halt.",
              "results": rows}
    (ROOT / "results/allocation_review.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
