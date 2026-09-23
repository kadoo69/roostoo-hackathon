---
name: roostoo-ops
description: Operate the Roostoo bot fleet - start/stop/restart, keep-awake, live validation against the backtest, log review, dashboard, reading errors. Use when running, checking, restarting, resetting or diagnosing the bots.
---

# Operating the fleet

Run everything from the repo root. Read `docs/ANTIPATTERNS.md` before editing `bot/run.py` or `run_bots.sh`.

## Commands

    ./run_bots.sh start | stop | restart | status     # the CONFIGS books (bot.run)
    ./run_bots.sh alphaflow | alphaflowstop           # alpha_flow + alt-data collector
    ./run_bots.sh scalper | scalperstop               # scalper_live
    ./run_bots.sh testnet | testnetstop               # REAL orders on Binance testnet
    ./run_bots.sh awake | awakestop                   # supervised caffeinate; needs mains power
    ./run_bots.sh dashboard                           # http://127.0.0.1:8787, foreground
    python3 -m gates.live_validation [book ...]       # every book vs the backtest on the live bar, no orders
    python3 -m gates.log_review [journal_root]        # P&L, benchmarks, uptime, booking, attribution

## Checks that mean something

- **Liveness**: each book's last line in `live/<book>/cycles-*.jsonl` should be under ~90s old (`ts_utc`). `status` only proves the process exists.
- **Errors**: the dashboard's grey "net" tag is a dropped connection retried next cycle, harmless. A red "err" tag is a non-network error: read `live/<book>/errors-*.jsonl`.
- **Crash vs restart**: only `exited code=` in `live/<book>.out` is a crash; `resumed` in lifecycle is any restart or probe.
- **Parity**: `gates.live_validation` must show 0 mismatches and rank `match`. Run it before any restart that matters.
- **Uptime**: `pmset -g log` shows sleeps; every sleep is a missed bar close.

## Rules

- Restart the whole stack together, never one book mid-bar (cold start chases the bar).
- A reset archives `live/<book>/` to `live/_archive/<tag>/`; never delete journals.
- Journal keys: timestamps are `ts_utc`; orders use `event` in `dry_run|skipped|placed`, `skipped` carries the reason.
- The terminal output filter can mangle piped `curl` JSON; save with `curl -o` before parsing.
