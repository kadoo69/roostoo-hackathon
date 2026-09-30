"""Universe scanner: classifies every name independently, publishes, never trades.

Declared at config/scanner.yaml. This process holds no capital and places no
orders. It writes `live/scanner/state.json` atomically; executor bots read it
and are required to fall back to ungated behaviour when it is stale or absent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import time

import numpy as np
import pandas as pd
import yaml

from bot import feed
from bot import universe as bu
from bot.settings import ROOT, load
from data import futures, microstructure
from venue.roostoo import RoostooClient

OUT = ROOT / "live" / "scanner"


def declaration() -> dict:
    with (ROOT / "config" / "scanner.yaml").open() as fh:
        return yaml.safe_load(fh)


def classify(m: pd.DataFrame, cfg: dict) -> dict:
    """Per-name state from the same channel the live bots use.

    Deliberately reuses the bots' own entry and exit levels rather than a new
    indicator: the scanner's job is to describe the book's world, and a state
    computed from a different rule would describe something else.
    """
    s = cfg["scan"]
    rows = {}
    for sym in m.columns:
        c = m[sym].dropna()
        if len(c) < max(s["entry_bars"], s["exit_bars"]) + 1:
            continue
        prior = c.iloc[:-1]
        upper = float(prior.tail(s["entry_bars"]).max())
        floor = float(prior.tail(s["exit_bars"]).min())
        px = float(c.iloc[-1])
        above = px > upper
        cushion = (px / floor - 1.0) * 100.0 if floor > 0 else float("nan")
        to_entry = (upper / px - 1.0) * 100.0 if px > 0 else float("nan")
        if above or cushion > s["at_risk_pct"]:
            state = "at_risk" if cushion <= s["at_risk_pct"] else "trend_up"
        elif 0 < to_entry <= s["pending_pct"]:
            state = "pending"
        else:
            state = "flat"
        rows[sym] = {"state": state, "close": px, "upper": round(upper, 10),
                     "floor": round(floor, 10),
                     "cushion_pct": round(cushion, 3),
                     "to_entry_pct": round(to_entry, 3)}
    return rows


def universe_state(rows: dict, m: pd.DataFrame, cfg: dict) -> dict:
    s = cfg["scan"]
    n = len(rows)
    up = sum(1 for r in rows.values() if r["state"] == "trend_up")
    k = int(s["dispersion_bars"])
    ret = (m.iloc[-1] / m.iloc[-1 - k] - 1.0).dropna() if len(m) > k else pd.Series(dtype=float)
    cush = [r["cushion_pct"] for r in rows.values()
            if r["state"] in ("trend_up", "at_risk") and np.isfinite(r["cushion_pct"])]
    return {
        "scanned": n,
        "pct_long": round(100.0 * up / n, 2) if n else 0.0,
        "n_at_risk": sum(1 for r in rows.values() if r["state"] == "at_risk"),
        "n_pending": sum(1 for r in rows.values() if r["state"] == "pending"),
        "dispersion_pct": round(float(ret.std() * 100), 3) if len(ret) > 2 else None,
        "median_ret_pct": round(float(ret.median() * 100), 3) if len(ret) else None,
        "median_cushion_pct": round(float(np.median(cush)), 3) if cush else None,
        "dispersion_bars": k,
    }


def enrich(rows: dict, cfg: dict) -> dict:
    """Positioning and microstructure for the names that can actually be traded.

    Only the top N by cushion plus anything pending, because these endpoints are
    per-symbol and rate limited - enriching all 66 every scan would buy noise
    with the request budget. Every failure is recorded per symbol rather than
    dropped, so a missing field is visibly missing.
    """
    e = cfg.get("enrichment", {})
    n = int(e.get("enrich_top_n", 12))
    ranked = sorted((k for k, v in rows.items()
                     if v["state"] in ("trend_up", "at_risk", "pending")),
                    key=lambda k: rows[k].get("cushion_pct") or -99, reverse=True)[:n]
    out = {}
    for sym in ranked:
        rec = {}
        for name, fn in (("crowding", lambda: futures.crowding(sym, "4h")),
                         ("book", lambda: microstructure.book(sym, 100)),
                         ("trades", lambda: microstructure.trade_profile(sym, 1000))):
            try:
                rec[name] = fn()
            except Exception as exc:
                rec[name] = {"error": repr(exc)[:160]}
        out[sym] = rec
    return out


def scan_once(cfg: dict, n_scan: int = 0) -> dict:
    s = cfg["scan"]
    settings = load(ROOT / "config" / "donchian_4h.yaml")
    c = RoostooClient()
    specs = c.exchange_info()
    venue = bu.venue_symbols(specs)
    frames = feed.bar_frame(venue, s["interval"], 120)
    m = feed.close_matrix(frames)
    rows = classify(m, cfg)
    every = int(cfg.get("enrichment", {}).get("enrich_every_n_scans", 3))
    payload = {"ts_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "interval": s["interval"],
               "config_sha": settings.config_sha256,
               "universe": universe_state(rows, m, cfg),
               "coins": rows}
    if n_scan % every == 0:
        payload["enriched"] = enrich(rows, cfg)
        payload["enriched_at"] = payload["ts_utc"]
    else:
        prev, _ = _previous()
        if prev and prev.get("enriched"):
            payload["enriched"] = prev["enriched"]
            payload["enriched_at"] = prev.get("enriched_at")
    return payload


def _previous() -> tuple[dict | None, str]:
    """Last published scan, so a non-enriching cycle can carry its fields
    forward with an honest `enriched_at` rather than dropping them."""
    try:
        return json.loads((OUT / "state.json").read_text()), "ok"
    except Exception as exc:
        return None, repr(exc)[:80]


def publish(payload: dict) -> None:
    """Atomic write. A reader must never see a partially written scan."""
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "state.json.tmp"
    tmp.write_text(json.dumps(payload, indent=1, default=str))
    os.replace(tmp, OUT / "state.json")
    with (OUT / f"scans-{dt.date.today().isoformat()}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts_utc": payload["ts_utc"],
                             **payload["universe"]}, default=str) + "\n")
    # Preserve the actual enrichment sample for forward feature studies. The
    # state file carries old enrichment between polls; logging it every time
    # would invent observations at timestamps when no API read happened.
    if payload.get("enriched_at") == payload["ts_utc"] and payload.get("enriched"):
        with (OUT / f"enriched-{dt.date.today().isoformat()}.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts_utc": payload["ts_utc"],
                                 "enriched": payload["enriched"]}, default=str) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    if a.root is not None:
        want = pathlib.Path(a.root).resolve()
        if want != pathlib.Path(ROOT).resolve():
            print(f"scanner refused: --root {want} is not this checkout {ROOT}", flush=True)
            return 2
    cfg = declaration()
    n = 0
    while True:
        try:
            p = scan_once(cfg, n)
            n += 1
            publish(p)
            u = p["universe"]
            print(f"{p['ts_utc']} scanned={u['scanned']} long={u['pct_long']}% "
                  f"at_risk={u['n_at_risk']} pending={u['n_pending']} "
                  f"disp={u['dispersion_pct']} med_ret={u['median_ret_pct']}% "
                  f"enriched={len(p.get('enriched') or {})}", flush=True)
        except Exception as exc:
            OUT.mkdir(parents=True, exist_ok=True)
            with (OUT / "errors.jsonl").open("a") as fh:
                fh.write(json.dumps({"ts_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                     "error": repr(exc)}) + "\n")
            print(f"scan_error {exc!r}", flush=True)
        if a.once:
            return 0
        time.sleep(cfg["scan"]["poll_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())
