"""Acceleration book on 1h, 30m and 15m against the live contenders rule and a sign-flipped
control, plus the pre-registered rank-IC diagnostic. DECISIONS.md#accel-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates.concentration import context
from gates.lowtf_breadth_shorts import score
from gates.lowtf_contenders import CFG as CONTENDERS
from gates.lowtf_paper_bots import W, fast_close
from signals import acceleration, contenders, donchian

GUARD = {"acc_entry_max": 2.0, "acc_exit": 1.5}
CFG = {"short_bars": 12, "mid_bars": 48, "breadth_max": 0.40, "n_enter": 3, "n_keep": 5, "max_weight": 0.50}


def rank_ic(sig: pd.DataFrame, fwd: pd.DataFrame, mask: pd.DataFrame, a: str, b: str) -> dict:
    s, f, m = sig.loc[a:b], fwd.loc[a:b], mask.loc[a:b]
    s = s.where(m)
    f = f.where(m & s.notna())
    ok = s.notna().sum(axis=1) >= 5
    ic = s[ok].rank(axis=1).corrwith(f[ok].rank(axis=1), axis=1).dropna()
    return {"mean": round(float(ic.mean()), 4), "t": round(float(ic.mean() / ic.std() * np.sqrt(len(ic))), 2), "n": int(len(ic))}


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    skips = {r["interval"]: r["skip_frozen_on_fit"] for r in json.loads((RESULTS / "lowtf_exhaustion.json").read_text())["rows"]}
    rows = []
    for iv in ("1h", "30m", "15m"):
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        bar = close.index[1] - close.index[0]
        s4 = sel4[cols].copy()
        s4.index = s4.index + pd.Timedelta(hours=4)
        sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
        sel.index = close.index
        f = acceleration.features(close, CFG)
        aligned = sel & (np.sign(f["m_m"]) == np.sign(f["m_s"]))
        diag = {}
        for h in (4, 12):
            fwd = close.shift(-h) / close - 1.0
            diag[f"{h}bar"] = {t: rank_ic(f["acc"], fwd, aligned, a, b) for t, (a, b) in W.items()}
        sk = skips[iv]
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        ctrl = contenders.targets(close, sel, {**CONTENDERS, "skip_long_z": sk["long"], "skip_short_z": sk["short"]}, short_on=flag)
        a1 = acceleration.targets(close, sel, CFG)
        a2 = acceleration.targets(close, sel, {**CFG, "skip_long_z": sk["long"], "skip_short_z": sk["short"]})
        nn = acceleration.targets(close, sel, CFG, flip=True)
        g = acceleration.guard_targets(close, sel, {**CONTENDERS, **GUARD, "short_bars": 12, "mid_bars": 48,
                                                    "skip_long_z": sk["long"], "skip_short_z": sk["short"]})
        res = {k: score(w, close, tick) for k, w in (("C_contenders_live", ctrl), ("A1", a1), ("A2", a2), ("N_flipped", nn), ("G_guard", g))}
        stats = {k: {"names": round(float((w.abs() > 0).sum(axis=1).loc["2023":].mean()), 2),
                     "short_share": round(float((w < 0).any(axis=1).loc["2023":].mean()), 3),
                     "gross": round(float(w.abs().sum(axis=1).loc["2023":].mean()), 2)}
                 for k, w in (("A1", a1), ("A2", a2), ("G_guard", g))}
        rows.append({"interval": iv, "ic": diag, "arms": res, "stats": stats})
        print(f"\n== {iv}  IC(acc -> fwd, trend-aligned): " + " | ".join(
            f"{h} {t} {v['mean']:+.4f} (t {v['t']:+.1f})" for h, d in diag.items() for t, v in d.items()), flush=True)
        for k, r in res.items():
            print(f"  {k:18s} " + " | ".join(f"{t}: med {r[t]['median_pct']:+7.2f} P5 {r[t]['p_gt5']:.2f} worst {r[t]['worst_pct']:+6.1f} drag {r[t]['cost_drag_per_14d_pct']}%" for t in W), flush=True)
        print("  ", stats, flush=True)
    verdict = {}
    for arm in ("A1", "A2", "G_guard"):
        ok = []
        for r in rows:
            a, c, n = r["arms"][arm], r["arms"]["C_contenders_live"], r["arms"]["N_flipped"]
            beats = (a["holdout"]["median_pct"] > c["holdout"]["median_pct"] and a["holdout"]["p_gt5"] > c["holdout"]["p_gt5"]
                     and a["fit"]["median_pct"] > c["fit"]["median_pct"]
                     and a["holdout"]["median_pct"] > n["holdout"]["median_pct"])
            ok.append(r["interval"] if beats else None)
        clocks = [x for x in ok if x]
        verdict[arm] = {"clocks_passing": clocks, "candidate": len(clocks) >= 2}
    print("\nverdict:", verdict)
    (RESULTS / "accel.json").write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
