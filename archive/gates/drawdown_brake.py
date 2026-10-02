"""A downside mirror of the target lock, on the competition's windows. config/drawdown_brake.yaml.

Inside each 14-day window the book's exposure is a multiplier on its hourly net
return: 0.5 once the window is 8% below its start (the brake), 0.3 once it is 5%
above (the lock), the lower of the two once both have fired. `window_table`
reproduces gates.competition_wf.windows_hourly exactly when the brake is off, and
that is asserted before any arm is read. DECISIONS.md#drawdown-brake-outcome.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates import competition_wf as cw
from gates.competition_window import window_stats
from signals import donchian

SEEDS = int(os.environ.get("BRAKE_SEEDS", "20"))
BRAKE, BRAKE_GROSS, LOCK, LOCK_GROSS = 0.08, 0.5, 0.05, 0.3
SIDE_COST = cw.FEE + 0.0004


def declaration() -> dict:
    with (ROOT / "config" / "drawdown_brake.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def path(seg: np.ndarray, lock: float | None, brake: float | None, force_at: int | None = None) -> tuple[np.ndarray, int | None]:
    seg = seg.copy()
    level, fired_brake = 1.0, None
    eq = 1.0
    charge = 0.0
    for i in range(len(seg)):
        seg[i] = seg[i] * level - charge
        charge = 0.0
        eq *= 1.0 + seg[i]
        if i + 1 >= len(seg):
            break
        want = level
        if lock is not None and eq >= 1.0 + lock:
            want = min(want, LOCK_GROSS)
        hit = (force_at is not None and i == force_at) or (force_at is None and brake is not None and eq <= 1.0 - brake)
        if hit and fired_brake is None:
            want = min(want, BRAKE_GROSS)
            fired_brake = i
        if want < level:
            charge = (level - want) * SIDE_COST
            level = want
    return seg, fired_brake


def window_table(net1: pd.Series, lock=None, brake=None, entry_cost=0.0, force: dict | None = None) -> pd.DataFrame:
    starts = net1.index[net1.index.hour == 0]
    vals = net1.to_numpy()
    pos = {t: i for i, t in enumerate(net1.index)}
    rows = []
    for s in starts:
        i = pos[s]
        seg = vals[i:i + 14 * 24]
        if len(seg) < 14 * 24:
            break
        seg = seg.copy()
        seg[0] -= entry_cost
        f = None if force is None else force.get(s)
        if force is not None and f is None:
            seg, fired = path(seg, lock, None)
        else:
            seg, fired = path(seg, lock, brake, f)
        eq = np.cumprod(1.0 + seg)
        daily = eq[23::24] / np.r_[1.0, eq[23::24][:-1]] - 1.0
        rows.append((s, eq[-1] - 1.0, float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1.0).min()), daily, fired))
    w = pd.DataFrame([(s, r, dd, fb) for s, r, dd, _, fb in rows], columns=["start", "ret", "maxdd", "fired"]).set_index("start")
    ws = window_stats(np.stack([d for _, _, _, d, _ in rows]), [s for s, *_ in rows])
    w["screen3"] = ws["screen3"].to_numpy()
    return w


def describe(w: pd.DataFrame) -> dict:
    out = {}
    for p, (a, b) in cw.PERIODS.items():
        s = w.loc[a:b]
        d = cw.describe(s)
        d["median_maxdd_pct"] = round(float(s.maxdd.median()) * 100, 1)
        d["p10_maxdd_pct"] = round(float(s.maxdd.quantile(0.1)) * 100, 1)
        d["p_maxdd_lt15"] = round(float((s.maxdd <= -0.15).mean()), 3)
        if "fired" in s:
            d["brake_fired"] = round(float(s.fired.notna().mean()), 3)
        out[p] = d
    return out


def main() -> int:
    declaration()
    close4, sel4, close1, tick = cw.load()
    live4 = (donchian.position(close4, 20, "lowchannel", 10) > 0.5) & sel4
    mom4 = close4 / close4.shift(40) - 1.0
    net = cw.book_hourly(close1, close4.index, long4=cw.ranked(mom4, live4), tick=tick)
    ec = cw.FEE + float((tick / close1.median()).median())
    for lock in (None, LOCK):
        ref = cw.windows_hourly(net, lock=lock, entry_cost=ec)
        mine = window_table(net, lock=lock, entry_cost=ec)
        gap = float(np.max(np.abs(ref.ret.to_numpy() - mine.ret.to_numpy())))
        print("reconciliation lock", lock, "max |ret gap|", gap, flush=True)
        if gap > 1e-9:
            raise RuntimeError("reconciliation_failed")
    out = {"declaration": "config/drawdown_brake.yaml", "arms": {}, "nonsense": {}}
    rng = np.random.default_rng(41)
    for name, lock in (("B1", None), ("B2", LOCK)):
        ctl = window_table(net, lock=lock, entry_cost=ec)
        arm = window_table(net, lock=lock, brake=BRAKE, entry_cost=ec)
        out["arms"][f"{name}_control"] = describe(ctl)
        out["arms"][name] = describe(arm)
        fired = arm.fired.dropna()
        seeds = []
        for _ in range(SEEDS):
            force = {s: int(rng.integers(0, 14 * 24 - 1)) for s in fired.index}
            seeds.append(describe(window_table(net, lock=lock, brake=BRAKE, entry_cost=ec, force=force)))
        out["nonsense"][name] = {p: {"p_gt2_mean": round(float(np.mean([s[p]["p_gt2"] for s in seeds])), 3),
                                     "median_mean": round(float(np.mean([s[p]["median_pct"] for s in seeds])), 2)}
                                 for p in cw.PERIODS}
        c, a = out["arms"][f"{name}_control"], out["arms"][name]
        ok = all(a[p]["p_gt2"] > c[p]["p_gt2"] and a[p]["median_pct"] > c[p]["median_pct"] for p in cw.PERIODS)
        worst = all(a[p]["worst_pct"] >= c[p]["worst_pct"] - 5 for p in cw.PERIODS)
        gain = a["2025-26"]["p_gt2"] - c["2025-26"]["p_gt2"]
        ng = out["nonsense"][name]["2025-26"]["p_gt2_mean"] - c["2025-26"]["p_gt2"]
        out.setdefault("verdict", {})[name] = {"all_periods": ok, "worst_ok": worst,
                                               "nonsense_ok": bool(gain > 0 and ng < 0.5 * gain),
                                               "candidate": bool(ok and worst and gain > 0 and ng < 0.5 * gain)}
        for p in cw.PERIODS:
            for tag, r in (("ctl", c[p]), (name, a[p])):
                print(f"{tag:4s} {p:8s} med {r['median_pct']:+6.2f} P>2 {r['p_gt2']:.3f} P>15 {r['p_gt15']:.3f} worst {r['worst_pct']:+6.1f} "
                      f"medDD {r['median_maxdd_pct']:6.1f} p10DD {r['p10_maxdd_pct']:6.1f} P(DD<-15) {r['p_maxdd_lt15']:.3f} S3 {r['median_screen3']:+.2f}"
                      + (f" fired {r['brake_fired']:.3f}" if tag != "ctl" else ""), flush=True)
        print("nonsense", name, out["nonsense"][name], "verdict", out["verdict"][name], flush=True)
    (RESULTS / "drawdown_brake.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
