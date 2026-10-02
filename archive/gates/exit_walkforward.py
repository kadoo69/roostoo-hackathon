"""Would RE-SELECTING exit_bars have beaten leaving it alone?

DECISIONS.md#ratchet-outcome found the holdout prefers exit_bars=3 while the
fit window prefers 10, so adopting 3 would be selecting on the test set. This
asks the honest version: run a process that re-picks the lookback on an
expanding window using only past data, trade the next block with that pick, and
compare the stitched result against every fixed setting.

The process never sees the future. If it still loses to leaving the parameter
alone, the parameter should be left alone.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from core.config import RESULTS
from gates.concentration import context, net_daily, rank_score, stats
from signals import donchian

warnings.filterwarnings("ignore")
POOL = 30
MOM_BARS = 40
CHOICES = [3, 5, 7, 10, 15]
BLOCK_DAYS = 90
MIN_TRAIN_DAYS = 365


def book(pos, close, qv, sel, kind):
    live = pos.where(sel, 0.0) > 0.5
    if kind == "donchian_4h":
        w = live.astype(float) / 20.0
    else:
        sc = rank_score("momentum", close, qv, pos, MOM_BARS).where(live)
        w = ((sc.rank(axis=1, ascending=False) <= 5) & live).astype(float) / 5.0
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def main() -> int:
    close, qv, sel, _ = context(POOL)
    out = {"choices": CHOICES, "block_days": BLOCK_DAYS,
           "min_train_days": MIN_TRAIN_DAYS, "books": {}}

    for kind in ("donchian_4h", "momentum_top5_4h"):
        # daily net return series for every fixed choice, computed once
        daily = {}
        for eb in CHOICES:
            pos = donchian.position(close, 20, "lowchannel", eb)
            daily[eb] = net_daily(book(pos, close, qv, sel, kind), close)
        idx = daily[CHOICES[0]].index
        start = idx[0] + pd.Timedelta(days=MIN_TRAIN_DAYS)
        edges = pd.date_range(start, idx[-1], freq=f"{BLOCK_DAYS}D")

        picks, stitched = [], []
        for i, e in enumerate(edges):
            nxt = edges[i + 1] if i + 1 < len(edges) else idx[-1] + pd.Timedelta(days=1)
            train = {eb: s.loc[:e - pd.Timedelta(days=1)] for eb, s in daily.items()}
            scored = {eb: (stats(s) or {}).get("screen3") for eb, s in train.items()}
            scored = {k: v for k, v in scored.items() if v is not None}
            if not scored:
                continue
            pick = max(scored, key=scored.get)          # argmax on PAST data only
            seg = daily[pick].loc[e:nxt - pd.Timedelta(days=1)]
            if len(seg):
                stitched.append(seg)
                picks.append({"from": str(e.date()), "pick": int(pick),
                              "train_days": int(len(train[pick])),
                              "block_return_pct": round(float((1 + seg).prod() - 1) * 100, 3)})
        if not stitched:
            continue
        wf = pd.concat(stitched).sort_index()
        span = (wf.index[0], wf.index[-1])
        res = {"walkforward": stats(wf), "picks": picks,
               "n_blocks": len(picks),
               "pick_counts": {str(c): sum(1 for p in picks if p["pick"] == c) for c in CHOICES},
               "span": [str(span[0].date()), str(span[1].date())],
               "fixed": {str(eb): stats(daily[eb].loc[span[0]:span[1]]) for eb in CHOICES}}
        out["books"][kind] = res
        w = res["walkforward"]
        print(f"=== {kind}   {res['span'][0]} -> {res['span'][1]}   blocks={res['n_blocks']}")
        print(f"    picks made: {res['pick_counts']}")
        print(f"    {'WALK-FORWARD':14s} S3={w['screen3']:+7.3f} Sharpe={w['sharpe']:+6.2f} maxDD={w['max_drawdown']*100:+6.1f}%")
        for eb in CHOICES:
            f = res["fixed"][str(eb)]
            tag = "  <- LIVE" if eb == 10 else ""
            print(f"    {'fixed ' + str(eb):14s} S3={f['screen3']:+7.3f} Sharpe={f['sharpe']:+6.2f} "
                  f"maxDD={f['max_drawdown']*100:+6.1f}%{tag}")
        print(flush=True)
    (RESULTS / "exit_walkforward.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"wrote {RESULTS/'exit_walkforward.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
