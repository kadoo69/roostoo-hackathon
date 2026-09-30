"""Live walk-forward scorecard: did picking the best recent variant pay on the bars that came after?

Reads the `walkforward` journal a live selector writes at every re-selection (each variant's return
from the previous pick to now) and compounds it. Nothing here is fitted or backtested.
DECISIONS.md#walkforward-live-declaration
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from bot.journal import Journal
from bot.settings import ROOT

FIXED = "30m|htf1|vol1.5"


def summary(book: str = "wf_live") -> dict:
    rows = Journal(book).read("walkforward")
    state = ROOT / "live" / book / "adaptive.json"
    cur = json.loads(state.read_text()) if state.exists() else {}
    top = sorted((cur.get("scores") or {}).items(), key=lambda kv: -kv[1])[:5]
    out = {"book": book, "periods": len(rows), "current_pick": cur.get("clock"), "picked_at": cur.get("at"),
           "top_trailing": [{"variant": k, "pct": v} for k, v in top]}
    if not rows:
        return out

    def comp(xs):
        return round(float(np.expm1(np.log1p(np.array(xs) / 100).sum()) * 100), 3)

    out.update({
        "since": rows[0]["from"], "to": rows[-1]["to"],
        "pick_cum_pct": comp([r["pick_fwd_pct"] for r in rows]),
        "mean_variant_cum_pct": comp([r["mean_fwd_pct"] for r in rows]),
        "hindsight_best_cum_pct": comp([r["best_fwd_pct"] for r in rows]),
        "fixed_competition_cum_pct": comp([r["fwd_pct"].get(FIXED, 0.0) for r in rows]),
        "pick_beat_mean_share": round(float(np.mean([r["pick_fwd_pct"] > r["mean_fwd_pct"] for r in rows])), 3),
        "pick_mean_rank": round(float(np.mean([r["pick_rank"] for r in rows])), 2),
        "n_variants": rows[-1]["n_variants"],
        "picks": {p: sum(1 for r in rows if r["pick"] == p) for p in sorted({r["pick"] for r in rows})},
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="wf_live")
    print(json.dumps(summary(ap.parse_args().book), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
