# CLAUDE.md - Roostoo Competition Bot

Lean on purpose: loaded into every agent session. Detail lives in the files it points to; read them only when the task needs them.

## What this is

Trading bots for the Roostoo crypto competition. **The competition starts 2026-10-03 12:00Z (20:00 HKT, operator 2026-10-02)** and runs to 10-17 per the slides; repo link due before 10-14 (`DECISIONS.md#comp-key-bot-only-2026-10-02`). Competition account = 100k per the slides (TEST account 50k), fees measured 0.10% taker / 0.05% maker.
**Screen 2** ranks raw 14-day return, top 20 per region advance. **Screen 3** ranks survivors on `0.4*Sortino + 0.3*Sharpe + 0.3*Calmar`. **Screen 1** is rule and trade-log compliance.
Rules (FAQ): 30 API calls/min all endpoints, EC2 Sydney via Session Manager, public GitHub repo, every live change committed, **no manual stop, override or trade on the competition account**.

**Live since 2026-09-30, on EC2 `i-015fad70d34b0b83d` since 2026-10-02 12:36Z:** `competition` (the `momentum_top3_30m` rule, lock off, COMP keys; waiting for Roostoo to activate the account) and `competition_rehearsal` (since 2026-10-02 16:40Z the 50/50 rule + ride sleeves of `sleeves_5m`, TEST keys, `#sleeves-rehearsal-2026-10-02`) place REAL Roostoo orders via `./run_bots.sh live`; keys in `.env` as `ROOSTOO_{TEST,COMP}_*`, picked by each config's `meta.keyset`. Units start `bot.runner`, which picks the bot class from the config. Paper books on EC2 and on the Mac: `BOTS.md`. Deploy: `deploy/ec2_bootstrap.sh`; checks: `python3 -m gates.preflight`, `gates.progress`. **Read HANDOVER.md "CURRENT STATE" first.**
Never run the `competition` book on two hosts at once (Mac and EC2 would both trade one account). Never buy a stale path entry after a restart (`bot/entry_guard.py`).

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
| re-running a finished study | `archive/README.md` (`python3 -m archive.gates.<name>`) |

Skills: `roostoo-live-report` (the 30-minute report), `roostoo-incident` (live faults and restarts), `roostoo-ops` (run, add, retire, deploy books) and `roostoo-research` (declare, test on history and the recent window, record).

## Hard rules

- **No comments in code.** Reasoning lives in `DECISIONS.md`; docstrings cite anchors. `tests/test_doc_anchors.py` fails on a citation that does not resolve.
- **Declare before you test**: a `config/<family>.yaml` with mechanism, failure mode, decision rule and nonsense control, written before any number is computed. Every configuration is a trial in `config/trials.yaml` (`core.config.record_trials`), nulls included.
- **Pre-registered thresholds are never moved** to make something pass.
- **Nothing is promoted on a backtest alone**: survivors paper-trade on the live feed first.
- **Registering a bot**: see `BOTS.md` "Registering a book" (host list, `bot/dashboard.py` BOTS/CONTROL_OF/EXPECTED_DRAG, `gates/live_validation.py` BOOKS, `bot/desk.py`).
- **Binance bars are labelled by OPEN time.** Join on close times (`signals.exit_clock.to_fast`), never on labels.
- Markdown: one sentence per line, never the em dash. Commits describe only what they contain, no co-author trailer.
- Checks before done: `python3 -m pytest tests -q` and `python3 -m ruff check bot/ signals/ gates/ data/ core/ tests/ archive/`.
- **Nothing live imports `archive/`.** A one-off study moves to `archive/gates/` once its outcome is in `DECISIONS.md`.

## Competition lessons (2026-10-04, first day live)

- Execution bugs cost more than strategy choices: a cash-capped entry could never be completed (`#underfilled-entry-2026-10-04`); test any same-cycle sell-then-buy path end to end.
- An entry completed in a later cycle pays the later price: PUMP's trigger bought 4.4k at 0.006492 and the completion bought 29.4k at 0.006636 thirty minutes later (+2.2%), while the take-profit stays anchored to the trigger close; PUMP was most of the 10-04 night drawdown.
- A day-one rank is noise: Screen 2 is the top 20 on 14-day raw return, and one coin moves a book several places; do not change the rule to chase rank.
- Every competition unit switch costs the first bar's trigger (cold-start guard) and resets state; switch only with a committed reason, never to chase a single move.
- Exit tuning is exhausted on the ride (trails, locks, shorter holds, rotation, nearer targets all null on 10-04); the edge is the entry trigger and staying fully invested.
- Hand-placed orders on the COMP keys are banned (FAQ Q28); a "probe" entry in code was borderline, do not repeat it.
- The Mac `aws` CLI is broken (Homebrew Python 3.14 pyexpat); use `bot.ec2_session.run_script`, and renew SSO with `deploy/aws_login.py`.
