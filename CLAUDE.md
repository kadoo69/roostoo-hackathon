# CLAUDE.md — Roostoo Competition Bot

Read this first, then `BOTS.md` for what is running and `DATA_SOURCES.md` before touching data.
`FINDINGS.md` indexes the evidence; `STRATEGY.md` is the strategy written up for a reader.
`DECISIONS.md` is the authoritative record: every non-obvious choice is anchored there with its reasoning and its evidence, and the code carries no comments by design.

---

## What this project is

A trading bot for the Roostoo crypto competition.
Live window is 2026-10-04 to 2026-10-17, fourteen days, 100,000 USD of paper capital, 1x only, directional strategies only.

Scoring runs two gates in sequence.
**Screen 2** ranks on raw return and advances the top 20 per region, so it is a hard qualification cut.
**Screen 3** then ranks survivors on `0.4*Sortino + 0.3*Sharpe + 0.3*Calmar`.
**Screen 1** is a compliance check on rule adherence, trade-log integrity and commit-history consistency, and failing it makes the other two irrelevant.

The repository is a research pipeline and a live bot in one.
Research is gated by a pre-registration at `config/preregistration.yaml` whose thresholds are frozen; the live bot is under `bot/`.

---

## The strategy in one paragraph

A Donchian channel breakout on 4h bars, long only, on the most liquid venue names.
Enter when the close exceeds the highest close of the prior 20 bars.
Exit when the close falls below the lowest close of the prior 10 bars.
Each position is one twentieth of equity, the remainder is cash, and gross exposure is hard-capped at 1.0.
The universe is the top 30 names by 30-day median dollar volume across the whole Binance USDT market, intersected with what Roostoo lists, refreshed daily.

Selected configuration is `donchian_4h`. `donchian_1h` is the same rule at 1h and exists as a comparison, not a candidate.
These were named `bot_a_4h` and `bot_b_1h` until the 2026-09 rename. Nothing by the old names exists any more, and `config/paper_lab_v2.yaml` is a frozen declaration that still points at the deleted `config/bot_a_4h.yaml`, so it can never be re-run.

---

## The three findings that shaped everything

**1. The edge is in the universe rule, not the signal.**
Ranking by liquidity inside Roostoo's own 66 listings scores an out-of-sample Sharpe of -0.15.
Ranking the full 264-name survivorship-free Binance universe and trading the listed intersection scores 1.56 with the identical signal.
A rank cut inside an already-filtered list admits the venue's thinnest names. The bar must be absolute.
Separately, coin-level performance has **zero persistence** (Spearman -0.018, p=0.91 between periods), and picking historical winners was worse than picking historical losers.
See `DECISIONS.md#roostoo-universe-pool-size` and `#roostoo-coin-selection-does-not-persist`.

**2. The two screens are collinear at 14 days, not merely in tension.**
Within a fortnight the Screen 3 composite is governed by the sign of the window's return, which is governed by BTC beta.
Anything that cuts beta cuts P(positive), P(qualifying) and the composite together.
Measured across a core/sleeve range and again across position sizing, the composite rises monotonically as qualification probability falls, with no interior point where both improve.
This refutes the original plan's claim that asymmetry serves both screens.
See `DECISIONS.md#beta-is-the-only-screen3-lever`.

**3. Nothing here passes Gate 4 at an honest trial count.**
The ledger stands at 413 trials. The Deflated Sharpe hurdle is a function of how many configurations were searched.
The selected strategy scores DSR 0.8687 against a pre-registered 0.95 threshold.
It is the first candidate whose Sharpe exceeds the null's expected maximum, so its minimum track record length is finite (2,927 observations, about 8 years) rather than infinite as every predecessor's was.
The claim is unproven, not refuted, and the submission must say so.
See `DECISIONS.md#gate4-rerun-outcome`.

---

## Repo layout

| Path | What it holds |
|---|---|
| `BOTS.md` | The fleet: every bot, its parameters, the booking ladder, how to run them, and the two subclass hooks that have drawn blood. |
| `DATA_SOURCES.md` | Every data source, its history depth, cache path and gotcha. Read before touching data: the `history` column decides what can be backtested at all. |
| `FINDINGS.md` | Index into `DECISIONS.md`'s 150 anchors: what is true, what is dead, what is settled, what is open. |
| `config/preregistration.yaml` | Frozen thresholds for every gate. Amending it invalidates all prior gate artifacts. |
| `config/trials.yaml` | Append-only trial ledger. Every configuration ever evaluated, including nulls and abandoned searches. |
| `config/donchian_4h.yaml` | The selected live configuration. `meta.frozen: true` or it will not load. |
| `config/donchian_1h.yaml` | 1h comparison bot. |
| `DECISIONS.md` | Authoritative reasoning log, anchor-linked from configs and commits. |
| `STRATEGY.md` | The strategy written up for a reader, including the gate scorecard and what it has not established. |
| `signals/donchian.py` | The channel rule, vectorised, used for backtesting. |
| `bot/strategy.py` | The same rule as a live incremental state machine. |
| `bot/` | Live bot: settings, feed, universe, strategy, portfolio, execution, risk, state, journal, verify, blotter, insights, dashboard, status, run. |
| `gates/` | Validation gates and research runs. |
| `results/` | Gate artifacts and backtest outputs, committed. |
| `deploy/` | systemd unit for EC2, launchd plist for macOS, and operating instructions. |
| `live/` | Journals, state, snapshots. Gitignored. |
| `data/cache/` | 1.7 GB of Binance klines. Gitignored. Rebuild with `python3 -m data.bootstrap 1h`. |

---

## How the live bot works

**Market data comes from Binance, execution goes to Roostoo.**
Roostoo publishes no historical endpoint, so a self-sourcing bot would need 20 bars of warm-up out of a fourteen-day window.
Roostoo mirrors Binance almost exactly, so signals are computed from Binance klines and orders are placed on Roostoo.
The mirror is measured every cycle, not assumed. Median deviation runs about 4 to 5 bps.

**Each cycle** refreshes the universe if stale, fetches bars, evaluates the channel state, computes target weights, diffs against current holdings, and places orders only when a new bar has closed or a halt fires.
State persists atomically to `live/<bot>/state.json` after every cycle. On restart it is restored, and outside dry run the venue wallet is read and adopted as authoritative where the two disagree.

**Execution** is limit-first at or inside the touch, never crossing. `Executor.limit_price` clamps a buy to `ask - tick` and a sell to `bid + tick`.
Unfilled orders are cancelled after 15 minutes rather than chased.
Empirically, a limit posted 1 bp inside the touch fills within 15 minutes 93.8% of the time at the median symbol, giving a blended 5.31 bps per side.

**Kill switches** halt on drawdown beyond 25%, error rate at or above 25%, ticker older than 120 seconds, or a material mirror deviation beyond 50 bps on two consecutive cycles.
A halt empties the target set, which flattens the book, so the hysteresis matters.

---

## Trade tracking and the dashboard

`bot/blotter.py` reconstructs round-trip trades from the order journal by FIFO lot matching, apportions both legs' fees to the matched quantity, and reports realised P&L separately from open lots.
Two identities are checkable and must always hold: **bought equals closed plus open**, and **sold equals closed**.
A breach is a reconciliation failure, not a reporting bug.

`bot/dashboard.py` serves a page and `/api/state` from the same journals the bots write, standard library only.
`bot/insights.py` derives interpretation rather than displaying bare numbers: live exposure against the 18% historical mean, realised fee drag against the backtest's expectation per bot, distance to each kill switch rather than raw levels, shadow days against the three Gate 10 needs, supervisor restarts, and an explicit warning that win rate is meaningless below about 30 closed trades.
Market breadth scans all 66 venue names on a background thread every four minutes, because the scan takes roughly 65 seconds and must never block a page load.

---

## Running it

    ./run_bots.sh start | stop | restart | status | report | trades | dashboard

Dry run is the default. `ROOSTOO_DRY_RUN=0` with credentials in `.env` places real orders.
`BOT_VENUE=binance_testnet` switches venue for order-lifecycle testing.

For unattended running, `deploy/README.md` covers systemd on EC2 and launchd on macOS.
Agent-spawned background processes do not survive between tool calls, so a shadow run has to be started from a real terminal or a service manager.

---

## Conventions

- **No comments in code.** Structure and naming carry meaning; reasoning lives in `DECISIONS.md`.
- **Declare before you test.** A new family gets a config file with a stated mechanism and failure mode before any backtest runs.
- **Every configuration counts as a trial**, including nulls and abandoned searches, because each one consumes the family-wise error budget and raises the Gate 4 hurdle for every other candidate.
- **Pre-registered thresholds are never moved** to make something pass. Scope a control or add hysteresis instead of loosening it.
- **A citation must resolve.** `tests/test_doc_anchors.py` fails the build on any anchor reference into `DECISIONS.md` that does not exist, across markdown, configs and code. An anchor that points at nothing reads as evidence and is not. It found a dead link in `HANDOVER.md` and eight in frozen configs the day it was written.
- **The declaration lives in `config/<family>.yaml`, the outcome in `DECISIONS.md#<family>-outcome`.** A `*-declaration` anchor here is only warranted when the reasoning did not fit in the config. `DECISIONS.md#declaration-anchors`.
- **Long markdown files put one sentence per line.**
- **Never use the em dash.** Use a plain dash.
- Commit messages describe what changed and why, and must not describe work the commit does not contain.

---

## Anti-patterns learned here, at cost

**Do not optimise on a short sample.** 413 trials say it reverses. Two live trades is not a sample and a 100% win rate on them is noise.

**Do not let a test harness reimplement the logic it tests.** A hand-rolled limit price inside `gates/order_lifecycle.py` produced a marketable order and led to a false claim that the bot was crossing the spread. It was not. The harness now calls `Executor.limit_price`.

**Check a new metric against a series whose answer you already know.** `bot/report.py` shipped a Sortino that omitted the annualisation of downside deviation, inflating it by sqrt(365). It was caught because BTC buy-and-hold returned 34.22 where its known value is 1.7913.

**A backtest cannot catch wire-format defects.** `PairSpec.round_qty` computed `(qty // step) * step` in binary float and produced `0.0024600000000000004`, which Binance rejects outright. Backtests multiply weight vectors and never format an order. This is why the interim venue exists.

**Mean exposure says nothing about maximum exposure.** The book averages 18% gross but the construction is bounded at 1.5x, and it hit 1.45x on live data, which would have breached the no-leverage rule. Cap on gross, not on the volatility scalar.

**`x = maybe or default` hides a missing value by giving it the same code path as a present one.** `ref = refs.get(sym) or px` silently recomputed a position's booking reference as the current price every cycle, so the step was never cleared and no pre-existing position could ever book. Eighteen holdings, zero references, and nothing in any log looked wrong. `DECISIONS.md#booking-on-every-bot`.

**A flag that changes WHEN a function is called is as dangerous as one that changes what it returns.** Enabling booking made `trades_every_cycle()` true, which made `deltas` run on cycles where `channels` is empty by construction. `deltas` correctly reads an empty target against a held book as "sell everything", and three books were liquidated. Neither function was wrong; the precondition was. `DECISIONS.md#booking-flattened-the-book`.

**A suppression rule will silently eat a deliberate trade that looks like the thing it suppresses.** The 25% no-trade band exists to stop drift chasing. A 15% booking skim sits inside it, so every skim would have been suppressed while still being journalled - a system that logs activity, places no orders and measures nothing. Found by a regression test, not by watching. Deliberate trades must be exempt, not merely smaller than the band.

**A default argument is a silent declaration.** `gates.concentration.rank_score` defaulted the momentum lookback to 20 bars while every deployed config says `momentum_bars: 40`. Five gates scored a book the bot does not trade, and no test could catch it because both numbers are valid. It surfaced only when a new gate failed to reconcile with an existing table. Pin a deployed parameter explicitly at the call site; never let a default stand in for a config file. `DECISIONS.md#ranking-lookback-mismatch`.

**Telemetry can lie without trading being wrong.** The journal logged `gross_exposure 0` while holding half the book, because intermediate cycles recorded an empty target instead of held weights. Trading was unaffected; the Screen 1 audit trail was not.

**Measure in the venue's units.** The mirror check counted single-tick rounding as divergence. PEPE's tick is 26.2 bps, so one tick alone approached the halt threshold.

**Binance bars are labelled by OPEN time, so a 4h row labelled 04:00 holds a close from 08:00.**
Any code that combines two bar frequencies must align on CLOSE times, never on labels.
A label-matched `reindex(method="ffill")` from a slow panel onto a fast index leaks up to one slow bar of future price.
This bit twice in one sweep: once in the position function (holdout Sharpe 7.29) and again, after that fix, in the ranking carried into `gates/exit_clock.py` (Sharpe 3.72, 114x).
The second was invisible to inspection because the slow-clock arms are immune - the reindex is a no-op there - so only the fast arms were inflated, which reads as a real effect of the fast clock.
Use `signals.exit_clock.to_fast`, and assert that a fast==slow run reproduces the single-clock function exactly.

**Every archive field has its own stamp convention, and one field can leak while its neighbours do not.**
In the Binance Vision metrics archive the taker ratio's `create_time` is the START of a 5-minute volume bucket, while open interest and the long/short ratios are snapshots that the REST API stamps five minutes later.
A right-closed hourly bucket handed every bar five minutes of future taker flow and produced the only significant positive per-coin IC in the run, +0.025 at t=2.35; the fix took it to t=-0.30.
Check each field against a live read at one past hour before trusting a join. `DECISIONS.md#positioning-history`.

**A state machine that advances one bar per call never catches up.** The live channel flag moved forward on the latest bar only, so any close the process missed (downtime, a respawn, a late start, a name joining the universe) was lost until the next fresh breakout. `bot/verify.signal_parity` could not see it because it replays every bar in order, which the live bot never did. On 2026-09-23 the cushion book held 7 of the 19 names its rule held. Live state is now replayed from the bars with the backtest's own function. `DECISIONS.md#live-validation-2026-09-23`.

**A gate the backtest never applied can quietly remove most of the edge.** Execution refused any quote above 5 bps; PEPE's tick alone is 20.6 bps; the momentum rank kept choosing it and its slot idled in cash. That took the ranked book's holdout median from the 3.12% every gate reported to 1.20%. Any filter in the live path must exist in the backtest, or be proven not to bind. `DECISIONS.md#live-validation-2026-09-23`.

**"The API keeps 30 days" is a statement about the API.** It kept positioning out of every backtest for months while `data.binance.vision` held four years of it. Ask the archive too.

**When a result is too good, run a deliberately nonsense control before believing it or debugging it.**
A random exit firing at the same rate as the real one, ignoring the stop level, returned 27,594x against the real rule's 114x.
That comparison located a look-ahead bug that a one-bar execution-delay test had already passed (112.94x against 114.19x), and that reading the diff had missed twice.
A control that *should* fail and does not is worth more than another read of the code.

**Identical turnover between two arms that trade at different frequencies is a bug signal, not a coincidence.**
It is what exposed the first of those two defects.

**A process pattern that omits the repo path is a cross-repo kill switch.** `run_bots.sh` matched workers with `pgrep -f "bot.run config/<name>.yaml"`.
The sibling checkout `~/roostoo-jev` holds configs at identical *relative* paths, so starting that stack SIGTERMed all three bots here at 2026-09-19T17:41:03Z and they stayed dead for 24 minutes.
Nothing was lost only because bot_a and bot_c had no bar close in that window.
Both runners now launch workers with the absolute config path and match on `$ROOT`, which makes the two stacks disjoint in the process table.
A pidfile alone is not enough: the supervisor dies with the worker and leaves the pidfile stale, so `status` must ask the process table.

**A backtest that never models drift cannot price the turnover drift causes.**
Backtest turnover is `|w_t - w_{t-1}|` on TARGET weights; the live book rebalances target against the DRIFTED ACTUAL weight.
A target that never changes contributes zero backtest turnover and still emits a live order every cycle as the mark moves.
Five of `donchian_1h`'s eleven closed trades on 2026-09-20 were exactly this, at 3 to 19 dollars, paying full fees nothing had charged for.
The fix needed no new parameter: `portfolio.no_trade_band: 0.25` was already pre-registered and unfitted, implemented in `portfolio/construct.py`, applied in several gates, and used nowhere in `bot/`.
Applying the same band INSIDE the backtest is a null and is bit-identical on the momentum books, because there is no drift there to suppress. A backtest could never have found this.

**A count-weighted statistic gives a rounding residue the same vote as a real position.**
`donchian_1h` reported a payoff ratio of 2,156 because its `avg_loss` was half a cent across three dust round trips.
Split material from dust at a stated notional and report BOTH numbers, so the threshold cannot hide anything.

**Distinguish a crash from an operator restart from a diagnostic run.**
The dashboard counted every `resumed` event as a supervisor respawn and told the reader a worker had died, on a run with zero crashes.
Only the supervisor's own `exited code=` line in `live/<bot>.out` means a process actually died; a `--once` probe restores state exactly like a respawn does.

**A pgrep guard that cannot match its own process is not a guard.**
`run_bots.sh scanner` tested `pgrep -f "$ROOT/.*bot\.scanner"`, but `$ROOT` reaches the supervisor as a TRAILING `bash -c` argument and the worker's argv was a bare `python3 -m bot.scanner` with no path in it at all.
Neither process could ever match, so every invocation started another supervisor.
Two ran concurrently on 2026-09-20 and both wrote `live/scanner/state.json`; the signature in `live/scanner.out` is pairs of scans about 47 seconds apart.
A guard must be tested by running the start command twice and checking that the second one refuses.
Both processes now carry `$ROOT` ahead of the module name and `bot.scanner --root` verifies it and exits 2 on a mismatch.

**A default argument that points at a fixed path goes stale exactly like a hardcoded list.**
`bot/paper_lab.py` defaulted `--config` to `config/paper_lab.yaml`, which is v1, so `--report` with no arguments silently described a root that stopped being written months of roots ago.
This is the same defect already fixed once in `bot/compare.py` and it should have been fixed in both places then.
The default now discovers the newest `config/paper_lab_v*.yaml`.

**A long-running observation process needs a supervisor, because its only product is elapsed time.**
The paper lab ran unsupervised until 2026-09-20.
Its entire output is forward days against `min_comparison_days: 28`, and a silent death costs days that cannot be backfilled by anything.
Use `./run_bots.sh paperlab`, not a bare `python3 -m bot.paper_lab`.

**Faster is not better here, and not only because of cost.** Gross Sharpe, before any fee, falls monotonically as the bar shortens and goes negative at 5m. A 5m breakout is noise that mean-reverts.

---

## Open items

- **2026-09-19 review update:** `results/logic_review_2026_09_19.md` records execution, universe and data-integrity gaps, and a surviving Sortino annualisation defect in five fortnight scorers.
  Their historical Screen 3 artifacts and the sign-indicator thesis need re-evaluation with corrected scoring.
- **Prospective paper lab:** `config/paper_lab.yaml` declares 1h, 4h, 8h and daily channels, a flow-confirmed 4h candidate and BTC control.
  `python3 -m bot.paper_lab --report` shows the isolated live-market paper comparison; simulated fills do not establish real fill quality or edge.

- **Roostoo credentials are not issued.** Every signed endpoint, the real `CommissionPercent`, fill quality, partial fills and rejections are untested on the competition venue. The README and the organizer disagree about commission by a factor of eight and only a live fill settles it.
- **Gate 10 needs three distinct days** of live operation and must run from a real terminal or EC2.
- **Gates 3, 5 and 7** have never been run. Gate 8 fails on drawdown.
- **Gate 4 is settled as unrecoverable and no further research should be spent on it.**
  `DECISIONS.md#trial-counting-rule` states a counting rule, committed before the number was computed, and applies it to the whole ledger: 754 raw rows become 470 in the Sharpe family.
  DSR rises only from 0.8009 to 0.8444 against a required 0.95, and the largest N that would pass is 94, which no honest reading reaches.
  The other two levers close by arithmetic: passing would need 3,579 daily observations against the 1,358 held, or an annual Sharpe of 2.498 against the 2.206 measured.
  The raw Sharpe is real and the strategy may work; what is established is that this sample cannot distinguish it from the best of 470 null draws at 95%, and the submission must say that.
- **The full-history drawdown is 38.1%**, not the 17.7% the 2023-onward window shows. Quote the longer number.
