---
name: roostoo-incident
description: Triage and fix a live Roostoo bot fault - a halted or frozen book, liquidation, cancel or order errors, stale or late entries, inactive competition account, wallet or ticker errors, Binance rate limits, a bot not cycling, the Mac sleeping. Use when something in the live books looks wrong or a report shows breakage.
---

# Live incident playbook

Reproduce from the journals first (`live/<book>/{cycles,orders,signals,errors,lifecycle}-<date>.jsonl`), then fix the root cause with a test, commit, push, restart.

## Symptom -> where to look -> known cause

| symptom | look at | known cause and anchor |
|---|---|---|
| book sold everything mid-bar | `cycles` rows with `halt: true` and `breaches` | drawdown kill, the only liquidating breach; anything else should freeze (`#live-faults-2026-10-01`) |
| `freeze: true` for many cycles | `breaches`: error_rate, stale_ticker, mirror | venue errors over the last 40 calls, a ticker older than the limit, a held coin unpriced or diverging from Binance |
| `cancel_error` in orders | error text | Roostoo takes `order_id` OR `pair`, never both (`#cancel-both-args-2026-10-01`) |
| a coin bought one bar after `stale_entry_blocked` | signals then orders for the symbol | fixed: the guard runs every decision (`#stale-rebuy-2026-10-01`); if seen again, the book runs old code |
| `submission_unknown`, then nothing trades | orders, lifecycle `submission_unblocked` | ambiguous submit; reconciles every cycle, process exits after 10 failures |
| `wallet_unavailable` on `competition` | `waiting-<date>.jsonl` | account not activated by Roostoo; only the organisers can fix it |
| `binance 418/429` | errors | rate limit; never run heavy fetches beside the fleet or within 90 s of a bar close (`#binance-rate-guard-2026-09-27`) |
| no new `cycles` rows | `pmset -g log`, `live/<book>.out` | Mac asleep or on battery; `exited code=` in `.out` is a crash, the supervisor respawns in 10 s |
| `config_changed_mid_run` | errors | expected after a config edit plus restart |

## Restart rules

- Paper set: `./run_bots.sh restart`. Live pair: `./run_bots.sh livestop && ./run_bots.sh live`. One book: `CONFIGS="config/<book>.yaml" ./run_bots.sh stop|start`.
- Never within ~20 s after a 5-minute mark (bots are deciding). Positions persist across restarts; the first decision after a start blocks stale entries by design.
- Code is loaded only at process start: a committed fix is not live until the book restarts. Check the new fields (for example `freeze`) appear in the next `cycles` row.
- NEVER run `competition` on two hosts (Mac and EC2) at once.

## What needs the operator

- Any change to the competition book's rule, sizing or real-money execution (the Claude Code auto-mode classifier also blocks these; ask the operator to leave auto mode or apply it).
- Contacting Roostoo or the organisers, AWS access, physical power.
- Record every incident and fix as a `DECISIONS.md` section; one sentence per line, no em dash.
