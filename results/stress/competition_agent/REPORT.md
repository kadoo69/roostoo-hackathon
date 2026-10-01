# Competition book red-team report

Book: `competition` (= `momentum_top3_30m` rule, `config/competition.yaml`).
Harness: `gates/stress.py`, declared at `DECISIONS.md#stress-harness-declaration`.
Tools: `gates/stress_competition.py` (this agent), tests `tests/test_stress_competition.py`.
Written 2026-09-30 ~20:20Z before any number below was computed by this agent.

## Pre-registered

Periods follow the harness: fit 2023-01-01..2025-01-01, holdout 2025-01-01..2026-09-19, recent 2026-06-01..data end.
Nothing is tuned on holdout.
Every proposed fix is reported on fit and holdout with the thresholds fixed here.

### Live-path hypotheses (a break = a concrete reproduction by unit test or log replay)

| id | hypothesis | counts as a break |
|---|---|---|
| L1 | `risk.max_drawdown` 0.25 trip liquidates and stops the book for the rest of the round, or never resumes | code path shows permanent halt or liquidation with no resume; quantified by how often the rule's 14-day windows touch -25% equity from peak |
| L2 | an unfilled or partial LIMIT maker order leaves cash idle, double-buys, or chases | any path where a retry sends a second buy while the first is resting or filled, or cash stays idle for a whole bar with a live target |
| L3 | the ladder misbehaves on the live venue (wrong reference, skim below min qty, skim re-bought) | a skim that is re-bought by the rebalance on the next cycle, or a reference reset that re-fires skims |
| L4 | restart or first-bar behaviour buys stale entries or sells fresh ones | a code path that trades a path entry older than one bar after a restart |
| L5 | account-activation start behaves differently from a normal start (first-bar suppression means the first trade is delayed, or a stale target is bought) | a stale entry on the first good wallet read, or an entry delay beyond one bar with a live signal |
| L6 | universe refresh drops a held coin and the book cannot sell it, or halted/delisted coins block the cycle | a held coin outside the universe that is never exited, or an exception that stalls the cycle |
| L7 | Roostoo prices diverge from Binance bar closes enough to matter | median absolute divergence of rehearsal fills vs the Binance 30m close above 10 bps, or any single one above 50 bps |
| L8 | API calls per cycle exceed the 30/min limit | any cycle whose call count in one minute can exceed 30 |
| L9 | an hour of Roostoo API errors kills the book (error-rate trip) or leaves it in a broken state | `max_error_rate` trip that halts permanently, or a state that does not recover after errors stop |
| L10 | bar-close timing: the cycle acts on an incomplete bar or late | any decision on a bar whose close is in the future, or median lag after close above 60 s in the rehearsal log |

### Scenario and structure hypotheses (thresholds are the harness break rule unless stated)

| id | hypothesis | counts as a break |
|---|---|---|
| S1 | harness scenarios (fee_taker, slip_10bps, delay_1bar, outage, data_holes, flash_wick, gap_shock, jitter) | the harness break rule: median <= 0, loses > half of baseline median, worst < -25%, or median maxDD worse than -15% |
| S2 | edge depends on a handful of outlier trades | dropping the top 1% of trades by P&L takes the holdout median 14-day return to <= 0 |
| S3 | false breakouts dominate in chop | in the chop regime the share of trades with net P&L <= 0 exceeds 65% and chop mean trade P&L is negative |
| S4 | the three positions are one bet | median pairwise 30m return correlation of held coins above 0.6 over the holdout |
| S5 | fee drag eats the edge | holdout fee drag per 14 days larger than half of the gross 14-day median |
| S6 | the worst 14-day windows are driven by few trades | the worst 3 trades explain more than half of the loss in each of the two worst windows |
| S7 | the fit-period negative median is a regime artefact (bear/chop 2023) rather than a rule failure | fit median positive in the up regime and negative in chop and down; if fit is negative in every regime the rule itself is suspect |
| S8 | time-of-day / weekday effects: entries in some hours lose money | an hour-of-day bucket (4 h bins) with fit AND holdout mean trade P&L both negative (reported only, not a fix licence) |
| S9 | a stop or tighter exit would have saved the tails without killing winners | MAE distribution: fraction of winning trades whose MAE is worse than the MAE threshold that would cut the worst losers; reported only, fit-only threshold |

### Nonsense control

The harness identity scenario must reproduce baseline exactly.
For S2, a random drop of the same count of trades must not move the median as much as dropping the top trades.
For S8, the same bucketing on shuffled entry hours must not show the same pattern.


### Addendum pre-registration, written 2026-09-30 ~20:25Z before the stop replay ran

S9 is upgraded from a trade-level estimate to a replay: a close-based stop at -3%, -5% and -8% below the entry close (levels fixed in code as `STOP_LEVELS` before any stop number existed), the book flat from the first close at or below the level to the end of the rule's spell, replayed through the shared simulator.
Decision rule: a level counts as an improvement only if the fit AND holdout median 14-day return both rise by at least 0.25 pp, the holdout worst window does not get worse, and the nonsense control (the same number of random spells cut at a random bar) does not show the same rise.
Anything that passes is an OPERATOR DECISION to paper-trade first, never a change to apply.

## Results

Evidence files are in this folder: `live.json`, `outliers.json`, `windows.json`, `kill.json`, `fees.json`, `concentration.json`, `timing.json`, `mae.json`, `stops.json`, `regimes.json`, `trades.csv`.
Scenario numbers are from the full harness run `results/stress/competition.json` (identity scenario reproduced the baseline exactly, `identity_ok: true`).
Live-path reproductions are the `test_repro_*` tests in `tests/test_stress_competition.py`; they pass today because they pin the defective behaviour, and each must be rewritten when its defect is fixed.

### Trials table

| id | test | result | break? |
|---|---|---|---|
| L1 | drawdown halt path (`bot/risk.py`, `bot/run.py` cycle) | halt empties the target, so the book is liquidated with LIMIT sells; the in-process equity curve keeps its peak forever, so the halt never clears while the process lives (clears only after a restart once 5,000 flat cycles, ~41.7 h, have pushed the peak out of the persisted curve). Historical: the 25% intrawindow drawdown fires in 2.1% of holdout windows (13/616), 2.3% fit, 6.0% recent, at a median day 11; killed holdout windows would have finished at a median -3.9% instead of the -8.1% the kill locks in (9 of 13 recovered above the kill level), fit neutral (-18.8% vs -18.4%) | yes, permanent and rarely protective (`test_repro_drawdown_halt_never_clears_once_flat`) |
| L1b | a held coin without a Roostoo quote is marked at 0 (`Bot.mark`) | a 0.5-weight coin missing from one ticker read is a -50% phantom drawdown, which trips the halt and liquidates the rest permanently | yes (`test_repro_missing_quote_marks_a_held_coin_at_zero_and_trips_the_drawdown_halt`) |
| L2 | unfilled/partial LIMIT orders | 4/4 rehearsal orders filled as MAKER at the limit; fill seen 33 s (buys) and 67-97 s (sells); no cancels, no partials. Code: a cancelled buy is re-quoted each cycle until the next close (no idle cash for the bar); a partial fill is never topped up (booking caps target at held), so it would idle cash for the whole trade. Double-buy path: when `query_order` fails in `refresh_pending` the previous cycle's empty pending set is reused and a resting buy is sent again | yes for the double-submit path (`test_repro_stale_pending_set_after_query_failure_resubmits_a_resting_buy`); partial fills null in evidence |
| L3 | ladder on the live venue | no skim fired in the rehearsal (no +3% move); code resets the reference when the skim is decided, even if the sell is then skipped (`order_already_pending`, below min order), so a skim can be lost; live checks every 30 s on LastPrice while the backtest checks 30m closes, so live skims more often than the backtest | minor, not a break |
| L4/L5 | restart and account-activation start | the first decision after a start is guarded, but the SECOND decision buys any name the rule's path already held. Rehearsal cold start 14:22Z: TRX was suppressed at the 13:30 bar and bought at 14:00 at 0.5 weight, a path entry one bar late (lost 29 bps before fees). The competition book will start the same way on activation | yes (`test_repro_second_decision_after_cold_start_buys_a_path_entry_one_bar_late`, log replay `live.json` `late_path_buys`) |
| L6 | universe refresh drops a held coin | `adopt_wallet` restricts holdings to the current universe, so a held coin that leaves the top 30 vanishes from holdings and equity: never sold, and a >=0.25-weight coin trips the drawdown halt, which liquidates everything else permanently. Churn is real: FIL, ASTER, ONDO and XLM left the paper books' universe 5 times in 8 days; the 30m paper book held ONDO until 2 h before ONDO left on 2026-09-28 | yes (`test_repro_universe_refresh_orphans_a_held_coin_and_trips_the_drawdown_halt`) |
| L7 | Roostoo vs Binance prices | rehearsal limit prices vs the Binance 30m close of the decision bar: TRX buy -2.9 bps, TRX sell +5.9 bps, PUMP buy 0.0, PUMP sell +10.2 bps (all at or better than the close); mirror worst-of-25 median 3.4 bps, p99 18.5, max 46.2 bps (threshold 50, needs 2 consecutive cycles), no consecutive pair >= 40 | no break; the mirror halt margin is thin (see L7b) |
| L7b | mirror halt | any universe coin whose Roostoo LastPrice is 0, or missing from Binance, makes the check incomplete (`inf`), and two such cycles halt and liquidate the whole book | yes, code path (`test_repro_mirror_row_dropped_for_zero_last_price_means_an_incomplete_check`) |
| L8 | API budget | 5 Roostoo calls per idle cycle (ticker, balance x2, query_order x2) = 10/min, ~16/min at a busy close; `CallBudget` caps each process at 28/min. On the Mac all 6 books call the unsigned ticker from one IP: ~28/min in total if the limit is per IP | no break per key; open question if per IP |
| L9 | an hour of Roostoo errors | `error_rate` is errors / attempts over the process lifetime, and query/cancel failures add errors without attempts. With 4 orders sent, ONE failed sweep query gives 0.25 and halts (liquidation). Once flat no orders are sent, attempts stop growing and the halt is permanent until restart. A failed `place_order` transport (timeout, 5xx, 429) latches `submission_blocked` for the process lifetime: every later order, exits included, raises, and nothing restarts the process (the loop catches the exception, the watchdog only catches a hung cycle) | yes, both (`test_repro_one_query_error_after_four_orders_halts_and_flattens`, `test_repro_ambiguous_submit_blocks_exits_for_the_life_of_the_process`) |
| L10 | bar-close timing | decisions 7-15 s after each close (median 10 s), ticker age median 0.19 s, max 2 s | no |
| S1 | harness scenarios | fit baseline median is already <= 0 (-0.76%). Holdout breaks: fee_taker (median -0.80, worst -25.2), slip_10bps (-2.67, worst -27.9), delay_1bar (worst -26.9), data_holes (lost > half, +0.37), flash_wick (-2.16, worst -26.6), gap_shock (-2.92, worst -28.4), jitter exit14 and mom30 (lost > half), n2 (worst -27.8). Holdout survivors: outage, entry15/25, exit7, mom50, vol1.25/2.0, n4. Recent: everything except vol1.25, exit14 and n2 breaks (median <= 0), and gap_shock breaks maxDD (< -15) | yes, see list |
| S2 | outlier dependence | dropping the top 1% of holdout trades (23 of 2,347) takes the holdout median from +1.13% to -1.51% (random drop of 23: +0.97%); top 5%: -9.36%. Fit: top 1% -> -3.03% (random -0.68%). The top 1% carry 146% of holdout net trade contribution | yes |
| S3 | false breakouts by regime | net-of-cost hit rate 30-32% in every regime; false-breakout rate chop 68.5% holdout / 69.7% fit, up 70.3% / 68.5%; mean chop trade is positive (+0.31% holdout, +0.11% fit). Daily P&L on chop DAYS is negative (-0.14%/day holdout, -85% of log P&L), up days carry +201% | no (chop trades are not negative on average); the losses are chop days, not chop entries |
| S4 | concentration | median pairwise 240-bar correlation of held coins 0.60 fit, 0.56 holdout, 0.38 recent; but the book holds 2+ names only 30% of the time (flat 51%, one name 19% of bars) | fit marginal break (0.603), holdout no |
| S5 | fee drag | turnover 42x equity per 14 days (holdout); median 14-day return gross 3.66%, no-fee 3.03%, net 1.13%: costs take 2.5 pp, more than half of gross. Fit gross 1.86% -> net -0.76% | yes |
| S6 | worst windows driven by few trades | worst holdout window 2025-06-25 (-22.3%): 92 trades, 17% hit rate, 72 of 92 entries in chop, worst 3 trades = 27% of the loss. Second 2025-05-11 (-19.8%): worst 3 = 67%. Fit 2024-03-10 (-24.9%): 82 trades, 31%; 2024-12-04 (-24.7%): 85% | no: the worst windows are mostly whipsaw sequences (~6 trades/day at 0.5 weight), not a few blow-ups |
| S7 | why fit median is negative | fit gross edge is only +1.86%/14d median against ~2.6 pp costs; by regime, fit up days +0.78%/day (+184% of log P&L), chop +0.07%/day (+23%), down -0.52%/day (-79%), crash -1.04%/day (-28%). Holdout: up +1.66%/day, chop -0.14%/day (-85%). The fit loss is down and crash days plus costs, the holdout drag is chop; the book only earns in up days | not a rule failure in one regime; the rule is an up-trend harvester whose costs exceed its edge outside up days |
| S8 | hour of day | 00-04 UTC closes: fit -0.32%, holdout -0.04% per trade (both negative); but the shuffled-hour control shows a -0.36% bucket in fit, so the effect is inside noise. Weekday (reported only): Tuesday negative both periods | pre-registered flag trips, but fails its nonsense control: not actionable |
| S9 | close-based stops -3/-5/-8% (replayed) | median 14d fit / holdout: baseline -0.76 / 1.13; stop-3 -0.69 / 1.17 (fit worst worse, -26.1); stop-5 -0.69 / 1.17; stop-8 -0.76 / 1.25. None clears +0.25 pp on both; the random-cut nonsense control does as well or better (holdout 1.61 / 1.35 / 1.19). Trade level: winners' MAE 10th pct -1.0%, losers' median MAE -0.9%; the worst losers lose in one bar (MAE ~= final), which no close stop catches | NULL: no stop helps; the 10-bar-low exit is already the stop |

### Scenarios that broke the book

Fit is broken by every scenario because its baseline median is already negative (-0.76%).
Holdout (2025-01..2026-09): fee_taker, slip_10bps, flash_wick and gap_shock break the median (<= 0); delay_1bar, flash_wick, gap_shock, fee_taker, slip_10bps and jitter n2 break the -25% worst window; data_holes, jitter exit14 and mom30 lose more than half the median.
Recent (2026-06..09): every scenario and every jitter except vol1.25, exit14 and n2 takes the median to <= 0; gap_shock also breaks median maxDD (< -15%).
The edge is thin enough that 5 bps more cost per fill (taker instead of maker) removes it: execution quality is the strategy.

## Proposed fixes

Each is either a safe bug fix (restores intended behaviour, no rule change) or an OPERATOR DECISION (changes what the book does).
None was applied.

1. **Ambiguous-submit latch never recovers** (safe bug fix). After `submission_unknown`, run `bot.intents.reconcile` inside the loop on the next cycles and clear `submission_blocked` when it comes back clean; if it cannot be settled after N cycles, `os._exit` so the supervisor respawns and the startup reconciliation runs. Test: the repro test flips to "a later cycle reconciles and sends the exit". Nonsense control: an intent that IS found at the venue must stay blocked until resolved.
2. **Error-rate kill is lifetime and asymmetric** (safe bug fix of the gate's definition; threshold unchanged). Count errors and attempts over a rolling window (for example the last 50 venue calls, every call counts as an attempt, query and cancel included), and never let a read-only query failure empty the target: a halt from `error_rate` should freeze new entries, not liquidate. Test: one failed sweep after 4 orders must not halt; 25% failures over the window must still halt. Control: the existing `-2010` loop regression (`DECISIONS.md#testnet-live` item 2) must still trip.
3. **Universe refresh orphans held coins** (safe bug fix). `adopt_wallet` should adopt `universe | previously held symbols` (and anything the venue lists that the book bought), so a coin that leaves the top 30 stays in holdings, is marked, and is sold by the rule. Test: the repro test flips to "coin kept and sold on the next close". Control: a pre-seeded testnet wallet must still not be adopted (existing `#testnet-live` test).
4. **Missing quote marks a held coin at 0** (safe bug fix). In `mark`, value a held coin without a quote at its last known mark (and journal it), never at 0; skip the drawdown gate on a cycle with an unmarked holding. Test: the repro flips.
5. **Mirror incompleteness halts and liquidates** (safe bug fix). Compute the mirror over coins that have both prices and only treat it as a breach for HELD coins; an incomplete check should block new entries, not empty the target. Test: the repro flips; a real 2-cycle 60 bps divergence on a held coin still halts.
6. **Stale path entry on the second decision after a start** (OPERATOR DECISION, it changes entries). Apply `drop_stale_entries` to every decision, with the exception that a name the book tried to enter at the previous decision (its pending entry) may still be bought. The rehearsal's TRX shows it happens on every cold start, which is exactly how the competition account will start. Mechanism: late path entries net negative live (`#catch-up-and-live-min-hold`). Failure mode: the book misses legitimate sticky re-entries after a failed fill. Decision rule: on the live books, count late path buys (tool: `python3 -m gates.stress_competition live --live-book <book>`) and their P&L over 7 days. Control: fresh entries on the latest bar must be unaffected.
7. **Drawdown halt is permanent** (OPERATOR DECISION). Either keep it (it rarely fires: 2.1% of holdout windows, and a -25% book does not qualify anyway) or reset it after the book is flat for a declared period. The evidence says the kill is not protective (9 of 13 killed holdout windows recovered above the kill level, median -3.9% vs -8.1% kept), so for Screen 2 it can only cost; for Screen 3 it cuts Calmar losses. It must also stop depending on the process lifetime (in memory the peak never leaves; after a restart it leaves after 41.7 h).
8. **Exits are passive maker sells** (OPERATOR DECISION). A 10-bar-low exit in a dump rests at the ask for up to 300 s, then re-quotes lower; sells took 67-97 s to fill even in calm markets. Escalate an exit to a marketable order after the first timeout. Cost: 5 bps on those exits; fee_taker on every fill breaks the book, so escalate only exits and halts, never entries.
9. **Double-submit after a failed pending query** (safe bug fix). When `refresh_pending` fails, treat every pair with an order sent in the last `limit_timeout_s` as pending (keep a local sent-orders set). Test: the repro flips.
10. **Operator questions, not code**: whether "first trade due 12:00 UTC" is a requirement (after a random start the rule's next entry is a median 5.9 h away holdout, P(no entry within 3 h) = 0.67, within 12 h = 0.31); whether the 30 calls/min limit is per key or per IP (the Mac's six books make ~28 calls/min from one IP).

## Structural facts for this clock (report only, nothing tuned)

- The edge is the right tail: the top 1% of holdout trades carry 146% of the trade P&L, and removing them makes the median negative; a random removal of the same count does not. Hit rate is 30-32% in every regime.
- Costs are the binding constraint: turnover 42x equity per 14 days, 2.5 pp of a 3.7 pp gross median.
- The book is flat 51% of bars and holds one name (at the 0.5 cap, half cash) another 19%; the three-slot concentration concern applies to under a fifth of the time, though held names correlate at 0.56 when it does.
- Worst windows are whipsaw runs of 80-90 trades in chop at a 17-26% hit rate, not a few blow-ups; no stop level changes them.
- Time-of-day and weekday effects do not survive their shuffled control.
