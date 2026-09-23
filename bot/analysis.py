"""Per-strategy series and readiness gates for the analysis page.

Kept out of bot/dashboard.py so it can be tested without a server, and so the
readiness gates live next to the series they govern rather than in a template.

The governing discipline is that this module never reports a comparison as
readable before its gate is met. bot/compare.py already refuses to read a
gated-vs-control lead before min_comparison_days, and a chart that quietly
ignored that would undo it.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from bot.journal import Journal
from bot.markout import HORIZONS_S, markouts
from bot.settings import ROOT

MIN_COMPARISON_DAYS = 28
MIN_MARKOUT_FILLS = 30
GATE10_DISTINCT_DAYS = 3
MAX_POINTS = 700


def _thin(frame: pd.DataFrame, n: int = MAX_POINTS) -> pd.DataFrame:
    if len(frame) <= n:
        return frame
    step = int(len(frame) / n) + 1
    keep = frame.iloc[::step]
    if keep.index[-1] != frame.index[-1]:
        keep = pd.concat([keep, frame.iloc[[-1]]])
    return keep


def series(name: str) -> dict:
    cycles = Journal(name).read("cycles")
    if not cycles:
        return {"bot": name, "points": [], "n": 0}
    f = pd.DataFrame(cycles)
    f["ts"] = pd.to_datetime(f["ts_utc"], utc=True)
    f = f.sort_values("ts").set_index("ts")
    eq = f["equity"].astype(float)
    base = float(eq.iloc[0]) or 1.0
    f = f.assign(
        norm=eq / base * 100.0,
        dd=(eq / eq.cummax() - 1.0) * 100.0,
        gross=pd.to_numeric(f.get("gross_exposure"), errors="coerce").fillna(0.0) * 100.0,
        n_long=pd.to_numeric(f.get("n_long"), errors="coerce").fillna(0),
    )
    thin = _thin(f)
    pts = [{"t": t.isoformat(), "e": round(float(r.equity), 2),
            "n": round(float(r.norm), 4), "dd": round(float(r.dd), 4),
            "g": round(float(r.gross), 2), "p": int(r.n_long)}
           for t, r in thin.iterrows()]
    decisions = []
    for t, r in f[f.get("new_bar", pd.Series(False, index=f.index)).fillna(False)].iterrows():
        decisions.append({"t": t.isoformat(), "bar": r.get("bar"),
                          "n_target": (None if pd.isna(r.get("n_target"))
                                       else int(r.get("n_target"))),
                          "orders": int(r.get("orders") or 0),
                          "equity": round(float(r.equity), 2)})
    return {"bot": name, "points": pts, "n": int(len(f)),
            "decisions": decisions[-40:], "n_decisions": len(decisions)}


def ab_spread(gated: str, control: str) -> dict:
    """Gated arm minus its control, on a common clock, with the gate stated."""
    a, b = series(gated), series(control)
    if not a["points"] or not b["points"]:
        return {"gated": gated, "control": control, "points": [], "readable": False,
                "verdict": "no data yet"}
    fa = pd.Series({p["t"]: p["n"] for p in a["points"]})
    fb = pd.Series({p["t"]: p["n"] for p in b["points"]})
    fa.index = pd.to_datetime(fa.index, utc=True)
    fb.index = pd.to_datetime(fb.index, utc=True)
    grid = fa.index.union(fb.index)
    lead = (fa.reindex(grid).ffill() - fb.reindex(grid).ffill()).dropna()
    days = (grid[-1] - grid[0]).total_seconds() / 86400.0 if len(grid) > 1 else 0.0
    readable = days >= MIN_COMPARISON_DAYS
    return {
        "gated": gated, "control": control,
        "points": [{"t": t.isoformat(), "d": round(float(v), 4)}
                   for t, v in _thin(lead.to_frame("d")).itertuples()],
        "days": round(days, 3), "days_needed": MIN_COMPARISON_DAYS,
        "lead_pp": round(float(lead.iloc[-1]), 4),
        "readable": readable,
        "verdict": ("comparable" if readable else
                    f"TOO EARLY - {round(MIN_COMPARISON_DAYS - days, 2)} more days "
                    f"before this lead means anything"),
    }


def readiness(bots: list[dict]) -> list[dict]:
    """Every gate that stands between the current state and a readable claim."""
    out = []
    for b in bots:
        name = b["bot"]
        days = b.get("wall_hours", 0.0) / 24.0
        distinct = b.get("distinct_days", 0)
        mk = b.get("markout") or {}
        best_n = max([v["n"] for v in (mk.get("horizons") or {}).values()] or [0])
        out.append({"bot": name, "gate": "forward A/B (28 complete days)",
                    "have": round(days, 2), "need": MIN_COMPARISON_DAYS,
                    "pct": min(100.0, round(days / MIN_COMPARISON_DAYS * 100, 1)),
                    "met": days >= MIN_COMPARISON_DAYS})
        out.append({"bot": name, "gate": "Gate 10 (3 distinct live days)",
                    "have": distinct, "need": GATE10_DISTINCT_DAYS,
                    "pct": min(100.0, round(distinct / GATE10_DISTINCT_DAYS * 100, 1)),
                    "met": distinct >= GATE10_DISTINCT_DAYS})
        out.append({"bot": name, "gate": f"markout ({MIN_MARKOUT_FILLS} fills/horizon)",
                    "have": best_n, "need": MIN_MARKOUT_FILLS,
                    "pct": min(100.0, round(best_n / MIN_MARKOUT_FILLS * 100, 1)),
                    "met": best_n >= MIN_MARKOUT_FILLS,
                    "note": ("dry run measures entry timing, not adverse selection"
                             if mk.get("dry_run") else None)})
    return out


def scanner_history(limit: int = 400) -> list[dict]:
    rows = []
    for f in sorted((ROOT / "live" / "scanner").glob("scans-*.jsonl")):
        for line in f.open():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # scans-*.jsonl is flat. live/scanner/state.json nests the same fields
            # under "universe"; reading the wrong one yields a full-length series
            # of nulls that charts as an empty panel rather than an error.
            rows.append({"t": d.get("ts_utc"), "disp": d.get("dispersion_pct"),
                         "long": d.get("pct_long"), "med": d.get("median_ret_pct"),
                         "cushion": d.get("median_cushion_pct"),
                         "at_risk": d.get("n_at_risk")})
    return rows[-limit:]


def _scanner_coins() -> dict:
    try:
        st = json.loads((ROOT / "live" / "scanner" / "state.json").read_text())
        return st.get("coins") or {}
    except Exception:
        return {}


def selection(name: str) -> dict:
    """Why each name in the pool is or is not held, as one funnel.

    This is the panel that answers "are the signals being picked up". The books
    look broad because the pool is 30 names; they are not. Every stage that
    removes a name is shown with its reason, so under-deployment (a book sitting
    in cash because nothing signalled) is visibly different from over-selection.
    """
    j = Journal(name)
    uni = j.read("universe")
    cycles = j.read("cycles")
    sigs = j.read("signals")
    if not uni or not cycles:
        return {"bot": name, "stages": [], "names": []}

    last_u = uni[-1]
    pool = list(last_u.get("pool") or [])
    sel = list(last_u.get("selected") or [])
    listed = last_u.get("venue_listed")
    held = dict((cycles[-1].get("positions") or {}))
    chans = (sigs[-1].get("channels") or {}) if sigs else {}
    targets = (sigs[-1].get("target_weights") or {}) if sigs else {}
    coins = _scanner_coins()

    rows = []
    for sym in pool:
        c = coins.get(sym) or {}
        ch = chans.get(sym) or {}
        if sym in held:
            status, why = "HELD", ch.get("action") or "held"
        elif sym in targets:
            status, why = "TARGET", "signalled but not yet filled"
        elif sym not in sel:
            status, why = "EXCLUDED", "not tradable on venue, spread gate, or short history"
        elif c.get("state") == "long":
            status, why = "SIGNAL_NOT_TAKEN", "above channel but outside the rank cut"
        elif c.get("state") == "pending":
            status, why = "PENDING", f"{c.get('to_entry_pct')}% below entry"
        elif c.get("state") == "at_risk":
            status, why = "AT_RISK", f"cushion {c.get('cushion_pct')}%"
        else:
            status, why = "FLAT", "no channel break"
        rows.append({"symbol": sym, "status": status, "why": why,
                     "weight": round(float(held.get(sym, 0.0)), 5),
                     "close": c.get("close"), "upper": c.get("upper"),
                     "floor": c.get("floor"),
                     "cushion_pct": c.get("cushion_pct"),
                     "to_entry_pct": c.get("to_entry_pct"),
                     "in_universe": sym in sel})
    order = {"HELD": 0, "TARGET": 1, "SIGNAL_NOT_TAKEN": 2, "AT_RISK": 3,
             "PENDING": 4, "FLAT": 5, "EXCLUDED": 6}
    rows.sort(key=lambda r: (order.get(r["status"], 9),
                             -(r["weight"] or 0),
                             r["to_entry_pct"] if r["to_entry_pct"] is not None else 1e9))
    n_sig = sum(1 for r in rows if r["status"] in ("HELD", "TARGET", "SIGNAL_NOT_TAKEN"))
    gross = float(cycles[-1].get("gross_exposure") or 0.0)
    stages = [
        {"stage": "listed on venue", "n": listed, "drop": None},
        {"stage": "top-30 by 30d median dollar volume", "n": len(pool),
         "drop": (listed - len(pool)) if listed else None},
        {"stage": "tradable: spread, asset type, history", "n": len(sel),
         "drop": len(pool) - len(sel)},
        {"stage": "above the 20-bar channel", "n": n_sig, "drop": len(sel) - n_sig},
        {"stage": "held after the rank cut", "n": len(held), "drop": n_sig - len(held)},
    ]
    return {"bot": name, "stages": stages, "names": rows,
            "gross": round(gross * 100, 2),
            "cash_pct": round(100.0 - gross * 100, 2),
            "n_held": len(held), "n_pool": len(pool), "n_universe": len(sel)}


def positions(name: str) -> dict:
    """Live per-position attribution: entry, mark, contribution, distance to exit.

    The panel exists because a book-level number cannot answer "which name is
    hurting me and how far is it from being cut". On 2026-09-20 every book was
    red while two of its three names were green; one name carried the whole loss.
    """
    j = Journal(name)
    cycles = j.read("cycles")
    sigs = j.read("signals")
    if not cycles:
        return {"bot": name, "rows": [], "total_contrib": 0.0}
    last = cycles[-1]
    marks = last.get("marks") or {}
    held = last.get("positions") or {}

    entry: dict[str, tuple[str, float]] = {}
    for o in j.read("orders"):
        if o.get("side") == "BUY" and o.get("price") and o.get("symbol"):
            entry[o["symbol"]] = (o.get("ts_utc"), float(o["price"]))

    chans: dict[str, dict] = {}
    for srec in sigs:
        for sym, c in (srec.get("channels") or {}).items():
            chans[sym] = c

    rows, total = [], 0.0
    for sym, w in sorted(held.items(), key=lambda x: -x[1]):
        mark = marks.get(sym)
        ent = entry.get(sym, (None, None))
        floor = (chans.get(sym) or {}).get("floor")
        chg = ((mark / ent[1] - 1.0) * 100.0) if (mark and ent[1]) else None
        contrib = (w * chg) if chg is not None else None
        if contrib is not None:
            total += contrib
        rows.append({
            "symbol": sym, "weight_pct": round(w * 100, 2),
            "entry": ent[1], "entry_at": ent[0], "mark": mark,
            "change_pct": None if chg is None else round(chg, 3),
            "contrib_pct": None if contrib is None else round(contrib, 4),
            "exit_floor": floor,
            "to_exit_pct": (round((floor / mark - 1.0) * 100.0, 2)
                            if (floor and mark) else None),
        })
    return {"bot": name, "rows": rows, "total_contrib": round(total, 4),
            "n": len(rows)}


def payload(bots: list[dict], control_of: dict) -> dict:
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "series": [series(b["bot"]) for b in bots],
        "selection": [selection(b["bot"]) for b in bots],
        "positions": [positions(b["bot"]) for b in bots],
        "ab": [ab_spread(g, c) for g, c in control_of.items()],
        "readiness": readiness(bots),
        "scanner": scanner_history(),
        "markout": {b["bot"]: (b.get("markout") or {}) for b in bots},
        "horizons": list(HORIZONS_S),
    }


def markout_for(name: str) -> dict:
    return markouts(ROOT / "live" / name)
