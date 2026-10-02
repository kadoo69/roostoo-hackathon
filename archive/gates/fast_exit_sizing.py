from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import daily, flow
from data import universe as ru
from gates.concentration import net_daily, stats
from archive.gates.rotation_hysteresis import A, B, END
from signals import donchian
from archive.signals.reversal_reentry import position as rr

WINDOW = 14
SCREEN2 = 0.05


def declaration():
    with (ROOT / "config" / "fast_exit_sizing.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def window_stats(dr: pd.Series) -> dict:
    d = dr.dropna().to_numpy()
    k = len(d) - WINDOW + 1
    if k < 1:
        return {}
    m = np.stack([d[i:i + WINDOW] for i in range(k)])
    r14 = np.cumprod(1.0 + m, axis=1)[:, -1] - 1.0
    return {"p_clears_screen2": round(float((r14 > SCREEN2).mean()), 4),
            "p_return_positive": round(float((r14 > 0).mean()), 4),
            "median_return_14d_pct": round(float(np.median(r14)) * 100, 3)}


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    slow = flow.panel(g["slow_interval"])["close"]
    fast = flow.panel(g["fast_interval"])["close"].reindex(columns=slow.columns)

    probe = slow.iloc[-3000:, :30]
    if not np.allclose(
            donchian.position(probe, g["entry_bars"], "lowchannel", g["exit_bars"]).to_numpy(),
            rr(probe, probe, g["entry_bars"], g["exit_bars"], 0.0, 0).to_numpy(), atol=1e-12):
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
    pos_slow = rr(slow, fast, g["entry_bars"], g["exit_bars"], 0.0, 0)
    pos_fast = rr(slow, fast, g["entry_bars"], g["exit_bars"], 1e9, 99)

    rows = []
    for div in g["weight_divisors"]:
        for exit_name, pos in (("slow_4h", pos_slow), ("fast_1h", pos_fast)):
            live = pos.where(sel_f, 0.0) > 0.5
            w = live.astype(float) / float(div)
            gr = w.abs().sum(axis=1)
            # Cap on GROSS, never on a scalar. CLAUDE.md records a 1.45x breach.
            w = w.div(np.maximum(g["max_gross"], gr / g["max_gross"]), axis=0)
            dr = net_daily(w, fast)
            row = {"divisor": div, "exit": exit_name,
                   "mean_gross": round(float(w.abs().sum(axis=1).mean()), 4),
                   "max_gross_seen": round(float(w.abs().sum(axis=1).max()), 4),
                   "turnover": round(float((w - w.shift(1)).abs().sum().sum()), 1)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
                for k, v in window_stats(seg).items():
                    row[f"{tag}_{k}"] = v
            rows.append(row)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "fast_exit_sizing.json").write_text(
        json.dumps({"declaration": "config/fast_exit_sizing.yaml", "results": rows},
                   indent=2, default=str))
    print(f"{'div':>4s} {'exit':9s} {'gross':>6s} {'maxg':>5s} {'fitS3':>7s} {'holdS3':>7s} "
          f"{'holdSh':>7s} {'holdDD':>8s} {'hP(S2)':>7s} {'holdCAGR':>9s}")
    for r in rows:
        print(f"{r['divisor']:4d} {r['exit']:9s} {r['mean_gross']:6.3f} {r['max_gross_seen']:5.2f} "
              f"{r.get('fit_screen3',0):7.4f} {r.get('hold_screen3',0):7.4f} "
              f"{r.get('hold_sharpe',0):7.4f} {r.get('hold_max_drawdown',0):8.2%} "
              f"{r.get('hold_p_clears_screen2',0):7.4f} {r.get('hold_cagr',0):9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
