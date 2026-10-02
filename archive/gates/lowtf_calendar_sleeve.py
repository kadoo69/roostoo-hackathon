"""Exploratory 20-day channel at hourly closes, as an idle-cash sleeve.

The rule was seen in a prior grid. Historical periods here are a combination
check, not a fresh out-of-sample discovery. Only forward paper can validate it.
"""
from __future__ import annotations

import json

import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from archive.gates.lowtf_idle_sleeve import capped, evaluate, sleeve_returns
from signals import donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_calendar_sleeve.yaml"
OUT = RESULTS / "lowtf_calendar_sleeve.json"


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    if not cfg["meta"]["declared_before_this_combination_test"]:
        raise RuntimeError("undeclared experiment")
    close4, sel4, close1, tick = cw.load()
    idx4, idx1 = close4.index, close1.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    momentum = close4 / close4.shift(40) - 1.0
    baseline, gross = cw.book_hourly(close1, idx4, long4=cw.ranked(momentum, live4),
                                     tick=tick, return_gross=True)
    ec = cw.FEE + float((tick / close1.median()).median())
    eligible = to_fast(sel4.astype(float), idx4, idx1).fillna(0.0) > 0.5
    idle = (1.0 - gross).clip(0, 1)
    hourly = (donchian.position(close1, 480, "midpoint") > 0.5) & eligible
    four = (to_fast((donchian.position(close4, 120, "midpoint") > 0.5).astype(float),
                    idx4, idx1).fillna(0.0) > 0.5) & eligible
    raw = hourly.astype(float) * 0.05
    targets = {"hourly_calendar": capped(raw, idle),
               "four_hour_calendar_control": capped(four.astype(float) * 0.05, idle),
               "stale_seven_day_control": capped(raw.shift(168).fillna(0.0), idle)}
    btc = pd.DataFrame(0.0, index=idx1, columns=close1.columns)
    btc["BTCUSDT"] = 0.5
    targets["bitcoin_idle_control"] = capped(btc, idle)
    out = {"declaration": str(CONFIG.relative_to(ROOT)),
           "prior_grid_selection_means_no_independent_historical_holdout": True,
           "baseline": evaluate(baseline, ec), "arms": {}, "operational": {}}
    for name, target in targets.items():
        sleeve, op = sleeve_returns(target, close1, tick)
        out["arms"][name] = evaluate(baseline + sleeve, ec)
        out["operational"][name] = op
        if name == "hourly_calendar":
            stress, _ = sleeve_returns(target, close1, tick, fee_multiple=2.0)
            out["arms"]["hourly_calendar_cost_2x"] = evaluate(baseline + stress, ec)
    arm, base = out["arms"]["hourly_calendar"], out["baseline"]
    keys = ("median_pct", "sharpe", "sortino", "calmar")
    periods = {p: bool(all(arm[p][k] > base[p][k] for k in keys) and
                       arm[p]["worst_pct"] >= base[p]["worst_pct"] - 5) for p in base}
    h = "2025-26"
    controls = all(arm[h][k] > out["arms"][control][h][k]
                   for control in targets if control != "hourly_calendar"
                   for k in ("median_pct", "sharpe"))
    stress = all(out["arms"]["hourly_calendar_cost_2x"][h][k] > base[h][k]
                 for k in ("median_pct", "sharpe"))
    out["verdict"] = {"historical_period_checks": periods, "beats_controls": bool(controls),
                      "double_cost": bool(stress),
                      "nominate_forward_paper": bool(all(periods.values()) and controls and stress),
                      "validated_edge": False, "bot_integration": False}
    OUT.write_text(json.dumps(out, indent=2, default=str) + "\n")
    for name, row in (("baseline", base), *out["arms"].items()):
        print(name, " | ".join(f"{p}: median {v['median_pct']:+.2f}%, Sharpe {v['sharpe']:+.2f}, "
                                  f"Sortino {v['sortino']:+.2f}, Calmar {v['calmar']:+.2f}"
                                  for p, v in row.items()), flush=True)
    print("verdict", out["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
