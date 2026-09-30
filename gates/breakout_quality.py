"""Breakout quality: higher-timeframe alignment, volume confirmation, failed-breakout exit,
each against the live short-term rule and its own control. DECISIONS.md#breakout-quality-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.config import RESULTS
from data import universe as ru
from gates.concentration import context
from gates.let_winners_run import describe, simulate
from gates.lowtf_contenders import CFG as CONTENDERS
from gates.lowtf_paper_bots import W, fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast


def fast_field(interval: str, field: str, source: str) -> pd.DataFrame:
    if source == "flow_1h":
        d = pd.read_parquet(ru.CACHE / "flow_1h.parquet", columns=["symbol", "open_time", field])
    else:
        d = pd.read_parquet(ru.CACHE / f"panel_{'1h' if interval == '1h' else '15m'}.parquet",
                            columns=["symbol", "open_time", field])
    f = d.pivot(index="open_time", columns="symbol", values=field)
    f.index = pd.to_datetime(f.index, utc=True)
    if interval == "30m":
        f = f.resample("30min", label="left", closed="left").sum(min_count=1)
    return f.sort_index().loc["2022-10-01":]


def main() -> int:
    close4, qv4, sel4, pos4 = context(30)
    specs = ru.tradable_symbols()
    tick = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    skips = {r["interval"]: r["skip_frozen_on_fit"] for r in json.loads((RESULTS / "lowtf_exhaustion.json").read_text())["rows"]}
    rng = np.random.default_rng(7)
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
        flag = donchian.breadth_short_regime(close, 40, 0.40, members=sel)
        base = {**CONTENDERS, "sticky": True, "skip_long_z": skips[iv]["long"], "skip_short_z": skips[iv]["short"]}
        c4 = close4[cols]
        up4 = donchian.position(c4, 20, "lowchannel", 10) > 0.5
        dn4 = donchian.breakdown_position(c4, 20, 10)
        up = to_fast(up4.astype(float), c4.index, close.index).fillna(0.0) > 0.5
        dn = to_fast(dn4.astype(float), c4.index, close.index).fillna(0.0) > 0.5
        mom = close / close.shift(40) - 1.0
        is_long = mom > 0
        htf = (up & is_long) | (dn & ~is_long)
        perm = rng.permutation(len(cols))
        up_p = up.iloc[:, perm].set_axis(cols, axis=1)
        dn_p = dn.iloc[:, perm].set_axis(cols, axis=1)
        htf_ctrl = (up_p & is_long) | (dn_p & ~is_long)
        qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
        vol_ok = qv >= 1.5 * qv.rolling(20, min_periods=10).median().shift(1)
        rate = float(vol_ok.where(sel).stack().mean())
        vol_ctrl = pd.DataFrame(rng.random(close.shape) < rate, index=close.index, columns=cols)
        weights = {
            "L_live": contenders.targets(close, sel, base, short_on=flag),
            "B1_htf": contenders.targets(close, sel, base, short_on=flag, entry_ok=htf),
            "B1_ctrl": contenders.targets(close, sel, base, short_on=flag, entry_ok=htf_ctrl),
            "B2_vol": contenders.targets(close, sel, base, short_on=flag, entry_ok=vol_ok),
            "B2_ctrl": contenders.targets(close, sel, base, short_on=flag, entry_ok=vol_ctrl),
            "B3_failed": contenders.targets(close, sel, {**base, "failed_breakout_bars": 4}, short_on=flag),
            "B3_ctrl": contenders.targets(close, sel, {**base, "time_stop_bars": 4}, short_on=flag),
        }
        if iv == "1h":
            tb = fast_field(iv, "taker_buy_quote", "flow_1h").reindex_like(close)
            qf = fast_field(iv, "quote_volume", "flow_1h").reindex_like(close)
            share = tb / qf
            taker_ok = vol_ok & (((share > 0.5) & is_long) | ((share < 0.5) & ~is_long))
            weights["B2t_vol_taker"] = contenders.targets(close, sel, base, short_on=flag, entry_ok=taker_ok)
        res = {k: describe(*simulate(close, w, tick, True), close) for k, w in weights.items()}
        rows.append({"interval": iv, "arms": res, "vol_pass_rate": round(rate, 3)})
        print(f"\n== {iv} (volume pass rate {rate:.2f})")
        for k, r in res.items():
            print(f"  {k:14s} " + " | ".join(f"{t}: med {r[t]['median_pct']:+7.2f} P5 {r[t]['p_gt5']:.2f} worst {r[t]['worst_pct']:+6.1f} turn {r[t]['turnover_per_14d']}" for t in W), flush=True)
    verdict = {}
    for arm, ctrl in (("B1_htf", "B1_ctrl"), ("B2_vol", "B2_ctrl"), ("B3_failed", "B3_ctrl")):
        clocks = [r["interval"] for r in rows
                  if r["arms"][arm]["holdout"]["median_pct"] > r["arms"]["L_live"]["holdout"]["median_pct"]
                  and r["arms"][arm]["holdout"]["p_gt5"] > r["arms"]["L_live"]["holdout"]["p_gt5"]
                  and r["arms"][arm]["fit"]["median_pct"] > r["arms"]["L_live"]["fit"]["median_pct"]
                  and r["arms"][arm]["holdout"]["median_pct"] > r["arms"][ctrl]["holdout"]["median_pct"]]
        verdict[arm] = {"clocks_passing": clocks, "adopt": len(clocks) >= 2}
    r1 = rows[0]["arms"]
    verdict["B2t_vol_taker"] = {"1h_beats_live": bool(r1["B2t_vol_taker"]["holdout"]["median_pct"] > r1["L_live"]["holdout"]["median_pct"]
                                                      and r1["B2t_vol_taker"]["fit"]["median_pct"] > r1["L_live"]["fit"]["median_pct"])}
    print("\nverdict:", verdict)
    (RESULTS / "breakout_quality.json").write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
