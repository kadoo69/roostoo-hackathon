"""Cross-venue feature study against the deployed momentum book.

All rules and windows are frozen in config/source_edges.yaml. This module
creates research results only; it is never imported by an execution bot.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core.config import ROOT
from data import flow
from gates.concentration import context, rank_score
from gates import positioning_edges as pe
from gates.positioning_edges import describe, paired, ranked, simulate
from ml_research.source_features import FOUR_HOURS, forward, historical

CONFIG = ROOT / "config" / "source_edges.yaml"
OUT = ROOT / "results" / "source_edges.json"
REPORT = ROOT / "results" / "source_edges.md"
START = pd.Timestamp("2024-12-01", tz="UTC")


def windows(cfg: dict) -> dict[str, tuple[str, str]]:
    return {k: tuple(v) for k, v in cfg["meta"]["windows"].items()}


def score_arms(momentum: pd.DataFrame, live: pd.DataFrame, fields: dict) -> dict[str, pd.DataFrame]:
    """Fixed half-weight tilts; missing Hyperliquid data is neutral."""
    mom = momentum.where(live).rank(axis=1, pct=True)
    hf = fields["hl_funding_3d"].where(live)
    bf = fields["bn_funding_3d"].where(live)
    spread = fields["funding_diff_3d"].where(live)
    h_rank = hf.rank(axis=1, pct=True).fillna(0.5)
    s_rank = spread.rank(axis=1, pct=True).fillna(0.5)
    consensus = ((hf < 0) & (bf < 0)).astype(float)
    inverse_consensus = ((hf > 0) & (bf > 0)).astype(float)
    scores = {
        "control": momentum,
        "hyper_funding_tilt": mom + 0.5 * (0.5 - h_rank),
        "cross_venue_tilt": mom + 0.5 * (0.5 - s_rank),
        "consensus_tilt": mom + 0.5 * consensus,
        "inverse_hyper": mom - 0.5 * (0.5 - h_rank),
        "inverse_spread": mom - 0.5 * (0.5 - s_rank),
        "inverse_consensus": mom + 0.5 * inverse_consensus,
    }
    expanding = fields["stable_impulse_7d"] > 0
    scores["cross_venue_plus_stable"] = scores["cross_venue_tilt"].where(
        np.repeat(expanding.to_numpy()[:, None], len(mom.columns), axis=1), mom)
    scores["inverse_spread_plus_stable"] = scores["inverse_spread"].where(
        np.repeat(expanding.to_numpy()[:, None], len(mom.columns), axis=1), mom)
    return {k: ranked(v, live) for k, v in scores.items()}


def xs_ic(feature: pd.DataFrame, close: pd.DataFrame, live: pd.DataFrame,
          period: tuple[str, str], horizon: int = 6) -> dict:
    """Non-overlapping 4h decisions and next-day rank IC among covered candidates."""
    fwd = close.shift(-horizon) / close - 1.0
    ics = []
    used = 0
    for t in close.loc[period[0]:period[1]].index[::horizon]:
        x, y = feature.loc[t].where(live.loc[t]), fwd.loc[t]
        good = x.notna() & y.notna()
        if good.sum() >= 4:
            ics.append(x[good].rank().corr(y[good].rank()))
            used += int(good.sum())
    arr = np.asarray([x for x in ics if np.isfinite(x)])
    if len(arr) < 10:
        return {"n": int(len(arr)), "coin_decisions": used}
    return {"n": int(len(arr)), "coin_decisions": used,
            "mean_ic": round(float(arr.mean()), 4),
            "t": round(float(arr.mean() / arr.std(ddof=1) * np.sqrt(len(arr))), 2)
                 if arr.std(ddof=1) > 0 else None}


def market_corr(feature: pd.Series, close: pd.Series, period: tuple[str, str],
                horizon: int = 18) -> dict:
    fwd = close.shift(-horizon) / close - 1.0
    pair = pd.concat([feature, fwd], axis=1).loc[period[0]:period[1]].dropna().iloc[::horizon]
    if len(pair) < 10:
        return {"n": int(len(pair))}
    return {"n": int(len(pair)), "corr": round(float(pair.iloc[:, 0].corr(pair.iloc[:, 1])), 4)}


def describe_forward() -> dict:
    f = forward()
    if f.empty:
        return {}
    out = {}
    for source, group in f.groupby("source"):
        out[source] = {"rows": int(len(group)),
                       "first": group["available_at"].min().isoformat(),
                       "last": group["available_at"].max().isoformat(),
                       "distinct_days": int(group["available_at"].dt.floor("D").nunique())}
    return out


def run(cfg: dict) -> dict:
    win = windows(cfg)
    close4, qv4, selected4, position4 = context(30)
    close4, qv4, selected4, position4 = (x.loc[START:] for x in
                                               (close4, qv4, selected4, position4))
    names = sorted(set(selected4.columns[selected4.any()]) | {"BTCUSDT", "ETHUSDT"})
    close4, qv4, selected4, position4 = (
        x[names] for x in (close4, qv4, selected4, position4))
    live = position4.where(selected4, 0.0) > 0.5
    decision_grid = close4.index + FOUR_HOURS
    fields = historical(decision_grid, names)
    fields = {k: v.set_axis(close4.index) for k, v in fields.items()}
    momentum = rank_score("momentum", close4, qv4, position4, 40)
    choices = score_arms(momentum, live, fields)
    close1 = flow.panel("1h")["close"][names].loc[START:]
    results = {"declaration": str(CONFIG.relative_to(ROOT)),
               "generated_at": dt.datetime.now(dt.UTC).isoformat(),
               "names": len(names), "history_start": str(close4.index.min()),
               "forward_only": describe_forward(), "windows": win}
    results["coverage"] = {}
    for label, (lo, hi) in win.items():
        eligible = live.loc[lo:hi]
        known = fields["funding_diff_3d"].loc[lo:hi].notna()
        results["coverage"][label] = {
            "candidate_fraction": round(float((known & eligible).sum().sum() /
                                              max(1, eligible.sum().sum())), 4),
            "active_bars_with_4_covered": int(((known & eligible).sum(axis=1) >= 4).sum()),
        }
    results["diagnostics"] = {}
    for feature in ("hl_funding_3d", "bn_funding_3d", "funding_diff_3d",
                    "hl_premium_24h", "premium_diff_24h"):
        results["diagnostics"][feature] = {
            label: xs_ic(fields[feature], close4, live, period) for label, period in win.items()}
    for feature in ("stable_impulse_7d", "stable_impulse_30d", "dvol_btc"):
        results["diagnostics"][feature] = {
            label: market_corr(fields[feature], close4["BTCUSDT"], period)
            for label, period in win.items()}
    runs = {}
    for name, choice in choices.items():
        daily, events = simulate(choice, close4.index, close1)
        runs[name] = daily
        print(f"simulated {name}: {events}", flush=True)
    rng = np.random.default_rng(625)
    results["arms"] = {}
    controls = {"hyper_funding_tilt": "inverse_hyper",
                "cross_venue_tilt": "inverse_spread",
                "consensus_tilt": "inverse_consensus",
                "cross_venue_plus_stable": "inverse_spread_plus_stable"}
    for name, daily in runs.items():
        if name.startswith("inverse_"):
            continue
        row = {"selection_change_fraction": round(float((choices[name] != choices["control"]).any(axis=1).mean()), 4)}
        for label, (lo, hi) in win.items():
            row[label] = describe(daily, lo, hi)
            if name != "control":
                row[label]["vs_control"] = paired(runs["control"], daily, lo, hi, rng)
        if name in controls:
            inverse = controls[name]
            row["inverse_holdout"] = describe(runs[inverse], *win["holdout"])
        results["arms"][name] = row
    base = results["arms"]["control"]
    verdict = {}
    for name, row in results["arms"].items():
        if name == "control":
            continue
        gains = {w: round(row[w]["median_pct"] - base[w]["median_pct"], 3)
                 for w in win}
        odds = {w: round(row[w]["p_gt5"] - base[w]["p_gt5"], 4) for w in win}
        inverse_gain = round(row["inverse_holdout"]["median_pct"] -
                             base["holdout"]["median_pct"], 3)
        preliminary = (all(gains[w] > 0 and odds[w] > 0 for w in
                      ("validation", "holdout", "recent"))
                  and row["holdout"]["vs_control"]["p_median"] < 0.10
                  and inverse_gain < 0.5 * gains["holdout"])
        cost_stress = None
        if preliminary:
            old_fee = pe.FEE
            try:
                pe.FEE = old_fee * 2
                expensive_control, _ = pe.simulate(choices["control"], close4.index, close1)
                expensive_arm, _ = pe.simulate(choices[name], close4.index, close1)
            finally:
                pe.FEE = old_fee
            cost_stress = {w: round(describe(expensive_arm, *win[w])["median_pct"] -
                                    describe(expensive_control, *win[w])["median_pct"], 3)
                           for w in ("validation", "holdout", "recent")}
        passes = bool(preliminary and cost_stress is not None and all(v > 0 for v in cost_stress.values()))
        verdict[name] = {"median_gain_pp": gains, "p_gt5_gain": odds,
                         "inverse_holdout_gain_pp": inverse_gain,
                         "cost_2x_median_gain_pp": cost_stress,
                         "candidate": bool(passes)}
    results["verdict"] = verdict
    selected = [k for k, v in verdict.items() if v["candidate"]]
    results["best_validated"] = selected if selected else None
    return results


def write_report(result: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str))
    lines = ["# Cross-venue source edge study", "",
             "Research only. No execution bot reads these features.", "",
             f"Declaration: `config/source_edges.yaml`. Generated: {result['generated_at']}.", "",
             "| Arm | Fit Δ median pp | Validation | Holdout | Recent | Candidate |",
             "|---|---:|---:|---:|---:|---|"]
    for name, v in result["verdict"].items():
        g = v["median_gain_pp"]
        lines.append(f"| {name} | {g['fit']:+.2f} | {g['validation']:+.2f} | "
                     f"{g['holdout']:+.2f} | {g['recent']:+.2f} | {'yes' if v['candidate'] else 'no'} |")
    lines += ["", "Coverage of active candidates with both funding feeds:", ""]
    for tag, c in result["coverage"].items():
        lines.append(f"- {tag}: {c['candidate_fraction']:.1%}; "
                     f"{c['active_bars_with_4_covered']} bars had at least four covered candidates.")
    lines += ["", "Forward-only sources:", ""]
    for source, row in result["forward_only"].items():
        lines.append(f"- {source}: {row['rows']} rows across {row['distinct_days']} day(s).")
    lines += ["", "Historical DefiLlama supply may have revisions. Deribit gamma, order book and "
              "trade-size snapshots lack a comparable history; they need forward outcomes before "
              "their edge or optimal combination can be claimed.", "",
              f"Full IC, return, probability and bootstrap results: `{OUT.relative_to(ROOT)}`."]
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if not args.run:
        ap.error("pass --run")
    cfg = yaml.safe_load(CONFIG.read_text())
    result = run(cfg)
    write_report(result)
    print(f"result: {OUT}")
    print(f"validated: {result['best_validated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
