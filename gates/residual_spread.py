"""Market-neutral residual spread on the recent live window and on history. Declared in
config/residual_spread.yaml before any number was computed. DECISIONS.md#residual-spread-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from bot import feed
from core.config import RESULTS, record_trials
from data import universe as ru
from gates import let_winners_run as lwr
from gates import stress
from gates.missed_replay import universe
from signals import residual_spread as rs

ARMS = {"RS8": 8, "RS48": 48}
SEEDS = 50
SINCE = pd.Timestamp("2026-09-19T00:00Z")


def sim(close: pd.DataFrame, w: pd.DataFrame, tick: pd.Series) -> pd.Series:
    net, _ = lwr.simulate(close, w, tick, False)
    return net


def stats(net: pd.Series) -> dict:
    eq = np.cumprod(1.0 + net.to_numpy())
    return {"return_pct": round((eq[-1] - 1) * 100, 2),
            "maxdd_pct": round(float((eq / np.maximum.accumulate(eq) - 1).min()) * 100, 2)}


def main() -> int:
    rng = np.random.default_rng(41)
    syms = universe("momentum_top3_30m")
    n = int((pd.Timestamp.now(tz="UTC") - SINCE) / pd.Timedelta("30min")) + 120
    close = feed.close_matrix(feed.bar_frame(syms, "30m", n))
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    first = int(np.searchsorted(close.index + pd.Timedelta("30min"), SINCE))
    live = {}
    for k, L in ARMS.items():
        w = rs.weights(rs.residual(close, members, L))
        net = sim(close.iloc[first - 1:], w.iloc[first - 1:], tick)
        ctrl = []
        for _ in range(SEEDS):
            noise = pd.DataFrame(rng.normal(size=close.shape), index=close.index, columns=close.columns)
            wr = rs.weights(noise)
            ctrl.append(stats(sim(close.iloc[first - 1:], wr.iloc[first - 1:], tick))["return_pct"])
        s = stats(net)
        s["random_median_pct"] = round(float(np.median(ctrl)), 2)
        s["random_beaten"] = int(sum(s["return_pct"] > c for c in ctrl))
        legs = w.iloc[first - 1:]
        s["long_leg_pct"] = stats(sim(close.iloc[first - 1:], legs.clip(lower=0), tick))["return_pct"]
        s["short_leg_pct"] = stats(sim(close.iloc[first - 1:], legs.clip(upper=0), tick))["return_pct"]
        live[k] = s
        print("live", k, s, flush=True)
    hist = {}
    b = stress.load("competition")
    for k, L in ARMS.items():
        w = rs.weights(rs.residual(b.close, b.sel.reindex_like(b.close).fillna(False), L))
        net, turn = lwr.simulate(b.close, w, b.tick, False)
        hist[k] = stress.describe(net, turn)
        print("history", k, {t: {m: hist[k][t].get(m) for m in ("median_pct", "p_gt5", "worst_pct", "median_maxdd_pct", "turnover_per_14d")}
                             for t in stress.PERIODS}, flush=True)
    verdict = {}
    for k in ARMS:
        checks = {"live_positive": live[k]["return_pct"] > 0, "live_dd_better_than_-10": live[k]["maxdd_pct"] > -10,
                  "beats_45_of_50_random": live[k]["random_beaten"] >= 45,
                  "holdout_median_positive": hist[k]["holdout"]["median_pct"] > 0}
        verdict[k] = {"checks": {c: bool(v) for c, v in checks.items()}, "pass": bool(all(checks.values()))}
    out = {"live_window": [str(SINCE), str(close.index[-1])], "live": live, "history": hist, "verdict": verdict}
    (RESULTS / "residual_spread.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(verdict))
    record_trials([{"signal": "residual_spread", "gate": "residual_spread", "config": f"residual_spread:{k}",
                    "status": "pass" if verdict[k]["pass"] else "fail", "note": "DECISIONS.md#residual-spread-outcome"} for k in ARMS])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
