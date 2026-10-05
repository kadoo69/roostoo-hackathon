"""Compact payload for the desk page: fleet totals, books grouped by role, A/B deltas against
their controls measured from the arm's own start, fleet coin exposure, recent activity and alerts.
Built from `bot.dashboard.snapshot()`; read-only. DECISIONS.md#desk-dashboard-2026-09-26
Since 2026-09-30 the desk shows only the live competition books (`DESK_GROUPS`); the paper fleet
stays on `/full`. DECISIONS.md#desk-competition-only-2026-09-30
"""
from __future__ import annotations


from bot.blotter import DUST_NOTIONAL

GROUPS = (("live", "LIVE on Roostoo - real orders"), ("scalper", "PAPER - the dynamic bot and fixed-clock baselines"))
LIVE_BOOKS = {"competition", "competition_split", "competition_wf", "competition_ride", "competition_z3", "competition_z25", "competition_r4", "competition_rehearsal"}
SCALPER_BOOKS = {"momentum_top3_30m", "wf_live", "blend_30m_ride", "resid_30m", "htf0_30m", "ride1_5m", "wide_30m", "ride1_wide_5m", "ride_5m", "regime_ls_30m", "ride_z3_5m", "sleeves_z3_5m", "split_tilt_5m", "ride_z25_5m", "ride_z25_swap_5m", "ride_z25_zrank_5m", "ride_z25_churn_5m", "ride_z25_gate_5m", "ride_z25_n4_5m"}
DESK_GROUPS = ("live", "scalper")
TOTALS_GROUPS = ("live",)
STALE_S = 300


def group_of(name: str, interval: str | None) -> str:
    return "live" if name in LIVE_BOOKS else "scalper"


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


COMP_OPEN = "2026-10-04T12:00:00+00:00"
COMP_END = "2026-10-18T12:00:00+00:00"
COMP_START_EQUITY = 100_000.0
BAR_MIN = 5


def rule_positions(bk: dict, lots: dict[str, list[float]], marks: dict, now) -> list[dict]:
    """Positions of a live book without a ride ledger (the regime rule): average cost over the open
    FIFO lots, live mark and P&L; no take-profit or timed exit, the rule exits on its 10-bar channel.
    DECISIONS.md#competition-r4-2026-10-05"""
    import datetime as dt
    first: dict[str, str] = {}
    for lot in bk.get("open_lots") or []:
        s = lot["symbol"].replace("USDT", "")
        if lot.get("entry_ts") and (s not in first or lot["entry_ts"] < first[s]):
            first[s] = lot["entry_ts"]
    out = []
    for s, w in (bk.get("positions") or {}).items():
        ent = (bk.get("entries") or {}).get(s, {})
        qty = ent.get("qty")
        fill = lots[s][1] / lots[s][0] if s in lots and lots[s][0] > 0 else ent.get("entry")
        at = dt.datetime.fromisoformat(first[s]) if s in first else None
        mark = marks.get(s)
        row = {"symbol": s, "qty": qty, "weight_now": w, "slot_weight": w, "entry_bar": at.isoformat() if at else None,
               "signal_px": None, "fill_px": fill, "target_pct": None, "target_px": None, "exit_at": None,
               "hours_left": None, "held_h": round((now - at).total_seconds() / 3600, 2) if at else None,
               "mark": mark, "next_skim_px": None, "exit_rule": "close below the prior 10-bar low (30m)"}
        if mark and fill:
            row.update({"pnl_pct": round((mark / fill - 1) * 100, 2),
                        "pnl_usd": round(qty * (mark - fill), 2) if qty else None})
        out.append(row)
    return out


def competition_view(ec2: dict | None, radar: dict) -> dict | None:
    """The live competition unit in detail: equity path, each position against its take-profit, 24 h exit
    and next skim, free slots, closed trades and the benchmark since the open. Cash, holdings and equity all come
    from one read of the unit's state.json, so a trade between reads cannot pair new cash with old holdings
    (the -15% that was not there, 2026-10-05 08:40 IST). DECISIONS.md#desk-revamp-2026-10-05"""
    import datetime as dt
    import json

    from bot.settings import ROOT
    if not ec2:
        return None
    bk = next((b for b in ec2["books"] if not b.get("paper") and b["bot"] != "competition_rehearsal"
               and b.get("active") == "active"), None)
    if not bk:
        return None
    now = dt.datetime.now(dt.UTC)
    ride = bk.get("ride") or {}
    held = ride.get("held") or {}
    mon = bk.get("monitor") or {}
    marks = {k.replace("USDT", ""): v.get("mark") for k, v in (mon.get("positions") or {}).items()}
    for r in radar.get("rows") or []:
        marks.setdefault(r["symbol"], r.get("price"))
    eq = bk.get("equity") or mon.get("equity")
    start = COMP_START_EQUITY
    hold = int(radar.get("hold_bars") or 288)
    slots = int(radar.get("slots") or 2)
    lots: dict[str, list[float]] = {}
    for lot in bk.get("open_lots") or []:
        q, c = float(lot.get("qty") or 0), float(lot.get("cost_basis") or 0)
        acc = lots.setdefault(lot["symbol"].replace("USDT", ""), [0.0, 0.0])
        acc[0] += q
        acc[1] += c
    pos = []
    for sym, rec in held.items():
        s = sym.replace("USDT", "")
        at = dt.datetime.fromisoformat(str(rec[0]).replace(" ", "T"))
        sig_px, tgt, wt = float(rec[1]), float(rec[2]), float(rec[3])
        qty = (bk.get("entries") or {}).get(s, {}).get("qty")
        if s in lots and lots[s][0] > 0:
            fill = lots[s][1] / lots[s][0]          # average cost over the open FIFO lots
        else:
            fill = (bk.get("entries") or {}).get(s, {}).get("entry") or sig_px
        mark = marks.get(s)
        tgt_px = sig_px * (1 + tgt)
        exit_at = at + dt.timedelta(minutes=BAR_MIN * (hold + 1))
        ref = (bk.get("skim_refs") or {}).get(sym)
        row = {"symbol": s, "qty": qty, "weight_now": (bk.get("positions") or {}).get(s), "slot_weight": wt,
               "entry_bar": at.isoformat(), "signal_px": sig_px, "fill_px": fill, "target_pct": round(tgt * 100, 2),
               "target_px": tgt_px, "exit_at": exit_at.isoformat(),
               "hours_left": round((exit_at - now).total_seconds() / 3600, 2),
               "held_h": round((now - at).total_seconds() / 3600, 2), "mark": mark,
               "next_skim_px": ref * 1.03 if ref else None}
        if mark:
            row.update({"pnl_pct": round((mark / fill - 1) * 100, 2),
                        "pnl_usd": round(qty * (mark - fill), 2) if qty else None,
                        "to_target_pct": round((tgt_px / mark - 1) * 100, 2),
                        "progress": round((mark - sig_px) / (tgt_px - sig_px), 3) if tgt_px > sig_px else None,
                        "to_skim_pct": round((ref * 1.03 / mark - 1) * 100, 2) if ref else None})
        pos.append(row)
    if not held:
        pos = rule_positions(bk, lots, marks, now)
        slots = int(bk.get("n_positions") or 3)
    pos.sort(key=lambda r: r["hours_left"] if r["hours_left"] is not None else 1e9)
    used = sum(r["slot_weight"] for r in pos)
    rows = radar.get("rows") or []
    btc = next((r for r in rows if r["symbol"] == "BTC"), {})
    opens = sorted(r["ret_open"] for r in rows if r.get("ret_open") is not None)
    closed = [{"symbol": t["symbol"].replace("USDT", ""), "entry_ts": t.get("entry_ts"), "exit_ts": t.get("exit_ts"),
               "entry": t.get("entry_price"), "exit": t.get("exit_price"), "qty": t.get("qty"),
               "net": round(float(t.get("net_pnl") or 0), 2), "ret_pct": round(float(t.get("net_return_pct") or 0), 2),
               "hold_h": t.get("hold_hours"), "kind": t.get("exit_kind")} for t in (bk.get("closed") or [])]
    closed.sort(key=lambda t: str(t["exit_ts"]), reverse=True)
    t0, t1 = dt.datetime.fromisoformat(COMP_OPEN), dt.datetime.fromisoformat(COMP_END)
    try:
        board = json.loads((ROOT / "run" / "leaderboard.json").read_text())
    except (OSError, ValueError):
        board = None
    return {"bot": bk["bot"], "since": bk.get("since"), "last_cycle": mon.get("ts_utc") or bk.get("last_cycle"),
            "cycle_age_s": mon.get("cycle_age_s"), "alerts": mon.get("alerts") or [],
            "equity": eq, "start": start, "ret_pct": round((eq / start - 1) * 100, 3) if eq else None,
            "net": round(eq - start, 2) if eq else None, "peak": mon.get("peak") or bk.get("peak"),
            "dd_pct": round((eq / (mon.get("peak") or bk.get("peak") or eq) - 1) * 100, 2) if eq else None,
            "cash": bk.get("cash") if bk.get("cash") is not None else mon.get("cash"),
            "bot_equity": bk.get("equity") or mon.get("equity"), "positions": pos, "slots": slots,
            "slots_free": max(0, int((1.0 - used + 1e-9) * slots)), "weight_used": round(used, 4),
            "series": bk.get("eq_series") or [], "closed": closed, "stats": bk.get("blotter") or {},
            "orders_today": mon.get("orders_today"), "faults_today": mon.get("faults_today"),
            "last_order": mon.get("last_order"), "orders": bk.get("orders") or [],
            "bench": {"btc_open": btc.get("ret_open"), "btc_24h": btc.get("ret_24h"),
                      "pool_median_open": opens[len(opens) // 2] if opens else None,
                      "pool_up": sum(1 for x in opens if x > 0), "pool_n": len(opens)},
            "clock": {"open": COMP_OPEN, "end": COMP_END, "elapsed_frac": round((now - t0) / (t1 - t0), 4),
                      "day": (now - t0).days + 1, "days": (t1 - t0).days,
                      "hours_left": round((t1 - now).total_seconds() / 3600, 1)},
            "leaderboard": board}


def payload(snap: dict) -> dict:
    by_name = {b["bot"]: b for b in snap["bots"]}
    shown = [b for b in snap["bots"] if group_of(b["bot"], (b.get("meta") or {}).get("interval")) in DESK_GROUPS]
    books = [book(b, by_name) for b in shown]
    from bot import ec2_feed, trigger_watch
    ec2 = ec2_feed.payload()
    radar = trigger_watch.payload()
    if ec2:
        on_ec2 = {b["bot"] for b in ec2["books"]}
        books = [b for b in books if b["group"] != "live" and b["bot"] not in on_ec2]
    prog = progress_by_book()
    for b in books:
        b["risk"] = (prog.get(b["bot"]) or {}).get("ratios_total")
        b["progress"] = prog.get(b["bot"]) or {}
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
            "closed": closed_feed(shown), "walkforward": {**walkforward(), **((ec2 or {}).get("wf") or {})},
            "breadth": snap.get("breadth"), "radar": radar, "competition": competition_view(ec2, radar),
            "ec2_progress": (ec2 or {}).get("progress") or {}}
