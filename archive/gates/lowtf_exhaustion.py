"""Do stretched breakdowns keep falling? Probability table by stretch bucket, then the contenders
rule with a fit-chosen entry filter. DECISIONS.md#lowtf-exhaustion-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates.concentration import context
from gates.lowtf_breadth_shorts import score
from gates.lowtf_contenders import CFG
from gates.lowtf_paper_bots import W, fast_close
from signals import contenders, donchian

EDGES = [-np.inf, -3, -2.5, -2, -1.5, -1, 1, 1.5, 2, 2.5, 3, np.inf]
HORIZONS = (1, 4, 12)


def table(close: pd.DataFrame, cand: pd.DataFrame, z: pd.DataFrame, side: int, a: str, b: str) -> list[dict]:
    rows = []
    zz = z.loc[a:b]
    cc = cand.loc[a:b]
    fwd = {h: (close.shift(-h) / close - 1.0).loc[a:b] for h in HORIZONS}
    for lo, hi in zip(EDGES[:-1], EDGES[1:]):
        m = cc & (zz >= lo) & (zz < hi)
        n = int(m.sum().sum())
        if n < 50:
            continue
        row = {"lo": None if np.isinf(lo) else lo, "hi": None if np.isinf(hi) else hi, "n": n}
        for h in HORIZONS:
            v = fwd[h].where(m).stack()
            pnl = side * v
            row[f"p_win_{h}"] = round(float((pnl > 0).mean()), 3)
            row[f"bps_{h}"] = round(float(pnl.mean() * 1e4), 1)
        rows.append(row)
    return rows


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    fit, hold = W["fit"], W["holdout"]
    out = []
    for iv in ("1h", "30m", "15m"):
        close = fast_close(iv)
        cols = [c for c in close.columns if c in sel4.columns]
        close = close[cols]
        bar = close.index[1] - close.index[0]
        s4 = sel4[cols].copy()
        s4.index = s4.index + pd.Timedelta(hours=4)
        sel = s4.reindex(close.index + bar, method="ffill").fillna(False)
        sel.index = close.index
        mom = close / close.shift(40) - 1.0
        live = (donchian.position(close, 20, "lowchannel", 10) > 0.5) & sel
        brk = donchian.breakdown_position(close, 20, 10) & sel & ~live
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        on = pd.DataFrame(np.repeat(flag.to_numpy()[:, None], close.shape[1], axis=1), index=close.index, columns=close.columns)
        short_c = brk & (mom < 0) & on
        long_c = live & (mom > 0)
        z = contenders.stretch(close)
        res = {"interval": iv}
        for name, cand, side in (("short", short_c, -1), ("long", long_c, 1)):
            res[f"{name}_fit"] = table(close, cand, z, side, *fit)
            res[f"{name}_holdout"] = table(close, cand, z, side, *hold)
        skip = {name: [[r["lo"], r["hi"]] for r in res[f"{name}_fit"] if r["bps_4"] < 0] for name in ("short", "long")}
        res["skip_frozen_on_fit"] = skip
        base = score(contenders.targets(close, sel, CFG, short_on=flag), close, tick)
        filt = score(contenders.targets(close, sel, {**CFG, "skip_long_z": skip["long"], "skip_short_z": skip["short"]},
                                        short_on=flag), close, tick)
        res["contenders"] = base
        res["contenders_filtered"] = filt
        wins = (filt["holdout"]["median_pct"] > base["holdout"]["median_pct"]) and (filt["holdout"]["p_gt5"] > base["holdout"]["p_gt5"])
        res["holdout_improves_median_and_p5"] = bool(wins)
        out.append(res)
        print(f"\n== {iv}: skip short z {skip['short']} | skip long z {skip['long']}")
        for name in ("short", "long"):
            for per in ("fit", "holdout"):
                print(f"  {name:5s} {per:7s} " + " ".join(
                    f"[{r['lo']},{r['hi']}) n{r['n']} P4 {r['p_win_4']:.2f} {r['bps_4']:+.0f}bps P12 {r['p_win_12']:.2f} {r['bps_12']:+.0f}bps |"
                    for r in res[f"{name}_{per}"]))
        print(f"  contenders holdout median {base['holdout']['median_pct']:+.2f} P5 {base['holdout']['p_gt5']:.2f} -> filtered {filt['holdout']['median_pct']:+.2f} P5 {filt['holdout']['p_gt5']:.2f}"
              f" | fit {base['fit']['median_pct']:+.2f} -> {filt['fit']['median_pct']:+.2f} | improves: {wins}", flush=True)
    n_ok = sum(r["holdout_improves_median_and_p5"] for r in out)
    verdict = {"clocks_improved": n_ok, "adopt": n_ok >= 2}
    print("\nverdict:", verdict)
    (RESULTS / "lowtf_exhaustion.json").write_text(json.dumps({"rows": out, "verdict": verdict}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
