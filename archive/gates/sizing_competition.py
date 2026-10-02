"""Position sizing on the competition rule. Declared in config/sizing_competition.yaml.
DECISIONS.md#sizing-competition-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from core.config import RESULTS, ROOT, record_trials
from data import universe as ru
from gates import let_winners_run as lwr
from gates import stress
from gates.missed_replay import universe
from signals import contenders

SINCE = pd.Timestamp("2026-09-19T00:00Z")


def eq(w: pd.DataFrame) -> pd.DataFrame:
    held = (w > 1e-12).astype(float)
    return contenders.cap_weights(held.div(held.sum(axis=1).replace(0, np.nan), axis=0).mul(w.sum(axis=1), axis=0).fillna(0.0), 0.5)


def cap33(w: pd.DataFrame) -> pd.DataFrame:
    return w.clip(upper=0.33)


def vt(w: pd.DataFrame, net: pd.Series, target: float) -> pd.DataFrame:
    rv = net.rolling(48, min_periods=24).std().shift(1)
    scale = (target / rv).clip(lower=0.3, upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def live_book() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, dict]:
    cc = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())["contenders"]
    syms = universe("momentum_top3_30m")
    n = int((pd.Timestamp.now(tz="UTC") - SINCE) / pd.Timedelta("30min")) + 200
    fr = feed.bar_frame(syms, "30m", n)
    close = feed.close_matrix(fr)
    qv = pd.DataFrame({s: f.set_index("open_time")["quote_volume"] for s, f in fr.items() if len(f)})
    c4 = feed.close_matrix(feed.bar_frame(syms, "4h", 150))
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    off = pd.Series(False, index=close.index)
    ok = contenders.entry_confirmation(close, qv, c4, cc)
    w3 = contenders.targets(close, members, cc, 20, 10, short_on=off, entry_ok=ok)
    w2 = contenders.targets(close, members, {**cc, "n": 2}, 20, 10, short_on=off, entry_ok=ok)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    return close, w3, w2, tick, cc


def window_return(close: pd.DataFrame, w: pd.DataFrame, tick: pd.Series) -> float:
    i0 = int(np.searchsorted(close.index + pd.Timedelta("30min"), SINCE))
    w, c = w.iloc[i0 - 1:].copy(), close.iloc[i0 - 1:]
    for s in w.columns[(w.iloc[0] > 0).to_numpy()]:
        on = (w[s] > 0).to_numpy()
        w.iloc[:int(np.argmin(on)) if not on.all() else len(on), w.columns.get_loc(s)] = 0.0
    net, _ = lwr.simulate(c, w, tick, True)
    return round(float(np.expm1(np.log1p(net).sum()) * 100), 2)


def main() -> int:
    b = stress.load("competition")
    w0 = stress.weights(b)
    net0, turn0 = stress.run(b, w0)
    target = float(net0.rolling(48, min_periods=24).std().loc[stress.PERIODS["fit"][0]:stress.PERIODS["fit"][1]].median())
    hist = {"C0": stress.describe(net0, turn0), "EQ": stress.describe(*stress.run(b, eq(w0))),
            "CAP33": stress.describe(*stress.run(b, cap33(w0))), "VT": stress.describe(*stress.run(b, vt(w0, net0, target))),
            "N2": stress.describe(*stress.run(b, stress.weights(b, {"n": 2})))}
    close, w3, w2, tick, _ = live_book()
    n3, _ = lwr.simulate(close, w3, tick, True)
    live = {"C0": window_return(close, w3, tick), "EQ": window_return(close, eq(w3), tick), "CAP33": window_return(close, cap33(w3), tick),
            "VT": window_return(close, vt(w3, n3, target), tick), "N2": window_return(close, w2, tick)}
    h0 = hist["C0"]["holdout"]
    verdict = {}
    for k in ("EQ", "CAP33", "VT", "N2"):
        h = hist[k]["holdout"]
        checks = {"holdout_median_higher": h["median_pct"] > h0["median_pct"], "live_window_higher": live[k] > live["C0"],
                  "worst_within_3pp": h["worst_pct"] >= h0["worst_pct"] - 3, "screen3_not_lower": h["median_screen3"] >= h0["median_screen3"]}
        verdict[k] = {"checks": {c: bool(v) for c, v in checks.items()}, "recommended": bool(all(checks.values()))}
    out = {"vt_target": target, "history": hist, "live_window_pct": live, "verdict": verdict}
    (RESULTS / "sizing_competition.json").write_text(json.dumps(out, indent=1, default=str))
    for k in hist:
        print(f"{k:6s} " + " | ".join(f"{t} med {hist[k][t]['median_pct']:+6.2f} worst {hist[k][t]['worst_pct']:+6.1f} s3 {hist[k][t]['median_screen3']:+5.2f}" for t in stress.PERIODS)
              + f" || live 09-19..now {live[k]:+6.2f}%")
    print(json.dumps({k: v["recommended"] for k, v in verdict.items()}))
    record_trials([{"signal": "sizing", "gate": "sizing_competition", "config": f"sizing_competition:{k}",
                    "status": "pass" if verdict[k]["recommended"] else "fail", "note": "DECISIONS.md#sizing-competition-outcome"} for k in verdict])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
