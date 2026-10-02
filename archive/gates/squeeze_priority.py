"""X4 short-squeeze priority, the post-hoc follow-up declared in config/positioning_edges.yaml.

Negative-funding candidates rank ahead of the rest; momentum orders each group.
The control is the identical rank with priority given to a random subset of the
same size at every bar. DECISIONS.md#positioning-edges-outcome.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import flow
from gates import positioning_edges as pe
from gates.concentration import context, rank_score

SEEDS = 20


def priority_rank(score: pd.DataFrame, live: pd.DataFrame, priority: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Priority names first, momentum inside each group. A pct rank is at most 1, so +1 lifts a group."""
    s = score.where(live).rank(axis=1, pct=True) + priority.where(live).fillna(False).astype(float)
    return pe.ranked(s, live, n)


def main() -> int:
    cfg = pe.declaration()
    win = {k: tuple(v) for k, v in cfg["meta"]["windows"].items()}
    close4, qv4, sel4, pos4 = context(30)
    start = pd.Timestamp("2021-10-01", tz="UTC")
    close4, qv4, sel4, pos4 = (x.loc[start:] for x in (close4, qv4, sel4, pos4))
    names = sorted(set(sel4.columns[sel4.any()]) | {"BTCUSDT", "ETHUSDT"})
    close4, sel4, pos4, qv4 = close4[names], sel4[names], pos4[names], qv4[names]
    close1 = flow.panel("1h")["close"][names].loc[start:]
    grid = close1.index + pe.H
    coin_h, _, _ = pe.features(names, grid, close1["BTCUSDT"].set_axis(grid))
    fund = pe.at_close(coin_h["funding_3d"], close4.index, pd.Timedelta(hours=4))
    score = rank_score("momentum", close4, qv4, pos4, 40)
    live = pos4.where(sel4, 0.0) > 0.5
    neg = (fund < 0).fillna(False) & live

    ctl, _ = pe.simulate(pe.ranked(score, live), close4.index, close1)
    arm, ev = pe.simulate(priority_rank(score, live, neg), close4.index, close1)
    share = float(neg.sum().sum() / max(1, live.sum().sum()))
    changed = float((priority_rank(score, live, neg) != pe.ranked(score, live)).any(axis=1).loc[win["pre"][0]:].mean())

    draws = []
    for s in range(SEEDS):
        r = np.random.default_rng(300 + s)
        rnd = pd.DataFrame(r.random(live.shape) < share, index=live.index, columns=live.columns) & live
        d, _ = pe.simulate(priority_rank(score, live, rnd), close4.index, close1)
        draws.append(d)

    rng = np.random.default_rng(0)
    out = {"declaration": "config/positioning_edges.yaml#followup", "post_hoc": True,
           "negative_funding_share_of_candidates": round(share, 4),
           "share_of_bars_where_top3_changes": round(changed, 4), "events": ev, "windows": {}}
    for tag, (lo, hi) in win.items():
        c, a = pe.describe(ctl, lo, hi), pe.describe(arm, lo, hi)
        nd = [pe.describe(d, lo, hi) for d in draws]
        out["windows"][tag] = {
            "control": c, "arm": a, "vs_control": pe.paired(ctl, arm, lo, hi, rng),
            "nonsense_median_pct_mean": round(float(np.mean([x["median_pct"] for x in nd])), 3),
            "nonsense_median_pct_p90": round(float(np.quantile([x["median_pct"] for x in nd], 0.9)), 3),
            "nonsense_p_gt5_mean": round(float(np.mean([x["p_gt5"] for x in nd])), 4),
            "arm_beats_every_nonsense_seed": bool(a["median_pct"] > max(x["median_pct"] for x in nd))}
        w = out["windows"][tag]
        print(f"{tag:8s} ctl {c['median_pct']:+.2f}/{c['p_gt5']:.3f}/P20 {c['p_gt20']:.3f}/w {c['worst_pct']:+.1f}  "
              f"arm {a['median_pct']:+.2f}/{a['p_gt5']:.3f}/P20 {a['p_gt20']:.3f}/w {a['worst_pct']:+.1f}  "
              f"p={w['vs_control']['p_median']:.3f}  nonsense {w['nonsense_median_pct_mean']:+.2f} "
              f"(p90 {w['nonsense_median_pct_p90']:+.2f})", flush=True)
    c = {t: out["windows"][t] for t in win}
    ok3 = all(c[t]["arm"]["median_pct"] > c[t]["control"]["median_pct"]
              and c[t]["arm"]["p_gt5"] > c[t]["control"]["p_gt5"] for t in win)
    h = c["holdout"]
    gain = h["arm"]["median_pct"] - h["control"]["median_pct"]
    n_gain = h["nonsense_median_pct_mean"] - h["control"]["median_pct"]
    out["verdict"] = {"all_three_windows": ok3,
                      "worst_ok": h["arm"]["worst_pct"] >= h["control"]["worst_pct"] - 5.0,
                      "p_ok": h["vs_control"]["p_median"] < 0.10,
                      "nonsense_not_reproducing": gain > 0 and n_gain < 0.5 * gain}
    out["verdict"]["candidate"] = all(out["verdict"].values())
    print(json.dumps(out["verdict"]), "share", round(share, 4), "changed", round(changed, 4))
    (RESULTS / "squeeze_priority.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
