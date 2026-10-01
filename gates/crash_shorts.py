"""Shorts only in a true crash regime, against the competition rule. Declared in
config/crash_shorts.yaml before any number was computed. DECISIONS.md#crash-shorts-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT, record_trials
from gates import stress
from gates.stress import PERIODS, Book, _clock, describe, regimes, run
from signals import contenders

SEEDS = 20


def book(iv: str) -> Book:
    raw = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())
    close, qv, close4, sel, tick = _clock(iv)
    return Book(f"competition@{iv}", iv, dict(raw["contenders"]), 20, 10, True, close, qv, close4, sel, tick)


def crash_flag(b: Book) -> pd.Series:
    bar = b.close.index[1] - b.close.index[0]
    return (regimes(b.close4, b.close.index + bar) == "crash").set_axis(b.close.index)


def arm(b: Book, flag: pd.Series, short_only: bool) -> pd.DataFrame:
    """Shorts follow the declared rule only (20-bar breakdown, negative momentum, crash on): the
    competition config's frozen short stretch filter and its long-side confirmations would block
    almost every short, which voided the first run."""
    is_long = (b.close / b.close.shift(int(b.cfg["momentum_bars"])) - 1.0) > 0
    long_ok = contenders.entry_confirmation(b.close, b.qv, b.close4, b.cfg)
    ok = ~is_long if short_only else (long_ok & is_long) | ~is_long
    cfg = {**b.cfg, "skip_short_z": []}
    return contenders.targets(b.close, b.sel, cfg, b.entry, b.exit, short_on=flag, entry_ok=ok)


def crash_pnl(net: pd.Series, flag: pd.Series, a: str, z: str) -> float:
    n, f = net.loc[a:z], flag.loc[a:z]
    return float(np.log1p(n[f.reindex(n.index).fillna(False).to_numpy()]).sum())


def shifted(flag: pd.Series, rng) -> pd.Series:
    bar = flag.index[1] - flag.index[0]
    k = int(rng.uniform(30, 180) * pd.Timedelta(days=1) / bar)
    return pd.Series(np.roll(flag.to_numpy(), k), index=flag.index)


def main() -> int:
    rng = np.random.default_rng(11)
    out = {}
    trials = []
    for iv in ("30m", "1h"):
        b = book(iv)
        flag = crash_flag(b)
        days = {t: int(flag.loc[a:z].resample("1D").max().sum()) for t, (a, z) in PERIODS.items()}
        c0 = describe(*run(b, stress.weights(b)))
        cc_net, cc_turn = run(b, arm(b, flag, False))
        cc = describe(cc_net, cc_turn)
        s_net, _ = run(b, arm(b, flag, True))
        s_crash = {t: crash_pnl(s_net, flag, *PERIODS[t]) for t in ("fit", "holdout")}
        ctrl = {"fit": [], "holdout": []}
        for _ in range(SEEDS):
            f2 = shifted(flag, rng)
            n2, _ = run(b, arm(b, f2, True))
            for t in ctrl:
                ctrl[t].append(crash_pnl(n2, f2, *PERIODS[t]))
        enough = all(days[t] >= 20 for t in ("fit", "holdout"))
        checks = {}
        for t in ("fit", "holdout"):
            checks[t] = {"median_ge_c0": cc[t]["median_pct"] >= c0[t]["median_pct"],
                         "worst_within_2pp": cc[t]["worst_pct"] >= c0[t]["worst_pct"] - 2.0,
                         "short_crash_pnl_positive": s_crash[t] > 0,
                         "beats_18_of_20_shifted": sum(s_crash[t] > x for x in ctrl[t]) >= 18}
        verdict = "INSUFFICIENT" if not enough else (
            "PASS" if all(all(v.values()) for v in checks.values()) else "FAIL")
        out[iv] = {"crash_days": days, "C0": c0, "C_crash": cc,
                   "S_only_crash_log_pnl": {t: round(v * 100, 3) for t, v in s_crash.items()},
                   "shifted_median_log_pnl": {t: round(float(np.median(v)) * 100, 3) for t, v in ctrl.items()},
                   "shifted_beaten": {t: int(sum(s_crash[t] > x for x in ctrl[t])) for t in ctrl},
                   "checks": checks, "verdict": verdict}
        print(iv, json.dumps({k: out[iv][k] for k in ("crash_days", "S_only_crash_log_pnl", "shifted_median_log_pnl",
                                                      "shifted_beaten", "verdict")}), flush=True)
        for t in ("fit", "holdout", "recent"):
            print(f"  {t:8s} C0 med {c0[t]['median_pct']:+6.2f} worst {c0[t]['worst_pct']:+6.2f} | "
                  f"C_crash med {cc[t]['median_pct']:+6.2f} worst {cc[t]['worst_pct']:+6.2f}", flush=True)
        trials += [{"signal": "crash_shorts", "gate": "crash_shorts", "config": f"crash_shorts:{a}@{iv}",
                    "status": verdict.lower(), "note": "rerun after the void first run, DECISIONS.md#crash-shorts-outcome"} for a in ("S_only", "C_crash")]
    (RESULTS / "crash_shorts.json").write_text(json.dumps(out, indent=1, default=str))
    record_trials(trials)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
