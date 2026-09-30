"""Clock-agreement ensemble of the live short-term rules: the mean of the 15m, 30m and 1h
long-only targets, simulated on 15m bars, against each component and a shifted control.
DECISIONS.md#lowtf-clock-ensemble-declaration
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
from gates.lowtf_idle_sleeve import evaluate
from gates.lowtf_paper_bots import fast_close
from signals import contenders, donchian
from signals.exit_clock import to_fast

CONFIG = ROOT / "config" / "lowtf_clock_ensemble.yaml"
OUT = RESULTS / "lowtf_clock_ensemble.json"
COMPONENTS = {"C15": ("15m", "momentum_top3_15m", True), "C30": ("30m", "momentum_top3_30m", True),
              "C1h_LO": ("1h", "momentum_top3_1h", False)}


def hourly(net: pd.Series) -> pd.Series:
    return (1.0 + net).resample("1h").prod() - 1.0


def component(iv: str, book: str, shorts: bool, close4: pd.DataFrame, sel4: pd.DataFrame,
              cols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    cc = yaml.safe_load((ROOT / "config" / f"{book}.yaml").read_text())["contenders"]
    close = fast_close(iv)[cols]
    eligible = to_fast(sel4[cols].astype(float), close4.index, close.index).fillna(0.0) > 0.5
    qv = fast_field(iv, "quote_volume", "panel").reindex_like(close)
    ok = contenders.entry_confirmation(close, qv, close4[cols], cc)
    sw = (donchian.breadth_short_regime(close, int(cc["momentum_bars"]), float(cc["breadth_max"]), members=eligible)
          if shorts else pd.Series(False, index=close.index))
    return close, contenders.targets(close, eligible, cc, short_on=sw, entry_ok=ok)


def main() -> int:
    if not yaml.safe_load(CONFIG.read_text())["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("undeclared experiment")
    close4, _, sel4, _ = context(30)
    specs = ru.tradable_symbols()
    base = fast_close("15m")
    cols = [c for c in base.columns if c in sel4.columns and c in fast_close("1h").columns
            and c in fast_close("30m").columns]
    tick = pd.Series({s: specs[s].tick for s in cols if s in specs}).reindex(cols).fillna(0.0)
    close15 = base[cols]
    ec = lwr.FEE + float((tick / close15.median()).median())
    reports, turns, on15 = {}, {}, {}
    for name, (iv, book, shorts) in COMPONENTS.items():
        close, w = component(iv, book, shorts, close4, sel4, cols)
        net, turn = lwr.simulate(close, w, tick, True)
        reports[name] = evaluate(hourly(net), ec)
        bar = close.index[1] - close.index[0]
        turns[name] = round(float(turn.loc["2023-01-01":].mean() * (14 * pd.Timedelta(days=1) / bar)), 1)
        on15[name] = w if iv == "15m" else to_fast(w, close.index, close15.index).fillna(0.0)
    per14 = 14 * pd.Timedelta(days=1) / (close15.index[1] - close15.index[0])
    shift = int(pd.Timedelta(days=7) / (close15.index[1] - close15.index[0]))
    arms = {"E_mean": (on15["C15"] + on15["C30"] + on15["C1h_LO"]) / 3.0,
            "NC_shifted": (on15["C15"] + on15["C30"].shift(shift).fillna(0.0)
                           + on15["C1h_LO"].shift(shift).fillna(0.0)) / 3.0}
    for name, w in arms.items():
        net, turn = lwr.simulate(close15, w.reindex_like(close15).fillna(0.0), tick, True)
        reports[name] = evaluate(hourly(net), ec)
        turns[name] = round(float(turn.loc["2023-01-01":].mean() * per14), 1)
    for name, r in reports.items():
        print(f"  {name:10s} " + " | ".join(
            f"{p}: med {r[p]['median_pct']:+.2f} P2 {r[p]['p_gt2']:.2f} P15 {r[p]['p_gt15']:.2f} worst {r[p]['worst_pct']:+.1f}"
            f" Sh {r[p].get('sharpe')} DD {r[p].get('max_drawdown_pct')}" for p in cw.PERIODS)
            + f" | turn/14d {turns[name]}", flush=True)
    E, NC = reports["E_mean"], reports["NC_shifted"]
    singles = [reports[k] for k in COMPONENTS]
    checks = {}
    for p in ("2023-24", "2025-26"):
        checks[p] = bool(all(E[p]["median_pct"] > s[p]["median_pct"] and E[p]["p_gt2"] > s[p]["p_gt2"] for s in singles))
    checks["2022"] = bool(E["2022"]["median_pct"] >= max(s["2022"]["median_pct"] for s in singles) - 1.0)
    checks["worst"] = bool(all(E[p]["worst_pct"] >= max(s[p]["worst_pct"] for s in singles) - 5 for p in cw.PERIODS))
    avg = {p: float(np.mean([s[p]["median_pct"] for s in singles])) for p in cw.PERIODS}
    gain = float(np.mean([E[p]["median_pct"] - avg[p] for p in cw.PERIODS]))
    nc_gain = float(np.mean([NC[p]["median_pct"] - avg[p] for p in cw.PERIODS]))
    checks["nonsense"] = bool(gain > 0 and gain > 2 * nc_gain)
    verdict = {"checks": checks, "gain_over_component_mean": round(gain, 2), "nonsense_gain": round(nc_gain, 2),
               "adopt_forward_paper": bool(all(checks.values()))}
    print("verdict", verdict, flush=True)
    OUT.write_text(json.dumps({"reports": reports, "turnover_per_14d": turns, "verdict": verdict},
                              indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
