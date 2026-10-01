"""Classic technical rules (SMA and EMA trend, Donchian breakout, Bollinger and RSI mean reversion,
VWAP trend and reversion) on 15m, 30m and 1h, on live Binance bars since 2026-09-19, split by the
market regime of `signals.regime_ls` (UP, NEUTRAL, DOWN) known before each bar's return, with maker fees and ticks; then the same
rules on the 2025-26 holdout of the cached 30m panel. Long-only, each signalled coin at most 1/3 of
the book. Descriptive survey: adopting any rule needs its own declaration.
DECISIONS.md#technicals-survey-2026-10-01

`python3 -m gates.technicals_survey`
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from core.config import RESULTS, ROOT
from data import universe as ru
from gates import let_winners_run as lwr
from gates import stress
from gates.adaptive_recent import frames
from gates.missed_replay import universe
from signals import donchian, regime_ls

SINCE = pd.Timestamp("2026-09-19T00:00Z")
CLOCKS = ("15m", "30m", "1h")


def hold(entry: pd.DataFrame, exit_: pd.DataFrame) -> pd.DataFrame:
    """1 from an entry row until the first exit row after it."""
    s = pd.DataFrame(np.nan, index=entry.index, columns=entry.columns)
    s = s.mask(exit_, 0.0).mask(entry, 1.0)
    return s.ffill().fillna(0.0)


def rules(c: pd.DataFrame, qv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sma20, sma50 = c.rolling(20).mean(), c.rolling(50).mean()
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    sd = c.rolling(20).std()
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    vwap = (c * qv).rolling(48).sum() / qv.rolling(48).sum()
    return {
        "sma_20_50_trend": ((c > sma20) & (sma20 > sma50)).astype(float),
        "ema_12_26_cross": (ema12 > ema26).astype(float),
        "donchian_20_10": (donchian.position(c, 20, "lowchannel", 10) > 0.5).astype(float),
        "bollinger_revert": hold(c < sma20 - 2 * sd, c >= sma20),
        "rsi_30_50_revert": hold(rsi < 30, rsi > 50),
        "vwap48_trend": (c > vwap).astype(float),
        "vwap48_revert": hold(c < vwap * 0.99, c >= vwap),
        "buy_and_hold": pd.DataFrame(1.0, index=c.index, columns=c.columns),
    }


def to_weights(sig: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    s = sig.where(members, 0.0).fillna(0.0)
    n = s.sum(axis=1)
    return s.div(np.maximum(n, 3.0), axis=0).fillna(0.0)


def run(c: pd.DataFrame, w: pd.DataFrame, tick: pd.Series) -> pd.Series:
    net, _ = lwr.simulate(c, w, tick, False)
    return net


def pct(x: pd.Series) -> float:
    return round(float(np.expm1(np.log1p(x).sum()) * 100), 2)


def main() -> int:
    rcfg = yaml.safe_load((ROOT / "config" / "regime_ls_30m.yaml").read_text())["regime"]
    syms = universe("momentum_top3_30m")
    specs = ru.tradable_symbols()
    warm = SINCE - pd.Timedelta(days=4)
    data = {iv: frames(syms, iv, warm) for iv in CLOCKS}
    c30 = data["30m"]["close"]
    reg30 = regime_ls.state(c30, rcfg)
    reg30.index = reg30.index + pd.Timedelta("30min")
    out = {"recent": {}, "regime_share": {}, "holdout_30m": {}}
    for iv in CLOCKS:
        c, qv = data[iv]["close"], data[iv]["qv"]
        step = pd.Timedelta(iv.replace("m", "min"))
        tick = pd.Series({s: specs[s].tick for s in c.columns if s in specs})
        members = pd.DataFrame(True, index=c.index, columns=c.columns)
        reg = reg30.reindex(c.index, method="ffill").fillna("NEUTRAL")
        live = (c.index + step) >= SINCE
        out["regime_share"][iv] = reg[live].value_counts(normalize=True).round(3).to_dict()
        for name, sig in rules(c, qv).items():
            net = run(c, to_weights(sig, members), tick)[live]
            rg = reg[live]
            out["recent"].setdefault(name, {})[iv] = {"total": pct(net), **{k: pct(net[rg == k]) for k in ("UP", "NEUTRAL", "DOWN")},
                                                      "invested": round(float((to_weights(sig, members)[live].sum(axis=1) > 0).mean()), 2)}
    b = stress.load("competition")
    members = b.sel.reindex_like(b.close).fillna(False)
    for name, sig in rules(b.close, b.qv).items():
        net, turn = lwr.simulate(b.close, to_weights(sig, members), b.tick, False)
        d = stress.describe(net, turn)
        out["holdout_30m"][name] = {t: {k: d[t].get(k) for k in ("median_pct", "worst_pct", "turnover_per_14d")} for t in ("holdout", "recent")}
    (RESULTS / "technicals_survey.json").write_text(json.dumps(out, indent=1))
    print("regime share of bars since 2026-09-19:", out["regime_share"]["30m"])
    for name, by in out["recent"].items():
        h = out["holdout_30m"][name]
        print(f"{name:18s} " + " | ".join(f"{iv}: {v['total']:+6.1f} (UP {v['UP']:+5.1f} NEU {v['NEUTRAL']:+5.1f} DN {v['DOWN']:+5.1f})" for iv, v in by.items())
              + f" || 30m history: 2025-26 median 14d {h['holdout']['median_pct']:+.2f} worst {h['holdout']['worst_pct']:+.1f}, Jun-Sep {h['recent']['median_pct']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
