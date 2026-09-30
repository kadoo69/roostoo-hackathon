"""Exploratory long-only check of the existing confirmed 1h paper book."""
from __future__ import annotations

import json

import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates.breakout_quality import fast_field
from gates.lowtf_contenders import CFG as CONTENDERS
from gates.lowtf_idle_sleeve import evaluate
from gates.lowtf_paper_bots import fast_close
from gates.concentration import context
from signals import contenders, donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_confirmed_long_only.yaml"
OUT = RESULTS / "lowtf_confirmed_long_only.json"


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    if not cfg["meta"]["declared_before_this_test"]:
        raise RuntimeError("undeclared experiment")
    close4, _, sel4, _ = context(30)
    close = fast_close("1h")
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    eligible = to_fast(sel4[cols].astype(float), close4.index, close.index).fillna(0.0) > 0.5
    skips = {r["interval"]: r["skip_frozen_on_fit"]
             for r in json.loads((RESULTS / "lowtf_exhaustion.json").read_text())["rows"]}
    cc = {**CONTENDERS, "sticky": True,
          "skip_long_z": skips["1h"]["long"], "skip_short_z": skips["1h"]["short"],
          "htf_confirm": True, "volume_confirm": 1.5}
    qv = fast_field("1h", "quote_volume", "panel").reindex_like(close)
    entry_ok = contenders.entry_confirmation(close, qv, close4[cols], cc)
    breadth = donchian.breadth_short_regime(close, 40, 0.40, members=eligible)
    no_shorts = pd.Series(False, index=close.index)
    full_target = contenders.targets(close, eligible, cc, short_on=breadth, entry_ok=entry_ok)
    long_target = contenders.targets(close, eligible, cc, short_on=no_shorts, entry_ok=entry_ok)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in cols if s in specs}).reindex(cols).fillna(0.0)
    full, _ = lwr.simulate(close, full_target, tick, True)
    long, _ = lwr.simulate(close, long_target, tick, True)
    old_fee, old_short = lwr.FEE, lwr.SHORT_FEE
    try:
        lwr.FEE, lwr.SHORT_FEE = 2 * old_fee, 2 * old_short
        long_stress, _ = lwr.simulate(close, long_target, tick * 2, True)
    finally:
        lwr.FEE, lwr.SHORT_FEE = old_fee, old_short
    ec = lwr.FEE + float((tick / close.median()).median())
    reports = {"confirmed_both_sides": evaluate(full, ec),
               "confirmed_long_only": evaluate(long, ec),
               "confirmed_long_only_cost_2x": evaluate(long_stress, ec)}
    periods = ("2023-24", "2025-26")
    keys = ("median_pct", "sharpe", "sortino", "calmar")
    checks = {p: bool(all(reports["confirmed_long_only"][p][k] >
                          reports["confirmed_both_sides"][p][k] for k in keys)
                      and reports["confirmed_long_only"][p]["worst_pct"] >=
                          reports["confirmed_both_sides"][p]["worst_pct"] - 5)
              for p in periods}
    out = {"declaration": str(CONFIG.relative_to(ROOT)),
           "prior_historical_selection": True, "metrics": reports,
           "verdict": {"period_checks": checks,
                       "post_result_cost_2x_holdout_beats_control": bool(all(
                           reports["confirmed_long_only_cost_2x"]["2025-26"][k] >
                           reports["confirmed_both_sides"]["2025-26"][k]
                           for k in keys)),
                       "nominate_forward_paper": bool(all(checks.values())),
                       "validated_alpha": False, "bot_integration": False}}
    OUT.write_text(json.dumps(out, indent=2, default=str) + "\n")
    for name, row in reports.items():
        print(name, " | ".join(f"{p}: median {row[p]['median_pct']:+.2f}%, "
                                  f"Sharpe {row[p]['sharpe']:+.2f}, Sortino {row[p]['sortino']:+.2f}, "
                                  f"Calmar {row[p]['calmar']:+.2f}"
                                  for p in periods), flush=True)
    print("verdict", out["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
