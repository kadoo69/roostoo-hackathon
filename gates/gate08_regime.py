from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from core import artifacts
from core.config import RESULTS, gate_config, prereg
from data import daily, flow, universe as ru
from signals import donchian

warnings.filterwarnings("ignore")
GATE = "g8_regime"
FEE = 0.0005
INTERVAL = "4h"
ENTRY, EXIT = 20, 10
POOL = 30
DIVISOR = 20


def regimes(btc_daily: pd.Series) -> pd.Series:
    ma = btc_daily.rolling(200).mean()
    r90 = btc_daily / btc_daily.shift(90) - 1.0
    out = pd.Series("range", index=btc_daily.index)
    out[(btc_daily > ma) & (r90 > 0.10)] = "bull"
    out[(btc_daily < ma) & (r90 < -0.10)] = "bear"
    out[ma.isna() | r90.isna()] = "warmup"
    return out


def book(close: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    pos = donchian.position(close, ENTRY, "lowchannel", EXIT)
    w = pos.where(members, 0.0) / float(DIVISOR)
    g = w.abs().sum(axis=1)
    return w.div(np.maximum(1.0, g), axis=0)


def net_returns(w: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    ret = close.pct_change(fill_method=None)
    gross = (w.shift(1) * ret).sum(axis=1, min_count=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    return (gross - (turn * FEE).shift(1).fillna(0.0)).fillna(0.0)


def to_daily(net: pd.Series) -> pd.Series:
    return ((1.0 + net.fillna(0.0)).resample("1D").prod() - 1.0).dropna()


def stats(dr: pd.Series) -> dict:
    dr = dr.dropna()
    if len(dr) < 30 or dr.std() == 0:
        return {"days": int(len(dr))}
    eq = (1.0 + dr).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    years = len(dr) / 365.0
    cagr = float(eq.iloc[-1]) ** (1 / years) - 1.0
    down = float(np.sqrt((dr.clip(upper=0.0) ** 2).mean()) * np.sqrt(365))
    return {"days": int(len(dr)), "total_return": round(float(eq.iloc[-1] - 1), 5),
            "cagr": round(cagr, 5),
            "sharpe": round(float(dr.mean() / dr.std() * np.sqrt(365)), 4),
            "sortino": round(float(dr.mean() * 365 / down), 4) if down > 0 else None,
            "max_drawdown": round(dd, 5),
            "p_positive_day": round(float((dr > 0).mean()), 4)}


def main() -> int:
    cfg = gate_config(GATE)
    p = flow.panel(INTERVAL)
    close = p["close"]
    pdl = daily.build()
    base = ru.membership(ru.load_panel("1h")).reindex(
        pdl["close"].index).fillna(False)
    members = ru.pit_top_n(pdl, base, top_n=POOL).reindex(
        close.index, method="ffill").fillna(False)

    w = book(close, members)
    dr = to_daily(net_returns(w, close))
    btc = pdl["close"]["BTCUSDT"].dropna()
    reg = regimes(btc).reindex(dr.index, method="ffill")
    hold = btc.pct_change().reindex(dr.index)

    out = {"regime_rule": "bull: BTC>200dma and 90d return>+10%; "
                          "bear: BTC<200dma and 90d return<-10%; else range",
           "universe": f"pit_top{POOL}_survivorship_free_no_venue_filter",
           "full_sample": stats(dr), "btc_hold_full": stats(hold.dropna()),
           "regimes": {}}
    for name in ("bull", "bear", "range"):
        sel = reg == name
        block = {"strategy": stats(dr[sel]), "btc_hold": stats(hold[sel].dropna())}
        block["share_of_days"] = round(float(sel.mean()), 4)
        out["regimes"][name] = block

    tested = {k: v for k, v in out["regimes"].items() if v["strategy"].get("cagr") is not None}
    positive = [k for k, v in tested.items() if v["strategy"]["cagr"] > 0]
    worst_dd = min((v["strategy"]["max_drawdown"] for v in tested.values()), default=0.0)
    passed = (len(positive) >= cfg["require_positive_in_n_regimes"]
              and abs(worst_dd) <= cfg["max_regime_drawdown"])
    out.update({"regimes_tested": sorted(tested), "regimes_positive": sorted(positive),
                "worst_regime_drawdown": round(worst_dd, 5),
                "threshold_max_regime_drawdown": cfg["max_regime_drawdown"],
                "threshold_require_positive_in": cfg["require_positive_in_n_regimes"]})
    artifacts.write(GATE, passed, out)
    (RESULTS / "g8_regime_detail.json").write_text(json.dumps(out, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
