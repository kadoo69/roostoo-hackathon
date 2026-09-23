"""What the end-of-window derisk ramp protects against, measured, not assumed.

HANDOVER.md section 4e measures the ramp's cost and states plainly that its
benefit is unmeasured, because the drawdown column there came from the full
daily series and never saw the ramp. This gate applies the ramp WINDOW
RELATIVE, so it tapers into the end of every rolling 14-day window exactly as
it tapers into the end of the one real one, and scores both tails on the same
footing.

Declaration: config/derisk_ramp.yaml. No argmax, nothing promoted, zero trials.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from gates.competition_window import window_stats
from gates.concentration import context, rank_score

warnings.filterwarnings("ignore")

FEE = 0.0005
POOL, WINDOW, MOM_BARS = 30, 14, 40
A, B, END = "2023-01-01", "2025-01-01", "2026-09-19"
RAMPS = {"none": None, "exact": (11, 68.0), "two_day": (12, 48.0), "three_day": (11, 72.0)}
KILL = -0.25


def declaration() -> dict:
    with (ROOT / "config" / "derisk_ramp.yaml").open() as fh:
        cfg = yaml.safe_load(fh)
    if not cfg["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return cfg


def book(close, qv, sel, pos, n, full):
    score = rank_score("momentum", close, qv, pos, MOM_BARS)
    live = pos.where(sel, 0.0) > 0.5
    chosen = ((score.where(live).rank(axis=1, ascending=False) <= n) & live)
    k = chosen.sum(axis=1)
    denom = k.replace(0, np.nan) if full else pd.Series(float(n), index=chosen.index)
    w = chosen.astype(float).div(denom, axis=0).fillna(0.0)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def legs(w, close):
    ret = close.reindex(columns=w.columns).pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1).fillna(0.0)
    turn = (w - w.shift(1)).abs().sum(axis=1).fillna(0.0)
    expo = w.abs().sum(axis=1).fillna(0.0)
    return pd.DataFrame({"gross": gross, "turn": turn, "expo": expo})


def multiplier(offsets, hours, spec):
    if spec is None:
        return np.ones(len(offsets))
    start, span = spec
    elapsed = (offsets - start) * 24.0 + hours
    return np.clip(1.0 - elapsed / span, 0.0, 1.0)


def ramped_daily(frame, dates, day_index, spec):
    """Daily returns for every rolling window, with the ramp tapering into its end."""
    g = frame["gross"].to_numpy()
    t = frame["turn"].to_numpy()
    e = frame["expo"].to_numpy()
    hours = frame.index.hour.to_numpy().astype(float)
    starts = np.searchsorted(dates, day_index, side="left")
    ends = np.searchsorted(dates, day_index, side="right")
    rows = []
    keep = []
    for i in range(len(day_index) - WINDOW + 1):
        lo, hi = starts[i], ends[i + WINDOW - 1]
        d = dates[lo:hi]
        off = (d - day_index[i]).astype("timedelta64[D]").astype(float)
        m = multiplier(off, hours[lo:hi], spec)
        mp = np.concatenate([[1.0], m[:-1]])
        ep = np.concatenate([[0.0], e[lo:hi - 1]])
        turn_r = m * t[lo:hi] + np.abs(m - mp) * ep
        net = mp * g[lo:hi] - FEE * np.concatenate([[0.0], turn_r[:-1]])
        day = pd.Series(net, index=d)
        comp = (1.0 + day).groupby(day.index).prod() - 1.0
        if len(comp) != WINDOW:
            continue
        rows.append(comp.to_numpy())
        keep.append(day_index[i])
    return (np.stack(rows) if rows else np.zeros((0, WINDOW))), keep


def summarise(w: pd.DataFrame) -> dict:
    return {
        "n_windows": int(len(w)),
        "median_return_pct": round(float(w["ret"].median()) * 100, 3),
        "mean_return_pct": round(float(w["ret"].mean()) * 100, 3),
        "p_clears_5pct": round(float((w["ret"] > 0.05).mean()), 4),
        "p_clears_10pct": round(float((w["ret"] > 0.10).mean()), 4),
        "p_clears_20pct": round(float((w["ret"] > 0.20).mean()), 4),
        "p05_return_pct": round(float(w["ret"].quantile(0.05)) * 100, 3),
        "worst_return_pct": round(float(w["ret"].min()) * 100, 2),
        "p_return_below_minus_10": round(float((w["ret"] < -0.10).mean()), 4),
        "p_return_below_minus_20": round(float((w["ret"] < -0.20).mean()), 4),
        "median_maxdd_pct": round(float(w["maxdd"].median()) * 100, 3),
        "p05_maxdd_pct": round(float(w["maxdd"].quantile(0.05)) * 100, 2),
        "worst_maxdd_pct": round(float(w["maxdd"].min()) * 100, 2),
        "p_maxdd_breaches_kill": round(float((w["maxdd"] <= KILL).mean()), 4),
        "median_screen3": round(float(w["screen3"].median()), 4),
    }


def paired(base: pd.DataFrame, alt: pd.DataFrame) -> dict:
    j = base.join(alt, rsuffix="_r", how="inner")
    worst = j[j["ret"] <= j["ret"].quantile(0.10)]
    best = j[j["ret"] >= j["ret"].quantile(0.90)]
    return {
        "n_paired": int(len(j)),
        "median_return_delta_pp": round(float((j["ret_r"] - j["ret"]).median()) * 100, 3),
        "median_maxdd_delta_pp": round(float((j["maxdd_r"] - j["maxdd"]).median()) * 100, 3),
        "worst_decile": {
            "n": int(len(worst)),
            "median_return_without_pct": round(float(worst["ret"].median()) * 100, 2),
            "median_return_with_pct": round(float(worst["ret_r"].median()) * 100, 2),
            "median_gain_pp": round(float((worst["ret_r"] - worst["ret"]).median()) * 100, 2),
            "median_maxdd_gain_pp": round(float((worst["maxdd_r"] - worst["maxdd"]).median()) * 100, 2),
            "p_ramp_helps": round(float((worst["ret_r"] > worst["ret"]).mean()), 4),
        },
        "best_decile": {
            "n": int(len(best)),
            "median_return_without_pct": round(float(best["ret"].median()) * 100, 2),
            "median_return_with_pct": round(float(best["ret_r"].median()) * 100, 2),
            "median_cost_pp": round(float((best["ret_r"] - best["ret"]).median()) * 100, 2),
        },
        "p_ramp_helps_overall": round(float((j["ret_r"] > j["ret"]).mean()), 4),
        "kill_breaches_without": int((j["maxdd"] <= KILL).sum()),
        "kill_breaches_with": int((j["maxdd_r"] <= KILL).sum()),
    }


def main() -> int:
    declaration()
    close, qv, sel, pos = context(POOL)
    day_index = close.resample("1D").last().index.to_numpy(dtype="datetime64[ns]")
    dates = close.index.normalize().to_numpy(dtype="datetime64[ns]")
    out = {"declaration": "config/derisk_ramp.yaml", "fee_bps": FEE * 1e4,
           "window_days": WINDOW, "kill_switch_drawdown": KILL, "books": {}}
    for name, (n, full) in (("momentum_top3_full", (3, True)),
                            ("momentum_top3_4h", (3, False))):
        w = book(close, qv, sel, pos, n, full)
        frame = legs(w, close)
        out["books"][name] = {}
        tables = {}
        for tag, spec in RAMPS.items():
            mat, idx = ramped_daily(frame, dates, day_index, spec)
            tables[tag] = window_stats(mat, pd.DatetimeIndex(idx))
        for seg, lo, hi in (("fit", A, B), ("hold", B, END)):
            base = tables["none"].loc[lo:hi]
            block = {"none": summarise(base)}
            for tag in RAMPS:
                if tag == "none":
                    continue
                alt = tables[tag].loc[lo:hi]
                block[tag] = summarise(alt)
                block[tag]["vs_none"] = paired(base, alt)
            out["books"][name][seg] = block
            e = block["exact"]
            b = block["none"]
            print(f"{name:20s} {seg:5s} n={b['n_windows']:5d}  "
                  f"medRet {b['median_return_pct']:+6.2f} -> {e['median_return_pct']:+6.2f}  "
                  f"p05 {b['p05_return_pct']:+7.2f} -> {e['p05_return_pct']:+7.2f}  "
                  f"worst {b['worst_return_pct']:+7.2f} -> {e['worst_return_pct']:+7.2f}  "
                  f"medDD {b['median_maxdd_pct']:+6.2f} -> {e['median_maxdd_pct']:+6.2f}  "
                  f"kill {b['p_maxdd_breaches_kill']:.4f} -> {e['p_maxdd_breaches_kill']:.4f}",
                  flush=True)
    (RESULTS / "derisk_ramp.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'derisk_ramp.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
