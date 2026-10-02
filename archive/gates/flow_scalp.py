"""Price-versus-order-flow divergence sweep, declared at config/flow_scalp.yaml.

Judged on a pre-registered per-trade floor of 20 bps, not on Sharpe. The
previous sweep established that net Sharpe at this horizon ranks configurations
by turnover rather than by edge.
"""
from __future__ import annotations

import itertools
import json
import warnings

import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from archive.gates.scalp_meanrev import stats, to_daily
from archive.signals import meanrev, orderflow

warnings.filterwarnings("ignore")
FLOOR_BPS = 20.0


def declaration() -> dict:
    with (ROOT / "config" / "flow_scalp.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def run_one(panels, feats, spec, win, g, fees):
    per, index = {}, None
    for sym, d in panels.items():
        w = d.loc[win[0]:win[1]]
        if len(w) < g["lookback_bars"] * 3:
            continue
        f = feats[sym].loc[win[0]:win[1]]
        m = orderflow.entry_mask(w, f, spec["arm"], spec["k"],
                                 spec["ret_thresh"], spec["ofi_thresh"],
                                 spec["vol_min"])
        p = meanrev.Params(entry_z=0.0, tp_atr=g["tp_atr"], sl_atr=g["sl_atr"],
                           lookback_bars=g["lookback_bars"],
                           atr_bars=g["atr_bars"],
                           max_hold_bars=g["max_hold_bars"])
        per[sym] = meanrev.trades(w, p, entries=m)
        index = w.index if index is None else index.union(w.index)
    if index is None:
        return {"trades": 0}
    nz = [t for t in per.values() if not t.empty]
    if not nz:
        return {"trades": 0}
    allt = pd.concat(nz)
    days = max((index[-1] - index[0]).days, 1)
    out = {"trades": int(len(allt)),
           "trades_per_day": round(len(allt) / days, 3),
           "win_rate": round(float((allt.gross_ret > 0).mean()), 4),
           "mean_gross_bps": round(float(allt.gross_ret.mean() * 1e4), 3),
           "median_gross_bps": round(float(allt.gross_ret.median() * 1e4), 3),
           "mean_bars_held": round(float(allt.bars_held.mean()), 2),
           "pct_target": round(float((allt.reason == "target").mean()), 4),
           "pct_stop": round(float((allt.reason == "stop").mean()), 4)}
    for fee in fees:
        net, gross, _ = meanrev.book_returns(per, index, g["weight_per_position"],
                                             g["max_concurrent"], fee)
        sn, sg = stats(to_daily(net)), stats(to_daily(gross))
        out[f"fee{int(fee)}"] = {**{f"net_{k}": v for k, v in sn.items()},
                                 "gross_sharpe": sg.get("sharpe")}
    return out


def main() -> int:
    cfg = declaration()
    g, m = cfg["grid"], cfg["method"]
    g = {**g, **{k: cfg["exits"][k] for k in ("tp_atr", "sl_atr", "max_hold_bars")}}
    fees = [float(f) for f in m["fee_bps"]]
    results = []
    for interval in g["interval"]:
        panels = {s: orderflow.bars(f"data/cache/5m/{s}.parquet", interval)
                  for s in cfg["universe"]["symbols"]}
        feats = {s: orderflow.features(d, g["lookback_bars"])
                 for s, d in panels.items()}
        for arm, rt, ot, vm in itertools.product(
                g["arm"], g["ret_thresh"], g["ofi_thresh"], g["vol_min"]):
            spec = {"arm": arm, "k": 3, "ret_thresh": rt,
                    "ofi_thresh": ot, "vol_min": vm}
            row = {"interval": interval, **spec}
            for tag, win in (("fit", m["fit_window"]), ("hold", m["holdout_window"])):
                row[tag] = run_one(panels, feats, spec, tuple(win), g, fees)
            h, f = row["hold"], row["fit"]
            he = h.get("mean_gross_bps")
            row["clears_floor"] = bool(
                he is not None and he > FLOOR_BPS
                and (f.get("mean_gross_bps") or -99) > FLOOR_BPS)
            results.append(row)
            print(f"{interval:>4s} {arm:12s} ret>{rt:.3f} ofi_z>{ot} vol_z>{vm} | "
                  f"hold n={h.get('trades',0):6d} edge={he if he is not None else float('nan'):8.2f}bps "
                  f"win={100*(h.get('win_rate') or 0):5.1f}% "
                  f"fit={f.get('mean_gross_bps', float('nan')):8.2f}bps "
                  f"{'CLEARS 20bps' if row['clears_floor'] else ''}", flush=True)
    out = {"declaration": "config/flow_scalp.yaml", "floor_bps": FLOOR_BPS,
           "universe": cfg["universe"]["symbols"], "configs": len(results),
           "clears": sum(r["clears_floor"] for r in results), "results": results}
    (RESULTS / "flow_scalp.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {RESULTS/'flow_scalp.json'}  clearing the 20bps floor: {out['clears']}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
