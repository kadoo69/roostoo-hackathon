"""Long-only against the exact live short-term rules at 15m, 30m and 1h, with a shifted-switch
nonsense control; 1h reconciles against results/lowtf_confirmed_long_only.json.
DECISIONS.md#lowtf-long-only-clocks-declaration
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates import competition_wf as cw
from gates import let_winners_run as lwr
from gates.breakout_quality import fast_field
from gates.concentration import context
from archive.gates.lowtf_idle_sleeve import evaluate
from gates.lowtf_paper_bots import fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_long_only_clocks.yaml"
OUT = RESULTS / "lowtf_long_only_clocks.json"
LIVE = {"15m": "momentum_top3_15m", "30m": "momentum_top3_30m", "1h": "momentum_top3_1h"}


def hourly(net: pd.Series) -> pd.Series:
    return (1.0 + net).resample("1h").prod() - 1.0


def run_clock(iv: str, close4: pd.DataFrame, sel4: pd.DataFrame, tick_all: pd.Series) -> dict:
    cc = yaml.safe_load((ROOT / "config" / f"{LIVE[iv]}.yaml").read_text())["contenders"]
    close = fast_close(iv)
    cols = [c for c in close.columns if c in sel4.columns]
    close = close[cols]
    eligible = to_fast(sel4[cols].astype(float), close4.index, close.index).fillna(0.0) > 0.5
    qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
    entry_ok = contenders.entry_confirmation(close, qv, close4[cols], cc)
    switch = donchian.breadth_short_regime(close, int(cc["momentum_bars"]), float(cc["breadth_max"]), members=eligible)
    shifted = pd.Series(np.roll(switch.to_numpy(), len(switch) // 2), index=switch.index)
    off = pd.Series(False, index=close.index)
    tick = tick_all.reindex(cols).fillna(0.0)
    ec = lwr.FEE + float((tick / close.median()).median())
    out, turns = {}, {}
    for arm, sw in (("L_live", switch), ("LO_long_only", off), ("NC_shifted_switch", shifted)):
        w = contenders.targets(close, eligible, cc, short_on=sw, entry_ok=entry_ok)
        net, turn = lwr.simulate(close, w, tick, True)
        out[arm] = evaluate(hourly(net), ec)
        bar = close.index[1] - close.index[0]
        turns[arm] = round(float(turn.loc["2023-01-01":].mean() * (14 * pd.Timedelta(days=1) / bar)), 1)
        short_share = float((w < -1e-9).sum().sum() / max(1, (w.abs() > 1e-9).sum().sum()))
        out[arm]["short_share_of_position_bars"] = round(short_share, 3)
        print(f"  {iv} {arm:18s} " + " | ".join(
            f"{p}: med {out[arm][p]['median_pct']:+.2f} P2 {out[arm][p]['p_gt2']:.2f} worst {out[arm][p]['worst_pct']:+.1f}"
            f" Sh {out[arm][p].get('sharpe')}" for p in cw.PERIODS) + f" | turn/14d {turns[arm]}", flush=True)
    return {"arms": out, "turnover_per_14d": turns}


def verdict(r: dict) -> dict:
    L, LO, NC = (r["arms"][k] for k in ("L_live", "LO_long_only", "NC_shifted_switch"))
    per = {p: bool(LO[p]["median_pct"] > L[p]["median_pct"] and LO[p]["p_gt2"] > L[p]["p_gt2"]
                   and LO[p]["worst_pct"] >= L[p]["worst_pct"] - 5) for p in cw.PERIODS}
    gain = float(np.mean([LO[p]["median_pct"] - L[p]["median_pct"] for p in cw.PERIODS]))
    nc_gain = float(np.mean([NC[p]["median_pct"] - L[p]["median_pct"] for p in cw.PERIODS]))
    nonsense_ok = gain > 0 and nc_gain < 0.5 * gain
    return {"periods": per, "mean_median_gain": round(gain, 2), "nonsense_gain": round(nc_gain, 2),
            "nonsense_ok": bool(nonsense_ok), "adopt_forward_paper": bool(all(per.values()) and nonsense_ok)}


def main() -> int:
    if not yaml.safe_load(CONFIG.read_text())["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("undeclared experiment")
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    tick_all = pd.Series({s: specs[s].tick for s in close4.columns if s in specs})
    rows = {}
    for iv in ("1h", "30m", "15m"):
        rows[iv] = run_clock(iv, close4, sel4, tick_all)
        if iv == "1h":
            ref = json.loads((RESULTS / "lowtf_confirmed_long_only.json").read_text())["metrics"]
            gaps = {k: abs(rows[iv]["arms"][a]["2025-26"]["median_pct"] - ref[k]["2025-26"]["median_pct"])
                    for a, k in (("L_live", "confirmed_both_sides"), ("LO_long_only", "confirmed_long_only"))}
            rows[iv]["reconciliation_gap"] = gaps
            print("  1h reconciliation gap (2025-26 median):", gaps, flush=True)
            if max(gaps.values()) > 0.1:
                OUT.write_text(json.dumps({"reconciled": False, "rows": rows}, indent=1, default=str))
                print("RECONCILIATION FAILED, nothing else is read")
                return 1
        rows[iv]["verdict"] = verdict(rows[iv])
        print(f"  {iv} verdict:", rows[iv]["verdict"], flush=True)
    OUT.write_text(json.dumps({"reconciled": True, "rows": rows}, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
