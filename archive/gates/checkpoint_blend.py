"""Competition rule vs momentum ride vs a 50/50 blend on the live window. DECISIONS.md#blend-checkpoint-declaration

Simulated on Binance 5m bars for the competition universe from 2026-09-19 with the backtest simulator
(maker fee, ticks, profit ladder); the 30m rule reaches the 5m clock by bar close (`to_fast`).
Writes results/checkpoint_blend.json.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot.scalper_adaptive_run import clock_weights, frames_to
from bot.settings import ROOT
from gates.let_winners_run import simulate
from signals import burst_rider
from signals.exit_clock import to_fast
from venue.roostoo import RoostooClient

START = pd.Timestamp("2026-09-19", tz="UTC")
SPLIT = pd.Timestamp("2026-09-25 12:00", tz="UTC")
OUT = ROOT / "results" / "checkpoint_blend.json"


def stats(net: pd.Series, w: pd.DataFrame) -> dict:
    eq = (1 + net).cumprod()
    hourly = eq.resample("1h").last().pct_change().dropna()
    ann = np.sqrt(24 * 365)
    sharpe = hourly.mean() / hourly.std() * ann if hourly.std() > 0 else 0.0
    down = hourly[hourly < 0]
    sortino = hourly.mean() / np.sqrt((down ** 2).mean()) * ann if len(down) else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    years = (net.index[-1] - net.index[0]).total_seconds() / (365 * 86400)
    calmar = (eq.iloc[-1] ** (1 / years) - 1) / abs(dd) if dd < 0 and years > 0 else 0.0

    def part(m):
        s = net[m]
        return round(float((1 + s).prod() - 1) * 100, 2)

    return {"total_pct": round(float(eq.iloc[-1] - 1) * 100, 2), "trend_half_pct": part(net.index < SPLIT),
            "chop_half_pct": part(net.index >= SPLIT), "last_3d_pct": part(net.index >= net.index[-1] - pd.Timedelta(days=3)),
            "max_dd_pct": round(dd * 100, 2), "invested_pct": round(float((w.abs().sum(axis=1) > 0.05).mean() * 100), 1),
            "sharpe": round(float(sharpe), 2), "sortino": round(float(sortino), 2), "calmar": round(float(calmar), 2),
            "screen3": round(float(0.4 * sortino + 0.3 * sharpe + 0.3 * calmar), 2)}


def main() -> int:
    comp = yaml.safe_load((ROOT / "config" / "competition.yaml").read_text())
    ride = yaml.safe_load((ROOT / "config" / "ride_5m.yaml").read_text())["adaptive"]["burst_arms"]["ride|+5%|24h"]
    syms = json.loads((ROOT / "live" / "momentum_top3_30m" / "state.json").read_text())["universe"]
    days = (pd.Timestamp.now(tz="UTC") - START).days + 3
    f5 = feed.bar_frame(syms, "5m", days * 288)
    f30 = feed.bar_frame(syms, "30m", days * 48 + 100)
    f4 = feed.bar_frame(syms, "4h", days * 6 + 60)
    c5, h5 = frames_to(f5, "close"), frames_to(f5, "high")
    c30, q30 = frames_to(f30, "close"), frames_to(f30, "quote_volume")
    c4 = feed.close_matrix(f4)
    st = comp["strategy"]
    rule30 = clock_weights(c30, q30, c4, comp["contenders"], int(st["entry_bars"]), int(st["exit_bars"]))
    rule = to_fast(rule30, c30.index, c5.index).reindex(columns=c5.columns).fillna(0.0)
    rd = burst_rider.weights(c5, h5, ride).reindex(columns=c5.columns).fillna(0.0)
    tick = pd.Series({s.binance_symbol: s.tick for s in RoostooClient().exchange_info().values()})
    keep = c5.index >= START
    out = {"window": [str(c5.index[keep][0]), str(c5.index[-1])], "coins": len(syms)}
    for name, w in {"A_rule": rule, "B_ride": rd, "C_blend": 0.5 * rule + 0.5 * rd}.items():
        net, _ = simulate(c5.loc[keep], w.loc[keep], tick, True)
        out[name] = stats(net, w.loc[keep])
    a, b, c = out["A_rule"], out["B_ride"], out["C_blend"]
    out["recommend_C_over_A"] = bool(c["total_pct"] >= a["total_pct"] and c["chop_half_pct"] > a["chop_half_pct"]
                                     and c["max_dd_pct"] >= a["max_dd_pct"] - 2.0)
    out["recommend_B_over_C"] = bool(b["trend_half_pct"] > c["trend_half_pct"] and b["chop_half_pct"] > c["chop_half_pct"])
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
