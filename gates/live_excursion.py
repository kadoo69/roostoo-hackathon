"""How much the live books left on the table, and whether any exit rule could take it.

Reconstructs every closed round trip's minute-resolution price path from the
per-cycle `marks` the bots journal, then replays trailing-stop and fixed-target
exits on those paths. Every headline number is deduplicated to symbol-episodes,
because the same move appears in up to five books at once and that is one
observation, not five.

Declaration: config/live_excursion.yaml.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from bot import blotter
from core.config import RESULTS, ROOT

warnings.filterwarnings("ignore")

BOOKS = ("momentum_top3_4h", "momentum_top5_4h", "momentum_top3_full",
         "momentum_top5_cushion", "donchian_4h", "donchian_1h", "scalper_live")
FEE = 0.0005
TRAILS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05)
TARGETS = (0.02, 0.03, 0.05, 0.08, 0.12)
MIN_MARKS = 30


def declaration() -> dict:
    with (ROOT / "config" / "live_excursion.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def marks(bot: str) -> dict[str, list[tuple[dt.datetime, float]]]:
    out = defaultdict(list)
    for f in sorted(glob.glob(f"live/{bot}/cycles-*.jsonl")):
        for line in open(f):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("ts_utc")
            if not ts:
                continue
            t = dt.datetime.fromisoformat(ts)
            for sym, px in (d.get("marks") or {}).items():
                if px:
                    out[sym].append((t, float(px)))
    for s in out:
        out[s].sort()
    return out


def episodes() -> list[dict]:
    seen, rec = set(), []
    for b in BOOKS:
        m = marks(b)
        try:
            closed = blotter.build(b)["closed"]
        except (FileNotFoundError, KeyError):
            continue
        for tr in closed:
            sym = tr["symbol"]
            e = dt.datetime.fromisoformat(tr["entry_ts"])
            x = dt.datetime.fromisoformat(tr["exit_ts"])
            key = (sym, e.replace(second=0, microsecond=0))
            path = [(t, p) for t, p in m.get(sym, []) if e <= t <= x]
            if len(path) < MIN_MARKS or key in seen:
                continue
            seen.add(key)
            ep = tr["entry_price"]
            hi = max(p for _, p in path)
            lo = min(p for _, p in path)
            t_hi = max(t for t, p in path if p == hi)
            span = (x - e).total_seconds()
            real = tr["return_pct"] / 100.0

            def at(mins, path=path, e=e, ep=ep):
                c = [p for t, p in path if (t - e).total_seconds() <= mins * 60]
                return c[-1] / ep - 1.0 if c else 0.0

            rec.append({"bot": b, "sym": sym, "entry_price": ep, "hold_h": tr["hold_hours"],
                        "real": real, "mfe": hi / ep - 1.0, "mae": lo / ep - 1.0,
                        "capture": real / (hi / ep - 1.0) if hi > ep else float("nan"),
                        "peak_frac": (t_hi - e).total_seconds() / span if span else 0.0,
                        "give_back": (hi / ep - 1.0) - real,
                        "r30": at(30), "r60": at(60),
                        "path": [p for _, p in path]})
    return rec


def replay(rec, kind, param):
    outs, fired = [], 0
    for t in rec:
        ep, peak, hit = t["entry_price"], t["entry_price"], None
        for p in t["path"]:
            peak = max(peak, p)
            if kind == "trail" and peak > ep and p <= peak * (1 - param):
                hit = p
                break
            if kind == "target" and p >= ep * (1 + param):
                hit = ep * (1 + param)
                break
        if hit is None:
            outs.append(t["real"])
        else:
            fired += 1
            outs.append(hit / ep - 1.0 - FEE)
    return np.array(outs), fired


def comovement() -> dict:
    rows = defaultdict(dict)
    for f in sorted(glob.glob("live/*/cycles-*.jsonl")):
        for line in open(f):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("ts_utc")
            if not ts:
                continue
            t = dt.datetime.fromisoformat(ts).replace(second=0, microsecond=0)
            for sym, px in (d.get("marks") or {}).items():
                if px:
                    rows[t][sym] = float(px)
    p = pd.DataFrame(rows).T.sort_index()
    p = p.loc[:, p.notna().sum() > 300]
    if p.shape[1] < 3:
        return {}
    out = {"minutes": int(p.shape[0]), "symbols": int(p.shape[1])}
    for k, lab in ((1, "1min"), (15, "15min"), (60, "60min"), (240, "240min")):
        c = p.pct_change(k).corr()
        s = c.where(~np.eye(len(c), dtype=bool)).stack()
        out[f"mean_corr_{lab}"] = round(float(s.mean()), 4)
        out[f"median_corr_{lab}"] = round(float(s.median()), 4)
    r1 = p.pct_change()
    X = r1.dropna(axis=1, thresh=int(len(r1) * 0.6)).dropna()
    if len(X) > 50:
        Xc = (X - X.mean()) / X.std()
        sv = np.linalg.svd(Xc.values, compute_uv=False)
        out["pc1_share_of_1min_variance"] = round(float((sv**2 / (sv**2).sum())[0]), 4)
    ac = [r1[s].dropna().autocorr(1) for s in r1.columns if r1[s].notna().sum() > 400]
    out["mean_lag1_autocorr_1min"] = round(float(np.nanmean(ac)), 4)
    out["n_symbols_autocorr"] = len(ac)
    return out


def main() -> int:
    declaration()
    rec = episodes()
    if len(rec) < 10:
        print(f"only {len(rec)} episodes, not enough to report")
        return 1
    real = np.array([r["real"] for r in rec])
    mfe = np.array([r["mfe"] for r in rec])
    cap = np.array([r["capture"] for r in rec])
    pk = np.array([r["peak_frac"] for r in rec])
    out = {"declaration": "config/live_excursion.yaml", "n_episodes": len(rec),
           "n_symbols": len(set(r["sym"] for r in rec)),
           "excursion": {
               "median_mfe_pct": round(float(np.median(mfe)) * 100, 3),
               "median_mae_pct": round(float(np.median([r["mae"] for r in rec])) * 100, 3),
               "median_realised_pct": round(float(np.median(real)) * 100, 3),
               "median_capture": round(float(np.nanmedian(cap)), 3),
               "median_peak_position_in_hold": round(float(np.median(pk)), 3),
               "total_give_back_pp": round(float(np.sum(mfe - real)) * 100, 1)},
           "exit_rules": {}, "predictability": {}, "comovement": comovement()}

    base_mean, base_med = float(real.mean()), float(np.median(real))
    print(f"{len(rec)} deduplicated symbol-episodes, {out['n_symbols']} symbols\n")
    print(f"{'rule':16s}{'mean%':>9s}{'median%':>9s}{'fired':>7s}{'wins':>8s}{'vs actual pp':>14s}")
    print(f"{'actual exits':16s}{base_mean*100:>9.2f}{base_med*100:>9.2f}{'-':>7s}{'-':>8s}{'-':>14s}")
    for kind, params in (("trail", TRAILS), ("target", TARGETS)):
        for p in params:
            o, f = replay(rec, kind, p)
            wins = int((o > real).sum())
            name = f"{kind} {p*100:.1f}%"
            out["exit_rules"][name] = {
                "mean_pct": round(float(o.mean()) * 100, 3),
                "median_pct": round(float(np.median(o)) * 100, 3),
                "fired": f, "wins_vs_actual": wins, "n": len(rec),
                "mean_delta_pp": round(float(o.mean() - base_mean) * 100, 3),
                "beats_actual": bool(o.mean() > base_mean and wins > len(rec) / 2)}
            print(f"{name:16s}{o.mean()*100:>9.2f}{np.median(o)*100:>9.2f}{f:>7d}"
                  f"{wins:>4d}/{len(rec):<3d}{(o.mean()-base_mean)*100:>14.2f}")

    for a, b in (("r30", "peak_frac"), ("r60", "peak_frac"), ("r60", "give_back"),
                 ("r60", "real"), ("mfe", "peak_frac")):
        rho, pv = stats.spearmanr([r[a] for r in rec], [r[b] for r in rec])
        out["predictability"][f"{a}_vs_{b}"] = {"spearman": round(float(rho), 4),
                                                "p": round(float(pv), 4)}
    out["candidates"] = [k for k, v in out["exit_rules"].items() if v["beats_actual"]]
    print("\npredictability of an early peak:")
    for k, v in out["predictability"].items():
        print(f"  {k:24s} rho={v['spearman']:+.3f}  p={v['p']:.3f}")
    print("\nco-movement:", json.dumps(out["comovement"]))
    print("\ncandidates by the declared rule:", out["candidates"] or "NONE")
    (RESULTS / "live_excursion.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
