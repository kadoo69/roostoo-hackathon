"""Predeclared hourly idle-cash sleeve against the unchanged 4h momentum book.

The sleeve trades only capital the baseline leaves idle at the prior close.
All decisions use closed bars and PIT universe membership. Research only.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from signals import donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_idle_sleeve.yaml"
OUT = RESULTS / "lowtf_idle_sleeve.json"


def declared() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text())
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("undeclared experiment")
    return cfg


def sleeve_returns(target: pd.DataFrame, close: pd.DataFrame, tick: pd.Series,
                   fee_multiple: float = 1.0) -> tuple[pd.Series, dict]:
    """At close t choose weights and pay turnover; weights earn t to t+1."""
    target = target.reindex_like(close).fillna(0.0)
    price_return = close.pct_change(fill_method=None).fillna(0.0)
    gross = (target.shift(1).fillna(0.0) * price_return).sum(axis=1)
    turnover = target.diff().abs().fillna(target.abs())
    tick_cost = (tick.reindex(close.columns).fillna(0.0) / close).fillna(0.0)
    cost = (turnover * (cw.FEE + tick_cost) * fee_multiple).sum(axis=1)
    net = gross - cost
    return net, {"mean_gross": round(float(target.abs().sum(axis=1).loc["2022":].mean()), 4),
                 "turnover_per_day": round(float(turnover.sum(axis=1).loc["2022":].mean() * 24), 4),
                 "cost_pct_per_14d": round(float(cost.loc["2022":].mean() * 24 * 14 * 100), 3)}


def capped(raw: pd.DataFrame, idle: pd.Series) -> pd.DataFrame:
    """Raw weights sum to at most 1 before multiplication by available cash."""
    raw = raw.clip(lower=0.0)
    total = raw.sum(axis=1)
    return raw.div(total.clip(lower=1.0), axis=0).mul(idle.clip(0, 1), axis=0)


def risk_stats(hourly_net: pd.Series, period: tuple[str, str]) -> dict:
    daily = ((1.0 + hourly_net).resample("1D").prod() - 1.0).loc[period[0]:period[1]].dropna()
    if len(daily) < 60:
        return {"days": len(daily)}
    eq = (1.0 + daily).cumprod()
    high = np.maximum.accumulate(np.r_[1.0, eq.to_numpy()])[1:]
    maxdd = float((eq.to_numpy() / high - 1.0).min())
    ann_return = float(eq.iloc[-1] ** (365.0 / len(daily)) - 1.0)
    vol = float(daily.std(ddof=1) * np.sqrt(365.0))
    downside = float(np.sqrt(np.mean(np.minimum(daily.to_numpy(), 0.0) ** 2)) * np.sqrt(365.0))
    return {"days": len(daily), "total_return_pct": round(float(eq.iloc[-1] - 1.0) * 100, 2),
            "cagr_pct": round(ann_return * 100, 2),
            "sharpe": round(float(daily.mean() * 365.0 / vol), 3) if vol else None,
            "sortino": round(float(daily.mean() * 365.0 / downside), 3) if downside else None,
            "calmar": round(ann_return / abs(maxdd), 3) if maxdd < 0 else None,
            "max_drawdown_pct": round(maxdd * 100, 2)}


def evaluate(net: pd.Series, entry_cost: float) -> dict:
    windows = cw.windows_hourly(net, entry_cost=entry_cost)
    return {name: {**cw.describe(windows.loc[a:b]), **risk_stats(net, (a, b))}
            for name, (a, b) in cw.PERIODS.items()}


def study() -> dict:
    declared()
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    chosen4 = cw.ranked(mom4, live4)
    base, gross = cw.book_hourly(close1, idx4, long4=chosen4, tick=tick, return_gross=True)
    entry_cost = cw.FEE + float((tick / close1.median()).median())
    baseline = evaluate(base, entry_cost)
    recorded = json.loads((RESULTS / "competition_wf.json").read_text())["arms"]["C0"]
    gap = abs(baseline["2025-26"]["median_pct"] - recorded["2025-26"]["median_pct"])
    print("fresh baseline holdout median", baseline["2025-26"]["median_pct"],
          "stored result", recorded["2025-26"]["median_pct"], flush=True)

    idle = (1.0 - gross).clip(0, 1)
    eligible = to_fast(sel4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    hourly_live = (donchian.position(close1, 20, "lowchannel", 10) > 0.5) & eligible
    four_live = (to_fast(live4.astype(float), idx4, idx1).fillna(0.0) > 0.5) & eligible
    raw_hourly = hourly_live.astype(float) * 0.05
    targets = {
        "hourly_breakout": capped(raw_hourly, idle),
        "four_hour_breakout_control": capped(four_live.astype(float) * 0.05, idle),
        "stale_seven_day_control": capped(raw_hourly.shift(168).fillna(0.0), idle),
    }
    btc = pd.DataFrame(0.0, index=idx1, columns=close1.columns)
    btc["BTCUSDT"] = 0.5
    targets["bitcoin_idle_control"] = capped(btc, idle)

    out = {"declaration": str(CONFIG.relative_to(ROOT)), "stored_baseline_gap_pp": round(gap, 4),
           "stored_baseline_stale": bool(gap > 0.02),
           "control": baseline, "arms": {}, "operational": {}, "verdict": {}}
    for name, target in targets.items():
        sleeve, op = sleeve_returns(target, close1, tick)
        out["arms"][name] = evaluate(base + sleeve, entry_cost)
        out["operational"][name] = op
        if name == "hourly_breakout":
            stress, _ = sleeve_returns(target, close1, tick, fee_multiple=2.0)
            out["arms"]["hourly_breakout_cost_2x"] = evaluate(base + stress, entry_cost)
    candidate = out["arms"]["hourly_breakout"]
    stress = out["arms"]["hourly_breakout_cost_2x"]
    keys = ("median_pct", "sharpe", "sortino", "calmar")
    period_pass = {p: bool(all(candidate[p][k] > baseline[p][k] for k in keys)
                           and candidate[p]["worst_pct"] >= baseline[p]["worst_pct"] - 5)
                   for p in baseline}
    hold = "2025-26"
    controls_pass = all(candidate[hold][k] > out["arms"][control][hold][k]
                        for control in targets if control != "hourly_breakout"
                        for k in ("median_pct", "sharpe"))
    stress_pass = all(stress[hold][k] > baseline[hold][k] for k in ("median_pct", "sharpe"))
    out["verdict"] = {"period_pass": period_pass, "controls_pass": bool(controls_pass),
                      "cost_2x_pass": bool(stress_pass),
                      "candidate_for_forward_paper": bool(all(period_pass.values()) and controls_pass and stress_pass),
                      "bot_integration": False}
    return out


def main() -> int:
    result = study()
    OUT.write_text(json.dumps(result, indent=2, default=str) + "\n")
    for name, row in (("control", result["control"]), *result["arms"].items()):
        print(name, " | ".join(f"{p}: median {v['median_pct']:+.2f}%, Sharpe {v['sharpe']:+.2f}, "
                                  f"Sortino {v['sortino']:+.2f}, Calmar {v['calmar']:+.2f}"
                                  for p, v in row.items()), flush=True)
    print("verdict", result["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
