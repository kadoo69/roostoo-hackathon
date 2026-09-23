from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import daily, flow
from data import universe as ru
from gates.concentration import net_daily, stats
from gates.rotation_hysteresis import A, B, END
from signals import donchian
from signals.exit_clock import to_fast
from signals.reversal_reentry import position as rr


def declaration():
    with (ROOT / "config" / "reversal_reentry.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    slow = flow.panel(g["slow_interval"])["close"]
    fast = flow.panel(g["fast_interval"])["close"]
    fast = fast.reindex(columns=slow.columns)

    # The guard that caught two look-ahead bugs. Read nothing before it passes.
    probe = slow.iloc[-3000:, :30]
    ref = donchian.position(probe, g["entry_bars"], "lowchannel", g["exit_bars"])
    got = rr(probe, probe, g["entry_bars"], g["exit_bars"], 0.0, 0)
    if not np.allclose(ref.to_numpy(), got.to_numpy(), atol=1e-12):
        raise RuntimeError("fast_equals_slow_does_not_reproduce_donchian_position")

    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    trad = set(ru.tradable_symbols()) - ru.STABLES
    pool = ru.pit_top_n(pdl, base, top_n=30)

    def sel_on(idx):
        m = pd.DataFrame(False, index=idx, columns=slow.columns)
        for s in sorted(trad & set(slow.columns)):
            m[s] = True
        return pool.reindex(idx, method="ffill").fillna(False) & m

    sel_f = sel_on(fast.index)
    score_slow = slow / slow.shift(40) - 1.0
    score_f = to_fast(score_slow, slow.index, fast.index)

    def weights(pos_f, book):
        live = pos_f.where(sel_f, 0.0) > 0.5
        if book == "donchian_4h":
            w = live.astype(float) / 20.0
        else:
            n = int(book.split("top")[1])
            rank = score_f.where(live).rank(axis=1, ascending=False)
            w = ((rank <= n) & live).astype(float) / float(n)
        gr = w.abs().sum(axis=1)
        return w.div(np.maximum(1.0, gr), axis=0)

    def score(w, tag):
        dr = net_daily(w, fast)
        row = {"turnover": round(float((w - w.shift(1)).abs().sum().sum()), 1)}
        for t, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
            for k, v in stats(seg).items():
                row[f"{t}_{k}"] = v
        return row

    rows = []
    slow_pos = rr(slow, fast, g["entry_bars"], g["exit_bars"], 0.0, 0)
    for book in g["books"]:
        rows.append({"book": book, "arm": "baseline_slow_clock",
                     "reclaim_bps": None, "max_cycles": 0, **score(weights(slow_pos, book), book)})
        no_re = rr(slow, fast, g["entry_bars"], g["exit_bars"], 1e9, 99)
        rows.append({"book": book, "arm": "fast_exit_no_reentry",
                     "reclaim_bps": None, "max_cycles": 0, **score(weights(no_re, book), book)})
        for mb in g["reclaim_margin_bps"]:
            for mc in g["max_cycles_per_slow_bar"]:
                pos = rr(slow, fast, g["entry_bars"], g["exit_bars"], float(mb), int(mc))
                rows.append({"book": book, "arm": "reversal_reentry",
                             "reclaim_bps": mb, "max_cycles": mc,
                             **score(weights(pos, book), book)})
        base_t = next(r["turnover"] for r in rows
                      if r["book"] == book and r["arm"] == "baseline_slow_clock")
        for mb in (0, 25):
            best = max((r for r in rows if r["book"] == book
                        and r["arm"] == "reversal_reentry" and r["reclaim_bps"] == mb),
                       key=lambda r: r["turnover"])
            extra = max(0.0, best["turnover"] / base_t - 1.0)
            rate = min(0.5, extra / 200.0)
            pos = rr(slow, fast, g["entry_bars"], g["exit_bars"], float(mb), 99,
                     rng=np.random.default_rng(11), random_rate=rate)
            rows.append({"book": book, "arm": "random_control",
                         "reclaim_bps": mb, "max_cycles": 99,
                         "random_rate": round(rate, 5), **score(weights(pos, book), book)})

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "reversal_reentry.json").write_text(
        json.dumps({"declaration": "config/reversal_reentry.yaml", "results": rows},
                   indent=2, default=str))
    for r in rows:
        print(f"{r['book']:14s} {r['arm']:20s} rc={str(r['reclaim_bps']):>5s} mc={r['max_cycles']:<3} "
              f"turn={r['turnover']:9.1f} fit_s3={r.get('fit_screen3')} "
              f"hold_s3={r.get('hold_screen3')} hold_dd={r.get('hold_max_drawdown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
