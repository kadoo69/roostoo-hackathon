"""Compact payload for the desk page: fleet totals, books grouped by role, A/B deltas against
their controls measured from the arm's own start, fleet coin exposure, recent activity and alerts.
Built from `bot.dashboard.snapshot()`; read-only. DECISIONS.md#desk-dashboard-2026-09-26
Since 2026-09-30 the desk shows only the live competition books (`DESK_GROUPS`); the paper fleet
stays on `/full`. DECISIONS.md#desk-competition-only-2026-09-30
"""
from __future__ import annotations

import pandas as pd

from bot.blotter import DUST_NOTIONAL

GROUPS = (("live", "LIVE on Roostoo - real orders"), ("scalper", "PAPER - the dynamic bot and fixed-clock baselines"), ("core", "Core 4h"),
          ("momentum", "Short-term momentum"), ("burst", "Burst"), ("ab", "A/B tests"), ("short", "Short"))
LIVE_BOOKS = {"competition", "competition_rehearsal"}
SCALPER_BOOKS = {"wf_live", "momentum_top3_5m", "momentum_top3_15m", "momentum_top3_30m",
                 "ride_5m", "blend_30m_ride", "regime_ls_30m", "resid_30m", "htf0_30m", "ride1_5m", "wide_30m", "ride1_wide_5m", "sleeves_5m", "sleeves_ivol_5m", "ride_z3_5m", "sleeves_z3_5m", "uni_donchian_15m"}
DESK_GROUPS = ("live", "scalper")
TOTALS_GROUPS = ("live",)
AB_ARMS = {"momentum_top3_15m_eq", "momentum_top3_15m_hold3h",
           "momentum_top3_5m_hold2h", "burst_strong_15m", "momentum_top3_15m_slowexit"}
STALE_S = 300


def group_of(name: str, interval: str | None) -> str:
    if name in LIVE_BOOKS:
        return "live"
    if name in SCALPER_BOOKS:
        return "scalper"
    if name.startswith("short_"):
        return "short"
    if name in AB_ARMS:
        return "ab"
    if name.startswith("burst"):
        return "burst"
    if interval == "4h":
        return "core"
    return "momentum"


def _equity_at(curve: list[dict], ts: pd.Timestamp) -> float | None:
    before = [p["e"] for p in curve if pd.Timestamp(p["t"]) <= ts]
    return before[-1] if before else (curve[0]["e"] if curve else None)


def ab_delta(arm: dict, control: dict | None) -> dict | None:
    """Arm return since its first cycle against the control's return over the same span."""
    if not control or not arm.get("equity_curve") or not control.get("equity_curve"):
        return None
    start = pd.Timestamp(arm.get("first_cycle"))
    c0 = _equity_at(control["equity_curve"], start)
    if not c0:
        return None
    arm_ret = (arm["equity"] / arm["equity_start"] - 1) * 100
    ctl_ret = (control["equity"] / c0 - 1) * 100
    return {"control": control["bot"], "arm_pct": round(arm_ret, 2), "control_pct": round(ctl_ret, 2),
            "delta_pts": round(arm_ret - ctl_ret, 2), "since": str(start)}


def positions(b: dict) -> list[dict]:
    lots: dict[str, dict] = {}
    for lot in b.get("open") or []:
        s = lots.setdefault(lot["symbol"], {"qty": 0.0, "cost": 0.0, "dir": lot.get("direction", "long"),
                                            "since": lot.get("entry_ts")})
        s["qty"] += float(lot["qty"])
        s["cost"] += float(lot.get("cost_basis") or float(lot["qty"]) * float(lot["entry_price"]))
        s["since"] = min(s["since"], lot.get("entry_ts")) if s["since"] and lot.get("entry_ts") else s["since"]
    out = []
    for sym, w in sorted((b.get("positions") or {}).items(), key=lambda x: -abs(x[1])):
        lot = lots.get(sym)
        mark = (b.get("marks") or {}).get(sym)
        row = {"symbol": sym.replace("USDT", ""), "weight": round(float(w), 4), "mark": mark}
        if lot and lot["qty"] > 0 and mark:
            entry = lot["cost"] / lot["qty"]
            sign = -1 if w < 0 else 1
            row.update({"entry": round(entry, 8), "qty": lot["qty"], "pnl": round(sign * (mark - entry) * lot["qty"], 2),
                        "pnl_pct": round(sign * (mark / entry - 1) * 100, 2), "since": lot["since"]})
        out.append(row)
    return out


def adaptive_clock(name: str) -> str | None:
    """The clock an adaptive book is trading now, from its `adaptive.json`.
    DECISIONS.md#scalper-adaptive-declaration"""
    import json

    from bot.settings import ROOT
    f = ROOT / "live" / name / "adaptive.json"
    try:
        return json.loads(f.read_text()).get("clock")
    except (OSError, ValueError):
        return None


def progress_by_book() -> dict:
    """The hourly review's latest row per book. DECISIONS.md#progress-review-2026-09-30"""
    import json

    from bot.settings import ROOT
    try:
        rep = json.loads((ROOT / "results" / "progress" / "latest.json").read_text())
        return {r["book"]: r for r in rep.get("books", [])}
    except (OSError, ValueError):
        return {}


def walkforward() -> dict:
    """Live walk-forward scorecard and the hedge explorer's learned weights for the desk.
    DECISIONS.md#walkforward-live-declaration, DECISIONS.md#hedge-explorer-declaration"""
    import json

    from bot.settings import ROOT
    try:
        from gates.wf_report import summary
        out = summary("wf_live")
    except Exception:                                      # noqa: BLE001
        out = {}
    try:
        ms = json.loads((ROOT / "results" / "market_structure.json").read_text())
        out["market"] = {"pc1_share": ms["pc_share"][0], "effective_bets": ms["effective_bets"], "n": ms["n_coins"],
                         "cluster": (ms.get("clusters_corr_0.7") or [[]])[0][:6],
                         "leaders": [k for k, _ in sorted(ms["coins"].items(), key=lambda kv: -kv[1]["resid_24h_pct"])[:3]],
                         "at": ms["generated"]}
    except (OSError, ValueError, KeyError, IndexError):
        out["market"] = None
    try:
        h = json.loads((ROOT / "live" / "hedge_explorer" / "hedge.json").read_text())
        top = sorted(h["weights"].items(), key=lambda kv: -kv[1])[:4]
        out["hedge_top"] = [{"variant": k, "share": round(v * 100, 1)} for k, v in top]
        out["hedge_at"] = h.get("at")
    except (OSError, ValueError, KeyError):
        out["hedge_top"] = []
    return out


def book(b: dict, by_name: dict) -> dict:
    m = b.get("meta") or {}
    st = b.get("blotter") or {}
    curve = b.get("equity_curve") or []
    step = max(1, len(curve) // 60)
    auto = adaptive_clock(b["bot"]) if b["bot"] in ("scalper_adaptive", "wf_live", "hedge_explorer") else None
    return {"bot": b["bot"], "group": group_of(b["bot"], m.get("interval")),
            "clock": f"auto: {auto}" if auto else m.get("interval"),
            "description": m.get("description"), "live": bool(b.get("live")),
        "waiting_for_account": bool(b.get("waiting_for_account")), "last_poll": b.get("last_poll"),
            "age_s": b.get("seconds_since_cycle"), "equity": b.get("equity"), "net": b.get("pnl"),
            "realised": b.get("realised_pnl"), "open": b.get("open_pnl"), "ret_pct": b.get("pnl_pct"),
            "drawdown_pct": b.get("drawdown_pct"), "gross": b.get("gross"),
            "spark": [p["e"] for p in curve[::step]] + ([curve[-1]["e"]] if curve and (len(curve) - 1) % step else []),
            "curve": curve, "positions": positions(b),
            "stats": {"trades": st.get("material_trades"), "win_rate": st.get("win_rate"),
                      "payoff": st.get("payoff_ratio"), "profit_factor": st.get("profit_factor"),
                      "fees": st.get("total_fees"), "fees_pct_gross": st.get("fees_pct_of_gross"),
                      "median_hold_h": st.get("median_hold_hours"), "best": st.get("best_trade"),
                      "worst": st.get("worst_trade")},
            "recent": [{"symbol": t["symbol"].replace("USDT", ""), "dir": t["direction"], "exit": t["exit_ts"],
                        "hold_h": t.get("hold_hours"), "net": round(float(t["net_pnl"]), 2),
                        "ret_pct": round(float(t.get("net_return_pct") or 0.0), 2), "kind": t.get("exit_kind")}
                       for t in (b.get("closed") or [])[:8]],
            "control": b.get("control_of"),
            "ab": ab_delta(b, by_name.get(b.get("control_of"))) if b["bot"] in AB_ARMS else None,
            "faults_last_hour": b.get("faults_last_hour", 0), "blips_last_hour": b.get("errors_last_hour", 0)}


def exposure(books: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for bk in books:
        for p in bk["positions"]:
            a = agg.setdefault(p["symbol"], {"symbol": p["symbol"], "usd": 0.0, "books": 0, "pnl": 0.0,
                                             "qty": 0.0, "basis": 0.0, "mark": p.get("mark")})
            a["usd"] += p["weight"] * (bk["equity"] or 0.0)
            a["books"] += 1
            a["pnl"] += p.get("pnl") or 0.0
            if p.get("qty") and p.get("entry"):
                sign = -1 if p["weight"] < 0 else 1
                a["qty"] += sign * p["qty"]
                a["basis"] += sign * p["qty"] * p["entry"]
    rows = sorted(agg.values(), key=lambda r: -abs(r["usd"]))
    return [{**r, "usd": round(r["usd"]), "pnl": round(r["pnl"]), "basis": round(r["basis"], 4)} for r in rows]


def activity(books: list[dict], limit: int = 14) -> list[dict]:
    ev = []
    for bk in books:
        for t in bk["recent"]:
            ev.append({"ts": t["exit"], "bot": bk["bot"], "kind": "close", "exit_kind": t.get("kind"), "symbol": t["symbol"],
                       "dir": t["dir"], "net": t["net"], "ret_pct": t["ret_pct"], "hold_h": t["hold_h"]})
        for p in bk["positions"]:
            if p.get("since"):
                ev.append({"ts": p["since"], "bot": bk["bot"], "kind": "open", "symbol": p["symbol"],
                           "dir": "short" if p["weight"] < 0 else "long", "weight": p["weight"]})
    ev.sort(key=lambda e: e["ts"] or "", reverse=True)
    return ev[:limit]


def closed_feed(bots: list[dict], limit: int = 1500) -> dict:
    """Every book's closed trades newest first, without slices below the blotter's dust floor, cut where the feed stops being complete: a book
    whose snapshot list is truncated sets the cut at its oldest listed exit.
    DECISIONS.md#desk-closed-trades-2026-09-27"""
    rows, cut = [], ""
    for b in bots:
        closed = b.get("closed") or []
        if closed and (b.get("closed_total") or 0) > len(closed):
            cut = max(cut, min(str(t["exit_ts"]) for t in closed))
        grp = group_of(b["bot"], (b.get("meta") or {}).get("interval"))
        for t in closed:
            notional = float(t["qty"]) * float(t["entry_price"]) if t.get("qty") and t.get("entry_price") else None
            if notional is not None and notional < DUST_NOTIONAL:
                continue
            rows.append({"bot": b["bot"], "group": grp, "symbol": t["symbol"].replace("USDT", ""),
                         "dir": t["direction"], "entry_ts": t.get("entry_ts"), "exit": str(t["exit_ts"]),
                         "entry": t.get("entry_price"), "exit_price": t.get("exit_price"),
                         "hold_h": t.get("hold_hours"), "notional": round(notional) if notional else None,
                         "net": round(float(t["net_pnl"]), 2), "fees": round(float(t.get("fees") or 0.0), 2),
                         "ret_pct": round(float(t.get("net_return_pct") or 0.0), 2), "kind": t.get("exit_kind")})
    rows = [r for r in rows if r["exit"] >= cut]
    rows.sort(key=lambda r: r["exit"], reverse=True)
    if len(rows) > limit:
        rows, cut = rows[:limit], rows[limit - 1]["exit"]
    return {"complete_since": cut or None, "trades": rows}


def alerts(books: list[dict]) -> list[dict]:
    """Fleet alerts; a live book still waiting for its Roostoo account leads the list.
    DECISIONS.md#competition-book-2026-09-30"""
    out = []
    for b in books:
        if b.get("waiting_for_account"):
            out.append({"level": "bad", "text": f"{b['bot']}: Roostoo account not active yet "
                                                f"(last poll {str(b.get('last_poll') or '')[:19]}Z), no orders possible"})
    stale = [b["bot"] for b in books if (b["age_s"] or 0) > STALE_S]
    if stale:
        out.append({"level": "bad", "text": f"{len(stale)} book(s) not cycling: {', '.join(stale)}"})
    errs = [b["bot"] for b in books if b.get("faults_last_hour")]
    if errs:
        out.append({"level": "bad", "text": f"real faults in the last hour: {', '.join(errs)}"})
    blips = sum(b.get("blips_last_hour") or 0 for b in books)
    if blips >= 20:
        out.append({"level": "warn", "text": f"{blips} network blips in the last hour (retried automatically)"})
    deep = [f"{b['bot']} {b['drawdown_pct']:.1f}%" for b in books if (b["drawdown_pct"] or 0) <= -10]
    if deep:
        out.append({"level": "warn", "text": "drawdown beyond -10%: " + ", ".join(deep)})
    return out


def payload(snap: dict) -> dict:
    by_name = {b["bot"]: b for b in snap["bots"]}
    shown = [b for b in snap["bots"] if group_of(b["bot"], (b.get("meta") or {}).get("interval")) in DESK_GROUPS]
    books = [book(b, by_name) for b in shown]
    from bot import ec2_feed
    ec2 = ec2_feed.payload()
    if ec2:
        on_ec2 = {b["bot"] for b in ec2["books"]}
        books = [b for b in books if b["group"] != "live" and b["bot"] not in on_ec2]
    prog = progress_by_book()
    for b in books:
        b["risk"] = (prog.get(b["bot"]) or {}).get("ratios_total")
    books.sort(key=lambda b: -(b["ret_pct"] or 0.0))
    live = [b for b in books if b["equity"] is not None and b["group"] in TOTALS_GROUPS]
    total = {"net": round(sum(b["net"] or 0.0 for b in live)), "realised": round(sum(b["realised"] or 0.0 for b in live)),
             "open": round(sum(b["open"] or 0.0 for b in live)), "books": len(live),
             "up": sum(1 for b in live if (b["net"] or 0) > 0), "down": sum(1 for b in live if (b["net"] or 0) < 0),
             "online": sum(1 for b in live if (b["age_s"] or 1e9) <= STALE_S),
             "best": max(live, key=lambda b: b["ret_pct"] or -1e9)["bot"] if live else None}
    paper = [b for b in books if b["equity"] is not None]
    paper_tot = {"net": round(sum(b["net"] or 0.0 for b in paper)), "books": len(paper),
                 "up": sum(1 for b in paper if (b["net"] or 0) > 0), "down": sum(1 for b in paper if (b["net"] or 0) < 0),
                 "online": sum(1 for b in paper if (b["age_s"] or 1e9) <= STALE_S),
                 "best": max(paper, key=lambda b: b["ret_pct"] or -1e9)["bot"] if paper else None,
                 "best_pct": max((b["ret_pct"] or -1e9) for b in paper) if paper else None}
    if ec2:
        eb = [b for b in ec2["books"] if b["net"] is not None and not b.get("paper")]
        total.update({"net": round(sum(b["net"] for b in eb)), "realised": None, "open": None, "books": len(ec2["books"]),
                      "up": sum(1 for b in eb if b["net"] > 0), "down": sum(1 for b in eb if b["net"] < 0),
                      "online": sum(1 for b in ec2["books"] if b["active"] == "active" and not b.get("paper"))})
    return {"generated": snap["generated"], "totals": total, "ec2": ec2, "paper": paper_tot,
            "groups": [{"key": k, "label": v} for k, v in GROUPS if k in DESK_GROUPS],
            "books": books, "exposure": exposure(books), "activity": activity(books), "alerts": alerts(books),
            "closed": closed_feed(shown), "walkforward": walkforward(),
            "breadth": snap.get("breadth")}
