"""Slower channel exit on the competition rule, against a price-blind hold control.

Declared in config/competition_exit.yaml before any number was computed.
DECISIONS.md#competition-exit-declaration
"""
from __future__ import annotations

import json

import pandas as pd
import yaml

from core.config import RESULTS, ROOT, record_trials
from data import universe as ru
from gates.breakout_quality import fast_field
from gates.concentration import context
from gates.let_winners_run import describe, simulate
from gates.lowtf_paper_bots import W, fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast


def contenders_cfg(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())["contenders"]


def setup(iv: str, close4: pd.DataFrame, sel4: pd.DataFrame):
    close = fast_close(iv)
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    bar = close.index[1] - close.index[0]
    s4 = sel4[cols].copy()
    s4.index = s4.index + pd.Timedelta(hours=4)
    sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
    sel.index = close.index
    c4 = close4[cols]
    up = to_fast((donchian.position(c4, 20, "lowchannel", 10) > 0.5).astype(float), c4.index,
                 close.index).fillna(0.0) > 0.5
    is_long = (close / close.shift(40) - 1.0) > 0
    qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
    vol_ok = qv >= 1.5 * qv.rolling(20, min_periods=10).median().shift(1)
    off = pd.Series(False, index=close.index)
    return close, sel, (up & is_long) & vol_ok, vol_ok, off


def main() -> int:
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    res = {}

    close, sel, ok30, _, off = setup("30m", close4, sel4)
    base = contenders_cfg("competition")
    arms = {"C0": (base, 10), "E20": (base, 20), "E40": (base, 40),
            "H6_ctrl": ({**base, "min_hold_bars": 6}, 10)}
    for k, (cfg, ex) in arms.items():
        w = contenders.targets(close, sel, cfg, 20, ex, short_on=off, entry_ok=ok30)
        res[k] = describe(*simulate(close, w, tick, True), close)
        print(k, json.dumps({t: {m: res[k][t][m] for m in ("median_pct", "p_gt5", "p_gt10", "worst_pct", "median_maxdd_pct", "turnover_per_14d")} for t in W}), flush=True)

    close15, sel15, _, vol15, off15 = setup("15m", close4, sel4)
    w = contenders.targets(close15, sel15, contenders_cfg("momentum_top3_15m_slowexit"), 20, 40,
                           short_on=off15, entry_ok=vol15)
    res["S15_slowexit"] = describe(*simulate(close15, w, tick, True), close15)
    print("S15_slowexit", json.dumps({t: {m: res["S15_slowexit"][t][m] for m in ("median_pct", "p_gt5", "p_gt10", "worst_pct", "median_maxdd_pct", "turnover_per_14d")} for t in W}), flush=True)

    c0 = res["C0"]

    def beats(arm: str, exit_arm: bool) -> dict:
        a = res[arm]
        checks = {"holdout_median": a["holdout"]["median_pct"] > c0["holdout"]["median_pct"],
                  "holdout_p5": a["holdout"]["p_gt5"] >= c0["holdout"]["p_gt5"],
                  "fit_median": a["fit"]["median_pct"] > c0["fit"]["median_pct"]}
        if exit_arm:
            checks["beats_ctrl"] = a["holdout"]["median_pct"] > res["H6_ctrl"]["holdout"]["median_pct"]
            checks["worst_within_5pp"] = a["holdout"]["worst_pct"] >= c0["holdout"]["worst_pct"] - 5
        return {"checks": checks, "pass": all(checks.values())}

    verdict = {"E20": beats("E20", True), "E40": beats("E40", True), "S15_slowexit": beats("S15_slowexit", False)}
    passing = [a for a in ("E20", "E40") if verdict[a]["pass"]]
    verdict["adopt"] = (max(passing, key=lambda a: res[a]["holdout"]["median_pct"]) if passing
                        else ("S15_slowexit" if verdict["S15_slowexit"]["pass"] else "C0"))
    print("verdict", json.dumps(verdict))
    (RESULTS / "competition_exit.json").write_text(json.dumps({"arms": res, "verdict": verdict}, indent=1))
    record_trials([{"signal": "exit_bars", "gate": "competition_exit", "config": f"competition_exit:{a}",
                    "status": "pass" if verdict.get(a, {}).get("pass") else ("control" if a in ("C0", "H6_ctrl") else "fail"),
                    "note": "DECISIONS.md#competition-exit-outcome"} for a in res])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
