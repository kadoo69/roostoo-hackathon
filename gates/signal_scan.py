"""Live signal scan: on every clock, which pool coins are in a breakout, which pass the entry
confirmations, and what the contenders rule would hold now. Read-only; places nothing.
DECISIONS.md#signal-scan-2026-09-30
"""
from __future__ import annotations

import argparse
import json

import pandas as pd
import yaml

from bot import feed
from bot import universe as bu
from bot.scalper_adaptive_run import clock_weights, frames_to
from bot.settings import ROOT, load
from signals import donchian
from venue.roostoo import RoostooClient

CLOCKS = {"5m": "momentum_top3_5m", "15m": "momentum_top3_15m", "30m": "competition",
          "1h": "momentum_top3_1h_long", "4h": "momentum_top3_full"}


def scan(symbols: list[str]) -> dict:
    c4 = feed.close_matrix(feed.bar_frame(symbols, "4h", 120))
    out = {}
    for iv, name in CLOCKS.items():
        raw = yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())
        s = raw["strategy"]
        cc = raw.get("contenders") or {"n": 3, "momentum_bars": 40, "breadth_max": 0.4, "max_weight": 0.5,
                                       "sticky": False}
        fr = feed.bar_frame(symbols, iv, 200)
        close, qv = frames_to(fr, "close"), frames_to(fr, "quote_volume")
        e, x = int(s["entry_bars"]), int(s["exit_bars"])
        in_ch = (donchian.position(close, e, "lowchannel", x) > 0.5).iloc[-1]
        prior_hi = close.shift(1).rolling(e).max().iloc[-1]
        fresh = close.iloc[-1] > prior_hi
        mom = (close / close.shift(int(cc["momentum_bars"])) - 1.0).iloc[-1]
        volx = (qv / qv.rolling(20, min_periods=10).median().shift(1)).iloc[-1]
        up4 = (donchian.position(c4, 20, "lowchannel", 10) > 0.5).iloc[-1].reindex(close.columns).fillna(False)
        w = clock_weights(close, qv, c4, cc, e, x).iloc[-1]
        rows = []
        for sym in close.columns:
            if not in_ch.get(sym, False):
                continue
            reasons = []
            if mom.get(sym, 0) <= 0:
                reasons.append("momentum<=0")
            if cc.get("volume_confirm") and not volx.get(sym, 0) >= float(cc["volume_confirm"]):
                reasons.append(f"volume {volx.get(sym, 0):.2f}x<{cc['volume_confirm']}")
            if cc.get("htf_confirm") and not up4.get(sym, False):
                reasons.append("no 4h breakout")
            rows.append({"symbol": sym.replace("USDT", ""), "fresh_breakout": bool(fresh.get(sym, False)),
                         "mom_pct": round(float(mom.get(sym, 0)) * 100, 2), "vol_x": round(float(volx.get(sym, 0)), 2),
                         "rule_weight": round(float(w.get(sym, 0)), 3), "blocked_by": reasons})
        rows.sort(key=lambda r: -r["mom_pct"])
        out[iv] = {"bar": str(close.index[-1]), "in_breakout": len(rows),
                   "rule_holds": {k.replace("USDT", ""): round(float(v), 3) for k, v in w.items() if abs(v) > 1e-9},
                   "candidates": rows}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    specs = RoostooClient().exchange_info()
    pool = bu.select(load(ROOT / "config" / "competition.yaml"), specs)["selected"]
    res = scan(sorted(pool))
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    for iv, r in res.items():
        print(f"\n== {iv} (last closed bar {r['bar']}): {r['in_breakout']} of {len(pool)} pool coins in a breakout; rule holds {r['rule_holds'] or 'cash'}")
        for c in r["candidates"][:10]:
            flag = "NEW " if c["fresh_breakout"] else "    "
            why = ", ".join(c["blocked_by"]) or ("HELD" if c["rule_weight"] else "passes, slot/sticky")
            print(f"   {flag}{c['symbol']:8s} mom {c['mom_pct']:+6.2f}%  vol {c['vol_x']:5.2f}x  -> {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
