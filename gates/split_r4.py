"""The improved split: the staged 50/50 split against the R4 rule half with the ride, a combined per-coin cap
and a heavier ride share, replayed on combined weights at the 5m clock.

Declared in config/split_r4.yaml.
DECISIONS.md#split-r4-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_exits import random_signal
from archive.gates.ride_exits import weights as ride_weights
from bot import feed
from bot.settings import ROOT
from core.config import RESULTS
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe
from gates.regime_competition import weights as rule_weights
from signals.exit_clock import to_fast

START, SPLIT = pd.Timestamp("2026-08-01", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")
ARMS = {"S0": ("R0", 0.5, None), "S4": ("R4", 0.5, None), "S4c": ("R4", 0.5, 0.35),
        "S4t": ("R4", 0.4, None), "S4ct": ("R4", 0.4, 0.35)}


def frame(fr: dict, k: str) -> pd.DataFrame:
    return pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    tot, dd = float(eq.iloc[-1] - 1), float((eq / eq.cummax() - 1).min())
    return {"total": round(tot * 100, 1), "maxDD": round(dd * 100, 1), "tot_dd": round(tot / -dd, 2) if dd < 0 else None}


def windows(net: pd.Series) -> dict:
    return {"full": stats(net), "pre": stats(net.loc[:SPLIT]), "live": stats(net.loc[SPLIT:])}


def combine(rule5: pd.DataFrame, ride5: pd.DataFrame, rule_share: float, cap: float | None) -> pd.DataFrame:
    w = rule_share * rule5 + (1 - rule_share) * ride5
    return w.clip(upper=cap) if cap else w


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    syms = universe("momentum_top3_30m")
    now = pd.Timestamp.now(tz="UTC")
    s30 = START - pd.Timedelta(days=6)
    f30 = feed.bar_frame(syms, "30m", int((now - s30) / pd.Timedelta("30min")) + 10)
    f4 = feed.bar_frame(syms, "4h", int((now - s30) / pd.Timedelta("4h")) + 100)
    s5 = START - pd.Timedelta(days=1)
    f5 = feed.bar_frame(syms, "5m", int((now - s5) / pd.Timedelta("5min")) + 10)
    c30, q30, c4 = frame(f30, "close").loc[s30:], frame(f30, "quote_volume").loc[s30:], frame(f4, "close")
    c5, h5 = frame(f5, "close").loc[s5:], frame(f5, "high").loc[s5:]
    cols = [c for c in c5.columns if c in c30.columns]
    c5, h5, c30, q30 = c5[cols], h5[cols], c30[cols], q30[cols]
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in cols if s in specs})
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())["contenders"]
    rl = yaml.safe_load((ROOT / "config" / "regime_ls_30m.yaml").read_text())
    rules30 = {"R0": rule_weights(c30, q30, c4, comp, None, False)[0],
               "R4": rule_weights(c30, q30, c4, rl["contenders"], rl["regime"], False)[0]}
    rules5 = {k: to_fast(w, c30.index, c5.index).fillna(0.0) for k, w in rules30.items()}
    cfg = yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"]["ride|+5%|24h"]
    sig = (c5 / c5.shift(3) - 1.0).to_numpy() >= float(cfg["thresh_pct"]) / 100
    ride5 = ride_weights(c5, h5, sig, cfg, "cap", 0.0)
    out: dict = {"ref": "DECISIONS.md#split-r4-declaration", "bars_end": str(c5.index[-1]), "coins": len(cols),
                 "reference_stress_S0": {"total": 85.5, "maxDD": -14.8}}
    nets = {}
    for arm, (rule, share, cap) in ARMS.items():
        w = combine(rules5[rule], ride5, share, cap)
        net, turn = lwr.simulate(c5, w, tick, True)
        net = net.loc[START:]
        nets[arm] = net
        lwr.FEE, lwr.SHORT_FEE = 0.001, 0.002
        n2, _ = lwr.simulate(c5, w, tick, True)
        lwr.FEE, lwr.SHORT_FEE = 0.0005, 0.0010
        out[arm] = {**windows(net), "fees_x2": stats(n2.loc[START:]),
                    "max_coin_weight": round(float(w.loc[START:].max().max()), 3),
                    "mean_gross": round(float(w.loc[START:].abs().sum(axis=1).mean()), 3),
                    "turnover_per_day": round(float(turn.loc[START:].sum() / max(1, (now - START).days)), 2)}
    r = {k: out[k] for k in ARMS}

    def better(x: dict, y: dict) -> bool:
        return all(x[w]["total"] > y[w]["total"] and (x[w]["tot_dd"] or -9) > (y[w]["tot_dd"] or -9) for w in ("pre", "live"))

    def adds(x: dict, base: dict) -> bool:
        return all((x[w]["tot_dd"] or -9) > (base[w]["tot_dd"] or -9) and x[w]["total"] >= base[w]["total"] - 2
                   for w in ("pre", "live"))

    s0_gap = round(r["S0"]["full"]["total"] - 85.5, 1)
    choice = "S0"
    checks = {"S0_within_15pp_of_stress": abs(s0_gap) <= 15, "S4_beats_S0": better(r["S4"], r["S0"])}
    if checks["S0_within_15pp_of_stress"] and checks["S4_beats_S0"]:
        choice = "S4"
        checks["cap_adds"] = adds(r["S4c"], r["S4"])
        checks["tilt_adds"] = adds(r["S4t"], r["S4"])
        if checks["cap_adds"] and checks["tilt_adds"]:
            checks["both_adds"] = adds(r["S4ct"], r["S4"]) and adds(r["S4ct"], r["S4c"]) and adds(r["S4ct"], r["S4t"])
            choice = "S4ct" if checks["both_adds"] else max(("S4c", "S4t"), key=lambda k: r[k]["full"]["tot_dd"] or -9)
        elif checks["cap_adds"]:
            choice = "S4c"
        elif checks["tilt_adds"]:
            choice = "S4t"
    rule, share, cap = ARMS[choice]
    checks["fees_x2_keeps_choice_over_S0"] = choice == "S0" or r[choice]["fees_x2"]["total"] > r["S0"]["fees_x2"]["total"]
    rng = np.random.default_rng(13)
    ctrl = []
    for _ in range(a.seeds):
        rs = random_signal(sig, c5.index, rng)
        w = combine(rules5[rule], ride_weights(c5, h5, rs, cfg, "cap", 0.0), share, cap)
        ctrl.append(stats(lwr.simulate(c5, w, tick, True)[0].loc[START:])["total"])
    checks["beats_16_of_20_random"] = sum(r[choice]["full"]["total"] > c for c in ctrl) >= 16
    out.update({"s0_gap_vs_stress_pp": s0_gap, "control_random_totals": ctrl, "checks": checks, "choice": choice})
    (RESULTS / "split_r4.json").write_text(json.dumps(out, indent=1, default=str))
    for k in ARMS:
        x = r[k]
        print(f"{k:5s} full {x['full']} pre {x['pre']['total']}/{x['pre']['maxDD']} live {x['live']['total']}/{x['live']['maxDD']} "
              f"x2 {x['fees_x2']['total']} maxcoin {x['max_coin_weight']} gross {x['mean_gross']}")
    print(json.dumps({"s0_gap": s0_gap, "controls": ctrl, "checks": checks, "choice": choice}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
