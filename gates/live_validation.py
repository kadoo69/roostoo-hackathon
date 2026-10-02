"""Every deployed book, validated on the live bar against live Binance and Roostoo public data.

No orders are submitted. The path is the one `Bot.cycle` runs - universe select,
closed bars, channel state machine, rank and select, target weights, order
planning through `Executor.prepare` - so this checks the live code rather than
a reimplementation of it. Each book is additionally checked against the
vectorised backtest on the same bars: the channel rule cell by cell and, for
ranked books, the momentum rank that `gates.concentration.rank_score` computes.

Until 2026-09-23 this gate read the deleted `config/bot_a_4h.yaml`, never
applied the rank, and probed a `RuntimeError` guard that `bot/intents.py`
replaced; it could not run at all. DECISIONS.md#live-validation-2026-09-23.

The mirror check re-reads the Roostoo ticker immediately before comparing it
with Binance. Its first version reused the quotes taken before nine books were
validated, minutes earlier, and reported an 18 bps median deviation that did
not exist; the live figure at the same moment was 0.0 bps.

A target the venue rule refuses is a failure, not a note: the backtest holds it
and the book idles its slot. ARB passed this gate while 12 books refused it.
DECISIONS.md#execution-gaps-2026-09-23.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np

from bot import feed, portfolio, risk, universe, verify
from bot.execution import Executor
from bot.settings import ROOT, load
from bot.strategy import (REGIME_SYMBOL, REPLAY_BARS, replay_book, replay_short_book,
                          short_bars_needed, short_regime)
from gates.concentration import rank_score
from venue.roostoo import RoostooClient

BOOKS = ("donchian_4h", "momentum_top3_full", "momentum_top3_lock", "testnet_live",
         "competition", "competition_rehearsal", "scalper_adaptive", "wf_live", "hedge_explorer",
         "momentum_top3_30m", "momentum_top3_15m", "momentum_top3_5m",
         "momentum_top3_1h_allcash", "momentum_top3_30m_allcash",
         "accel_15m", "burst_5m", "burst_15m", "burst_strong_15m", "momentum_top3_15m_eq", "short_accel_15m",
         "momentum_top3_15m_hold3h", "momentum_top3_5m_hold2h", "short_pullback_15m", "momentum_top3_15m_slowexit",
         "ride_5m", "blend_30m_ride", "regime_ls_30m", "resid_30m", "htf0_30m", "ride1_5m",
         "wide_30m", "ride1_wide_5m", "sleeves_5m", "sleeves_ivol_5m", "ride_z3_5m", "sleeves_z3_5m")
EQUITY = 100_000.0


def rank_parity(matrix, settings, channels) -> dict:
    """The live rank against the backtest's rank_score on the identical bars."""
    if not settings.n_positions or settings.ranking_rule != "momentum":
        return {"applies": False}
    held = [s for s, c in channels.items() if c.held]
    ref = rank_score("momentum", matrix, None, None, settings.momentum_bars).iloc[-1]
    ref = ref[[s for s in held if s in ref.index]].dropna()
    want = list(ref.sort_values(ascending=False).index[: settings.n_positions])
    got, info = portfolio.rank_and_select(channels, matrix, settings)
    return {"applies": True, "fired": len(held), "backtest_top": want,
            "live_top": list(got), "match": sorted(want) == sorted(got),
            "scores": info.get("scores", {})}


def short_parity(matrix, settings, channels, selected, btc) -> dict:
    """The live short pick against gates.short_paper_books.sleeve on the identical bars."""
    if not settings.shorts_enabled:
        return {"applies": False, "pick": []}
    from gates.short_paper_books import sleeve
    from signals import donchian
    regime = short_regime(btc, settings, matrix)
    pick, info = portfolio.select_shorts(replay_short_book(matrix, settings), channels,
                                         len(selected), matrix, settings, regime["on"])
    cfg = settings.short
    brk = donchian.breakdown_position(matrix, int(cfg["entry_bars"]), int(cfg["exit_bars"]))
    live = (donchian.position(matrix, settings.entry_bars, "lowchannel", settings.exit_bars) > 0.5)
    longs = live.copy() * False
    longs.loc[longs.index[-1], list(selected)] = True
    mom = matrix / matrix.shift(settings.momentum_bars) - 1.0
    if cfg.get("regime") == "breadth_below":
        flag = donchian.breadth_short_regime(matrix, int(cfg.get("momentum_bars", settings.momentum_bars)),
                                             float(cfg["breadth_max"]))
    else:
        flag = donchian.bear_regime(btc.reindex(matrix.index), int(cfg["regime_bars"]))
    slots = int(cfg.get("slots") or settings.n_positions or settings.weight_divisor)
    ref = sleeve(flag, brk, live, longs.astype(bool), mom, slots, bool(cfg.get("own_slots")),
                 bool(cfg.get("require_negative_momentum"))).iloc[-1]
    want = sorted(ref[ref].index)
    return {"applies": True, "regime": regime, "backtest_pick": want, "live_pick": sorted(pick),
            "match": want == sorted(pick), "info": info, "pick": pick}


def validate(name: str, client, specs, quotes, selection_cache: dict) -> dict:
    s = load(ROOT / "config" / f"{name}.yaml")
    key = s.top_n_pool
    if key not in selection_cache:
        selection_cache[key] = universe.select(s, specs)["selected"]
    symbols = selection_cache[key]
    need = max(s.entry_bars, s.exit_bars) + 5
    frames = feed.bar_frame(symbols, s.interval, max(need + 20, REPLAY_BARS, short_bars_needed(s)))
    matrix = feed.close_matrix(frames)
    parity = verify.signal_parity(matrix, s)
    channels = replay_book(matrix, s)
    rp = rank_parity(matrix, s, channels)
    selected, _ = portfolio.rank_and_select(channels, matrix, s)
    btc = (matrix[REGIME_SYMBOL] if REGIME_SYMBOL in matrix.columns else feed.close_matrix(
        feed.bar_frame([REGIME_SYMBOL], s.interval, short_bars_needed(s))).get(REGIME_SYMBOL))
    sp = short_parity(matrix, s, channels, selected, btc) if s.shorts_enabled else {"applies": False, "pick": []}
    targets = portfolio.target_weights(selected, s, shorts=sp["pick"])
    by_symbol = {spec.binance_symbol: spec for spec in specs.values()}
    prices = {sym: float(quotes[by_symbol[sym].pair]["LastPrice"]) for sym in targets
              if sym in by_symbol and by_symbol[sym].pair in quotes}
    executor = Executor(client, specs, s, None)
    plans = []
    for order in portfolio.deltas(targets, {}, EQUITY, prices):
        plan = executor.prepare(order, quotes)
        if plan is None:
            continue
        row = dict(plan)
        if not row.get("skipped"):
            q = quotes[row["pair"]]
            bid, ask = float(q["MaxBid"]), float(q["MinAsk"])
            row["marketable"] = (False if row["type"] == "MARKET" else
                                 row["price"] >= ask if row["side"] == "BUY" else row["price"] <= bid)
            row["spread_bps"] = round((ask / bid - 1.0) * 1e4, 3)
            spec = by_symbol[row["symbol"]]
            row["qty_on_step"] = spec.round_qty(row["quantity"]) == row["quantity"]
        plans.append(row)
    live = [r for r in plans if not r.get("skipped")]
    checks = {
        "all_selected_symbols_have_bars": len(frames) == len(symbols),
        "bar_is_closed": bool(len(matrix)) and (
            matrix.index[-1] + (matrix.index[-1] - matrix.index[-2]) <= dt.datetime.now(dt.timezone.utc)),
        "signal_parity_exact": parity.get("mismatches") == 0,
        "rank_matches_backtest": (not rp["applies"]) or rp["match"],
        "short_pick_matches_backtest": (not sp["applies"]) or sp["match"],
        "gross_within_cap": sum(abs(w) for w in targets.values()) <= s.max_gross + 1e-9,
        "no_marketable_limits": all(not r["marketable"] for r in live),
        "spread_gate_holds": all(r["spread_bps"] <= s.max_spread_bps or r["wide_tick"] for r in live),
        "quantities_on_venue_step": all(r["qty_on_step"] for r in live),
        "notional_within_equity": sum(abs(r["notional"]) for r in live) <= EQUITY,
        "no_target_refused_by_venue_rule": not any(
            r.get("skipped") in ("spread_exceeds_limit", "pair_not_tradable") for r in plans),
    }
    return {"book": name, "interval": s.interval, "bar": matrix.index[-1].isoformat() if len(matrix) else None,
            "config_sha": s.config_sha256, "universe": len(symbols), "fired": sum(c.held for c in channels.values()),
            "targets": {k: round(v, 4) for k, v in targets.items()}, "target_gross": round(sum(targets.values()), 4),
            "orders_planned": len(live), "skipped": [f"{r['symbol']}:{r['skipped']}" for r in plans if r.get("skipped")],
            "signal_parity": parity, "rank_parity": rp,
            "short_parity": {k: v for k, v in sp.items() if k != "pick"},
            "checks": checks, "pass": all(checks.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="*", default=list(BOOKS))
    a = ap.parse_args()
    client = RoostooClient()
    offset = client.sync_time()
    specs = client.exchange_info()
    quotes = feed.roostoo_quotes(client)
    cache: dict = {}
    books = [validate(b, client, specs, quotes, cache) for b in a.books]
    symbols = sorted(set().union(*cache.values()))
    quotes = feed.roostoo_quotes(client)
    ticker_age = max(0.0, (client._timestamp() - client.last_ticker_server_time_ms) / 1000)
    mirror = feed.mirror_check(quotes, specs, symbols)
    material = [abs(m["deviation_bps"]) for m in mirror if m["material"]]
    s0 = load(ROOT / "config" / "donchian_4h.yaml")
    gate = risk.gate([EQUITY], 0.0, ticker_age, max(material, default=0.0), s0)
    market = {
        "ticker_age_s": round(ticker_age, 3),
        "ticker_fresh": ticker_age < s0.kill_stale_ticker_s,
        "mirror_checked": len(mirror), "mirror_symbols": len(symbols),
        "mirror_abs_median_bps": round(float(np.median([abs(m["deviation_bps"]) for m in mirror])), 3) if mirror else None,
        "mirror_material_count": len(material),
        "mirror_material_max_bps": round(max(material, default=0.0), 3),
        "risk_gate_clear": not (gate["halt"] or gate["freeze"]),
    }
    ok = all(b["pass"] for b in books) and market["ticker_fresh"] and market["risk_gate_clear"]
    report = {"written_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "PASS" if ok else "FAIL", "orders_submitted": 0,
              "server_offset_ms": offset, "venue_pairs": len(specs), "market": market, "books": books}
    (ROOT / "results" / "live_validation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    lines = ["# Live public-data validation", "", f"**{report['status']}** at {report['written_utc']}. No orders were submitted.", "",
             f"Roostoo ticker age {market['ticker_age_s']}s; mirror median {market['mirror_abs_median_bps']} bps over {market['mirror_checked']} names, "
             f"{market['mirror_material_count']} material deviations.", "",
             "| book | bar | universe | fired | held | gross | orders | parity | rank | pass |", "|---|---|---|---|---|---|---|---|---|---|"]
    for b in books:
        rp = b["rank_parity"]
        lines.append(f"| {b['book']} | {b['bar']} | {b['universe']} | {b['fired']} | {len(b['targets'])} | {b['target_gross']} | "
                     f"{b['orders_planned']} | {b['signal_parity'].get('mismatches')}/{b['signal_parity'].get('checked')} | "
                     f"{'n/a' if not rp['applies'] else ('match' if rp['match'] else 'MISMATCH')} | {'PASS' if b['pass'] else 'FAIL'} |")
    fails = [(b["book"], k) for b in books for k, v in b["checks"].items() if not v]
    lines += ["", "Failed checks: " + (", ".join(f"{b}:{k}" for b, k in fails) if fails else "none"), ""]
    (ROOT / "results" / "live_validation.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
