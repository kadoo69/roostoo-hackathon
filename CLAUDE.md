# CLAUDE.md - Roostoo Competition Bot

Lean on purpose: loaded into every agent session. Detail lives in the files it points to; read them only when the task needs them.

## What this is

Trading bots for the Roostoo crypto competition: live window **2026-10-04 to 2026-10-17**, 100,000 USD paper capital (the venue's exchangeInfo says 50,000 - unconfirmed), 1x, spot long plus venue shorts.
**Screen 2** ranks raw 14-day return, top 20 per region advance. **Screen 3** ranks survivors on `0.4*Sortino + 0.3*Sharpe + 0.3*Calmar`. **Screen 1** is rule and trade-log compliance.
Past Roostoo events: top three finished +20.5%, +8.1%, +5.7%, so qualifying needs roughly a positive fortnight and winning roughly +17 to 20%.

Signals come from Binance klines (Roostoo mirrors Binance at ~0 bps); orders go to Roostoo. **Roostoo API keys are not issued yet**, so every Roostoo book runs in dry run; `testnet_live` places real orders on Binance testnet.

## The strategy

Donchian channel on 4h bars: enter when the close exceeds the prior 20-bar high, exit below the prior 10-bar low. Universe = top 30 by 30-day median dollar volume across ALL Binance USDT pairs, intersected with Roostoo listings, refreshed daily.
Deployed variants: `donchian_4h` (1/20 per name) and `momentum_top3_full` (40-bar momentum rank, top 3, fully deployed). Every book runs the booking ladder (sell 15% each +3%, cash idles).
Channel state is replayed from 150 bars at every close (`bot/strategy.replay_book`). A one-tick quote is always tradeable (PEPE and other wide-tick coins carry most of the ranked book's edge).
The only tested change that passed every period is the **target lock** (`bot/lock.py`: once the fortnight is up 5%, hold at most 0.3 gross); it trades the chance of winning for the chance of qualifying and is an operator decision.

## Where things are

| read when | file |
|---|---|
| operating or changing bots | `BOTS.md` - fleet, parameters, how to run, the two subclass hooks |
| touching any data | `DATA_SOURCES.md` - history depth, stamping gotchas |
| deciding what to research | `FINDINGS.md` - what is true, what is dead (do not re-test dead families) |
| evidence for any claim | `DECISIONS.md#<anchor>` - authoritative, ~3,000 lines, search by anchor, never read whole |
| editing the live cycle, a join, a harness or `run_bots.sh` | `docs/ANTIPATTERNS.md` |
| current state and next steps | `HANDOVER.md` |
| questions only the organisers can answer | `ORGANISER_QUESTIONS.md` |

Skills: `roostoo-ops` (run, validate, review the fleet) and `roostoo-research` (declare, test, record a new idea).

## Hard rules

- **No comments in code.** Reasoning lives in `DECISIONS.md`; docstrings cite anchors. `tests/test_doc_anchors.py` fails on a citation that does not resolve.
- **Declare before you test**: a `config/<family>.yaml` with mechanism, failure mode, decision rule and nonsense control, written before any number is computed. Every configuration is a trial in `config/trials.yaml` (`core.config.record_trials`), nulls included.
- **Pre-registered thresholds are never moved** to make something pass.
- **Nothing is promoted on a backtest alone**: survivors paper-trade on the live feed first.
- **Registering a bot takes three places**: `run_bots.sh` CONFIGS, `bot/dashboard.py` BOTS (and EXPECTED_DRAG), `gates/live_validation.py` BOOKS.
- **Binance bars are labelled by OPEN time.** Join on close times (`signals.exit_clock.to_fast`), never on labels.
- Markdown: one sentence per line, never the em dash. Commits describe only what they contain, no co-author trailer.
- Checks before done: `python3 -m pytest tests -q` and `python3 -m ruff check bot/ signals/ gates/ data/ core/ tests/`.
