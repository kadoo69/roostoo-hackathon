# Anti-patterns learned here, at cost

Moved out of `CLAUDE.md` on 2026-09-23 to keep every agent session's context light.
Read this before touching the live cycle (`bot/run.py`), a data join, a gate harness, or `run_bots.sh`.
Each entry links to the `DECISIONS.md` anchor that carries its evidence.

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
