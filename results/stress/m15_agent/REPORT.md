# momentum_top3_15m red-team report

Book: `config/momentum_top3_15m.yaml`, harness `gates/stress.py` (`DECISIONS.md#stress-harness-declaration`), tools `gates/stress_m15.py`.
Periods are the harness's: fit 2023-01-01..2025-01-01, holdout 2025-01-01..2026-09-19, recent 2026-06-01..data end.
Trades are the harness's `trades(w, close)` spells on the baseline target path; a trade's net return charges the round trip at the simulator's maker fee plus one tick each way.

## Pre-registered (written 2026-09-30 ~20:05Z, before any number below was computed)

Each hypothesis names what counts as a BREAK; anything else is recorded as a null.
Thresholds are not moved after numbers are seen.

| id | hypothesis | break threshold |
|---|---|---|
| H1 | Whipsaw: trades that end within 1-4 bars carry the book's cost | trades held <= 4 bars pay >= 50% of all round-trip fee+tick cost AND their summed net return is negative, in fit and holdout |
| H2 | Volume confirmation does not separate false breakouts | whipsaw rate (exit within 4 bars at a loss) in the top volume-multiple bucket (>= 5x) is not lower than in the bottom bucket (1.5-2x), in both fit and holdout |
| H3 | The 10-bar-low exit is noise | >= 30% of losing exits see the close back above the entry price within 8 bars (2 h) after the exit, in both periods |
| H4 | Short holds destroy what long holds earn | summed net return of holds < 4 bars is negative and its magnitude exceeds 50% of the summed net return of holds >= 12 bars, in both periods |
| H5 | Session / funding-hour effect | one session (Asia 00-08, EU 08-16, US 16-24 UTC by entry-bar close) or the funding-hour bars (close at 00/08/16) has mean trade net return < 0 with t < -2 in BOTH fit and holdout |
| H6 | Weekend effect | weekend-entry mean trade net return below weekday with Welch t < -2 in both periods |
| H7 | BTC-led vs idiosyncratic | one class (BTC itself in a 20-bar 15m long channel at entry, or not) has mean trade net return < 0 with t < -2 in both periods |
| H8 | Concentration: the three slots are one bet | on >= 50% of bars holding 2+ names, the mean pairwise 96-bar (24 h) return correlation of held names exceeds 0.7 |
| H9 | Fee+tick drag dominates | median 14-day fee+tick drag exceeds the median 14-day gross (pre-cost) return, in holdout |
| H10 | Outlier dependence | removing the top 1% of trades by net return makes summed net return negative (fit or holdout); 5% and 10% reported |
| H11 | Execution latency | filling each entry and exit at the 1-minute close k minutes after the bar close (k = 1, 2, 5) instead of the bar close costs more than 10 bps per round trip on average at k = 1 |
| H12 | Live window parity | the live cycle's 149-bar windowed replay disagrees with the full-history rule (different held set) on >= 5% of bars in the recent period, or its 14-day median differs by more than 1 pp |
| H13 | Live fills differ from the backtest | any systematic difference between the paper fill (limit at mark +/- 1 bp, decided 5-13 s after the close) and the backtest's at-close maker fill larger than 5 bps per fill |
| H14 | Harness scenarios | the harness's own break rule (`config/stress_harness.yaml`) applied per scenario and period |

Nonsense controls declared with the hypotheses:
- H2/H5/H6/H7: the same split applied to trades with labels shuffled (seed 0) must NOT show the effect (|t| < 2); if it does the split test is void.
- H10: the same drop applied to the bottom 1/5/10% must raise the sum (sanity of the trade ledger).
- H12: a window equal to the whole history must reproduce the full-history rule exactly (zero disagreement).
- Trade ledger: summed log trade returns weighted by entry weight must track the simulator's net within the drift of the ladder (reported, not a gate).

## Trials

| # | test | result | break? |
|---|---|---|---|
| 1 | L1 live late entries (journal audit, archived + current run) | 10 late entries, 9 closed, all 9 lost, mean -131 bps, -5,399 USD; on-time entries +71.5 bps, +14,767 USD | BREAK (live bug) |
| 2 | H1 whipsaw cost share | holds <= 4 bars pay 30.6% (fit) / 30.5% (holdout) of cost; their P&L -8.56 / -7.75 weight-units | null (cost share < 50%), but see H4 |
| 3 | H2 volume vs whipsaw | whipsaw 34.3% at 1.5-2x -> 20.2% at >= 5x (fit), 34.2% -> 24.1% (holdout) | null (volume does separate) |
| 4 | H3 exit noise | 44.1% (fit), 45.1% (holdout), 45.5% (recent) of losing exits trade back above entry within 8 bars | BREAK (no base-rate control; F2 shows holding through it does not pay) |
| 5 | H4 short vs long holds | < 4 bars -6.71 / -6.08 vs >= 12 bars +16.74 / +16.33 | null by threshold (ratio 0.40 / 0.37 < 0.5); every bucket under 3 h loses |
| 6 | H5 session / funding hour | shuffled-label control shows |t| > 2 (e.g. fit eu -2.85, holdout eu -3.48) | VOID (control failed: the whole population mean is negative) |
| 7 | H6 weekend | Welch t -0.72 (fit), +1.24 (holdout) | null |
| 8 | H7 BTC-led vs idiosyncratic | shuffled control |t| > 2 in fit and holdout | VOID |
| 9 | H8 concentration | share of 2+-name bars with mean pairwise 24 h corr > 0.7: 27.4% / 26.3% / 8.7% | null |
| 10 | H9 fee+tick drag | median 14-day gross +0.37 / +1.25 / -1.20% vs drag 8.23 / 9.11 / 10.71% (turnover 136 / 140 / 157x per 14 d) | BREAK |
| 11 | H10 outlier dependence | sum already negative (-2.94 / -1.52); dropping top 1% -> -9.12 / -8.77, 5% -> -17.1 / -15.6 | BREAK (degenerate: negative before any drop) |
| 12 | H11 latency, k=1 min | entry +0.5 / +1.7 bps, exit -2.0 / -5.9 bps (n 103 entries, 70 exits on 4h-boundary bars only) | null |
| 13 | H12 window parity, pure | 0.01% of 10,912 recent bars differ; 14-day median identical | null |
| 14 | H12 window parity, live-like universe | 1.29% of bars differ; 14-day median -12.50 vs -12.39 | null |
| 15 | H13 paper fill vs mid | -1.06 to -1.34 bps (paper buys at the bid); decision lag median 6.7 s, p90 9.8 s | null (< 5 bps) |
| 16 | H14 harness scenarios | baseline already breaks every period; every scenario breaks | BREAK (see table) |
| 17 | F2 min_hold_bars 12 | fit +1.98 pp, holdout -0.05 pp, holdout worst +3.18 pp | FAIL (holdout gain < 1 pp) |
| 18 | F2c min_hold_bars 2 (dose control) | fit +0.17, holdout -0.07 pp | control, not a candidate |

## Proposed fixes, declared 2026-09-30 ~20:35Z before any fix number was computed

F1 (safe bug fix, no backtest needed): `bot/entry_guard.GuardedTarget.guard` applies `drop_stale_entries` on every decision, not only on the first or a catch-up decision.
Mechanism: the backtest opens a name only on the bar its path enters it; the live book must never open a name whose path entry is older than the latest bar.
Failure mode: an entry whose order failed on its own bar is never retried at the next close (the intrabar `pending_entries` retry still acts).
Decision rule: `repro_stale_rebuy()` must return an empty on-time decision, and `tests/test_entry_guard.py` must stay green.
Nonsense control: a fresh entry (absent from the previous row) must still pass (already covered by `test_stale_entries_are_dropped_but_fresh_and_held_names_stay`).

F2 (OPERATOR DECISION, backtest only; the live A/B `momentum_top3_15m_hold3h` already runs this parameter): `min_hold_bars: 12` on the 15m rule, the value the live twin was declared with at `DECISIONS.md#live-hold-time-2026-09-26`, not chosen here.
Mechanism: trades held under 3 h lose at every hold bucket while trades held 3 h+ carry all the profit; 45% of losing exits trade back above entry within 2 h, so the channel exit inside the first 3 h is mostly noise.
Failure mode: true failures are held for 3 h, deepening loss per losing trade and the worst window.
Decision rule (fixed): improves the median 14-day return by >= 1.0 pp in BOTH fit and holdout, AND the holdout worst window is not more than 3 pp worse, AND beats the dose control on holdout median.
Dose control: `min_hold_bars: 2` (a hold too short to reach the 3 h zone); if it matches F2 the mechanism is not the 3 h boundary.
Reported also under `fee_taker` to check the gain is not turnover alone.
Any volume-threshold change is NOT tested: H2 was read on fit and holdout, so any threshold chosen from it would be tuned on holdout; the harness's own jitter arms (vol1.25, vol2.0) are reported instead.

## Results

Evidence files: `results/stress/m15_agent/{live,anatomy,drag,concentration,latency,window_pure_149,window_live_149,fixes,repro_stale_rebuy}.json`, trade ledger `trades.parquet`, harness `results/stress/momentum_top3_15m.json` (identity_ok true).

### L1 live bug: a blocked stale entry is bought on the very next bar

`bot/entry_guard.GuardedTarget.guard` drops stale path entries only on a catch-up decision or the first decision after a start.
On the next on-time bar the rule's path still holds the name, the book still does not, and nothing blocks it, so the book buys it one bar later.
Every one of the 10 late entries in the 15m journals follows a `stale_entry_blocked` or `cold_start_entry_suppressed` of the same symbol one decision earlier.
Examples: ARB blocked 2026-09-29 11:58:39Z, bought 12:00:09Z, -159 bps; WLD blocked 2026-09-30 13:52:57Z, bought 14:00:09Z, -374 bps; ENA/PUMP/SUI suppressed at the 17:34Z cold start, bought 17:45:06Z, -127/-108/-69 bps (this is the whole -1.24k of the current run).
9 of 9 closed late entries lost, mean -131 bps, -5,399 USD; on-time entries earned +71.5 bps on average, +14,767 USD.
Reproduction: `python3 -m gates.stress_m15 repro` drives the real guard through a catch-up decision and the next on-time decision; the second returns `{"ARBUSDT": 0.5}`. `tests/test_stress_m15.py::test_a_blocked_stale_entry_is_not_bought_on_the_next_on_time_bar` is a strict xfail that flips when the bug is fixed.
The same class serves `competition` and `competition_rehearsal` (`bot.contenders_run`): when the competition account activates, the first decision is suppressed and the second buys whatever the path entered earlier, so the first real trade would be a stale entry.
Fix F1 (safe bug fix): in `guard`, call `drop_stale_entries` on every decision with more than one row, not only when `first or is_catch_up(...)`; keep the journal event.

### Harness scenarios (break rule of `config/stress_harness.yaml`)

| scenario | holdout median | P(>5%) | worst | median maxDD | recent median |
|---|---|---|---|---|---|
| baseline | -7.89 | 0.20 | -35.99 | -13.71 | -12.39 |
| fee_taker | -14.07 | 0.12 | -41.20 | -18.04 | -18.79 |
| slip_10bps | -19.91 | 0.07 | -45.98 | -22.51 | -25.04 |
| delay_1bar | -6.99 | 0.20 | -33.59 | -13.53 | -12.54 |
| outage | -7.64 | 0.21 | -36.48 | -13.77 | -11.41 |
| data_holes | -7.86 | 0.16 | -33.81 | -13.75 | -13.68 |
| flash_wick | -10.52 | 0.17 | -40.09 | -15.28 | -15.71 |
| gap_shock | -11.45 | 0.17 | -40.40 | -15.62 | -17.43 |
| jitter best (exit14) | -6.62 | 0.23 | -32.77 | -14.12 | -13.95 |
| jitter worst (exit7) | -10.02 | 0.13 | -39.76 | -15.63 | -14.44 |

The baseline itself breaks every period (median <= 0, worst < -25%); no parameter in the neighbourhood rescues it.
A one-bar-late fill IMPROVES the median by 0.9 pp: the 15m breakout close is, on average, a worse price than the next bar's close.
BTC regime split (holdout daily): up +1.12%/day (118 days), chop -0.54%/day (396 days, 85% of the log loss), down -1.35%/day, crash -1.48%/day. The decision point currently reads the market as chop.

### Microstructure facts for the 15m clock

- Hit rate 26%; per-trade mean -8.6 bps (fit), -6.8 (holdout) after a 10 bps maker round trip plus ticks.
- Every hold bucket under 3 h loses (hit 4-10%, -65 to -107 bps per trade); 3-6 h +30 bps, 6-12 h +244 bps (hit 89%), 12-24 h +770 bps. The top 5% of trades carry 68-72% of positive P&L with a median hold of 33 bars (8.25 h).
- Gross edge is +0.4 to +1.3% per fortnight; costs are 8-11% per fortnight at 136-157x turnover. Taker fills (-14.1) or 10 bps slippage (-19.9) deepen the loss roughly linearly.
- Volume confirmation works as intended: whipsaw rate falls from 34% at 1.5-2x to 20-24% at >= 5x volume.
- 45% of losing exits trade back above entry within 2 h, yet a 3 h minimum hold (F2) does not lift the holdout median: noise both ways.
- Exits delayed 2-5 minutes filled 8-15 bps better in holdout (t about -2.1, n 34, 4h-boundary bars only): post-exit bounce, a small-sample hint, not tested.
- No weekend effect; session and BTC-channel splits are void because their shuffled controls also reject.
- Held names are not one bet (mean pairwise 24 h correlation above 0.7 on 26% of multi-name bars).
- The live 149-bar replay matches the full-history rule on 99.99% of bars; the live universe definition moves 1.3% of bars and 0.1 pp of the 14-day median. Rolling-window seeding is not a defect.

## Verdict

The 15m rule has no edge after costs in any period (the frozen config already records the backtest FAIL); the red team adds that no scenario, neighbourhood point or the declared hold fix changes that.
The one concrete, fixable defect is L1, and it also affects the real-money competition book.
