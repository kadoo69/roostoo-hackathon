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
from portfolio.construct import apply_no_trade_band
from signals import donchian


def declaration():
    with (ROOT / "config" / "no_trade_band_live.yaml").open() as fh:
        c = yaml.safe_load(fh)
    if not c["meta"]["declared_before_any_backtest"]:
        raise RuntimeError("not_declared")
    return c


def main() -> int:
    cfg = declaration()
    g = cfg["grid"]
    p = flow.panel("4h")
    close = p["close"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(pdl["close"].index).fillna(False)
    trad = set(ru.tradable_symbols()) - ru.STABLES
    rmask = pd.DataFrame(False, index=close.index, columns=close.columns)
    for s in sorted(trad & set(close.columns)):
        rmask[s] = True
    sel = ru.pit_top_n(pdl, base, top_n=30).reindex(
        close.index, method="ffill").fillna(False) & rmask
    pos = donchian.position(close, 20, "lowchannel", 10)
    live = pos.where(sel, 0.0) > 0.5
    score = close / close.shift(40) - 1.0

    def book(kind):
        if kind == "donchian_4h":
            w = pos.where(sel, 0.0) / 20.0
        else:
            n = int(kind.split("top")[1])
            rank = score.where(live).rank(axis=1, ascending=False)
            w = ((rank <= n) & live).astype(float) / float(n)
        gr = w.abs().sum(axis=1)
        return w.div(np.maximum(1.0, gr), axis=0)

    rows = []
    for name in g["books"]:
        w0 = book(name)
        for band in g["bands"]:
            w = w0 if band == 0.0 else apply_no_trade_band(w0, band)
            dr = net_daily(w, close)
            row = {"book": name, "band": band,
                   "turnover": round(float((w - w.shift(1)).abs().sum().sum()), 1)}
            for tag, seg in (("fit", dr.loc[A:B]), ("hold", dr.loc[B:END])):
                for k, v in stats(seg).items():
                    row[f"{tag}_{k}"] = v
            rows.append(row)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "no_trade_band_live.json").write_text(
        json.dumps({"declaration": "config/no_trade_band_live.yaml", "results": rows},
                   indent=2, default=str))
    for r in rows:
        print(f"{r['book']:16s} band={r['band']:<5} turn={r['turnover']:9.1f} "
              f"fit_s3={r.get('fit_screen3')} hold_s3={r.get('hold_screen3')} "
              f"hold_sh={r.get('hold_sharpe')} hold_dd={r.get('hold_max_drawdown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
