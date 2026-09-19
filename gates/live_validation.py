from __future__ import annotations

from dataclasses import replace
import datetime as dt
import json
from pathlib import Path

import numpy as np

from bot import feed, portfolio, risk, universe, verify
from bot.execution import Executor
from bot.run import Bot
from bot.settings import ROOT, load
from bot.strategy import evaluate_book
from venue.roostoo import RoostooClient


def main() -> int:
    settings = load(ROOT / "config" / "bot_a_4h.yaml")
    client = RoostooClient()
    offset = client.sync_time()
    specs = client.exchange_info()
    selection = universe.select(settings, specs)
    symbols = selection["selected"]
    need = max(settings.entry_bars, settings.exit_bars) + 25
    frames = feed.bar_frame(symbols, settings.interval, need)
    matrix = feed.close_matrix(frames)
    quotes = feed.roostoo_quotes(client)
    ticker_age = max(0.0, (client._timestamp() - client.last_ticker_server_time_ms) / 1000)
    parity = verify.signal_parity(matrix, settings)
    channels = evaluate_book(matrix, {}, settings)
    targets = portfolio.target_weights(channels, settings)
    mirror = feed.mirror_check(quotes, specs, symbols)
    mirror_abs = [abs(row["deviation_bps"]) for row in mirror]
    executor = Executor(client, specs, settings, None)
    by_symbol = {spec.binance_symbol: spec for spec in specs.values()}
    plans = []
    for order in portfolio.deltas(targets, {}, 100_000.0,
                                  {s: float(quotes[by_symbol[s].pair]["LastPrice"])
                                   for s in targets}):
        plan = executor.prepare(order, quotes)
        if plan is None:
            continue
        row = dict(plan)
        if not row.get("skipped"):
            quote = quotes[row["pair"]]
            bid, ask = float(quote["MaxBid"]), float(quote["MinAsk"])
            row["marketable"] = (row["price"] >= ask if row["side"] == "BUY"
                                 else row["price"] <= bid)
            row["spread_bps"] = round((ask / bid - 1.0) * 1e4, 4)
        plans.append(row)
    executable = [row for row in plans if not row.get("skipped")]
    gate = risk.gate([100_000.0], 0.0, ticker_age,
                     max(mirror_abs, default=float("inf")), settings)
    try:
        Bot(replace(settings, dry_run=False))
        real_order_block = False
    except RuntimeError as exc:
        real_order_block = "restart_reconciliation" in str(exc)
    checks = {
        "all_selected_symbols_have_bars": len(frames) == len(symbols),
        "signal_parity_exact": parity.get("mismatches") == 0,
        "gross_exposure_within_one": sum(targets.values()) <= settings.max_gross,
        "full_mirror_coverage": len(mirror) == len(symbols),
        "mirror_within_50bps": max(mirror_abs, default=float("inf")) < settings.mirror_max_deviation_bps,
        "ticker_fresh": ticker_age < settings.kill_stale_ticker_s,
        "risk_gate_clear": not gate["halt"],
        "spread_limit_enforced": all(row.get("spread_bps", 0.0) <= settings.max_spread_bps
                                     for row in executable),
        "all_limit_orders_passive": all(not row["marketable"] for row in executable),
        "gross_order_notional_within_cash": sum(row["notional"] for row in executable) <= 100_000.0,
        "authenticated_orders_safety_block_active": real_order_block,
    }
    g4 = json.loads((ROOT / "results" / "g4_deflated_sharpe.json").read_text())
    counts = g4["result"]["report"]["homogeneous_42"]["counts"]
    full_count_key = max(counts, key=lambda key: int(key.split("_")[1]))
    trial_count = int(full_count_key.split("_")[1])
    dsr = counts[full_count_key]["donchian_4h_roostoo_top30"]["dsr"]
    report = {
        "written_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "DRY_RUN_PASS_LIVE_DEPLOYMENT_BLOCKED" if all(checks.values()) else "DRY_RUN_FAIL",
        "orders_submitted": 0,
        "config_sha": settings.config_sha256,
        "server_offset_ms": offset,
        "bar": matrix.index[-1].isoformat(),
        "venue_pairs": len(specs),
        "selected_symbols": len(symbols),
        "long_signals": len(targets),
        "target_gross": round(sum(targets.values()), 6),
        "ticker_age_s": round(ticker_age, 3),
        "mirror_checked": len(mirror),
        "mirror_abs_median_bps": round(float(np.median(mirror_abs)), 3),
        "mirror_abs_max_bps": round(max(mirror_abs), 3),
        "signal_parity": parity,
        "proposed_orders": plans,
        "checks": checks,
        "deployment_blocks": {
            "restart_safe_local_portfolio_state": True,
            "restart_safe_pending_order_intent_reconciliation": False,
            "authenticated_fill_role_and_commission_observed": False,
            "deflated_sharpe_gate_0_95": dsr >= 0.95,
        },
        "deflated_sharpe_trial_count": trial_count,
        "deflated_sharpe_probability": dsr,
    }
    path = ROOT / "results" / "live_validation.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Live public-data validation",
        "",
        f"**{report['status']}**. No orders were submitted.",
        "",
        f"Validated the completed `{settings.interval}` bar at `{report['bar']}` using live Binance and Roostoo public endpoints.",
        "",
        f"- Venue pairs: {report['venue_pairs']}; selected liquid intersection: {report['selected_symbols']}.",
        f"- Long signals: {report['long_signals']}; target gross exposure: {report['target_gross']:.1%}.",
        f"- Signal parity: {parity['mismatches']} mismatches across {parity['checked']} cells.",
        f"- Binance–Roostoo absolute deviation: median {report['mirror_abs_median_bps']:.3f} bps, maximum {report['mirror_abs_max_bps']:.3f} bps.",
        f"- Roostoo ticker age: {report['ticker_age_s']:.3f} seconds.",
        f"- Proposed limit orders: {len(executable)}; marketable limits: {sum(row['marketable'] for row in executable)}.",
        "",
        "## Public-data and dry-run checks",
        "",
    ]
    lines += [f"- {name}: {'PASS' if value else 'FAIL'}" for name, value in checks.items()]
    lines += [
        "",
        "## Deployment blocks",
        "",
        "- Local holdings and cash survive a restart, but pending-order intents are not adopted before new orders are planned: FAIL.",
        "- Authenticated maker/taker role and commission observation: FAIL.",
        f"- Deflated Sharpe at {trial_count} trials: {dsr:.4f}, below the frozen 0.95 gate: FAIL.",
        "",
        "Authenticated order submission is blocked in code until reconciliation is implemented. This report validates the public market-data, signal, risk and order-planning path only.",
        "",
    ]
    (ROOT / "results" / "live_validation.md").write_text("\n".join(lines))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
