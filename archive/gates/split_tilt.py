"""The staged split with a heavier ride share: rule 40% / ride 60% against 50/50, on the separate-ledger replay.

Declared in config/split_tilt.yaml.
DECISIONS.md#split-tilt-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_exits import random_signal
from archive.gates.ride_exits import weights as ride_weights
from archive.gates.split_r4 import START, frame, ledger, stats, windows
from bot import feed
from bot.settings import ROOT
from core.config import RESULTS
from data import universe as ru
from gates.missed_replay import universe
from gates.regime_competition import weights as rule_weights
from signals.exit_clock import to_fast

SHARES = {"T0": 0.5, "T1": 0.4, "S60": 0.6, "S30": 0.3}


def worst_14d(net: pd.Series) -> float:
    daily = ((1 + net).resample("1D").prod() - 1).dropna()
    r = [float(np.prod(1 + daily.iloc[i:i + 14]) - 1) for i in range(0, len(daily) - 13)]
    return round(min(r) * 100, 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    syms = universe("momentum_top3_30m")
    now = pd.Timestamp.now(tz="UTC")
    s30, s5 = START - pd.Timedelta(days=6), START - pd.Timedelta(days=1)
    f30 = feed.bar_frame(syms, "30m", int((now - s30) / pd.Timedelta("30min")) + 10)
    f4 = feed.bar_frame(syms, "4h", int((now - s30) / pd.Timedelta("4h")) + 100)
    f5 = feed.bar_frame(syms, "5m", int((now - s5) / pd.Timedelta("5min")) + 10)
    c30, q30, c4 = frame(f30, "close").loc[s30:], frame(f30, "quote_volume").loc[s30:], frame(f4, "close")
    c5, h5 = frame(f5, "close").loc[s5:], frame(f5, "high").loc[s5:]
    cols = [c for c in c5.columns if c in c30.columns]
    c5, h5, c30, q30 = c5[cols], h5[cols], c30[cols], q30[cols]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in cols if s in specs})
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())["contenders"]
    rule5 = to_fast(rule_weights(c30, q30, c4, comp, None, False)[0], c30.index, c5.index).fillna(0.0)
    cfg = yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"]["ride|+5%|24h"]
    sig = (c5 / c5.shift(3) - 1.0).to_numpy() >= float(cfg["thresh_pct"]) / 100
    ride5 = ride_weights(c5, h5, sig, cfg, "cap", 0.0)
    out: dict = {"ref": "DECISIONS.md#split-tilt-declaration", "bars_end": str(c5.index[-1]), "reference_S0": 89.5}
    for arm, share in SHARES.items():
        net, top = ledger(c5, rule5, ride5, share, None, tick)
        n2, _ = ledger(c5, rule5, ride5, share, None, tick, fee=0.001)
        out[arm] = {**windows(net), "fees_x2": stats(n2), "worst_14d": worst_14d(net), "max_coin_weight": top}
    t0, t1 = out["T0"], out["T1"]
    rng = np.random.default_rng(17)
    ctrl = [stats(ledger(c5, rule5, ride_weights(c5, h5, random_signal(sig, c5.index, rng), cfg, "cap", 0.0),
                         0.4, None, tick)[0])["total"] for _ in range(a.seeds)]
    checks = {"T0_reproduces_S0_within_1pp": abs(t0["full"]["total"] - 89.5) <= 1.0,
              **{f"beats_{k}_{w}": (t1[w]["total"] > t0[w]["total"]) if k == "total" else
                 ((t1[w]["tot_dd"] or -9) > (t0[w]["tot_dd"] or -9)) for k in ("total", "totdd") for w in ("pre", "live")},
              "fees_x2": t1["fees_x2"]["total"] > t0["fees_x2"]["total"],
              "worst_14d_within_1pp": t1["worst_14d"] >= t0["worst_14d"] - 1.0,
              "beats_16_of_20_random": sum(t1["full"]["total"] > c for c in ctrl) >= 16}
    out.update({"control_random_totals": ctrl, "checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"})
    (RESULTS / "split_tilt.json").write_text(json.dumps(out, indent=1, default=str))
    for k in SHARES:
        x = out[k]
        print(f"{k:4s} rule {SHARES[k]:.0%} full {x['full']} pre {x['pre']['total']}/{x['pre']['maxDD']} "
              f"live {x['live']['total']}/{x['live']['maxDD']} x2 {x['fees_x2']['total']} worst14 {x['worst_14d']} coin {x['max_coin_weight']}")
    print(json.dumps({"controls": ctrl, "checks": checks, "verdict": out["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
