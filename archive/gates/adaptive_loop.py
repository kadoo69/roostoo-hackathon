"""The stop-and-retune loop: hold the best recent configuration, and when a detector says the market changed,
stand aside, re-select on the newest data and resume. Compared with the static staged split, a random-firing
control and the whole grid of detectors, look-backs and pauses.

Declared in config/adaptive_loop.yaml before any number was computed.
DECISIONS.md#adaptive-loop-declaration
"""
from __future__ import annotations

import argparse
import json
from itertools import product

import numpy as np
import pandas as pd
import yaml

from archive.gates.ride_exits import weights as ride_weights
from bot import feed
from bot.settings import ROOT
from core.config import RESULTS
from data import universe as ru
from gates import let_winners_run as lwr
from gates.missed_replay import universe
from gates.regime_competition import weights as rule_weights
from signals import regime_ls

CACHE = ROOT / "data" / "cache" / "adaptive_loop_arms.pkl"
START, SPLIT = pd.Timestamp("2026-08-01", tz="UTC"), pd.Timestamp("2026-09-19", tz="UTC")
SWITCH, STOP, RESUME = 0.001, 0.0005, 0.0005
DETECTORS = ("dd5", "dd10", "regime", "cal1d", "cal3d", "never")
W_DAYS, STOPS = (3, 7, 14), (0, 12)
PRIMARY = ("dd5", 7, 12)


def col(fr: dict, k: str) -> pd.DataFrame:
    return pd.DataFrame({s: f.set_index("open_time")[k] for s, f in fr.items() if len(f)}).sort_index()


def build_arms(refresh: bool) -> tuple[pd.DataFrame, pd.Series]:
    if CACHE.exists() and not refresh:
        return pd.read_pickle(CACHE)
    syms = universe("momentum_top3_30m")
    now = pd.Timestamp.now(tz="UTC")
    a30 = pd.Timestamp("2026-07-10", tz="UTC")
    f30 = feed.bar_frame(syms, "30m", int((now - a30) / pd.Timedelta("30min")) + 10)
    f4 = feed.bar_frame(syms, "4h", int((now - a30) / pd.Timedelta("4h")) + 100)
    close, qv, close4 = col(f30, "close").loc[a30:], col(f30, "quote_volume").loc[a30:], col(f4, "close")
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close.columns if s in specs})
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())["contenders"]
    rl = yaml.safe_load((ROOT / "config" / "regime_ls_30m.yaml").read_text())
    rcc, rcfg = rl["contenders"], rl["regime"]
    arms = {}
    for k, (cc, rc, sh) in {"R0": (comp, None, False), "R1": (rcc, rcfg, True),
                            "R3": ({**comp, "htf_confirm": False}, None, False), "R4": (rcc, rcfg, False)}.items():
        w, _ = rule_weights(close, qv, close4, cc, rc, sh)
        arms[k] = lwr.simulate(close, w, tick, True)[0]
    a5 = pd.Timestamp("2026-07-14", tz="UTC")
    f5 = feed.bar_frame(syms, "5m", int((now - a5) / pd.Timedelta("5min")) + 10)
    c5, h5 = col(f5, "close").loc[a5:], col(f5, "high").loc[a5:]
    cfg = yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"]["ride|+5%|24h"]
    r3 = (c5 / c5.shift(3) - 1.0).to_numpy()
    for th in (1, 2, 3):
        w = ride_weights(c5, h5, r3 >= th / 100, cfg, "cap", 0.0)
        n5 = lwr.simulate(c5, w, tick, True)[0]
        arms[f"ride{th}"] = (1 + n5).groupby(n5.index.floor("30min")).prod() - 1
    A = pd.DataFrame(arms).loc[a5 + pd.Timedelta(days=1):].fillna(0.0)
    A["S0"] = 0.5 * A["R0"] + 0.5 * A["ride2"]
    A["S4"] = 0.5 * A["R4"] + 0.5 * A["ride2"]
    A["cash"] = 0.0
    lr = np.log(close).diff()
    pool = lr.mean(axis=1)
    down = (regime_ls.state(close, rcfg) == "DOWN").astype(int)
    ratio = pool.rolling(48).std() / pool.rolling(336).std()
    above = (ratio > 1.5).astype(int)
    event = ((down.diff().abs() > 0) | (above.diff().abs() > 0)).reindex(A.index).fillna(False)
    pd.to_pickle((A, event), CACHE)
    return A, event


def run_loop(A: pd.DataFrame, event: pd.Series, det: str, w_days: int, stop: int,
             forced: np.ndarray | None = None) -> tuple[pd.Series, np.ndarray, list]:
    trail = np.exp(np.log1p(A).rolling(w_days * 48).sum()) - 1
    idx = A.index[A.index >= START]
    cols = list(A.columns)
    R = A.loc[idx].to_numpy()
    TR = trail.loc[idx].to_numpy()
    EV = event.loc[idx].to_numpy()
    out = np.zeros(len(idx))
    fires = np.zeros(len(idx), dtype=bool)
    picks = []
    pos = int(np.nanargmax(TR[0]))
    picks.append((str(idx[0]), cols[pos]))
    eq, peak, adopted, wait = 1.0, 1.0, 0, 0
    for t in range(len(idx)):
        r = R[t, pos] if pos is not None else 0.0
        cost = 0.0
        eq_new = eq * (1 + r)
        peak = max(peak, eq_new)
        if wait > 0:
            wait -= 1
            if wait == 0:
                pos = int(np.nanargmax(TR[t]))
                cost += RESUME if cols[pos] != "cash" else 0.0
                picks.append((str(idx[t]), cols[pos]))
                peak, adopted = eq_new, t
        else:
            if forced is not None:
                fire = bool(forced[t])
            elif det in ("dd5", "dd10"):
                fire = eq_new / peak - 1 <= -(0.05 if det == "dd5" else 0.10)
            elif det == "regime":
                fire = bool(EV[t])
            elif det in ("cal1d", "cal3d"):
                fire = t - adopted >= (48 if det == "cal1d" else 144)
            else:
                fire = False
            if fire:
                fires[t] = True
                if stop > 0:
                    if pos is not None and cols[pos] != "cash":
                        cost += STOP
                    pos, wait = None, stop
                else:
                    new = int(np.nanargmax(TR[t]))
                    if new != pos:
                        cost += SWITCH if "cash" not in (cols[new], cols[pos]) else STOP
                        picks.append((str(idx[t]), cols[new]))
                    pos = new
                    peak, adopted = eq_new, t
        out[t] = (1 + r) * (1 - cost) - 1
        eq = eq_new * (1 - cost)
    return pd.Series(out, index=idx), fires, picks


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    tot, dd = float(eq.iloc[-1] - 1), float((eq / eq.cummax() - 1).min())
    return {"total": round(tot * 100, 1), "maxDD": round(dd * 100, 1),
            "tot_dd": round(tot / -dd, 2) if dd < 0 else None}


def windows(net: pd.Series) -> dict:
    return {"full": stats(net), "pre": stats(net.loc[:SPLIT]), "live": stats(net.loc[SPLIT:])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    A, event = build_arms(a.refresh)
    out: dict = {"ref": "DECISIONS.md#adaptive-loop-declaration", "bars_end": str(A.index[-1]),
                 "static": {k: windows(A[k].loc[START:]) for k in A.columns}}
    grid = {}
    for det, w, st in product(DETECTORS, W_DAYS, STOPS):
        if det in ("cal1d", "cal3d", "never") and st:
            continue
        net, fires, picks = run_loop(A, event, det, w, st)
        grid[f"{det}|W{w}|stop{st}"] = {**windows(net), "fires": int(fires.sum()), "switches": len(picks) - 1,
                                        "picks": pd.Series([p for _, p in picks]).value_counts().to_dict()}
    out["grid"] = grid
    pkey = f"{PRIMARY[0]}|W{PRIMARY[1]}|stop{PRIMARY[2]}"
    pnet, pf, ppicks = run_loop(A, event, *PRIMARY)
    out["primary_picks"] = ppicks
    idx = pnet.index
    rng = np.random.default_rng(5)
    ctrl = []
    for _ in range(a.seeds):
        forced = np.zeros(len(idx), dtype=bool)
        for m in (idx < SPLIT, idx >= SPLIT):
            k = int(pf[m].sum())
            if k:
                forced[rng.choice(np.flatnonzero(m), size=k, replace=False)] = True
        ctrl.append(stats(run_loop(A, event, *PRIMARY, forced=forced)[0])["total"])
    out["control_random_totals"] = ctrl
    s0, p = out["static"]["S0"], grid[pkey]
    med = float(np.median([g["full"]["total"] for g in grid.values()]))
    checks = {"beats_S0_total_pre": p["pre"]["total"] > s0["pre"]["total"],
              "beats_S0_total_live": p["live"]["total"] > s0["live"]["total"],
              "beats_S0_totdd_pre": (p["pre"]["tot_dd"] or -9) > (s0["pre"]["tot_dd"] or -9),
              "beats_S0_totdd_live": (p["live"]["tot_dd"] or -9) > (s0["live"]["tot_dd"] or -9),
              "beats_16_of_20_controls": sum(p["full"]["total"] > c for c in ctrl) >= 16,
              "grid_median_beats_S0": med > s0["full"]["total"]}
    out["grid_median_full_total"] = med
    out["checks"] = checks
    out["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    (RESULTS / "adaptive_loop.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"static": {k: v["full"] for k, v in out["static"].items()}, "primary": p,
                      "control": ctrl, "grid_median": med, "checks": checks, "verdict": out["verdict"]}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
