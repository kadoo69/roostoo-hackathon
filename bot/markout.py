"""Post-fill markout: the direct measure of passive-fill adverse selection.

DECISIONS.md#passive-fill-adverse-selection records that portfolio/backtest.py
prices every LIMIT fill at the fee plus ZERO spread, and that arXiv:2502.18625
shows a resting order fills with probability 1 exactly when the next move is
against it. Bracketing that in backtest bounded it at 0.042 Sharpe. Bounding is
not measuring, and nothing in a backtest can measure it, because the quantity is
the price path AFTER a fill that the backtest assumes always happened.

Markout is that measurement. For a fill at price p on side s, with mid m(h) at
horizon h after the fill:

    markout_bps(h) = sign(s) * (m(h) - p) / p * 1e4      BUY: +1, SELL: -1

A positive markout means the price moved the way the trade wanted after it was
filled. A negative mean markout is adverse selection, in basis points, directly
comparable to the fee. Slippage (fill price against intended price) is a
different statistic and this repo already has it; slippage says whether the
order was executed well, markout says whether it was executed against.

The reference mid at submission comes from Executor.prepare, and the later mids
come from the per-cycle `marks` in the cycles stream. Both were added on
2026-09-20; markout is unavailable for anything journaled before that.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HORIZONS_S = (60, 300, 900, 3600)
SIGN = {"BUY": 1.0, "SELL": -1.0}


def _ts(rec: dict) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(rec["ts_utc"])
    except (KeyError, TypeError, ValueError):
        return None


def _read(directory: Path, stream: str) -> list[dict]:
    out = []
    for f in sorted(directory.glob(f"{stream}-*.jsonl")):
        for line in f.open():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def mark_series(directory: Path) -> list[tuple[dt.datetime, dict]]:
    series = []
    for c in _read(directory, "cycles"):
        t, m = _ts(c), c.get("marks")
        if t is not None and m:
            series.append((t, m))
    series.sort(key=lambda x: x[0])
    return series


def _mark_at(series, symbol: str, when: dt.datetime, tol_s: float = 180.0):
    best = None
    for t, m in series:
        if t < when:
            continue
        if symbol in m:
            best = (t, float(m[symbol]))
            break
    if best is None or (best[0] - when).total_seconds() > tol_s:
        return None
    return best[1]


def fills(directory: Path) -> list[dict]:
    out = []
    for o in _read(directory, "orders"):
        if o.get("event") not in {"fill", "dry_run", "accepted"}:
            continue
        if o.get("side") not in SIGN or not o.get("price"):
            continue
        out.append(o)
    return out


def markouts(directory: Path) -> dict:
    series = mark_series(directory)
    rows = []
    for o in fills(directory):
        t, sym, px = _ts(o), o.get("symbol"), float(o["price"])
        if t is None or sym is None or px <= 0:
            continue
        row = {"ts_utc": o["ts_utc"], "symbol": sym, "side": o["side"],
               "price": px, "ref_mid": o.get("ref_mid"),
               "ref_spread_bps": o.get("ref_spread_bps")}
        if o.get("ref_mid"):
            row["entry_edge_bps"] = round(
                SIGN[o["side"]] * (float(o["ref_mid"]) - px) / px * 1e4, 3)
        for h in HORIZONS_S:
            m = _mark_at(series, sym, t + dt.timedelta(seconds=h))
            row[f"markout_{h}s_bps"] = (
                None if m is None else round(SIGN[o["side"]] * (m - px) / px * 1e4, 3))
        rows.append(row)

    summary = {}
    for h in HORIZONS_S:
        vals = [r[f"markout_{h}s_bps"] for r in rows if r.get(f"markout_{h}s_bps") is not None]
        summary[f"{h}s"] = {
            "n": len(vals),
            "mean_bps": round(sum(vals) / len(vals), 3) if vals else None,
            "median_bps": round(sorted(vals)[len(vals) // 2], 3) if vals else None,
            "pct_negative": round(sum(v < 0 for v in vals) / len(vals), 4) if vals else None,
        }
    edges = [r["entry_edge_bps"] for r in rows if r.get("entry_edge_bps") is not None]
    raw = fills(directory)
    dry = bool(raw) and all(o.get("event") == "dry_run" for o in raw)
    return {
        "n_fills": len(rows),
        "n_with_reference_quote": len(edges),
        "mean_entry_edge_bps": round(sum(edges) / len(edges), 3) if edges else None,
        "horizons": summary,
        "dry_run": dry,
        "measures": ("entry_timing_only_every_order_fills_by_assumption" if dry
                     else "adverse_selection_on_real_fills"),
        "verdict": verdict(summary, dry_run=dry),
        "fills": rows[-50:],
    }


def verdict(summary: dict, dry_run: bool = False) -> str:
    if dry_run:
        return _dry_verdict(summary)
    return _live_verdict(summary)


def _dry_verdict(summary: dict) -> str:
    """In dry run every order fills at its own limit price by assumption.

    Nothing about fill SELECTION is being measured, because nothing was ever
    declined a fill. What the number means here is entry timing: when the book
    decided to trade, which way did price go next. That is worth watching, but
    calling it adverse selection would be wrong, and the two differ precisely in
    the cases arXiv:2502.18625 is about - the orders that would NOT have filled.
    """
    ns = [v["n"] for v in summary.values()]
    if not ns or max(ns) < 30:
        return ("DRY RUN, INSUFFICIENT - needs about 30 fills per horizon. "
                "Note this measures ENTRY TIMING, not adverse selection: every dry-run "
                "order fills at its own limit by assumption, so no fill was ever declined.")
    worst = min((v["mean_bps"] for v in summary.values() if v["mean_bps"] is not None),
                default=None)
    return (f"DRY RUN - entry timing, NOT adverse selection. Worst mean post-decision "
            f"move {worst} bps. Real adverse selection needs real fills, which needs "
            "the API keys in ORGANISER_QUESTIONS.md.")


def _live_verdict(summary: dict) -> str:
    ns = [v["n"] for v in summary.values()]
    if not ns or max(ns) < 30:
        return ("INSUFFICIENT - markout needs about 30 fills per horizon before its "
                "sign means anything. Read nothing yet.")
    worst = min((v["mean_bps"] for v in summary.values() if v["mean_bps"] is not None),
                default=None)
    if worst is None:
        return "INSUFFICIENT - no horizon has a mean yet."
    if worst < -5.0:
        return (f"ADVERSE SELECTION MATERIAL: worst mean markout {worst} bps is larger "
                "than the 5 bps limit fee. The backtest's zero-spread LIMIT assumption "
                "is understating cost by more than the fee itself.")
    if worst < 0.0:
        return (f"MILD: worst mean markout {worst} bps, inside the fee. Consistent with "
                "the bracket at DECISIONS.md#passive-fill-adverse-selection.")
    return f"NO ADVERSE SELECTION DETECTED: worst mean markout {worst} bps is non-negative."
