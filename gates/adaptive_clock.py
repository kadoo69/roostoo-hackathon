"""Adaptive clock: hold, each day, the clock whose trailing return was best, against a random clock.

Declared in config/adaptive_clock.yaml before any number was computed.
DECISIONS.md#adaptive-clock-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS, record_trials
from data import universe as ru
from gates.competition_exit import contenders_cfg, setup
from gates.concentration import context
from gates.let_winners_run import describe, simulate
from gates.lowtf_paper_bots import W
from signals import contenders
from signals.exit_clock import to_fast

CLOCKS = {"30m": "competition", "1h": "momentum_top3_1h_long", "15m": "momentum_top3_15m"}


def clock_targets(iv: str, close4: pd.DataFrame, sel4: pd.DataFrame, tick: pd.Series):
    close, sel, htf_vol, vol_ok, off = setup(iv, close4, sel4)
    cfg = contenders_cfg(CLOCKS[iv])
    ok = htf_vol if cfg.get("htf_confirm") else (vol_ok if cfg.get("volume_confirm") else None)
    w = contenders.targets(close, sel, cfg, 20, 10, short_on=off, entry_ok=ok)
    net, _ = simulate(close, w, tick, True)
    return close, w, net


def daily(net: pd.Series) -> pd.Series:
    return np.log1p(net).resample("1D").sum()


def splice(choice: pd.Series, weights: dict[str, pd.DataFrame], grid: pd.DatetimeIndex,
           cols: list[str]) -> pd.DataFrame:
    """Each 15m row carries the chosen clock's weight for the day its bar CLOSES in."""
    day = (grid + pd.Timedelta(minutes=15)).floor("D")
    pick = choice.reindex(day).to_numpy()
    out = np.zeros((len(grid), len(cols)))
    for iv, w in weights.items():
        mask = pick == iv
        if mask.any():
            out[mask] = w.to_numpy()[mask]
    return pd.DataFrame(out, index=grid, columns=cols)


def main() -> int:
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    runs = {iv: clock_targets(iv, close4, sel4, tick) for iv in CLOCKS}
    grid_close = runs["15m"][0]
    cols = list(grid_close.columns)
    grid = grid_close.index
    weights = {}
    for iv, (close, w, _) in runs.items():
        w = w.reindex(columns=cols).fillna(0.0)
        weights[iv] = w if iv == "15m" else to_fast(w, close.index, grid).fillna(0.0)
    d = pd.DataFrame({iv: daily(net) for iv, (_, _, net) in runs.items()}).dropna()
    days = d.index
    choices = {"C0": pd.Series("30m", index=days)}
    for L in (7, 3):
        trail = d.rolling(L).sum().shift(1)
        choices[f"AD{L}"] = trail.idxmax(axis=1).fillna("30m")
    rng = np.random.default_rng(11)
    choices["RND_ctrl"] = pd.Series(rng.choice(list(CLOCKS), len(days)), index=days)
    res, share = {}, {}
    for k, ch in choices.items():
        w = splice(ch, weights, grid, cols)
        res[k] = describe(*simulate(grid_close, w, tick, True), grid_close)
        share[k] = ch.value_counts(normalize=True).round(3).to_dict()
        print(k, share[k], json.dumps({t: {m: res[k][t][m] for m in ("median_pct", "p_gt5", "p_gt10", "worst_pct", "median_maxdd_pct", "turnover_per_14d")} for t in W}), flush=True)
    persist = {f"{a}->{a}": round(float((d[a].shift(1).rank() == d[a].shift(1).rank()).mean()), 3) for a in d}
    rank_ic = float(d.rolling(7).sum().shift(1).rank(axis=1).stack().corr(d.rank(axis=1).stack(), method="spearman"))
    c0 = res["C0"]

    def passes(arm: str) -> dict:
        a = res[arm]
        checks = {"holdout_median": a["holdout"]["median_pct"] > c0["holdout"]["median_pct"],
                  "holdout_p5": a["holdout"]["p_gt5"] >= c0["holdout"]["p_gt5"],
                  "fit_median": a["fit"]["median_pct"] > c0["fit"]["median_pct"],
                  "beats_random": a["holdout"]["median_pct"] > res["RND_ctrl"]["holdout"]["median_pct"],
                  "worst_within_5pp": a["holdout"]["worst_pct"] >= c0["holdout"]["worst_pct"] - 5}
        return {"checks": checks, "pass": all(checks.values())}

    verdict = {"AD7": passes("AD7"), "AD3": passes("AD3"), "trailing7_vs_next_day_rank_corr": round(rank_ic, 4)}
    ok = [a for a in ("AD7", "AD3") if verdict[a]["pass"]]
    verdict["adopt"] = max(ok, key=lambda a: res[a]["holdout"]["median_pct"]) if ok else "C0"
    print("verdict", json.dumps(verdict))
    (RESULTS / "adaptive_clock.json").write_text(json.dumps({"arms": res, "clock_share": share, "verdict": verdict,
                                                              "persist": persist}, indent=1))
    record_trials([{"signal": "adaptive_clock", "gate": "adaptive_clock", "config": f"adaptive_clock:{a}",
                    "status": "pass" if verdict.get(a, {}).get("pass") else ("control" if a in ("C0", "RND_ctrl") else "fail"),
                    "note": "DECISIONS.md#adaptive-clock-outcome"} for a in res])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
