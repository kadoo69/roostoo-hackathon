"""Portfolio impact of the already-selected 1h confirmed breakout book.

Both subbooks retain their own position accounting and execution charges.
The 80/20 combination pays an additional fee to rebalance capital between them.
This historical test is exploratory because the 1h signal was previously chosen
using the same years. No execution bot imports this module.
"""
from __future__ import annotations

import json

import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from gates import let_winners_run as lwr
from gates.breakout_quality import fast_field
from gates.lowtf_contenders import CFG as CONTENDERS
from archive.gates.lowtf_idle_sleeve import evaluate
from gates.lowtf_paper_bots import fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_portfolio_mix.yaml"
OUT = RESULTS / "lowtf_portfolio_mix.json"


def combine(slow: pd.Series, fast: pd.Series, fast_weight: float = 0.2,
            side_cost: float = 0.0005) -> pd.Series:
    """Constant 80/20 capital split with end-of-hour rebalancing fees."""
    pair = pd.concat([slow.rename("slow"), fast.rename("fast")], axis=1).dropna()
    w = float(fast_weight)
    preliminary = (1.0 - w) * pair["slow"] + w * pair["fast"]
    after = w * (1.0 + pair["fast"]) / (1.0 + preliminary)
    transfer = (after - w).abs()
    return preliminary - 2.0 * transfer * side_cost


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    if not cfg["meta"]["declared_before_combination_test"]:
        raise RuntimeError("undeclared experiment")
    close4, sel4, close1, tick = cw.load()
    idx4 = close4.index
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    slow = cw.book_hourly(close1, idx4, long4=cw.ranked(mom4, live4), tick=tick)

    close = fast_close("1h")
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    eligible = to_fast(sel4[cols].astype(float), idx4, close.index).fillna(0.0) > 0.5
    flag = donchian.breadth_short_regime(close, 40, 0.40, members=eligible)
    skips = {r["interval"]: r["skip_frozen_on_fit"]
             for r in json.loads((RESULTS / "lowtf_exhaustion.json").read_text())["rows"]}
    cc = {**CONTENDERS, "sticky": True,
          "skip_long_z": skips["1h"]["long"], "skip_short_z": skips["1h"]["short"],
          "htf_confirm": True, "volume_confirm": 1.5}
    qv = fast_field("1h", "quote_volume", "panel").reindex_like(close)
    confirmed = contenders.entry_confirmation(close, qv, close4[cols], cc)
    target_confirmed = contenders.targets(close, eligible, cc, short_on=flag, entry_ok=confirmed)
    target_unconfirmed = contenders.targets(close, eligible, cc, short_on=flag)
    tk = tick.reindex(cols).fillna(0.0)
    fast, _ = lwr.simulate(close, target_confirmed, tk, True)
    unconfirmed, _ = lwr.simulate(close, target_unconfirmed, tk, True)
    old_fee, old_short = lwr.FEE, lwr.SHORT_FEE
    try:
        lwr.FEE, lwr.SHORT_FEE = 2 * old_fee, 2 * old_short
        stressed, _ = lwr.simulate(close, target_confirmed, tk * 2, True)
    finally:
        lwr.FEE, lwr.SHORT_FEE = old_fee, old_short

    start = cfg["sample"]["start"]
    ec = cw.FEE + float((tick / close1.median()).median())
    width = float(cfg["books"]["mix_fast_weight"])
    arms = {"slow_control": slow.loc[start:],
            "fast_confirmed": fast.loc[start:],
            "mix_confirmed": combine(slow, fast, width),
            "mix_unconfirmed_control": combine(slow, unconfirmed, width),
            "mix_fast_cost_2x": combine(slow, stressed, width)}
    report = {"declaration": str(CONFIG.relative_to(ROOT)),
              "selected_on_previous_historical_grid": True,
              "metrics": {k: evaluate(v, ec) for k, v in arms.items()},
              "fast_reconciliation": {}, "verdict": {}}
    stored = json.loads((RESULTS / "breakout_quality_b12.json").read_text())["1h"]["B12"]
    from gates import positioning_edges as pe
    fdaily = ((1.0 + fast).resample("1D").prod() - 1.0).dropna()
    for tag, (a, b) in {"fit": ("2023-01-01", "2025-01-01"),
                        "holdout": ("2025-01-01", "2026-09-19")}.items():
        fresh = pe.describe(fdaily, a, b)["median_pct"]
        report["fast_reconciliation"][tag] = {"fresh_median_pct": fresh,
                                              "stored_median_pct": stored[tag]["median_pct"],
                                              "gap_pp": round(fresh - stored[tag]["median_pct"], 3)}
    m = report["metrics"]
    keys = ("median_pct", "sharpe", "sortino", "calmar")
    periods = ("2023-24", "2025-26")
    checks = {p: bool(all(m["mix_confirmed"][p][k] > m["slow_control"][p][k] for k in keys))
              for p in periods}
    h = "2025-26"
    controls = all(m["mix_confirmed"][h][k] > m["mix_unconfirmed_control"][h][k]
                   for k in ("median_pct", "sharpe"))
    stress = all(m["mix_fast_cost_2x"][h][k] > m["slow_control"][h][k]
                 for k in ("median_pct", "sharpe"))
    report["verdict"] = {"historical_period_checks": checks,
                         "beats_unconfirmed_mix": bool(controls),
                         "double_fast_cost": bool(stress),
                         "nominate_forward_paper": bool(all(checks.values()) and controls and stress),
                         "validated_alpha": False, "bot_integration": False}
    OUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    for name, row in m.items():
        print(name, " | ".join(f"{p}: median {row[p]['median_pct']:+.2f}%, "
                                  f"Sharpe {row[p]['sharpe']:+.2f}, Sortino {row[p]['sortino']:+.2f}, "
                                  f"Calmar {row[p]['calmar']:+.2f}"
                                  for p in periods), flush=True)
    print("fast reconciliation", report["fast_reconciliation"], flush=True)
    print("verdict", report["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
