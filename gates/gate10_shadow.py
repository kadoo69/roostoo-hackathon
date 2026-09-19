from __future__ import annotations

import argparse
import datetime as dt
import json
import warnings

import numpy as np
import pandas as pd

from bot import feed, universe as bu, verify
from bot.journal import Journal
from bot.settings import load
from core import artifacts
from core.config import RESULTS, gate_config
from venue.roostoo import RoostooClient

warnings.filterwarnings("ignore")
GATE = "g10_shadow"


def journal_frames(name: str) -> dict[str, list[dict]]:
    j = Journal(name)
    return {s: j.read(s) for s in
            ("cycles", "orders", "signals", "errors", "reconcile", "lifecycle")}


def uptime(cycles: list[dict]) -> dict:
    if not cycles:
        return {"cycles": 0, "days": 0.0}
    ts = pd.to_datetime([c["ts_utc"] for c in cycles], utc=True).sort_values()
    span = (ts[-1] - ts[0]).total_seconds()
    gaps = np.diff(ts.astype("int64") // 10**9) if len(ts) > 1 else np.array([0])
    return {"cycles": len(cycles), "first": str(ts[0]), "last": str(ts[-1]),
            "days": round(span / 86400.0, 3),
            "distinct_utc_days": int(len({t.date() for t in ts})),
            "median_gap_s": float(np.median(gaps)) if len(gaps) else 0.0,
            "max_gap_s": float(gaps.max()) if len(gaps) else 0.0}


def mirror_stats(cycles: list[dict]) -> dict:
    v = [c["mirror_worst_bps"] for c in cycles
         if c.get("mirror_worst_bps") is not None]
    if not v:
        return {"samples": 0}
    a = np.abs(np.array(v, dtype=float))
    return {"samples": len(a), "median_bps": round(float(np.median(a)), 3),
            "p95_bps": round(float(np.quantile(a, 0.95)), 3),
            "max_bps": round(float(a.max()), 3)}


def live_signal_parity(bot_name: str) -> dict:
    s = load(f"config/{bot_name.replace('bot_', 'bot_')}.yaml"
             if bot_name.endswith((".yaml",)) else
             ("config/bot_a_4h.yaml" if bot_name == "bot_a_4h"
              else "config/bot_b_1h.yaml"))
    client = RoostooClient()
    specs = client.exchange_info()
    sel = bu.select(s, specs)["selected"]
    frames = feed.bar_frame(sel, s.interval, 200)
    m = feed.close_matrix(frames)
    return verify.signal_parity(m, s)


def journalled_signal_agreement(signals: list[dict], bot_name: str) -> dict:
    if not signals:
        return {"bars": 0}
    s = load("config/bot_a_4h.yaml" if bot_name == "bot_a_4h"
             else "config/bot_b_1h.yaml")
    client = RoostooClient()
    specs = client.exchange_info()
    sel = bu.select(s, specs)["selected"]
    frames = feed.bar_frame(sel, s.interval, 400)
    m = feed.close_matrix(frames)
    from signals import donchian
    ref = donchian.position(m, s.entry_bars, "lowchannel", s.exit_bars)
    agree = total = 0
    for rec in signals:
        bar = pd.Timestamp(rec["bar"])
        if bar not in ref.index:
            continue
        for sym, ch in rec["channels"].items():
            if sym not in ref.columns:
                continue
            total += 1
            agree += int(bool(ch["held"]) == bool(ref.at[bar, sym] > 0.5))
    return {"bars": len(signals), "cells": total,
            "agreement": round(agree / total, 6) if total else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="bot_a_4h")
    a = ap.parse_args()
    cfg = gate_config(GATE)
    j = journal_frames(a.bot)

    up = uptime(j["cycles"])
    mir = mirror_stats(j["cycles"])
    fills = verify.fill_quality(j["orders"])
    parity = live_signal_parity(a.bot)
    agreement = journalled_signal_agreement(j["signals"], a.bot)

    halts = [c for c in j["cycles"] if c.get("halt")]
    order_events = {}
    for o in j["orders"]:
        order_events[o.get("event", "?")] = order_events.get(o.get("event", "?"), 0) + 1

    corr = parity.get("match_rate")
    dev = fills.get("median_slippage_bps")
    checks = {
        "shadow_days": {"value": up.get("distinct_utc_days", 0),
                        "threshold": cfg["min_shadow_days"],
                        "ok": up.get("distinct_utc_days", 0) >= cfg["min_shadow_days"]},
        "signal_parity": {"value": corr,
                          "threshold": cfg["min_signal_correlation_live_vs_backtest"],
                          "ok": corr is not None
                          and corr >= cfg["min_signal_correlation_live_vs_backtest"]},
        "fill_deviation_bps": {"value": dev,
                               "threshold": cfg["max_fill_price_deviation_bps"],
                               "ok": dev is None or abs(dev)
                               <= cfg["max_fill_price_deviation_bps"]},
        "no_unexplained_halt": {"value": len(halts), "threshold": 0,
                                "ok": len(halts) == 0},
        "no_errors": {"value": len(j["errors"]), "threshold": 0,
                      "ok": len(j["errors"]) == 0},
    }
    passed = all(c["ok"] for c in checks.values())
    payload = {"bot": a.bot, "uptime": up, "mirror": mir, "fills": fills,
               "signal_parity": parity, "journalled_agreement": agreement,
               "order_events": order_events, "halts": len(halts),
               "errors": j["errors"][:10], "checks": checks,
               "dry_run_note": "fill metrics require live orders; "
                               "dry-run reports zero fills",
               "evaluated_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    artifacts.write(GATE, passed, payload)
    (RESULTS / f"g10_shadow_{a.bot}.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps({"passed": passed, "checks": checks, "uptime": up,
                      "mirror": mir}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
