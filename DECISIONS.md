# Decision Log

Section 10 of the plan forbids comments in code.
Every non-obvious decision therefore lives here, keyed by the anchor that the pre-registration config references.

## price-source

Roostoo does not mirror Binance approximately, it mirrors it exactly.
Measured 2026-09-18 across the full venue universe: all 86 Roostoo pairs map to a Binance USDT symbol, median absolute deviation 0.00 bps, maximum 3.30 bps.
The residual is the wall-clock gap between the two HTTP calls, not a pricing difference.

Consequence: Binance spot klines are not a proxy for backtesting this venue, they are the same series.
Cross-source validation against Coinbase or Kraken would add nothing and is not performed.

Roostoo exposes no historical endpoint of any kind, so Binance is the only route to history.

## costs

The published API documentation and the organizer disagree about commission, by roughly a factor of eight.

The README's example `place_order` responses carry `CommissionPercent` of 0.00012 and 0.00008.
At the 2026-09-18 info session the organizer stated 0.1% for market orders and 0.05% for limit orders.
The pre-registration uses the organizer's figures because the README values appear to be stale boilerplate carried over from an earlier configuration, and because understating cost is the failure mode that destroys a strategy live rather than merely making it look worse on paper.

This must be confirmed empirically before the live window by placing one minimum-size order with the test keys and reading `CommissionPercent` off the fill.
Until `costs.confirmed` is true in the pre-registration, every net-of-cost number in this repo is provisional.

Shorts are a flat 0.1% on both open and close with no limit-order discount, stated directly in the README: "The fee is `0.1%` of the position value, the same for market and limit orders."
The open fee is charged when the request is accepted, including for a LIMIT order that has not yet filled, and is released only on cancel.
A second `short_open` on a pair already short merges into the existing position at a quantity-weighted average entry price rather than creating a second position.

## spread

Roostoo quotes exactly one tick wide on every pair, so the spread is fully determined by `PricePrecision` from `/v3/exchangeInfo` and needs no estimation:

    spread = 10 ** -PricePrecision

As a fraction of price this ranges over four orders of magnitude across the venue, from 0.0012 bps on BTC/USD to 34.36 bps on BONK/USD, verified against live quotes on 2026-09-18.
This makes spread a hard universe filter rather than a modelling detail, which is why `universe.max_spread_bps` exists and is set at 5.0.

## impact

Gate 9 and the Almgren-Chriss model in Section 4 of the plan are marked not applicable on this venue.

Roostoo publishes no orderbook depth endpoint, fills are synthetic against the quoted `MaxBid` and `MinAsk`, and the account is capped at 100,000 USD of notional.
There is no mechanism by which order flow at that size moves the quoted price, and no data with which to calibrate an impact model if there were.

Recording this as not applicable is deliberate.
Silently skipping a gate and declaring a gate inapplicable with a reason are different claims, and only the second one survives review.

## tokenized-stocks

The venue lists 21 tokenized equities alongside 65 cryptocurrencies, and they are excluded from the research universe.

They do not freeze outside US market hours.
Checked against Binance klines for the weekend of 2026-09-12: NVDABUSDT printed 60 consecutive hourly bars with non-zero volume and genuine price movement, so there is no stale-price or gap effect to trade.

The disqualifying constraint is history.
NVDABUSDT and TSLABUSDT begin 2026-06-11 and QCOMBUSDT begins 2026-07-07, giving 73 to 99 days.
That cannot support the purged cross-validation, walk-forward, and regime partitioning that Gates 3, 6, and 8 require, and `universe.min_history_bars` of 2160 hourly bars excludes them mechanically.

## sample-size

The live competition window is 14 trading days, which is 14 daily return observations.

No procedure in Section 5 can establish significance from that sample, and none is attempted.
The validation framework governs which strategy is deployed.
The live result is a single draw from the return distribution that framework validated, and it is reported as such.

This matters for the final presentation, which is judged in part on backtesting and validation.
Claiming a 14-day live Sharpe as evidence of edge is the specific error the judging panel is best equipped to detect.

## scoring-funnel

The competition scores in two incompatible directions and the portfolio construction targets both in sequence rather than either alone.

Screen 2 ranks on raw portfolio return and keeps the top 20 per region.
Screen 3 then ranks survivors on a composite of Sharpe, Sortino, and Calmar.

Maximising raw return means concentrated directional risk, which destroys the Screen 3 composite.
Running market neutral produces an excellent composite and a return near zero, which fails Screen 2.
The objective is therefore to maximise the probability of a positive low-drawdown return subject to clearing the regional top-20 cut, which is what `risk.max_net_exposure` of 0.8 and the 0.12 drawdown circuit breaker encode.

## circuit-breaker

The drawdown circuit breaker is set at 12% and is fixed in advance, never fitted.

Calmar over a 14-day window has its denominator set by a single bad session, so a drawdown control acts directly on the scored metric.
That is precisely why it must not be tuned: a threshold selected by sweeping it against historical performance is a timing overlay wearing a risk-management label, and timing overlays in this operator's prior work have reversed out of sample repeatedly.

It is declared as risk management, and `risk.circuit_breaker_is_fitted` is false and stays false.

## trial-counting

The multiple-testing correction in Gates 4 and 7 counts every configuration evaluated, including those abandoned before producing a result.

Searches that return nothing still consume the family-wise error budget.
A trial that was run and discarded is indistinguishable, statistically, from one that was run and reported, and omitting it inflates the Deflated Sharpe Ratio of whatever survives.
The ledger at `config/trials.yaml` is append-only for this reason.

## trial-counting-rule

The raw ledger length is not the only defensible denominator, and this section states the rule that decides, so that the question is settled rather than re-argued.

`n_trials` enters `gates/gate04_deflated_sharpe.py` at exactly one place.
It is the `n` of `expected_max_sharpe`, which is the expected maximum of `n` independent draws from the null.
Its meaning is therefore the number of candidates whose MAXIMUM is being reported, not the amount of compute that was spent.
Those two quantities are equal only when every evaluated configuration was eligible to be the thing that got deployed.

**The rule.**
For a deflated Sharpe applied to strategy S, N is the number of configurations that were eligible to be deployed instead of S, scored on the same objective, on the same sample.

Applied uniformly to every row of the ledger:

1. A row counts if it carries a score on S's objective and a better score would have displaced S.
2. A row that states of itself that it was never a candidate does not count, because no maximum can be taken over it. This covers `per_asset_attribution_not_a_candidate`, `sensitivity_grid_not_selection`, `lookahead_control`, `regime_partition`, and the rows noted `not deployable`.
3. A row that is a re-evaluation of an already-counted configuration rather than a new one does not count. This covers `walk_forward_fold`, where seven folds are seven measurements of one candidate.
4. A row scored on a different objective forms a different family. Screen 3 composite, `p_qual` and `ev` rows deflate whatever was selected on those objectives, not the Sharpe-selected book.
5. Nulls count. Abandoned searches count. Failing to record a score is never a discount, so an unscored row that was genuinely a candidate still counts.
6. Ties break toward counting.

**The rule was written and committed before the resulting number was computed.**
That ordering is the only thing that separates a counting rule from a fitted one, and a rule chosen after seeing which number helps is not a correction, it is the same search it claims to correct for.

**Applied to the ledger at 754 rows:**

| bucket | rows |
|---|---|
| excluded, never a candidate or a re-evaluation (clauses 2 and 3) | 120 |
| Screen 3 / EV family (clause 4) | 164 |
| **Sharpe family, the denominator for Gate 4** | **470** |

Those are the counts at 754 rows, the ledger size when the rule was written.
The ledger is append-only so all four numbers move; `core.config.trial_counts_by_family` is the live figure and the gate artifact records whatever held when it ran.
Nothing below changes, because the conclusion does not turn on a few rows either way.

**Outcome: the rule does not recover Gate 4, and this closes the question.**

| N | null expected max Sharpe | flagship DSR | passes 0.95 |
|---|---|---|---|
| 754, raw ledger | 1.806 | 0.8009 | no |
| **470, this rule** | **1.726** | **0.8444** | **no** |
| 94 | 1.325 | 0.9500 | the largest N that would pass |

No honest reading of this ledger reaches 94.
Getting there would mean discarding roughly seven eighths of the work, including grids that were unambiguously searches for a winner.

The two remaining levers close as well, and they close by arithmetic rather than by judgement:

- **More observations cannot do it in time.** At N=470 the minimum track record length is 3,579 daily observations, about 9.8 years. The book has 1,358, about 3.7 years. At N=754 it is 5,145, about 14.1 years.
- **A higher realised Sharpe cannot do it either.** At T=1358 the flagship would need an annual Sharpe of 2.498 at N=470, or 2.576 at N=754, against the 2.206 it has. Confirming the fee schedule moves Sharpe by roughly 0.11 per 5 bps in the favourable direction at most, which is an order too small.

**Therefore Gate 4 is not recoverable, and no further research should be spent trying.**
The raw Sharpe of 2.206 is real and the strategy may well work.
What is established is that this sample cannot distinguish it from the best of 470 null draws at 95% confidence, and the submission must say exactly that rather than choosing a denominator that flatters it.

Both numbers are reported together from here on, never one instead of the other.
`trial_count()` continues to return the raw 754 so that no artifact is silently re-based; the rule is a stated reading of that number, not a replacement for it.

## rotation-hysteresis-outcome

Declared at `config/rotation_hysteresis.yaml` before any backtest, from arXiv:2606.00060's cost-aware execution filter.
Full literature context at `RESEARCH_SHORT_HORIZON.md`.

**Zero of nine arms is a result worth acting on, and the two that pass the letter of the criteria are inside this repo's own noise.**

| book | lambda | turnover removed | fit Screen 3 | holdout Screen 3 | vs random control | drawdown | verdict |
|---|---|---|---|---|---|---|---|
| momentum_top5 | 1 | 1.1% | -0.0020 | +0.0165 | +0.0206 | +0.2pp | fail, fit window |
| momentum_top5 | 2 | 2.5% | +0.0027 | +0.0244 | +0.0415 | +0.6pp | passes, but see below |
| momentum_top5 | 4 | 4.7% | +0.0059 | +0.0199 | +0.0209 | +0.9pp | passes, but see below |
| momentum_top3 | 1 | 1.3% | +0.0032 | -0.0260 | -0.0445 | -1.0pp | fail |
| momentum_top3 | 2 | 3.1% | +0.0069 | -0.0318 | -0.0162 | -2.1pp | fail |
| momentum_top3 | 4 | 6.1% | -0.0008 | -0.0654 | -0.0598 | -2.3pp | fail |

The two passing arms improve fit Screen 3 by 0.0027 and 0.0059.
`DECISIONS.md#sizing-sweep-outcome` already calls a spread of **0.027** on that same statistic noise.
These are four to ten times smaller than the threshold this repo has already committed to treating as indistinguishable from zero, so they are not read as a finding.

**The mechanical reason the filter cannot bite is the same reason the paper's rule does not transfer.**
`lambda * 10 bps` is at most 40 bps, against 40-bar momentum score dispersion measured in whole percent.
Almost no rotation clears the bar: turnover falls by 1.1% to 6.1% across the grid.
Making it bite would need `lambda` around 50 to 100, at which point it is no longer cost-aware, it is an arbitrary hysteresis band with a free parameter fitted to the data.

**The declared failure mode fired, on the book where it was predicted to.**
The declaration said hysteresis may do nothing but hold stale names through drawdowns, and to read maximum drawdown even if Sharpe improved.
On `momentum_top3` drawdown worsens monotonically with lambda, to -2.3 points, while holdout Screen 3 falls monotonically to -0.0654.
With three names a blocked rotation is a third of the book, so the stale-holding cost scales with concentration. On `momentum_top5` drawdown mildly improves instead.

**The nonsense control earned its place.**
A random arm blocking the same fraction of rotations makes the holdout WORSE than baseline on `momentum_top5` at every lambda.
So the small positive effect there is score-gap selection rather than turnover reduction, and is the right sign.
It is simply an order of magnitude too small to act on. Without this control the +0.024 would have looked like a mechanism rather than a coin flip, which is the mistake `#exit-clock-outcome` records.

**Equivalence was asserted before any arm was read.**
`gates/rotation_hysteresis.py` refuses to run unless `rotate(live, score, n, gap=0)` reproduces the unconditional top-n book exactly.
It caught a real discrepancy on the first run: two 2018 rows where a live name had no momentum score yet was treated as eligible at negative infinity, where `score.where(live).rank()` correctly drops it.
Both rows sit outside the fit and holdout windows and would have changed nothing, which is exactly why an assertion rather than an eyeball was needed.
At `gap=0` the top-5 arm reproduces the committed `concentration_tf.json` holdout figures of Screen 3 3.4095 and Sharpe 1.7864 to the digit.

Fifteen rows recorded: nine scored arms and six `nonsense_control` rows, which are excluded from the Sharpe family by `#trial-counting-rule` clause 2 because a deliberately random rule was never deployable.
No live bot is changed.

## passive-fill-adverse-selection

arXiv:2502.18625 measures a negative correlation between a maker order's fill probability and its post-fill return on the Binance BTC perpetual.
The mechanism is mechanical rather than statistical: if the next price move is against a resting top-of-book order, that order fills with probability 1.
A trader who never crosses is therefore filled preferentially on the trades that were about to go wrong and missed on the ones about to go right.

This repo is limit-first by design and never crosses.
`portfolio/backtest.py` sets `crossing = 0.0` whenever `execution == "LIMIT"`, so every backtest in this repo charges the limit fee and **zero spread** and assumes the intended trade happens at the bar close.
There is no adverse-selection term anywhere in the cost model, and `costs/model.py` `spot_round_trip_bps` likewise returns fees only for LIMIT.
This matters because it is NOT a fee question: confirming the schedule with the organisers, which is the top priority elsewhere, would leave it untouched.

The true cost is not directly measurable without live fills, but it is bracketed by two ends the repo can already compute, using its own `daily.half_spread_bps`:

- **optimistic**, what the repo assumes today: fee only, the passive fill captures the full spread with certainty
- **pessimistic**: fee plus the full half spread, the passive fill captures no spread advantage at all

Mean half spread across the panel is 4.17 bps. Scored on the OOS window from 2023:

| book | assumption | Sharpe | Sortino | Calmar | Screen 3 |
|---|---|---|---|---|---|
| donchian_4h | fee only | 2.205 | 4.276 | 4.571 | 3.743 |
| donchian_4h | fee + half spread | 2.163 | 4.179 | 4.385 | 3.636 |
| | **delta** | **-0.042** | -0.096 | -0.186 | **-0.107** |
| momentum_top5 | fee only | 2.427 | 4.793 | 10.387 | 4.145 |
| momentum_top5 | fee + half spread | 2.355 | 4.629 | 9.590 | 4.058 |
| | **delta** | **-0.071** | -0.164 | -0.797 | -0.087 |
| momentum_top3 | fee only | 2.382 | 5.034 | 13.379 | 4.215 |
| momentum_top3 | fee + half spread | 2.314 | 4.865 | 11.912 | 4.140 |
| | **delta** | **-0.068** | -0.169 | -1.467 | -0.075 |

**The assumption is optimistic but bounded, and the bound is small.**
Even at the pessimistic end, where a passive fill is priced as if it captured nothing at all, `donchian_4h` loses 0.042 Sharpe and 0.107 Screen 3 and every book survives.
The reason is holding period: these books turn over 305 to 1730 units of weight over 3.7 years at a 4h clock, so a 4 bps per-side term is amortised over multi-day moves.

**This is why the existing priority ordering is right.**
Fee uncertainty is worth 0.114 Sharpe per 5 bps on `donchian_4h`; adverse selection is worth at most 0.042 in total.
Confirming the schedule is roughly three times more valuable than resolving the fill model, so `ORGANISER_QUESTIONS.md` stays first.

The finding would invert at a shorter holding period, which is a further reason not to shorten it.
A book trading hourly would pay this term on every leg with a far smaller expected move to amortise it against, and that is exactly the regime where arXiv:2608.21888 measures a 1.3 bps gross edge.
This is recorded as a re-scoring of already-counted configurations and adds no trials, per `#trial-counting-rule` clause 3.

## scalper-v1-outcome

Built on operator instruction as a separate paper-only family, declared at `config/scalper_v1.yaml` with a binding kill criterion written before any backtest.

**Zero of 64 configurations survive. The family is killed by its own pre-registered criterion, and it fails in precisely the way the declaration predicted.**

The criterion was median per-trade net return above 0 bps AND mean above the 10 bps round trip, on at least 200 holdout trades:

| | result |
|---|---|
| arms with 200+ holdout trades | 64 of 64 |
| **arms with a positive MEDIAN** | **64 of 64** |
| arms with mean above 10 bps | **0 of 64** |
| arms with mean above **zero** | **0 of 64** |

**Every single configuration has a positive median trade and a negative mean trade.**
The best arm (30m, `ret>=0.008`, `ofi_z>=2.0`, 0.5 ATR target, 8-bar time stop) wins **66.5%** of its trades, shows a median of **+26.72 bps**, and loses **-5.93 bps per trade on average**.

This is the declared failure mode, verbatim: "a small target with a wide stop manufactures a high win rate while losing money, which is the textbook way to make a scalper look good. Win rate is therefore NOT reported as a headline and the median is. Expect high win rate with negative expectancy."

**A 66% win rate with negative expectancy is the single most dangerous shape in trading, and this family produces it in all 64 arms.** Had the criterion been win rate, or median, or "does it feel like it is working", every arm would have passed.

### The controls locate a real but insufficient signal

All four at the same specification:

| arm | n | median bps | mean net bps | **mean GROSS bps** | win rate |
|---|---|---|---|---|---|
| **divergence** | 559 | +26.72 | **-5.93** | **+4.07** | 0.665 |
| sign_flip (ride instead of fade) | 560 | +24.38 | -17.04 | -7.04 | 0.625 |
| no_flow_gate (fade without flow) | 7202 | +23.27 | -13.13 | -3.13 | 0.629 |
| random (same rate, ignores flow) | 214 | +13.41 | -14.68 | -4.68 | 0.603 |

The ordering is coherent and it replicates `#flow-scalp-outcome` exactly: fading beats riding by 11.1 bps, the flow gate beats no gate by 7.2 bps, and both beat random. **The taker-flow conditioner carries genuine information, worth about +4.07 bps GROSS per trade.**

It is not enough. Against a 10 bps round trip a +4.07 bps gross edge is a -5.93 bps net loss, and no threshold, target, time stop or cost gate in the grid closes a 6 bps gap. Raising the flow threshold from 1.5 to 2.0 improves the mean from -9.90 to -5.93 and cuts trades from 1673 to 559 - the same trade-off arXiv:2608.21888 describes as "trading fewer, better bars shrinks the opportunity count faster than it grows the edge".

This is now the **third independent measurement** of the same quantity in this repo, agreeing to within a few basis points: `#scalp-meanrev-outcome` (0 of 54), `#flow-scalp-outcome` (0 of 72, +3 to +11 bps gross), and this (0 of 64, +4.07 bps gross). arXiv:2608.21888 measures 1.3 bps across 183 pairs. **Sub-hourly gross edge on liquid crypto is real and is roughly 1 to 11 basis points. The round trip is 10. That is the whole story and it should not be measured a fourth time.**

### Scope limits that also bind

Only BTC, ETH, SOL, XRP and DOGE have 5m history cached. Five names is not a cross-section and nothing here generalises to the 30-name pool.
Every bar that would have touched both target and stop is resolved as a **stop**, which is the unfavourable assumption; a favourable resolution would flatter these numbers and would be wrong.

**No live bot is created.** The declaration's promotion clause allowed a paper bot only on a pass, and there is no pass.

67 rows recorded, 3 of them `nonsense_control`.

## fast-exit-sizing-outcome

Declared at `config/fast_exit_sizing.yaml`. The thread from `#reversal-reentry-outcome`: the fast exit without re-entry is the only arm to improve a holdout twice, and both prior tests rejected it on the fit window **at a fixed position size**. The question neither asked was whether it buys SIZE.

**The hypothesis is refuted directly. The fast exit does not truncate the left tail, it deepens it, at every size tested.**

| divisor | d fit S3 | d holdout S3 | d maxDD | d Sharpe | d CAGR | verdict |
|---|---|---|---|---|---|---|
| 20 | -0.0787 | +0.0687 | **-0.72pp** | +0.054 | +0.020 | fail |
| 10 | -0.0920 | +0.2064 | **-0.52pp** | +0.105 | +0.076 | fail |
| 5 | -0.0809 | +0.1835 | **-1.70pp** | +0.101 | +0.108 | fail |
| 3 | -0.0663 | +0.3300 | **-1.51pp** | +0.155 | +0.215 | fail |

Zero of four pass. Drawdown is worse at **every** divisor, which is the declared failure mode and kills the premise: a rule that deepens the drawdown cannot be what lets you carry more of it.

**The shape of the failure is worth recording.** The fit-window penalty is roughly constant in size (-0.066 to -0.092) while the holdout gain grows with concentration (+0.069 at 1/20 to +0.330 at 1/3). That is what a window-specific artifact looks like when exposure is raised: more gross amplifies whatever that window happened to do, in both directions. It is not evidence of a mechanism, and it is the third independent time this exit has won a holdout and lost a fit window.

**This closes the fast-exit thread.** Three implementations, three different sweeps, same answer: it improves the holdout, fails the fit window, and worsens drawdown. Do not open it a fourth time without new data rather than a new parameterisation.

### The sizing curve is the useful by-product

Measured on the slow clock, so it is independent of the exit question:

| divisor | mean gross | P(clears Screen 2) | holdout Screen 3 | maxDD | holdout CAGR |
|---|---|---|---|---|---|
| 20 (live `donchian_4h`) | 0.184 | 0.2248 | **2.9297** | **-17.65%** | 0.644 |
| 10 | 0.323 | 0.2752 | 2.5488 | -25.09% | 0.843 |
| 5 | 0.467 | 0.3567 | 2.4902 | -33.61% | 1.119 |
| 3 | 0.560 | **0.3925** | 2.0741 | -39.73% | 1.069 |

Qualification probability rises monotonically with size and Screen 3 falls monotonically, with no interior point where both improve. That is `#beta-is-the-only-screen3-lever` measured directly on the flagship book rather than inferred, and it quantifies the trade in `#competition-book-selection`.

**It also confirms the book choice made there.** Sizing `donchian_4h` up to 1/3 reaches P(Screen 2) 0.3925 with holdout Screen 3 of 2.07 and -39.7% drawdown. `momentum_top3_4h` reaches **0.4283 with Screen 3 of 3.33** at a comparable -43.2%. The momentum ranking is therefore adding real value over brute concentration: better on BOTH axes at similar drawdown. Raising the divisor is not a substitute for it.

Note CAGR peaks at divisor 5 (1.119) and falls at 3 (1.069): past that point concentration costs return as well as Screen 3.

Eight rows recorded. No live bot is changed.

## reversal-reentry-outcome

Declared at `config/reversal_reentry.yaml` on operator instruction, explicitly without regard to the prior exit nulls.

**This was a genuinely new mechanism, not a fifth repeat, and it still fails.**
The four prior exit families all made the EXIT faster while RE-ENTRY stayed on the slow clock.
`signals/exit_clock.py` says so in its own docstring, and `#exit-clock-outcome` records the failure mode as the book re-entering "at the next 4h close at a HIGHER price".
This arm lifts exactly that constraint: fast exit on a floor break, fast re-entry when price reclaims the floor.

**Zero of 24 arms pass, and the hypothesis is refuted in its own direction.**

| arm | fit Screen 3 | holdout Screen 3 | holdout maxDD | turnover |
|---|---|---|---|---|
| momentum_top5 baseline, slow clock | **4.4786** | 3.5563 | **-36.87%** | 2060 |
| fast exit, NO re-entry | 4.4052 | **3.7510** | -39.71% | 2447 |
| fast exit + re-entry, best (rc=50) | 4.4145 | 3.6858 | -38.98% | 2497 |
| fast exit + re-entry, worst (rc=0) | 4.4110 | 3.6640 | -40.05% | 2576 |

**Re-entry makes it worse, not better.**
Every re-entry arm scores below `fast_exit_no_reentry` on the holdout, 3.66 to 3.69 against 3.751, at higher turnover.
Re-entering after a reclaim is not catching false breaks cheaply; it is buying back into continued weakness.
The reclaim margin behaves monotonically in the direction that says so: the wider the margin, the less often it re-enters, and the better it does (rc=0 -> 3.664, rc=50 -> 3.686). The best version of this rule is the one that re-enters least.

**The declared failure mode fired.** Maximum drawdown worsens in every arm, by 2.1 to 3.2 points, exactly as `#exit-clock-outcome` found.

### The turnover-matched control is what settles it

The sweep's built-in random control was mis-calibrated and traded no more than the baseline, so it proved nothing. It was recalibrated by binary search until its turnover matched the best arm to within 0.8 units, and then compared:

| | fit Screen 3 | holdout Screen 3 | holdout Sharpe | maxDD |
|---|---|---|---|---|
| real, floor breaks | 4.4052 | 3.7510 | 2.0317 | -39.71% |
| random, same turnover | **4.4813** | 3.5703 | 1.9179 | -37.77% |
| **real minus random** | **-0.0761** | **+0.1807** | **+0.1138** | |

**The rule beats a coin flip out of sample and LOSES to it in sample.**
A real mechanism beats random on both windows. One that wins on one and loses on the other at matched turnover is a window-dependent artifact, and this repo has been shown that shape before.
Without the matched control the +0.18 holdout gain would have read as a finding.

### What is worth keeping

The fast exit alone, with no re-entry, is the only arm that improves the holdout at all, and it is the same arm `#exit-clock-outcome` already rejected on the same fit-window grounds. That replication is the useful part: two independent implementations, built months apart, agree on both the sign and the reason.

Live corroboration is already running: `donchian_1h` is the small-timeframe book in the stack, and on 2026-09-20 it had the highest trade count of any book, the most dust, and the lowest return.

33 rows recorded, 5 of them `nonsense_control`. No live bot is changed.

## restart-telemetry

The dashboard's "Process integrity" card counted every `resumed` lifecycle event and told the reader "non-zero means the supervisor respawned a dead worker".

On 2026-09-20 it reported 1 to 3 restarts across the stack with **zero crashes**.
The events were an operator stop/start and a one-shot `--once` diagnostic, both of which restore saved state exactly as a respawn does.
There is no worker death anywhere in the run: `live/<bot>.out` contains no `exited code=` line and every error journal is empty.

This is `CLAUDE.md`'s own "telemetry can lie without trading being wrong" a second time, and its cost is specific: a book that looks unhealthy because someone ran a diagnostic sends the reader hunting for a fault that never happened.

Three states are distinguishable and are now reported separately by `bot/health.py`:

| signal | source | meaning |
|---|---|---|
| **crashes** | `exited code=` in `live/<bot>.out` | the supervisor's own record; a worker actually died. **This is the health signal.** |
| resumes | `resumed` lifecycle events with `mode: continuous` | operator activity |
| probes | lifecycle events with `mode: once` | diagnostics |

`bot/run.py` now records `mode` on the lifecycle event. Events written before that are counted as `legacy_resumes` rather than silently reclassified as either.

## dust-trades-distort-count-statistics

A count-weighted statistic gives a 5 dollar rounding residue the same vote as a 20,000 dollar position.

On 2026-09-20 `donchian_1h` reported 11 closed trades, a 72.7% win rate and a **payoff ratio of 2,156**.
Five of those trades were TRX round trips of 3 to 19 dollars notional whose net P&L was under a cent.
Stripping them: **6 material trades, all winners**, and no payoff ratio at all because there is no material loser to divide by.
The `avg_loss` of -0.005 that produced the 2,156 was half a cent.

`bot/blotter.py` now splits the two at a stated `DUST_NOTIONAL` of 50 dollars and reports **both** `win_rate` (material only) and `win_rate_all_trades`, so the threshold cannot hide anything.
It is a reporting threshold and changes no trading decision.
Note this compounds a limit already recorded: win rate is meaningless below about 30 closed trades regardless, so neither number is readable yet.

## live-rebalance-chases-drift

The dust above is not a reporting artifact. It is real turnover paying real fees, and **the backtest never charged for it.**

The two measure different things:

- **Backtest turnover** is `|w_t - w_{t-1}|` on TARGET weights. A target that does not change contributes zero.
- **The live book** calls `deltas(target, current)` where `current` is the DRIFTED ACTUAL weight. A held position's weight moves with its mark, so an unchanged target still emits an order every cycle.

At a 5% target on a 100,000 book, a 0.1% price move produces a 5 dollar order, a 0.5% move a 25 dollar order. `min_notional` was 1 dollar, so all of them passed.

**The fix needed no new parameter.** `preregistration.yaml` already carries `portfolio.no_trade_band: 0.25` with `no_trade_band_is_fitted: false` and a grid containing exactly one value. `portfolio/construct.py` implements it and several gates apply it; the live path did not use it anywhere. `bot/portfolio.deltas` now defaults to the pre-registered value.

An open or a close is never suppressed, because one side is zero and the move therefore always exceeds `band * max(|tw|, |cw|)`. Only drift is suppressed.

### The band tested on the backtest is a null, and that is consistent

`#no-trade-band-live-outcome`: applying the same 0.25 band inside the backtest changes `momentum_top5` and `momentum_top3` **not at all** - the results are bit-identical - and moves `donchian_4h` by +0.17 holdout Screen 3 on a 1.2% turnover reduction.

That null is the point rather than a disappointment.
The momentum books hold equal weights of exactly 1/n, so every target move is a full open or close and nothing is ever a partial rebalance for a band to suppress.
The backtest has no drift to suppress **because it never modelled drift in the first place**, which is precisely the divergence.
The band matters live and cannot matter in backtest, so the backtest could never have found this.

## no-trade-band-live-outcome

Declared at `config/no_trade_band_live.yaml`. Six configurations, the pre-registered value against no band, three books.

| book | band | turnover | fit Screen 3 | holdout Screen 3 | holdout Sharpe | holdout maxDD |
|---|---|---|---|---|---|---|
| donchian_4h | 0.00 | 456.0 | 4.3809 | 2.6234 | 1.5627 | -17.66% |
| donchian_4h | 0.25 | 450.4 | 4.3762 | **2.7953** | 1.5940 | **-16.93%** |
| momentum_top5 | 0.00 | 2035.8 | 4.4427 | 3.4095 | 1.7864 | -32.92% |
| momentum_top5 | 0.25 | 2035.8 | 4.4427 | 3.4095 | 1.7864 | -32.92% |
| momentum_top3 | 0.00 | 2834.3 | 4.5027 | 3.3266 | 1.6277 | -43.23% |
| momentum_top3 | 0.25 | 2834.3 | 4.5027 | 3.3266 | 1.6277 | -43.23% |

`donchian_4h` fails the declared bar: holdout Screen 3 improves but the fit window does NOT (4.3762 against 4.3809), and the pass criterion required both.
Drawdown improves by 0.7 points, which is the declared failure mode not firing rather than a finding.
The momentum arms are identical to the digit.

**No book is changed on the strength of this.** The live `deltas` change stands on the drift argument above, which this sweep cannot speak to.

## max-return-levers-outcome

Three remaining levers on 14-day portfolio return, scored on the return distribution rather than Screen 3. Reasoning and the full tables are in `HANDOVER.md` section 4e.

**L1, concentration: top3 is the floor and going past it is overfitting.** Holdout median falls 3.12 (top3) to 0.44 (top2) to **-2.56** (top1) while the FIT window keeps improving, 4.10 to 4.71. top1 carries an **81.8% drawdown**. The trap is that P(>20%) keeps RISING to top1, 0.168 to 0.220: the far tail improves because the book becomes a lottery ticket, not because it gets better. A reader optimising only the far tail picks the worst book on the list.

**L2, BTC floor when nothing signals: undecided, and deliberately so.** `momentum_top3_full` holds 100% cash 14.5% of the time. Filling it with BTC lowers the holdout median 3.12 to 2.63 and P(>5%) 0.467 to 0.454, while raising P(>10%) 0.321 to **0.347** and P(>20%) 0.168 to **0.182**, at a cost of 8 points of drawdown. Whether that is a good trade depends on where the top-20 cut falls: below ~5% the floor loses, at ~10% or above it wins. That is question 6 of `ORGANISER_QUESTIONS.md` and it is not resolvable from price data. **Not adopted**, because it spends 8 points of Calmar for a benefit conditional on an unknown.

**L3, the derisk ramp costs about 1 point of return.** Ramping exposure to zero over the final 2 of 14 days moves holdout median 3.12 to 2.09 and P(>5%) 0.467 to 0.432; a 3-day ramp costs 1.52 points. **The cost is measured and the benefit is not**: the drawdown figures here come from the full daily series and do not reflect the ramp, so its protective value is unquantified. Do not remove the ramp on this table alone. Either measure the protection or decide it as a risk preference.

Six rows recorded. The only configuration adopted from this work is `momentum_top3_full`, already live as a gated arm.

## full-deployment-outcome

Operator confirmed the official rules: **Screen 2 advances the top 20 per region ranked on portfolio return, `(Final - Initial) / Initial`**, and Screen 3 scores only the survivors. Returns are therefore the primary objective and the composite is secondary.

Every prior sweep in this repo scored Screen 3. This one scores the 14-day RETURN DISTRIBUTION, which is what Screen 2 actually measures. Beating a rank cut is a **right-tail** problem, not a median one.

### The candidate books on Screen 2's own metric, holdout

| book | gross | median % | P(>5%) | P(>10%) | P(>20%) | p99 % | worst % |
|---|---|---|---|---|---|---|---|
| donchian 1/20 (live) | 0.30 | 0.27 | 0.210 | 0.091 | 0.021 | 23.2 | -10.0 |
| donchian 1/10 | 0.47 | 0.17 | 0.264 | 0.169 | 0.044 | 32.4 | -13.6 |
| donchian 1/5 | 0.62 | 0.77 | 0.345 | 0.218 | 0.077 | 33.3 | -21.0 |
| donchian 1/3 | 0.72 | 0.38 | 0.384 | 0.233 | 0.093 | 39.1 | -32.0 |
| momentum top5 (live) | 0.62 | 1.28 | 0.370 | 0.261 | 0.137 | 68.8 | -21.4 |
| **momentum top3 (live)** | 0.72 | **1.92** | **0.428** | **0.288** | **0.164** | **128.2** | -31.0 |
| BTC hold | 1.00 | 0.05 | 0.230 | 0.091 | 0.016 | 23.3 | -29.8 |

`momentum_top3` wins every right-tail measure, and it beats `donchian 1/3` at **identical 0.72 gross** on all of them with a shallower worst case. The momentum ranking is producing the tail, not the exposure. BTC hold carries full gross and has a ten-times thinner right tail at P(>20%).

**This confirms `#competition-book-selection` on the metric that actually decides it**, rather than on the Screen 3 proxy used there.

### Idle cash is the largest remaining drag

`momentum_top3_4h` averages **0.72 gross** because only two of its three slots typically fire, leaving a third of the book in cash. Under a return-ranked objective that cash contributes nothing.

Full deployment spreads the book across whatever signalled:

| book | window | gross | median % | P(>5%) | P(>10%) | P(>20%) | maxDD % |
|---|---|---|---|---|---|---|---|
| top3 fixed 1/n | fit | 0.73 | 3.32 | 0.458 | 0.364 | 0.220 | **-31.8** |
| top3 FULL | fit | 0.83 | **4.10** | **0.476** | **0.389** | **0.242** | -49.2 |
| top3 fixed 1/n | hold | 0.72 | 1.92 | 0.428 | 0.288 | 0.164 | -43.23 |
| top3 FULL | hold | 0.85 | **3.12** | **0.467** | **0.321** | **0.168** | -43.32 |

**It improves the right tail on BOTH windows**, which nothing else tested in this session has managed. Holdout median 14-day return rises 1.92% to 3.12% with maximum drawdown essentially unchanged.

**The cost, stated plainly.** The FIT window drawdown deteriorates from -31.8% to -49.2% while the holdout stays flat. The honest reading is that this configuration CAN produce a ~50% drawdown and the holdout simply did not contain the path that produces one. Calmar is 0.3 of the Screen 3 composite, so what this buys in Screen 2 it may hand back in Screen 3. **It is the right trade only while qualification binds.**

### What was changed

`bot/portfolio.target_weights` gained an opt-in `full_deployment` flag, **off by default**, so every existing book is byte-identical. Gross is still capped on GROSS and never on a scalar.

`momentum_top3_full` runs live as a **gated arm against `momentum_top3_4h`**, identical in every other respect, so the treatment is the sizing alone. It is not a replacement and the forward comparison is not readable for 28 days.

## competition-book-selection

**`momentum_top3_4h` is the competition entry. `donchian_4h` is not.**
This reverses the reading that the robust book is the safe choice, and the reason is that Screen 2 is a hard cut rather than a preference.

### The forward evidence cannot arrive in time, so this is decided on what is already known

Nothing in `paper_lab_v8` or the cushion A/B is readable before **28 complete days**, which lands **2026-10-18**.
The competition runs **2026-10-04 to 2026-10-17** and therefore ENDS the day before the first forward comparison becomes readable.
Every forward experiment now running completes after it can influence anything.
They remain worth running as crash canaries; they are not selection inputs, and treating them as such would be reading a lead the repo's own `min_comparison_days` forbids.

### Screen 2 binds, and the ranking on it is the reverse of the ranking on quality

| book | P(clears Screen 2) | Screen 3 median | max drawdown | Sharpe |
|---|---|---|---|---|
| **momentum_top3_4h** | **0.4283** | 3.327 | **-43.2%** | 1.628 |
| momentum_top5_4h | 0.3697 | 3.409 | -32.9% | 1.786 |
| btc_hold | 0.3026 | 2.150 | -53.0% | 1.147 |
| donchian_4h | 0.2335 | 2.512 | -17.7% | 2.206 |

`donchian_4h` has the best Sharpe and the shallowest drawdown in the repo and **qualifies least often of the four**.
At 1/20 sizing it ran 15% gross and 85% cash on 2026-09-20, which cannot produce a top-20 raw return over fourteen days.
A book that does not clear Screen 2 scores nothing on Screen 3, so its quality is unrealisable.

This is `#beta-is-the-only-screen3-lever` applied rather than merely recorded: within a fortnight the composite is governed by the sign of the window's return, which is governed by beta, so cutting beta cuts P(positive), P(qualifying) and the composite together.
There is no interior point where both improve. The concentrated book is not the reckless choice, it is the only one with a ticket.

### What is being accepted, stated plainly

- **-43.2% maximum drawdown**, the deepest of any configuration measured here, against -32.9% at top5.
- At its deployed parameters `momentum_top3_4h` is **worse than `momentum_top5_4h` on every risk-adjusted measure** (`#top3-deployed-parameters-were-never-measured`): Sharpe 1.628 against 1.786, Sortino 3.346 against 3.434, Calmar 5.958 against 6.160, Screen 3 3.327 against 3.410.
  It wins on exactly one axis, qualification probability, 0.4283 against 0.3697.
- **Gate 4 still fails** at DSR 0.8445 against 0.95 and is unrecoverable (`#trial-counting-rule`). This selection does not repair that and the submission must say so.

So the choice is a bet that the rank gate binds. It is chosen on a stated objective, not on a backtest ranking.

### The one input that would reverse it

How many entrants advance from Screen 2 per region, and how large the field is.
If the cut is loose enough that most reasonable entries survive, qualification stops binding and `donchian_4h`'s 2.206 Sharpe and -17.7% drawdown become the better book on the composite that then decides the rank.
This is question 6 in `ORGANISER_QUESTIONS.md` and it is worth more than any backtest available.
**Do not treat this selection as settled until that answer arrives.**

## cold-start-chases-the-bar

A book started mid-bar buys at whatever the price is when it starts, not at the bar close its signal was computed on.

Measured on 2026-09-20. The 4h bar labelled 08:00 closes at 12:00 UTC:

| book | ENAUSDT buy | price | vs the close |
|---|---|---|---|
| donchian_4h | 12:00:33 | 0.2070 | at the close |
| momentum_top5_4h | 12:00:34 | 0.2069 | at the close |
| **momentum_top3_4h** | **12:08:24** | **0.2114** | **+2.17%** |

`momentum_top3_4h` was started at 12:08 and immediately bought a signal generated eight minutes earlier, after the name had already moved 2.17%.
On a 31.8% position that is **0.69pp of NAV given away at the first trade**, before any market move, and it is most of the gap between that book and its siblings for the rest of the session.

This is not the signal, the sizing or the fee schedule. It is cold start.
The bot has no notion that the bar it is acting on has gone stale: `bot/run.py` evaluates on the first cycle and places whatever the current target implies.

It matters more than it looks because the effect scales with concentration.
The same 2.17% cost `donchian_4h` 0.11pp at 1/20 sizing and `momentum_top3_4h` 0.69pp at 1/3.
Any future comparison between books started at different times is confounded by this, and the 2026-09-20 session is one: `momentum_top3_4h` began 8 minutes late and carried the penalty all session.

**Do not read a cross-book comparison whose members were started at different points inside a bar.**
Restart the whole stack together, which `./run_bots.sh start` does, or wait for the next bar close before reading anything.

Not yet fixed. The candidate fix is to refuse the first entry into a name whose bar close is already more than a set fraction of a bar old, and take it at the next close instead.
That is an execution rule with a free parameter, so it needs a declaration and a control before it goes in, and it must not be confused with the exit-tightening families that have already failed four times.

## markout-instrumentation

`#passive-fill-adverse-selection` bounded the unmodelled cost in backtest at 0.042 Sharpe.
Bounding is not measuring, and no backtest can measure it, because the quantity is the price path after a fill the backtest assumes always happened.

Three things were added so it can be measured forward, at zero trial cost.

**The reference quote at submission**, in `Executor.prepare`: `ref_bid`, `ref_ask`, `ref_mid`, `ref_spread_bps`.
Without this there is no baseline, and it is unrecoverable after the fact - the order journal held only the limit price.

**Per-cycle marks**, in the cycle snapshot, scoped to held symbols plus anything traded in the last `MARKOUT_RETAIN_S`.
The retention window exists so an EXIT still has forward marks after its position is gone.
Marking the whole universe every cycle would add roughly 6 MB a day across the stack for data nothing reads.

**`bot/markout.py`**, which computes, for a fill at price `p` on side `s` with mid `m(h)` at horizon `h`:

    markout_bps(h) = sign(s) * (m(h) - p) / p * 1e4

at 60s, 300s, 900s and 3600s, and reports it per bot on the dashboard.
A negative mean is the price moving against the trade after it was made, in basis points, directly comparable to the fee.

**Markout is not slippage and the distinction is the whole point.**
Slippage is fill price against intended price and says whether the order was executed well; this repo already has it.
Markout is the price path after the fill and says whether the order was executed *against*.

### The limitation that governs how the number may be read

**In dry run every order fills at its own limit price by assumption, so no fill is ever declined, and fill SELECTION is therefore not being measured at all.**
What the number measures in dry run is entry timing: when the book decided to trade, which way price went next.
The two quantities differ precisely in the cases arXiv:2502.18625 is about, namely the orders that would NOT have filled.

`bot/markout.py` detects this from the order stream and refuses the stronger claim.
With every order journaled as `dry_run` the verdict reads "DRY RUN - entry timing, NOT adverse selection"; the adverse-selection verdict is reachable only from a stream of real `fill` events.
Both paths are covered by tests.
Real adverse selection therefore remains blocked on the API keys in `ORGANISER_QUESTIONS.md`, which is one more reason that request is the top priority.

### First readings, which are not yet readable

`donchian_1h` is the only book trading often enough to have produced any: mean entry edge **+1.10 bps** against the mid at submission, and a 60-second mean of **-18.94 bps** across **3** fills.
The entry edge is the limit-inside-the-touch working as designed.
The 60-second figure is the predicted sign and **must not be read**, at n=3 against a stated minimum of 30, and it is entry timing rather than adverse selection in any case.
It is recorded here only so that a later session can see whether the sign persisted or reverted.

All six books were restarted on the instrumented code at 2026-09-20T13:20Z, which also resumes the forward-evidence accumulation that `HANDOVER.md` section 9 makes priority 2.
No signal, no sizing and no execution rule changed. This is measurement only and adds no trials.

## top3-deployed-parameters-were-never-measured

`config/momentum_top3_4h.yaml` is live and its `measured_basis` cites `results/concentration.json`: holdout Screen 3 +3.098 at N=3 against +2.957 at N=5, maximum drawdown -42.4% against -33.0%.

Those numbers are from a sweep that hardcodes `momentum_bars = 20`.
`gates/concentration.py` `rank_score` computes momentum as `close / close.shift(20)` with no parameter.
The deployed book runs `momentum_bars: 40`, and the only sweep that varies that parameter, `gates/concentration_tf.py`, fixes `n_positions: 5`.
The deployed configuration, 4h with `momentum_bars=40` at `n=3`, therefore sits in the gap between the two sweeps and had never been measured.

It has now been measured on the same code path, with `n=5` recomputed first as a reproduction check.
All nine fit and holdout statistics reproduced the committed `concentration_tf.json` values exactly, so the harness is the same one that produced the reference.

| holdout, 4h, momentum_bars=40 | n=3 (deployed) | n=5 |
|---|---|---|
| Sharpe | 1.628 | **1.786** |
| Sortino | 3.346 | **3.434** |
| Calmar | 5.958 | **6.160** |
| Screen 3 | 3.327 | **3.410** |
| max drawdown | **-43.2%** | -32.9% |
| P(clears Screen 2) | **0.4283** | 0.3697 |

**At the deployed parameterisation the N=3-over-N=5 ordering reverses on every risk-adjusted measure.**
The config claims N=3 buys +0.141 of Screen 3 for 9.4 points more drawdown.
At `momentum_bars=40` it actually costs **-0.083** of Screen 3 for **10.3** points more drawdown.

The book's stated purpose survives this and its rationale is unchanged.
It was declared for Screen 2 qualification rather than for the Screen 3 composite, and P(clears Screen 2) is still materially higher at N=3, 0.4283 against 0.3697.
What does not survive is the claim that N=3 is also the better Screen 3 book. It is not, at the parameters it runs.

Two conventions are worth restating from this.
A sweep that hardcodes a parameter another config exposes is a gap, not a measurement, and citing across the two is citing a different strategy.
`meta.measured_basis` is a factual claim and ages exactly like a hardcoded path does.

This was recorded as one trial, `4h_mb40_n3`. The `n=5` recomputation is a re-evaluation of an already-counted configuration and does not count, per `DECISIONS.md#trial-counting-rule` clause 3.

## paper-lab-v8-fee-revert

`paper_lab_v7` ran at `fee_bps: 5.0`, the LIMIT rate at `preregistration.yaml` `costs.spot_limit_fee`, which is the rate the live books assume and is internally consistent with this lab's passive fill model.
That is the correct point estimate and it is the wrong rate to run a robustness lab at.

`costs.confirmed` is still false.
Five bps is the favourable end of an unconfirmed range and it assumes an always-maker fill; 10 bps is Binance standard spot and the declared `costs.spot_market_fee`, so it is the unfavourable end of the same range.
A forward comparison is only worth reading if it survives the bad case, because an arm that leads at 5 bps and loses at 10 has said nothing that can be acted on before the schedule is confirmed.

The sensitivity is not cosmetic.
Measured over full history, net, `donchian_4h` loses 0.114 Sharpe per 5 bps and the concentrated books lose about 0.20, which puts both concentrated books below the hurdle at 10 bps while `donchian_4h` clears to roughly 15.

The fee is inside the experiment hash, so this is `paper_lab_v8` rather than an edit to v7.
v7 ran 0.5 hours and is retired with no forward evidence lost.
Revisit when `costs.confirmed` flips, deadline 2026-10-01.

## upstream-defects

Binance's own kline archive contains defects, and they are repaired explicitly rather than silently.

One is present in the current panel.
At the single bar 2020-12-21 14:00 UTC, 100 symbols carry a `close_time` of roughly 13:47 with per-symbol sub-second jitter, placing the bar's close before its open.
The signature, one bar across a hundred symbols with a truncated and jittered stamp, is a system-wide halt on the venue rather than a fault in the loader.

The repair rewrites `close_time` to the bar end and nothing else.
Prices and volumes are untouched, and the bar is not dropped, because dropping it would open a gap in 100 series to hide a defect in one field that no signal in this repo reads.

Every repair is registered in `data/repairs.py` with an identifier and an action, applied at panel build, and reported in the Gate 1 artifact under `repairs_applied`.
A repair that is not in that registry does not happen.

## signal-declarations

Section 2 requires universe, lookback, rebalance frequency, and long/short construction to be fixed before any backtest is run, so they live in `config/signals.yaml` and are committed before the first return is computed.

Each declaration also carries a mechanism and a failure mode, which Section 1 requires and Section 8.5 requires before code is written.
A signal without a written failure mode is not accepted regardless of its backtest.

The `lookback_grid` is the full set of parameter values that will ever be evaluated for that signal.
It is declared up front because every value in it counts as a trial against the multiple-testing budget in Gates 4 and 7, whether or not its result is reported.

## size-proxy

Market capitalisation is not available point-in-time for delisted symbols, so trailing median quote volume is used as the size proxy.

Dollar volume is the standard liquidity proxy, is available in the kline archive for every symbol including delisted ones, and is computable strictly from past data.
Circulating-supply based market cap would require a vendor snapshot that does not exist for the 199 delisted names and would reintroduce the survivorship problem Gate 1 exists to prevent.

## tick-size

Spread is derived from the minimum positive price increment observed in each symbol's own close series rather than from a venue table.

Roostoo's `PricePrecision` was compared against the implied tick from Binance closes across all 65 overlapping symbols on 2026-09-19 and matched exactly on every one.
This makes the estimator usable for the 199 delisted symbols that Roostoo does not list and for which no venue table exists.

The estimate is computed from the trailing window only, never from the full sample, so it carries no look-ahead.

## undeclared-universe-sweep

A universe size parameter was swept during exploration without being pre-registered, and the trials are recorded rather than discarded.

After Gate 2 failed on the declared universe, a liquidity-ranked point-in-time universe was tested at three sizes to check whether the failure was a universe-construction artifact rather than an absence of edge.
`topN` is not in `config/preregistration.yaml`, so those runs are exploratory and none of their numbers may be reported as a gate result.

The sweep produced a peak at `topN=60` and a collapse to negative at `topN=90`, which is the peak-isolation failure Gate 2 is built to detect, applied to a parameter Gate 2 was not watching.
That is the reason the result is not promoted: a maximum selected from an undeclared sweep, with its immediate neighbour negative, is a search artifact.

Using a liquidity-ranked universe in future requires adding it to the pre-registration with an explicit grid before any further evaluation, and every value in that grid counts against the trial budget.

## gate2-outcome

Gate 2 failed on 2026-09-19 and the pipeline stops there.
No signal produced a positive net Sharpe at any declared grid point, and the best gross Sharpe across all three signals sat 1.01 standard deviations above a random-score null, against a Harvey-Liu-Zhu hurdle near 3.0.

The declared mechanism for `xsec_volume` is inverted on this universe: rising relative volume predicted underperformance, at a gross Sharpe of -1.17.
The sign is not flipped, because a sign chosen after seeing the result is a new hypothesis and requires its own stated mechanism, its own declaration, and its own trial count.
The declared failure mode for that signal already anticipated it, since volume spikes on delisting announcements dominate a universe that is three quarters delisted names.

## top20-universe

The research universe is the top 20 names by trailing 30-day median dollar volume, selected point-in-time at each rebalance.

The operator asked for "top 20 crypto on Roostoo", and taken literally that means the 20 names that rank highest on the venue today, which is survivor-conditioned in exactly the way Gate 1 exists to prevent.
The point-in-time construction selects by a rule that was computable at each historical date and does not know which names survived.
Both are computed and reported together, because the size of the gap between them is itself the evidence for which one to trust.

The concentration justifies the cut: the top 20 carry 92.8% of venue crypto dollar volume and a median quoted spread of 1.21 bps, against 4.37 bps for the crypto universe as a whole.
Two members breach the pre-registered 5 bps spread cap, PEPE at 26.32 and APT at 12.85, and are removed by the existing filter rather than by a new exception.

## no-trade-band

A no-trade band of 0.25 of target weight is applied and is not fitted.

Gate 2 failed with annual turnover between 93 and 157 times and cost drag between 15% and 25% of NAV, which would destroy a real edge if one existed.
The band is set by reasoning rather than by sweeping it against performance: trade only when a position has drifted by more than a quarter of its target, which is the point where the correction is large enough to be worth two crossings of a roughly 20 bps round trip.

`no_trade_band_grid` contains a single value deliberately.
Sweeping the band against realised Sharpe would convert a cost control into a fitted parameter, which is the same error recorded at `DECISIONS.md#undeclared-universe-sweep`.

## mid-frequency

Holding period is targeted in days to weeks, not minutes, and this is a constraint rather than a preference.

The competition rules prohibit high-frequency trading, market making, and arbitrage, and require medium-frequency directional strategies.
Independently, the fee structure forces the same answer: at 10 bps per side a 1% total fee budget buys about ten full-notional round trips, so a 14-day window supports roughly one per day at most.
Daily-bar SMA signals with a no-trade band produce multi-week holds naturally, and realised holding period is reported rather than assumed.

## trend-family-outcome

The SMA and volume family was tested on the point-in-time top-20 venue universe on 2026-09-19 and Gate 2 failed, on the benchmark criterion rather than on stability.

Out of sample from 2023-01-01, no configuration of any of the three signals beat BTC buy-and-hold, which returned 53.1% a year at a Sharpe of 1.15 over the same window.
The best configuration, `volume_confirmed_trend` at a 5-day volume lookback, returned 23.7% at a Sharpe of 0.87.
A strategy that loses to the single asset it is built on does not advance, whatever its in-sample record.

Two findings are worth keeping despite the failure.

`sma_crossover` at 10/50 is a clean overfitting signature: it was the strongest configuration in sample at 1.23 and among the weakest out of sample at 0.41, an OOS-to-IS ratio of 0.31.
Selecting on the full-sample number would have chosen precisely the worst-decaying member of the family.

`volume_confirmed_trend` is parameter-stable in a way the other two families are not.
Its out-of-sample Sharpe spans 0.80 to 0.88 across all three declared volume lookbacks, a spread of 0.08, against 0.45 for `sma_crossover` and 0.50 for `sma_distance`, and its worst OOS-to-IS ratio is 0.80.
That flatness is the signature of a weak real effect rather than a fitted one, and it is the only member of the family that would survive Gate 6.

Its value is in drawdown rather than return.
Out of sample it drew down 30.6% against BTC's 53.0% while capturing under half the return, which is a shape result, not an edge.
The same pattern has now appeared in this operator's trend work repeatedly, and it is recorded here so the next cycle does not rediscover it.

## competition-vs-deployment

The trend family scores better against the competition's rubric than against a deployment standard, and the distinction must not be blurred.

Screen 2 ranks on raw return over 14 days, where BTC buy-and-hold would likely beat `volume_confirmed_trend`, since the strategy captured under half of BTC's out-of-sample return.
Screen 3 ranks survivors on a composite of Sharpe, Sortino, and Calmar, where the strategy's halved drawdown feeds directly into Calmar.

This does not make it deployable.
It makes it a candidate whose only demonstrated advantage happens to be the thing the scoring rubric rewards, which is a reason for care rather than confidence.
Nothing here has passed Gates 3 through 9, the deflated Sharpe against 53 trials has not been computed, and the out-of-sample drawdown of 30.6% breaches the pre-registered Gate 8 limit of 25%.

## composite-objective

The objective is the mean of Sharpe, Sortino, and Calmar, matching the three metrics the organisers named for Screen 3.

Calmar is capped at 5.0 before averaging.
Over a short window a near-zero maximum drawdown sends Calmar toward infinity and would let a single quiet fortnight dominate an average that is supposed to summarise three things.
The cap is set above any plausible sustained value and is not tuned.

Weights across the three are equal because the organisers did not publish weights.
Equal weighting is also the construction least sensitive to being wrong about their choice, since a strategy strong on all three ranks well under any positive weighting.

## overlay-grid

The overlay is fitted on data before 2023-01-01 only, and every number reported for it comes from the out-of-sample period or the bootstrap.

The grid is deliberately small, three volatility targets by two de-risking modes, because the trial ledger already stood at 53 before this stage and each additional configuration raises the hurdle that the survivor must clear at Gate 4.

The drawdown circuit breaker is held fixed at the pre-registered 12% and is not swept.
Sweeping it against the scored objective would convert the one risk control declared as unfitted into the most heavily fitted parameter in the repo, and this operator's prior work has seen regime overlays of exactly that shape reverse out of sample repeatedly.

Volatility targeting is expected to help, and that expectation is itself a caution.
A prior replication in this operator's trend work found volatility scaling supplied roughly 0.33 of Sharpe while the underlying signal supplied close to nothing, so any improvement here must be attributed between the overlay and the signal rather than credited to the strategy as a whole.

## competition-bootstrap

Performance is reported over 4000 contiguous 14-day windows in addition to the full out-of-sample record.

The competition is a single 14-day draw, and a nine-year Sharpe describes the distribution that draw comes from, not the draw.
A strategy with a better long-run composite can easily lose a given fortnight, and the spread between those two facts is the quantity a team actually needs in order to decide anything.

The bootstrap is contiguous rather than resampled within the window so that autocorrelation and drawdown structure survive, since Calmar is meaningless once the path is shuffled.

## objective-optimisation-outcome

Optimising the Sharpe/Sortino/Calmar composite succeeded in sample and failed out of sample, and the attribution matters more than the headline.

Selection on pre-2023 data chose `volume_confirmed_trend` at a 5-day volume lookback with a 50% volatility target and symmetric de-risking, at an in-sample composite of 1.30 against BTC buy-and-hold at 0.70.
Out of sample that configuration scored 1.18 against BTC at 1.31.
The optimised strategy lost to holding BTC on the exact objective it was optimised for.

Decomposing the out-of-sample composite isolates where the gain came from:

    raw signal              0.99
    + volatility target     1.01
    + circuit breaker       1.17
    + both                  1.18

Volatility targeting contributed 0.02 and the circuit breaker contributed 0.18.
This contradicts the prior expectation recorded at `DECISIONS.md#overlay-grid`, where volatility scaling had supplied most of the Sharpe in earlier trend work, and the difference is that the no-trade band had already removed most of the turnover-driven volatility this overlay would otherwise have damped.

The circuit breaker's contribution is not an improvement in the strategy.
It holds cash on 84.8% of out-of-sample days, which shrinks the drawdown denominator faster than it shrinks the return numerator and mechanically lifts Calmar.
Diluting a position with cash raises a ratio without adding edge, and reporting that as optimisation would be a misattribution.

## breaker-misspecification

The 12% drawdown circuit breaker is mis-specified for a strategy whose natural drawdown is 30%, and it is not being retuned.

A breaker set below a strategy's ordinary drawdown does not control risk, it exits the strategy permanently, which is what the 84.8% cash weighting shows.
The threshold was pre-registered as unfitted and the correct response to discovering it is wrong is a new pre-registration with a stated derivation, not an adjustment made after seeing which value scores better.
Tuning it now against the composite would make the single control declared as unfitted into the most heavily fitted parameter in the repo.

## screen-ordering

Optimising the Screen 3 composite in isolation is the wrong objective, because Screen 2 runs first and is a return gate.

The composite-optimised configuration returns exactly zero in 84.2% of 14-day windows and is positive in 9.3%, against 55.6% for BTC buy-and-hold.
Screen 2 ranks on raw portfolio return and advances only the top 20 per region, so a flat fortnight is elimination before the composite is ever computed.

The correct objective is the composite conditional on clearing the return cut, not the composite alone.
A configuration that maximises Screen 3 while failing Screen 2 scores nothing, and the two-stage structure means the gates cannot be optimised independently.

## horizon-search

The existing signals hold for 7 to 22 days, which is incoherent with a 14-day competition, and the horizon is therefore searched explicitly.

A 21-day holding period inside a 14-day window produces at most one signal change, so the outcome is a single directional bet rather than a repeated process.
None of the three scored metrics is meaningful on one flip: Sharpe and Sortino need a return series, and Calmar needs a drawdown path.
The horizon must be short enough that the strategy completes several independent cycles inside the window, which is why `min_flips_per_14d` is set at 2.

The search is bounded below by the cost arithmetic measured on 2026-09-19.
Break-even directional accuracy is 61.7% at a 1-hour horizon and 55.8% at 4 hours, against realised accuracy of 47.9% to 52.1% for simple signals on hourly BTC over a year.
Nothing faster than 4 hours is tested, because below that the average move is smaller than the round trip cost and no accuracy makes it profitable.

Selection is on the median composite across 14-day windows, not on full-sample statistics, and is subject to a hard constraint that the configuration must be positive in at least half of those windows.
That constraint encodes the Screen 2 return gate, which the previous optimisation stage failed by producing a configuration that was flat in 84% of fortnights.

## horizon-search-outcome

Twelve configurations across four bar intervals were tested out of sample on 2026-09-19, and the result reverses the premise that motivated the search.

Directional accuracy was 48.8% on average with a range of 48.2% to 49.4%.
Not one configuration at any timeframe exceeded a coin flip, yet several were clearly profitable, the best returning 28.9% a year at a Sharpe of 0.97.
This is the ordinary signature of trend following: it is right slightly less than half the time and wins more when right than it loses when wrong.

Directional accuracy is therefore the wrong optimisation target for this strategy family.
It cannot be raised materially and does not need to be, and a search that maximised it would select against the asymmetry that produces the returns.

Speed made performance monotonically worse.
Out-of-sample Sharpe ran 0.00 to 0.32 at four-hour bars against 0.39 to 0.97 at daily bars, while cost drag ran 9.5% to 14.4% of NAV a year at four hours against 1.8% to 2.6% at daily.
Cost scales inversely with horizon and consumes the entire gross edge at the fast end, which is the same arithmetic recorded at `DECISIONS.md#mid-frequency` arriving from the opposite direction.

One configuration passed both pre-registered constraints, eight-hour bars with a 20/50 crossover, at a median 14-day composite of 0.53 and a positive return in 51.0% of windows.
BTC buy-and-hold scored 2.25 and 56.0% on the same basis and beat it, as it has beaten every configuration tested in this repo.

## flips-constraint-misspecified

The `min_flips_per_14d` constraint excluded the strongest configuration, and its stated rationale was partly wrong.

The constraint was declared on the reasoning that Sharpe, Sortino, and Calmar are not meaningful across one signal change.
That reasoning is incorrect: all three are computed from the return series, not from the trade sequence, and fourteen daily returns support them regardless of how many times the position flipped.

The variance argument survives, since a fortnight containing 1.6 position changes is closer to a single directional bet than to a repeated process, and its outcome is correspondingly more idiosyncratic.
The constraint stands as declared for this cycle, because relaxing it after seeing that it excluded the best result is precisely the post-hoc adjustment the pre-registration exists to prevent.
The configuration it excluded, daily bars at 12/48 with a median 14-day composite of 1.55, is recorded here so a future cycle can test it under a constraint declared in advance.

## screen2-needs-variance

The two screens want opposite distributional shapes, and the horizon search made the conflict measurable.

Across 14-day windows the selected configuration spans a 5th percentile of -8.3% and a 95th of 13.6%, against BTC buy-and-hold at -11.3% and 21.0%.
The strategy's tighter distribution is what lifts Sortino and Calmar for Screen 3.

Screen 2 is a rank cut that advances the top 20 of a region on raw return, and a rank cut is won from the right tail rather than the median.
Compressing the distribution improves the scored composite while reducing the probability of reaching a tail outcome large enough to survive the cut that precedes it.
A configuration optimised purely for Screen 3 is therefore selecting against its own chance of being scored at all.

## screen3-caps

Sortino, Sharpe, and Calmar are each capped at 5.0 before the weighted sum.

Over a 14-day window a near-zero drawdown or a run without a single down day sends Calmar or Sortino toward infinity, and an uncapped average would let one quiet fortnight dominate a statistic meant to summarise three properties.
The caps sit far above any sustained value and are not tuned.

The weighting is 0.4 Sortino, 0.3 Sharpe, 0.3 Calmar, taken from the competition plan rather than assumed.
This replaces the equal-weighted mean used earlier in this repo, and the change matters: Sortino carries the largest single weight, so upside volatility is free and only downside deviation is penalised.

## asymmetry-thesis

The plan's central claim is that cutting losers hard while letting winners run serves both screens at once, and it is treated as a hypothesis to be tested rather than a design to be implemented.

The reasoning is that Screen 2 rewards magnitude while Screen 3 rewards shape, and an asymmetric payoff raises raw return through uncapped upside while improving Sortino and Calmar through bounded downside.
It is plausible and it is also exactly the kind of claim that survives in a backtest because stops are path-dependent and easy to fit.

Testing it requires a path-dependent simulator rather than the weight-vector backtest used so far.
A stop that triggers intrabar cannot be represented by a vector of target weights applied at bar close, so the engine now tracks each position, its stop level, and its trailing high, and exits at the stop price when the bar's low or high breaches it.

The stop and trailing multiples are declared as a small grid and the daily loss breaker is fixed at 3% and not swept, for the reason recorded at `DECISIONS.md#overlay-grid`.

## plan-correction-shorting

The plan marks the short-selling mechanic UNCONFIRMED and states the API exposes only BUY and SELL with no short flag.
This is incorrect and the correction is material to the design.

`POST /v6/short_open`, `POST /v6/short_close`, and `GET /v6/short_positions` are documented and live, verified against the running API on 2026-09-18.
A short is sized by committed collateral rather than by quantity, with quantity derived as `collateral / EntryPrice` rounded down to the pair's `AmountPrecision`.

The cost asymmetry between the legs is the part that changes strategy design.
Spot orders pay 0.10% taker and 0.05% maker, so limit execution halves the fee, but shorts pay 0.10% on both open and close with no maker discount, stated directly in the README as "the same for market and limit orders".
A short round trip therefore costs 20 bps regardless of execution style, against 10 bps for a spot round trip worked with limits, which makes the short leg twice as expensive and argues for using it as a hedge rather than as a symmetric alpha source.

One further trap: the short open fee is charged when the request is accepted, including for a LIMIT order that has not yet filled, and is released only on cancel.

## asymmetry-engine-defects

Testing the asymmetry thesis required a path-dependent simulator, and the first version of it produced fabricated results through three separate defects.
They are recorded because each one is the kind that survives casual inspection by making performance better rather than worse.

The first run reported a Sharpe of 6.59, an annual return of 428.7%, and a maximum drawdown of 7.8%, with 93.8% of 14-day windows positive.
None of that was real.

The first defect was a stale stop on a direction flip.
A position moving from long to short without passing through zero kept its old stop, and a long's stop sits below the market while a short's triggers when price rises to meet it, so the inherited level fired immediately at an absurd price.

The second was a trailing stop permitted to ratchet above the current price.
Measured across the panel, the trailing level sat above the current close on 37.8% of cells, by a median of 548 bps.
A long stop-loss that fills 5.5% above the market is not a stop, it is a guaranteed profitable exit, and it was the largest contributor to the fabricated return.

The third was that stopped positions were zeroed before the bar's profit and loss was computed, so the stop-out loss was never booked at all.
Stops were free escapes from losing positions.

The engine now clamps a long's stop at or below the current close and a short's at or above it, fills at the bar open when a gap carries price through the stop level, and books the realised loss before flattening.
Validation is a control run with stops disabled, which reproduces the weight-vector backtest at a correlation of 0.9999981, plus a monotonicity check confirming that tighter stops reduce cumulative return rather than raising it.

## asymmetry-outcome

The asymmetry thesis failed on this data and the failure is mechanically explicable.

All eight declared configurations lost money out of sample, returning between -2.4% and -9.9% a year at Screen 3 scores between -1.51 and +0.03, against BTC buy-and-hold at 1.36.
On the 14-day bootstrap every configuration had a negative median Screen 3 score and a negative median return.

Stops and trend following are working against each other here.
A trend signal earns its return by holding a position through drawdowns that later recover, and an ATR stop is an exit rule that fires precisely during those drawdowns.
The signal already exits on the moving-average cross, so the stop is a second and strictly worse exit that triggers first, and tightening it monotonically reduced cumulative return in the sanity check.

The plan's reasoning that asymmetry serves both screens is sound in the abstract and does not hold for this signal family.
It would need a signal whose losses are genuinely terminal rather than temporary, which cross-sectional trend is not.

## screen2-tail-evidence

The bootstrap quantifies why a low-volatility design is the wrong answer to a rank cut.

Screen 2 advances the top 20 of a region on raw return, which is won from the right tail.
Across 14-day windows BTC buy-and-hold exceeded a 5% return 29.6% of the time, against 11.1% to 16.8% for the eight asymmetry configurations, whose 95th percentile outcomes ran 8.7% to 10.7% against BTC's 21.8%.

Volatility targeting and stops both compress the distribution, and compressing the distribution is what removes the tail outcome the first screen requires.
A design that improves Screen 3 by suppressing variance is reducing its own probability of ever reaching Screen 3.

## screen2-threshold

A 5% 14-day return is used as the proxy for clearing the Screen 2 rank cut, and it is an assumption rather than a known quantity.

The organisers advance the top 20 per region on raw return without publishing an absolute bar, so the real threshold depends on what other teams achieve and cannot be known in advance.
5% over 14 days is roughly 150% annualised, which is the order of magnitude a competitive entry in a crypto trading contest would need, and it is held fixed across every family so that comparisons between them are unaffected by the choice.

The quantity that matters is therefore relative: which family most often reaches a tail outcome large enough to qualify, not whether 5% is exactly right.

## family-comparison-design

Families are compared at one fixed parameter setting each, chosen from convention rather than fitted, because the question is which mechanism suits the competition rather than which parameter suits the history.

The trial ledger stood at 109 before this stage.
Every additional configuration raises the hurdle that any survivor must clear at Gate 4, so a full parameter sweep across five families would cost more statistical power than the answer is worth.
Tuning each family to its own best setting would also bias the comparison toward whichever family has the most parameters to tune.

Stops are disabled for every family, following the result at `DECISIONS.md#asymmetry-outcome` that they cut trend positions during recoverable drawdowns.
Two mechanisms not previously tested are included: range breakout, and short-horizon reversal, the latter because it was the only signal to exceed 50% directional accuracy in the hourly check recorded at `DECISIONS.md#horizon-search-outcome`.

## family-comparison-outcome

Five mechanisms were compared at fixed untuned settings across four bar intervals on 2026-09-19, and the ranking depends entirely on which screen is being optimised.

BTC buy-and-hold led on every measure: out-of-sample Screen 3 of 1.36, the highest probability of clearing the Screen 2 proxy at 29.5%, and the highest expected value at 41.3.
This is the fifth consecutive stage in which it has beaten every constructed strategy.

The best timeframe is family-dependent rather than universal, which is the main reason the comparison was worth running.
Trend and volume-gated trend improve monotonically as they slow down, peaking at daily bars.
Cross-sectional momentum peaks in the middle at eight to twelve hours, scoring 0.97 and 0.84 against 0.51 at four hours and 0.20 at daily, so it is the one family with a genuine interior optimum rather than a preference for the slowest setting available.

Short-horizon reversal is the clearest cost casualty in the repo.
It was the only signal to exceed 50% directional accuracy in the earlier hourly check, at 52.1%, and it lost money at every timeframe tested, returning -40.3% a year at daily bars and -85.4% at four hours against cost drag of 27.6% and 164.5% respectively.
Directional accuracy above a coin flip is worth nothing when the trade frequency required to harvest it costs more than the edge.

Range breakout produced the best downside control of any family, drawing down 18.6% at eight hours and 20.4% at daily against 33% to 66% elsewhere, and the highest lower-quartile Screen 3 among qualifying windows at 72.6.
It also qualified least often, reaching the return threshold in 4.3% to 8.4% of windows, so its risk control comes from rarely taking meaningful exposure.

## screen-tension-quantified

The comparison measures the conflict between the two screens directly, and it is consistent across families rather than particular to one design.

The strategies with the strongest full-sample Screen 3 scores have the weakest chance of ever being scored.
Volume-gated trend at daily bars ranks second on out-of-sample Screen 3 at 1.11 and reaches the return threshold in only 14.0% of windows.
Breakout at daily bars has the highest lower-quartile conditional Screen 3 at 72.6 and qualifies in 4.9%.
Plain trend at daily bars scores 0.36 and qualifies in 22.4%.

The mechanism is the same in each case: everything that improves a risk-adjusted ratio does so by suppressing variance, and the first screen is a rank cut decided in the right tail.
Selecting on Screen 3 alone systematically selects against Screen 2, and the expected-value ordering is therefore closer to the qualification probability ordering than to the Screen 3 ordering.

One caveat limits how far this can be pushed.
Conditional on a window clearing the return threshold, the median Screen 3 score ran between 37 and 143 across families, because annualising Sortino and Calmar over fourteen observations produces very large numbers whenever the path is smooth.
Discrimination between qualifying teams on Screen 3 may therefore be dominated by path noise rather than by strategy quality, which argues for prioritising qualification over ratio optimisation.

## gate4-outcome

Gate 4 failed for every candidate on 2026-09-19, and the single number that decides it is the expected maximum Sharpe under the null.

Across 131 trials, with a per-observation trial-Sharpe variance of 0.00088663 estimated from 42 homogeneous out-of-sample runs, the expected maximum Sharpe obtainable by chance alone is 0.07814 per observation, or 1.493 annualised.
No candidate reached it.
Volume-gated trend at daily bars, the strongest constructed strategy in the repo, has an annualised Sharpe of 0.947 and a Deflated Sharpe Ratio of 0.146 against a 0.95 threshold.

The required Sharpe to clear the gate at this trial count is 2.353 for that strategy, a gap of 1.406, and the minimum track record length is infinite because its observed Sharpe sits below the null's expected maximum.
No quantity of additional data fixes that; only a smaller search would.

The sensitivity to trial count is the instructive part.
The same strategy and the same return series would have produced a Deflated Sharpe Ratio of 0.966 and passed if it had been the first and only configuration tested, 0.896 at two trials, 0.698 at five, and 0.398 at twenty.
The edge did not disappear between those points, the evidence for it did.
A search of 131 configurations cannot distinguish this result from the best of 131 coin flips.

## btc-benchmark-trial-count

Applying the 131-trial deflation to BTC buy-and-hold is incorrect and the correct treatment changes its verdict.

BTC buy-and-hold was not selected from a search.
It was fixed in advance as the benchmark, its honest trial count is one, and at one trial its Deflated Sharpe Ratio is 0.9873, which passes.
Under the 131-trial deflation it scores 0.2503 and fails alongside everything else.

This is not a technicality, it is the whole finding stated precisely.
The one strategy in this repo with defensible statistical support is the one nobody searched for, and it beat every constructed alternative on out-of-sample Screen 3, on probability of clearing the Screen 2 return cut, and on expected value.

The asymmetry is the cost of searching.
Every configuration tested raised the bar for all the others, and a hundred and thirty-one attempts to beat a passive benchmark produced nothing that survives being counted honestly.

## kurtosis-penalty

Fat tails made the gate materially harder and are worth noting for any future cycle.

Observed kurtosis ran 5.98 for plain trend, 13.10 for volume-gated trend, 21.29 for cross-sectional momentum at eight-hour bars, and 37.19 for breakout.
The Deflated Sharpe Ratio penalises kurtosis through its denominator, so cross-sectional momentum needed an annualised Sharpe of 3.405 to pass against 2.353 for volume-gated trend, despite a similar observed Sharpe.

A strategy whose returns arrive in rare large moves requires substantially more evidence to establish the same claim, which is an argument for preferring smoother return streams at equal Sharpe rather than only at equal drawdown.

## paper-ensemble-declaration

The strategy in `config/paper_ensemble.yaml` is the first candidate in this repo whose parameters were fixed by someone else before anyone here saw the data.

Zarattini, Pagani and Barbon (SSRN 5209907, April 2025) specify an ensemble of nine Donchian channels at lookbacks of 5, 10, 20, 30, 60, 90, 150, 250 and 360 days, each exiting on a stop that ratchets to the channel midpoint, aggregated equal-weight, sized to a 25% annualised volatility target from a 90-day realised estimate with leverage capped at 1.0, on a monthly snapshot of the top 20 most liquid coins.
Every one of those numbers is external.
That is the entire reason this family is worth running after 131 trials had already exhausted the statistical budget: a parameter set nobody here searched for carries a trial count of one, which is the same argument already recorded at `DECISIONS.md#btc-benchmark-trial-count`.

The paper itself is paywalled and the parameter values come from a public reconstruction rather than from the paper's own text.
An independent replication's preview names the ladder as beginning "5, 10, 2..." which is consistent, and the count of nine matches the paper's abstract, but the ladder, the midpoint stop rule and the volatility lookback are third-party attributions and are labelled as such in the declaration.
If the real paper differs, this family's trial-count-of-one claim survives but its replication claim does not.

## leverage-cap-semantics

The paper's "leverage capped at 1.0" was first implemented as a cap on the volatility scalar and that was wrong.

With the scalar capped, a book whose unlevered gross exposure was 21% of NAV could never scale up, because the scalar sat pinned at its ceiling whenever realised volatility ran below the 25% target, which was most of the time.
Mean gross exposure came out at 18.5% and the strategy was measuring an 81%-cash portfolio.
Leverage is gross exposure divided by NAV, not the scalar that produces it, so the cap belongs on the resulting exposure.

Corrected, the scalar is uncapped and gross exposure is capped at 1.0, which lifts mean exposure to 31% on the top-20 book and 38% on BTC.
The correction is a bug fix rather than a parameter change, and it is recorded because the defective version looked plausible: its performance numbers were unremarkable rather than absurd, so nothing about the output announced that the book was barely invested.

## donchian-pulse-defect

The `donchian_breakout` entry in `signals/families.py`, on which the family comparison at `DECISIONS.md#family-comparison-outcome` reported, is not a Donchian trend system and its conclusions about that family do not stand.

The implementation marks a position only on bars where the close sits outside the channel, so the position vanishes the moment price stops making new extremes.
Measured on the point-in-time top-20 universe, it carried a mean gross exposure of 8.8% at eight-hour bars and 9.3% at daily, held 1.4 names at a time, and had a holding period of 1.3 bars.
A Donchian channel rule holds until the opposite channel is breached; this one held for one bar.

Two reported findings were therefore artifacts.
The family's "best drawdown control of any family" at 18.6% to 20.4% was the drawdown of a portfolio that was more than 90% in cash, and its low Screen 2 qualification rate of 4.3% to 8.4% was the direct arithmetic consequence of never taking meaningful exposure rather than evidence about range expansion as a mechanism.
The stateful implementation in `signals/ensemble_trend.py` is the corrected form, and the prior row is left in place rather than deleted so that the correction is auditable.

## paper-ensemble-outcome

The declared ensemble is the first constructed strategy in this repo to beat BTC buy-and-hold on the Screen 3 composite, and it does so in the two windows that matter most.

Applied to BTC alone with portfolio-level volatility targeting, out of sample from 2023-01-01 it returned 34.3% a year at a Sharpe of 1.25, a Sortino of 2.10, a Calmar of 1.39 and a maximum drawdown of 24.7%, for a Screen 3 score of 1.632 against BTC buy-and-hold at 1.364.
In the post-publication window from 2025-04-01, the only stretch of data that postdates the paper's own parameter choices, it scored 0.667 against buy-and-hold at 0.150 and returned 11.4% a year while holding BTC lost 1.3%.
Five prior stages in this repo produced nothing that beat the benchmark on any of these measures.

The replication is directional rather than exact.
On BTC the full record gives a Sharpe of 1.14 and a Sortino of 1.86 against the paper's 1.58 and 2.03, and the gap is consistent with history: this panel starts 2017-08-17 because Binance did not exist earlier, while the paper starts January 2015 and therefore includes the 2015-2017 bull run, which is the single most favourable stretch for a long-only crypto trend system.
The top-20 book reproduced the paper's drawdown almost exactly, 10.6% against 11%, but only a third of its return, 6.2% against 18%, which says the paper deploys roughly three times the notional at the same risk and that the sizing reading here is more conservative than theirs.

The observed return distribution is positively skewed at 1.35 with a kurtosis of 12.57.
That is the payoff shape the asymmetry thesis wanted and failed to obtain with ATR stops at `DECISIONS.md#asymmetry-outcome`, and it arrives here from an exit rule that ratchets to the channel midpoint rather than to a volatility multiple, which lags far enough behind price to survive the drawdowns a trend needs to hold through.

## paper-ensemble-trial-count

Gate 4 passes for this candidate at an honest trial count of one or two and fails at any larger count, and which of those applies is a question about discipline rather than about the data.

With the trial-Sharpe variance of 0.00088663 already estimated in `results/g4_deflated_sharpe.json`, the Deflated Sharpe Ratio of the BTC ensemble's out-of-sample record is 0.9938 at one trial and 0.9719 at two, against the 0.95 threshold, and 0.5741 at 27, 0.3116 at 131 and 0.2865 at 167.
BTC buy-and-hold scores 0.9874 and 0.9519 at one and two.
Nothing in this repo had previously cleared the gate at any count.

The claim to a trial count of one rests on the parameters being external, and it is weaker than it looks.
The lookback ladder, the volatility target, the volatility lookback and the leverage cap were all published before this data was touched, so those contribute nothing to a search.
But three readings of the sizing rule were evaluated here before the best one was identified, across two execution styles and two no-trade-band settings, and the configuration now reported is the one that scored highest.
That is a search of 36, and the DSR at 27 trials already fails.

The defensible position is therefore narrow.
`btc_voltgt_port` is the literal reading of "25% target annualised volatility, leverage capped at 1.0" once the cap is applied to exposure rather than to the scalar, so it is the reading that should have been committed to first on a stated principle, and it is a coincidence which cannot be demonstrated that the principled reading is also the best-performing one.
Deploying it honestly requires declaring it prospectively as a single configuration and accepting the verdict of the window that follows, not reporting the 0.9719 obtained after looking.

## screen3-is-a-sign-indicator

Over a 14-day window the Screen 3 composite does not measure strategy quality, it measures whether the fortnight was up, and the bootstrap makes this unambiguous.

Across 4000 contiguous out-of-sample 14-day windows, every configuration with a negative median 14-day return scored a median composite between -2.70 and -3.89, while BTC buy-and-hold, whose median 14-day return is +0.86%, scored +3.72.
The mechanism is the Calmar term: annualising a small negative 14-day return produces a large negative CAGR, dividing it by a small drawdown produces a large negative ratio, and the 5.0 cap then pins the term at its floor.
Sortino behaves the same way through its own sign.
The composite spans roughly -3.9 to +3.7 with almost nothing in between, so it is a coin-flip readout on the sign of the window rather than a ranking of skill.

This sharpens the caveat already recorded at `DECISIONS.md#screen-tension-quantified` from "discrimination may be dominated by path noise" to a specific claim: the single quantity that predicts a team's Screen 3 rank is the probability that its fortnight finishes positive.
On that measure the ranking inverts everything the full-sample composite says.
BTC buy-and-hold finishes positive in 55.5% of windows and clears the 5% return proxy in 29.8%, against 45.2% and 16.8% for the best-scoring ensemble configuration.
The strategy with the best Sharpe, Sortino and Calmar over nine years is the one less likely to be scored at all, and optimising the composite harder makes that worse rather than better.

## competition-window-outcome

Tested on the actual shape of the competition rather than on a nine-year record, the ensemble fails, and the paired comparison is what settles it.

Every contiguous 14-day window in the out-of-sample period was scored exactly as the two screens would score it: raw return for Screen 2, and the 0.4/0.3/0.3 weighted composite computed from the fourteen daily returns for Screen 3.
Each window was then compared against BTC buy-and-hold *over the same fourteen days*, which is the only comparison the competition actually makes.

Across 1345 out-of-sample windows, the best candidate beat buy-and-hold on raw return in 34.3% of them and on the Screen 3 composite in 10.3%.
The joint event that decides the competition, clearing the Screen 2 return cut and outscoring passive BTC on the composite, occurred in 0.2% of windows.
No configuration tested reached 5.2% on that joint measure, including the top-20 book and both core-plus-sleeve blends.

The full-period Screen 3 advantage recorded at `DECISIONS.md#paper-ensemble-outcome` is therefore real and irrelevant.
A Screen 3 of 1.632 against 1.364 is a statement about nine years of compounding, in which avoided drawdowns accumulate into a better ratio.
At 14-day resolution the same strategy scores a median composite of -2.67 against buy-and-hold's +3.73, because the composite over fourteen observations is governed by the sign of the window and the ensemble's median 14-day return is -0.17% against buy-and-hold's +0.86%.
The mechanism that wins over years is invisible over a fortnight.

## beta-is-the-only-screen3-lever

The two screens are not merely in tension, they are collinear over a 14-day window, which closes off the design the plan proposed.

Within a fortnight the composite is a function of the sign of the return, the sign of the return is a function of exposure to BTC, and so any reduction in beta reduces P(positive), P(clearing the return cut) and the composite together rather than trading one against another.
The core-plus-sleeve blends make this explicit by construction: at a 70% permanent core the full-period composite is 1.385 and P(return above 5%) is 26.0%, at a 50% core they are 1.393 and 23.3%, and at pure conviction sizing they are 1.632 and 17.2%.
The composite rises monotonically as qualification probability falls, across the whole range, with no interior point where both improve.

This is the quantitative refutation of Section 1 of the plan, which claimed that an asymmetric payoff serves both screens simultaneously because Sortino leaves upside unpenalised.
It is true that Sortino does not penalise upside. It is false that this creates a design in which shape can be improved without surrendering tail exposure, because over fourteen observations the downside deviation that Sortino measures and the right tail that Screen 2 requires are both produced by the same beta.

## entry-state-conditioning-does-not-replicate

Conditioning on the ensemble's conviction at the start of the window looked exploitable out of sample and reversed after publication, so it is not used.

Out of sample from 2023 the relationship is monotonic: windows entered with seven or more of the nine channels open cleared the 5% return proxy 24.9% of the time at a median composite of +1.67, against 15.6% and -2.75 for windows entered with fewer than two open.
That is an attractive result and it would be actionable, because conviction on the morning of 4 October is observable in advance rather than something to forecast.

In the post-publication window it inverts.
The highest conviction bucket produced a median return of -1.77%, cleared the proxy 8.0% of the time, and scored a median composite of -4.26, the worst of the four buckets.
The bucket holds 25 windows, which is too few to establish the reversal as a fact, but it is also far too few to defend the original relationship as anything other than the in-sample pattern it was found in.
Recorded here so that a future cycle does not rediscover the 2023-2025 monotonicity and treat it as a filter.

## competition-live-state

As of 2026-09-19, five of the nine Donchian channels on BTC are open, conviction stands at 0.556, and the volatility-targeted book would hold 95.1% gross exposure. Nineteen of the twenty top-20 names carry a signal.

This matters more than any backtest statistic for the fortnight in question.
At 95% gross exposure the ensemble is not a meaningfully different position from holding BTC; it is holding BTC with a stop attached.
If the competition began today the two entries would track each other closely, and would diverge only if BTC broke down during the window.

Stated as the actual decision rather than as a ranking: the cost of attaching the stop is 13 percentage points of qualification probability, 17.2% against 30.3% at the 5% proxy, and the benefit is a median 14-day drawdown of 2.9% against 5.5% and a worst observed 14-day outcome of -10.1% against -29.8%.
That is a real trade and the right side of it depends on where the regional top-20 cut lands, which is unknowable in advance. It is not a trade that the Screen 3 composite rewards.

## volume-family-declaration

The operator asked for a rule that goes long when volume rises and short when it falls, across several horizons, and it was declared at `config/volume_family.yaml` before any of it was run.

The declaration records the defect in the literal rule rather than quietly fixing it.
Volume is unsigned: it rises on capitulation selling as readily as on accumulation, so a rule keyed to volume direction alone holds no view on price direction.
This repo had already measured that once, at `DECISIONS.md#gate2-outcome`, where rising relative volume predicted underperformance at a gross Sharpe of -1.17.
The literal rule was therefore tested exactly as asked, alongside six signed or normalised variants, so that a failure of the literal rule could be attributed to signing rather than to volume.

Binance klines carry `taker_buy_base` and `taker_buy_quote`, which the repo's loader already parsed and cached but the panel builder discarded.
Aggressor-side imbalance is therefore available from OHLCV alone for all 264 symbols with no nulls across the full history, and `data/flow.py` rebuilds the panel with those fields.
No call to `aggTrades` or `depth` was needed, and no new download was required.

## volume-family-outcome

There is a real gross volume edge, it is larger than the benchmark's, and trading costs remove all of it.

Across 35 declared configurations out of sample from 2023, the best gross Sharpes were 1.81 for `signed_volume` at four-hour bars, 1.60 for `vol_confirmed_mom` at four hours, and 1.48 for `vol_z` at eight hours, against BTC buy-and-hold's net Sharpe of 1.15.
Net of a 5 bps maker fee per side, the same configurations returned -2.27, 0.02 and 0.07.
Not one of the 35 beat the benchmark net, and only three had a positive net Sharpe at all.

The arithmetic is the entire result.
`vol_z` at eight hours turns over 1077 times NAV a year and pays 53.9% of NAV in fees; at four hours `vol_confirmed_mom` turns over 2023 times and pays 101.2%.
Section 2.5 of the plan budgeted roughly ten full-notional round trips against a 1% fee allowance.
This family requires between 700 and 3300, which is not a tuning problem but a two-order-of-magnitude mismatch between the decay rate of the signal and the cost of acting on it.

The edge is also real enough to be worth stating precisely, because it is the only mechanism tested in this repo whose gross Sharpe exceeds the benchmark.
It peaks at four to twelve hours and collapses at daily bars, where the best gross Sharpe across all seven features is 0.35.
That interior optimum is the signature of a genuine short-horizon effect rather than a fitted one, and it matches the interior optimum found for cross-sectional momentum at `DECISIONS.md#family-comparison-outcome`.

## volume-literal-rule-is-a-coinflip

The operator's rule as literally stated carries no directional information on BTC.

Tested as a time-series signal, long when the five-bar volume average exceeds the twenty-bar average and short otherwise, directional accuracy ran 49.3% to 50.9% across 1h, 4h, 8h, 12h and 1d bars.
Gross Sharpe reached 0.88 at hourly bars and was 0.50, 0.00, 0.50 and 0.06 at the slower ones, and net Sharpe was negative at every interval except twelve hours at 0.24.

Cross-sectionally the same feature was the weakest of the seven tested, at a gross Sharpe of 0.73 at best and negative at eight hours and slower.
The features that did carry gross edge were the ones that gave volume a direction, either by ranking its magnitude cross-sectionally (`vol_z`) or by multiplying it against the sign of the bar's return (`signed_volume`).
The declared failure mode was therefore the correct diagnosis: volume is a measure of participation, not of direction, and it becomes tradeable only once something else supplies the sign.

## no-trade-band-cannot-fix-a-quantile-book

The pre-registered no-trade band was applied to the best gross configurations and reduced turnover by less than a tenth of one percent, which is a structural fact rather than a poor choice of threshold.

At an 8h `vol_z` book, annual turnover was 1077 with no band, 1076 at a band of 0.25, and 1075 at 0.60.
A quantile book assigns a name either its share of the long or short sleeve or nothing at all, so a position entering or leaving the top quintile moves between zero and full weight.
Every such move is a 100% change in that name's weight and clears any band below 1.0 by construction.

Bands damp drift in a continuously weighted book; they do nothing to a discrete one.
Reducing turnover in this family would require changing the construction, by holding names for a minimum number of bars or by weighting continuously on the score, and neither is declared.
Recorded so that the band is not reached for again as a cost remedy in a ranked book.

## volume-family-cost-to-the-ledger

Running this family moved the trial ledger from 169 to 236 and returned a null, and that cost is borne by every other candidate in the repo.

The Deflated Sharpe hurdle is a function of the total number of configurations evaluated, so 67 further trials raise the bar that the single-channel Donchian and BTC buy-and-hold must clear, without any of them having changed.
This is the policy at `DECISIONS.md#trial-counting` applied to a request rather than to a search, and the entry exists so the cost is visible rather than absorbed silently.

The result is still worth having.
A family with a gross Sharpe of 1.8 that dies entirely on turnover is a different finding from a family with no edge, and it says where a tradeable version would have to come from: the same signal harvested at a fraction of the turnover, not a better volume feature.

## donchian-lowtf-declaration

The operator asked for the single-channel Donchian taken to lower timeframes for the competition, without adding rules, and the grid was declared at `config/donchian_lowtf.yaml` before any of it was run.

The declaration separates two readings of "lookback" that are different signals rather than different settings.
In `bars` mode the entry window is a fixed twenty bars, so the signal itself speeds up as the interval shortens and a 4h channel spans 3.3 days rather than 20.
In `calendar` mode the window is twenty days expressed in bars, so the signal is nominally unchanged and only the execution grid gets finer.
Running one without the other would have confounded "trade faster" with "execute more precisely", which are the two distinct things a lower timeframe can buy.

Exit is either the ratcheting midpoint already used by the ensemble or the opposite channel at half the entry lookback, the latter being the canonical Turtle construction. Twenty and its half are conventional values, not fitted.

## annualisation-across-intervals

Full-sample Sharpe, Sortino and Calmar must be computed from a single daily return series, never from each configuration's native bar, and the first version of this comparison got it wrong.

Annualising a per-bar Sharpe by the square root of bars per year assumes serial independence.
Crypto returns are not independent at intraday frequencies, so the factor is wrong by a different amount at every interval and the resulting table compares configurations on inconsistent scales.
Every metric reported for this family is therefore computed after compounding each strategy's returns to daily.

The measured distortion runs the opposite way to the expectation that prompted the check.
Native-bar annualisation understated the calendar-mode Sharpe, by 7.5% at 1h and 5.2% at 4h, and was within 1% for every bars-mode and daily configuration.
The correction strengthened the low-timeframe result rather than removing it, but the discipline stands regardless of which way it cut: the comparison is only meaningful on a common sampling frequency.

## donchian-lowtf-outcome

Lowering the timeframe improves the same channel rule substantially, and the reason splits into two separable effects that the declared grid was built to distinguish.

Out of sample from 2023, on daily-compounded returns, the twenty-day channel executed on 1h bars returned 68.9% a year at a Sharpe of 1.99, a Sortino of 3.23 and a Calmar of 3.33, against the identical twenty-day channel on daily bars at 24.2%, 0.86, 1.29 and 0.69.
Annual turnover is 25 times NAV in both cases and cost drag is 1.3% in both.
The same trade sequence executed on a finer grid more than doubled the Sharpe at no additional cost.

Part of that is exit granularity: a stop checked twenty-four times a day releases a losing position hours rather than up to a day after the level breaks, and crypto drawdowns are fast.
Part of it is that the channel is not actually the same. A maximum taken over 480 hourly closes exceeds the maximum over 20 daily closes on 100% of days, by a median of 103 bps, so the hourly-defined channel is a strictly more selective entry. Both effects are legitimate and neither is look-ahead.

For the competition specifically the ranking differs from the full-sample ranking, and the competition ranking is the one that governs.
Measured over 14-day windows, `bars` mode beats `calendar` mode because a 3.3-day channel completes several independent cycles inside a fortnight while a twenty-day channel completes roughly one.
The selected configuration, 4h bars with a 20-bar entry and a 10-bar low exit, is positive in 57.0% of 14-day windows against buy-and-hold's 55.7%, carries a median 14-day Screen 3 of +3.84 against +3.73, and reaches the joint event of clearing the Screen 2 proxy while outscoring buy-and-hold on the composite in 9.5% of windows.
That last figure was 0.2% for the paper ensemble and 4.7% for the daily single channel, so it is the first configuration in this repo to make that joint event other than negligible.

The worst 14-day outcome is -11.1% against buy-and-hold's -29.8%, and the position turns over on 13.1 of every 14 days, which satisfies the Screen 1 activity requirement without any rule added for that purpose.

## lowtf-lookahead-control

The low-timeframe result was checked for look-ahead by inserting extra bars of delay between signal and execution, and it degrades smoothly rather than collapsing.

At 1h calendar the Sharpe ran 2.00, 1.95 and 1.91 at zero, one and two bars of additional lag. At 4h bars with the low-channel exit it ran 1.71, 1.35 and 1.08.
A look-ahead artifact dies at the first bar of delay because the information it depends on is no longer available; a real effect decays in proportion to the edge given away, which is what both series show.
The faster configuration decays faster, as it should, since one 4h bar of delay surrenders four hours of a 3.3-day signal.

## stablecoin-universe-leak

`PAXGUSDT` was selected into the top-20 book on 651 days despite appearing in this repo's own `STABLES` exclusion set, and the filter has been moved to where the book is actually chosen.

The exclusion list was applied in `research_symbols`, which governs which symbols get downloaded, but `pit_top_n` ranked on dollar volume without consulting it, so anything already in the panel could be selected.
Tokenized gold is not a cryptocurrency trend candidate and its presence contradicted the declared universe.

The fix filters `STABLES` and leveraged tokens inside `pit_top_n`, and no leveraged token was present in the panel to begin with.
The impact is immaterial and is recorded as such rather than left implied: on the selected configuration the Sharpe moved from 1.71 to 1.70 and the Screen 3 score from 2.625 to 2.611.
A correctness defect that changes nothing is still a correctness defect, and the reason for recording the size of it is that the next such leak may not be immaterial.

## roostoo-coin-selection-does-not-persist

The operator asked which coins are best suited to the channel strategy, and the answer is that the question has no stable answer: coin-level performance carries no information from one period to the next.

The 4h channel was run standalone on each of the 66 tradable Roostoo cryptocurrencies, split into a fit period of 2023-01-01 to 2025-01-01 and a test period running to 2026-09-19.
Across the 43 coins with a full record in both, the Spearman rank correlation between the two periods was -0.018 for Sharpe at p=0.907, +0.021 for the Screen 3 composite at p=0.894, and +0.031 for annual return at p=0.843.
There is no relationship at all, and none of the three is distinguishable from noise.

The direction of the residual is worth stating because it is the opposite of the intuition behind the question.
The ten best coins of the fit period returned a mean test-period Sharpe of 0.099 and an annual return of -0.4%, while the ten worst returned 0.262 and +44.2%, against a full-sample mean of 0.196 and +7.8%.
Selecting the historical winners would have been worse than selecting the historical losers and worse than taking every coin.

The cherry-picked list makes the mechanism obvious: the top ten by fit-period Screen 3 were PEPE, FLOKI, FET, SOL, POL, BTC, CAKE, SHIB, CFX and XLM, which is a list of what ran in the 2023-24 memecoin cycle.
Deployed into the test period that book returned 7.4% a year at a Screen 3 of 0.433, against 2.622 for the liquidity rule over the same window.
Selecting coins on history destroyed roughly 80% of the strategy.

No coin property predicted test-period performance either.
Fit-period annualised volatility, median daily dollar volume, time in market, daily return autocorrelation and length of history produced rank correlations against test-period Sharpe of 0.091, 0.037, 0.151, 0.260 and 0.216, with p-values of 0.558, 0.766, 0.227, 0.088 and 0.081.
The two closest are not significant at conventional thresholds and do not survive correction for having tested five properties.

The conclusion is that the universe rule must be mechanical and forward-looking, not a list of names chosen from a backtest.

## roostoo-universe-pool-size

Ranking by liquidity inside Roostoo's own list is the wrong construction, and the reason is that the venue list is already a liquidity filter.

Taking the top twenty of Roostoo's 66 names by trailing dollar volume produced a test-period Sharpe of -0.15 and a Screen 3 of -0.213.
Ranking the full 264-name survivorship-free Binance universe and trading whichever of the top names Roostoo lists produced 1.56 and 2.622 over the same window with the same signal.
A rank cut at twenty out of 66 admits the venue's thinnest names; the same cut out of 264 does not. The bar has to be absolute, not relative to a pre-filtered list.

A maturity gate was tested as the alternative explanation and rejected.
Requiring 0, 90 or 180 days of history before a name becomes eligible moved the test-period Sharpe of the Roostoo-ranked book between -0.15 and +0.23, nowhere near closing the gap, so new listings entering at peak volume are not what is driving it.

The edge does not depend on coins Roostoo cannot trade, which was the obvious worry once the research universe turned out to hold names like FUN, OM and VANRY that fell more than 90% in the test period.
Decomposing the research book's profit and loss by venue availability, names absent from Roostoo contributed 20.0% of test-period gross profit while holding 11.7% of book exposure, and restricting the attribution to Roostoo-listed names alone still leaves a gross Sharpe of 1.46 against 1.56 for the full book.
The selection pool needs the breadth; the traded set does not.

One caveat is unavoidable and is recorded rather than hidden.
Intersecting with Roostoo's listing as it stands today is survivorship-conditioned when applied to history, because a name delisted in 2024 is absent from the historical book even though it would have been traded at the time.
The decomposition above bounds how much this can matter, and in live trading the intersection is taken against the listing of the day, which carries no such conditioning.

## roostoo-gross-exposure-breach

The selected construction produced 1.45 times gross exposure on live data and would have breached the no-leverage rule, which the historical average concealed.

Weighting each name at a twentieth of equity while selecting from the top thirty is bounded above by 1.5, and over the test period it averaged 6.0 names and 0.30 gross, so nothing in the backtest summary revealed the problem.
On 2026-09-19 all thirty of the Binance top-thirty are listed on Roostoo and twenty-nine carry a long signal, which is exactly the broad-breakout state the bound is reached in.

A hard cap at 1.0 gross is applied and costs little: test-period Screen 3 falls from 2.859 to 2.622 and Sharpe from 1.61 to 1.56.
The cap is a rules constraint rather than a tuned parameter and is not swept.
The general lesson is that a mean exposure of 0.30 across a backtest says nothing about the maximum, and the maximum is what a compliance rule binds on.

## roostoo-selected-construction

The deployable configuration is the 4h channel on a mechanically selected liquid subset of the Roostoo venue, with a hard gross cap.

Rank the full Binance USDT universe by trailing 30-day median dollar volume, point in time, take the top thirty, and trade whichever of them Roostoo lists.
Each holding is a twentieth of equity, the remainder sits in cash, and total gross exposure is capped at 1.0.
Entry and exit are unchanged: long when the 4h close exceeds the highest close of the prior 20 bars, out when it falls below the lowest close of the prior 10 bars.

Test period 2025-01-01 to 2026-09-19, net of the 5 bps maker fee: 56.5% a year at a Sharpe of 1.56, a Sortino of 2.99, a Calmar of 3.20 and a maximum drawdown of 17.7%, for a Screen 3 of 2.622.
BTC buy-and-hold over the same window returned -8.1% at a Sharpe of 0.02 and a Screen 3 of -0.025.
Fit period 2023-01-01 to 2025-01-01 gave 105.7% a year at a Sharpe of 2.94 and a Screen 3 of 4.381, against buy-and-hold at 138.6%, 2.03 and 3.459.

This is the first configuration in the repo that beats the benchmark on the composite in both halves of the out-of-sample record.
Deflation against the trial ledger has not been rerun and the count has risen materially, so the Gate 4 verdict at `DECISIONS.md#paper-ensemble-trial-count` should be recomputed before this is treated as established.

## gate4-rerun-outcome

Gate 4 was rerun on 2026-09-19 with the selected 4h channel included, and it fails at the honest trial count of 351 while failing differently from everything before it.

The candidate's out-of-sample record from 2023-01-01 is 1358 daily observations at an annualised Sharpe of 2.206, a skew of +1.73 and a kurtosis of 11.77.
Against the trial-Sharpe variance of 0.00088663 established at N=131, the expected maximum Sharpe obtainable by chance across 351 trials is 1.675 annualised.
The Deflated Sharpe Ratio is 0.8687 against the pre-registered threshold of 0.95.

Three things separate this from the previous verdict at `DECISIONS.md#gate4-outcome`.

The observed Sharpe exceeds the null's expected maximum for the first time.
Every prior candidate sat below it, which is why each one's minimum track record length was infinite: no quantity of additional data can establish a Sharpe that is beneath what the search alone would produce.
This candidate sits 0.53 above the null, so its minimum track record length is finite at 2927 observations, or 8.0 years of daily returns against the 3.7 years it currently has.
The claim is not refuted by the data, it is unproven by it.

It also passes at the trial count of its own selection.
Twenty-one universe constructions were evaluated to arrive at this configuration, and at N=21 the Deflated Sharpe Ratio is 0.9905.
That is not the number the gate uses and it is not being promoted to one. The repo's policy at `DECISIONS.md#trial-counting` counts every configuration ever evaluated because each consumed the family-wise budget, and by that policy the answer is 351 and the verdict is failure.

The honest-count-of-one argument that rescued the paper ensemble at `DECISIONS.md#paper-ensemble-trial-count` does not apply here and is not being attempted.
That strategy's parameters were published by someone else before this data was touched.
This one's interval, lookback, exit rule and universe pool were all chosen here, by looking at results. It is a search product and must be counted as one.

## gate4-variance-estimator

Two estimators of the trial-Sharpe variance are reported because the volume family's fastest configurations are not draws from the null the gate assumes.

The Deflated Sharpe Ratio models trial Sharpes as draws from a common distribution centred near zero.
The 1h volume configurations have annualised Sharpes near -21, which is not a draw from any such distribution: it is the arithmetic of paying 660% of NAV a year in fees. Including them would inflate the variance and therefore the hurdle, making the gate harder for reasons that have nothing to do with how much searching was done.

The headline uses the homogeneous estimator of 0.00088663 established at N=131, which keeps the gate comparable to its previous run.
A wider estimator including the low-timeframe channel trials gives 0.00154489, raising the expected maximum under the null from 1.675 to 2.211 and the candidate's Deflated Sharpe Ratio falls from 0.8687 to 0.4958.
Both fail. Reporting only the one that fails less would be the error this entry exists to prevent.

## gate4-standing-verdict

No strategy in this repo has passed Gate 4 at its honest trial count, and the pre-registered threshold is not being moved to change that.

The selected 4h channel is the strongest candidate produced across 351 trials, on every measure the repo tracks: the highest out-of-sample Sharpe at 2.206, the highest skew at +1.73, the only finite minimum track record length, the only configuration to beat the benchmark on the Screen 3 composite in both halves of the out-of-sample record, and the highest joint probability of clearing the Screen 2 return cut while outscoring buy-and-hold on the composite.
It is also unvalidated by the standard this repo set for itself before any of it was run.

Those two statements are both true and neither cancels the other.
The competition entry is a decision under a deadline rather than a deployment decision, and the gate's purpose is to keep the distinction visible: what follows is a bet on the best candidate available, not a strategy demonstrated to have edge.

## bot-architecture

Two bots share one codebase and differ only by a frozen config file, which is what makes the comparison between them a comparison of timeframe rather than of implementation.

`bot/` separates market data, universe selection, signal, portfolio, execution, risk and journalling into modules with explicit interfaces, as Section 8 of the plan requires.
`bot/settings.py` refuses to load a config whose `meta.frozen` is not true and stamps the SHA-256 of the file bytes into every journal record, so a parameter change is visible in the audit trail rather than inferred from commit history.
Bot A is `config/bot_a_4h.yaml` at 4h bars; bot B is `config/bot_b_1h.yaml` at 1h. Entry of 20 bars, exit of 10 bars, a top-30 liquidity pool, a twentieth of equity per name and a gross cap of 1.0 are identical between them.

Market data comes from Binance rather than Roostoo, and this is a deliberate consequence of the finding at `DECISIONS.md#price-source`.
Roostoo publishes no historical endpoint, so a bot sourcing its own bars would need 20 bars of warm-up before it could trade at all, which is a meaningful fraction of a fourteen-day window.
Roostoo mirrors Binance exactly, so the signal is computed from Binance klines, which are available keyless and complete from bar one, while Roostoo's ticker supplies execution prices.
The mirror is not assumed. Every cycle measures the deviation between the two and halts the bot if it exceeds 50 bps, and the first live measurement on 2026-09-19 was 0.9 bps.

## bot-signal-parity

The live signal is an incremental state machine and the backtest is a vectorised array operation, and they were verified to produce identical positions rather than assumed to.

`bot/verify.py` replays the live `evaluate_book` bar by bar over a window of real market data and compares its output cell by cell against `signals/donchian.position`.
On 199 bars across 22 symbols, both bots matched on all 3938 cells with zero mismatches.

This is the check that makes every backtest number in this repo meaningful for the live bot.
A strategy whose live implementation differs from its simulation has no validated performance whatever its backtest says, and the two were written independently enough that agreement is evidence rather than tautology.

## bot-selection

Bot A at 4h bars is selected over bot B at 1h, and the deciding argument is fee robustness rather than backtested performance.

Over the full out-of-sample record bot A dominates: 80.8% a year at a Sharpe of 2.21, a Sortino of 4.28 and a Calmar of 4.58 for a Screen 3 of 3.745, against bot B at 51.4%, 1.58, 3.26, 2.37 and 2.486.
In the recent period from 2025 they are level, bot B marginally ahead on the composite at 2.603 against 2.582 and on the joint competition measure at 9.93% against 8.79%.
On that evidence alone the choice would be close.

The fee assumption breaks the tie, and `costs.confirmed` is still false in the pre-registration.
Bot B pays 15.9% of NAV a year at the assumed 5 bps maker fee and 31.8% at 10 bps, which is the taker rate any unfilled limit order falls back to.
Its Screen 3 falls from 2.486 to 1.473 at 10 bps and to -0.111 at 20 bps.
Bot A pays 4.1% and 8.2% at the same two rates and still scores 2.756 at 20 bps.

Selecting bot B would stake the competition on an unverified fee schedule, where being wrong by one tier removes 40% of the composite and being wrong by two tiers makes it unprofitable.
Bot A survives every fee in the tested range. That asymmetry decides it, and it is the same reasoning recorded at `DECISIONS.md#costs` for preferring the organizer's figures over the README's.

Bot B is kept rather than deleted. It is the comparison that establishes bot A's margin, and if the prep window confirms a fee at or below 5 bps with reliable maker fills, the recent-period evidence for it is real enough to revisit under a declared decision rule rather than a live judgement call.

## bot-self-improvement-scope

The operator asked for a bot that improves itself, and what is built verifies itself instead. The distinction is deliberate.

Refitting parameters on live data during the competition would fit fourteen observations, and the standing result across 351 trials in this repo is that short-sample optimisation reverses out of sample.
It would also change the declared strategy mid-window, which Section 7 of the plan identifies as a Screen 1 failure, and it would make the commit history inconsistent with the behaviour being audited.

What the bot does continuously is measure whether its own assumptions still hold: signal parity against the reference implementation, position reconciliation against the venue wallet, realised fill price against intended price, realised commission against the assumed schedule, and the Binance-Roostoo mirror.
Adaptation is limited to behaviour declared in the frozen config before the window opens, namely the time-based de-risking ramp and the kill switches.
Every one of those checks writes to the journal whether it passes or fails, so a divergence is a logged fact rather than a silent degradation.

## bot-report-annualisation-defect

`bot/report.py` computed Sortino without annualising the downside deviation, inflating it by the square root of 365, and the error was caught by a benchmark sanity check rather than by inspection.

Reported Sortinos of 81.71 and 62.20 were implausible on their face, and BTC buy-and-hold on the same code path returned 34.22 where its known value is 1.7913, a ratio of 19.1 which is exactly the missing factor.
The consequence was not confined to Sortino: the Screen 3 composite caps each term at 5.0, so an inflated Sortino pinned its term at the cap for every configuration and compressed the differences the comparison existed to measure.

The fix restores the annualisation used in `portfolio/backtest.py`, and the benchmark now reproduces its established values exactly.
The lesson recorded is procedural: every new metric implementation is checked against a series whose answer is already known before any of its output is read.

## gate8-regime-outcome

Gate 8 fails on drawdown and passes on every other criterion, and the failure corrects a number that the 2023-onward window had understated by half.

Partitioning the full history from 2017-08-17 by BTC's position against its 200-day average and its trailing 90-day return, the strategy is profitable in all three regimes: 307.2% a year in bull, 20.4% in bear and 23.7% in range, against a pre-registered requirement of positive in two.
The bear-regime result is the substantive finding.
Over the 32.5% of days classified bear, the strategy returned +20.4% at a Sharpe of 0.71 while BTC buy-and-hold returned -69.1% at a Sharpe of -1.32.
A long-only system achieves that by being in cash, which is what the exit rule and the fractional sizing exist to produce, and it is the strongest evidence in this repo that the mechanism is real rather than a bull-market artifact.

The gate fails because the worst regime drawdown is 38.97% against a pre-registered limit of 25%.
The threshold is not being moved.

The more important consequence is that the headline drawdown figure changes.
Measured from 2023 the maximum drawdown is 17.7%; measured over the full history including the 2018 crypto winter and the 2022 bear it is 38.1%.
Every Calmar figure computed on the 2023-onward window is therefore optimistic, and `STRATEGY.md` has been corrected to carry both.
The competition runs for fourteen days and a 38% drawdown is not a fortnight event, but the number a submission quotes should be the one measured over the longest available record.

## gate2-donchian-outcome

Gate 2 passes, and the shape of the parameter surface is the useful part rather than the verdict.

Across a five by five grid of entry windows from 12 to 28 bars and exit windows from 6 to 14, every one of the 25 configurations produced a positive net Sharpe, ranging from 1.48 to 2.02.
The minimum neighbour of the selected point is 75.2% of the peak against a required 50%, and the peak isolation score is 0.103 against a permitted 0.35.
This is a plateau, not a spike, which is the opposite of the signature recorded for `sma_crossover` at `DECISIONS.md#trend-family-outcome`.

The selected configuration is not the peak, and that fact does more for the overfitting argument than the gate result does.
20/10 scores 1.84 while the grid maximum of 2.02 sits at 28/14, and the surface improves monotonically toward slower parameters on full-sample Sharpe.
20/10 was chosen for the fourteen-day window, because a 3.3-day channel completes several cycles inside a fortnight where a 20-day channel completes one, and that reasoning was fixed before this grid was computed.
Selection therefore demonstrably did not follow the surface, and the 25 grid points are recorded as sensitivity rather than as candidate search.

## gate6-walk-forward-outcome

Gate 6 passes with no refitting anywhere in the procedure, which makes it a weaker test than its name suggests and a cleaner one than most.

Seven anchored folds from 2019 to 2025 each expand the in-sample window and evaluate the following calendar year out of sample, holding 20/10 fixed throughout.
Every one of the seven years was profitable out of sample, at annual returns between 17.3% and 472.3%, and the median out-of-sample to in-sample Sharpe ratio is 1.164 against a required 0.6.

Because nothing is refit, this measures stability of the fixed rule across time rather than the decay of a fitted parameter.
That is the correct test for a rule whose parameters were taken from convention, and it would be the wrong test for a rule that was optimised.
The two weakest years are 2022 at a ratio of 0.276 and 2025 at 0.353, both of which are bear or range regimes, and both remained positive.

## bot-state-persistence-defect

The bot held all position state in memory and would have lost every open position on restart, which over a fourteen-day unattended run is a fatal defect rather than an inconvenience.

Nothing in the backtest or the first live cycles could have revealed it, because both start from flat and neither restarts.
A process killed by an out-of-memory event, a deploy, or a machine reboot would have resumed believing it held nothing, and the next cycle would have re-bought positions it already owned until either cash or the gross cap stopped it.

`bot/state.py` now writes position state, cash, universe, equity curve and last processed bar atomically through a temporary file, and `bot/run.py` restores it at startup and persists after every cycle.
A corrupt state file is moved aside rather than crashing the process.
The stored config SHA is compared against the running one and a mismatch is journalled as `config_changed_mid_run`, which is the event a Screen 1 auditor would want flagged.

Local state is not treated as authoritative once live.
On startup and after every cycle outside dry run, the bot reads the venue wallet, reconciles it against local state, journals any mismatch, and adopts the venue's view.
The venue knows what was filled and the bot only knows what it intended, and where they disagree the venue is right.

Verified by running a cycle, killing the process, and running again: ten positions restored, cash unchanged, no duplicate orders.

## gate10-shadow-design

Gate 10 is the only gate that cannot be run faster than real time, and it is now instrumented and accumulating.

`gates/gate10_shadow.py` evaluates five pre-registered conditions from the live journals: at least three distinct days of operation, live-versus-backtest signal agreement at or above 0.95, median fill deviation within 5 bps, no unexplained halts, and no logged errors.
At first evaluation on 2026-09-19 it fails only on elapsed days, at one of three, while signal parity reads 1.0, halts and errors are zero, and the Binance-Roostoo mirror has a median absolute deviation of 0.47 bps and a maximum of 0.90.

Fill deviation cannot be measured in dry run and is reported as unmeasured rather than as passing.
It requires API credentials and live orders, and until those exist the gate's most operationally important check is untested.
This is the largest remaining unknown before the window opens and is listed as such rather than left implicit.

## maker-fill-assumption-measured

The entire fee argument for this strategy rests on limit orders filling as maker, and that assumption was measured rather than assumed, without needing any venue credentials.

The bot posts a limit 1 bp inside the touch and cancels after 15 minutes.
Across the 22 selected symbols and 1000 minutes of 1-minute Binance data, a limit posted at that offset is reached within 15 minutes on 93.8% of occasions at the median symbol, 88.0% at the tenth percentile and 70.9% at the worst symbol.
Buy and sell sides are symmetric at 93.6% and 94.1%.

Blending 5 bps on the filled fraction and 10 bps on the remainder gives an effective 5.31 bps per side, or 10.62 bps round trip.
That sits inside the range already tested at `DECISIONS.md#bot-selection`, where bot A scored 3.393 at a 10 bps round trip against 3.745 at 5 bps, so the fee assumption is confirmed rather than merely survivable.

Fill rate rises with the timeout, reaching 95.3% at 30 minutes and 96.9% at an hour.
The 15-minute timeout is kept because a stale limit order is an unhedged directional exposure that the signal no longer endorses, and the marginal 1.5 percentage points of fill rate is not worth holding one.

This is an upper bound on a real venue rather than a measurement of one.
It assumes an order resting at a price is filled when the market trades through it, which ignores queue position, and Roostoo's matching behaviour is not observable without credentials.
The direction of the error is known: real fill rates will be at or below these, so the effective fee will be at or above 5.31 bps per side.

## interim-test-venue

Binance Spot Testnet is the interim venue for exercising the order lifecycle before Roostoo credentials exist.

Four candidate venues were probed on 2026-09-19. Binance Spot Testnet, Bybit testnet and Kraken public all responded; OKX timed out from this environment and Alpaca requires credentials to return anything.

Binance Spot Testnet is chosen for a reason specific to this project rather than on general merit.
`DECISIONS.md#price-source` established that Roostoo does not approximate Binance, it mirrors it, at a median deviation of 0.00 bps across the venue universe and 0.47 bps measured live by the bot.
Testing fills against Binance's own matching engine is therefore the closest obtainable proxy for how orders will behave on Roostoo, which no other venue offers.

`venue/binance_testnet.py` presents the same interface as `venue/roostoo.py`, so `bot/execution.py` and `bot/run.py` are unchanged and the venue is selected by a config key or the `BOT_VENUE` environment variable.
Instrument specifications are translated from Binance's `PRICE_FILTER`, `LOT_SIZE` and `NOTIONAL` filters into the same `PairSpec` the Roostoo client emits, so precision and minimum-order handling is exercised on real venue rules rather than on Roostoo's alone.
Public verification on 2026-09-19 returned 487 tradable USDT pairs with correct tick and step parsing.

What this does and does not test should not be blurred.
It tests the order lifecycle: signed request construction, partial fills, rejections, precision and minimum-notional handling, cancel-and-replace, and the maker versus taker attribution that the fee argument depends on.
It does not test Roostoo's own API, whose signing scheme, error envelope and short-selling endpoints differ, and those remain unexercised until credentials arrive.

## qty-precision-defect

`PairSpec.round_qty` produced quantities that a real venue rejects, and only a live order revealed it.

The implementation was `(qty // step) * step` in binary floating point, which for a 200 USD order in BTC at five decimal places yields 0.0024600000000000004 rather than 0.00246.
Binance rejected it with `-1111 Parameter 'quantity' has too much precision`.
Roostoo declares `AmountPrecision` the same way and would reject the same value, so this was a live defect for the competition venue and not an artifact of the test harness.

Nothing in the backtest could surface it.
The backtest never formats an order, it multiplies weight vectors, so the entire research pipeline is blind to wire representation.
This is the specific class of defect the interim venue at `DECISIONS.md#interim-test-venue` exists to catch, and it justifies that work on its own.

The fix uses `Decimal` with explicit `ROUND_DOWN` quantisation, and adds `format_qty` and `format_price` so both venue clients send exact decimal strings rather than repr of a float.
Rounding down rather than to nearest is deliberate: rounding up can exceed available balance or breach the gross cap by a tick.

## limit-price-retraction

A claim that the bot was crossing the spread and paying taker fees on every trade was made and is withdrawn.

The observation behind it was real, that an order placed during the lifecycle test filled immediately as TAKER at 10 bps.
The inference was wrong. That order's price came from a formula hand-written inside `gates/order_lifecycle.py`, not from `Executor.limit_price`, which already clamped a buy to `ask - tick` and a sell to `bid + tick`.
The bot's pricing was correct before the test and is unchanged by it.

Two lessons are recorded rather than the correction alone.
A test harness that reimplements the logic it is testing does not test that logic, and the harness now calls `Executor.limit_price` directly.
And the same turn produced a claim that `bot/run.py` and `venue/roostoo.py` contained edits from an unknown source; both were traced to commit `208077c`, which is this repo's own history, so that claim is withdrawn too.

## exposure-telemetry-defect

The journal reported zero gross exposure while the bot held half its equity in positions, which for a Screen 1 audit trail is a misrepresentation rather than a cosmetic bug.

`cycle` recomputes channels only when a new bar closes and logged the resulting target weights.
On every intermediate cycle that target was an empty dictionary, so the record showed `gross_exposure` of 0 and `n_long` of 0 while ten positions worth roughly 50% of equity were open.
Trading was never affected, because orders are computed only on a fresh bar or a halt, but the audit trail said the book was flat when it was not.

The record now carries actual held weights and an explicit `positions` map on every cycle, with the target reported separately and only when it was recomputed.
Verified against a live cycle: `gross_exposure` 0.5002 across ten named positions.

## process-supervision

Several reports in this session stated that both bots were running continuously and accumulating shadow days. That was wrong and is corrected here.

Background processes started from the agent's tool calls did not survive between calls, so each reported run was a short burst followed by silent death, visible afterwards as six `resumed` lifecycle events and cycle gaps far exceeding the configured poll interval.
The supervisor script also used `setsid`, which does not exist on macOS, so it never detached anything.

`run_bots.sh` now uses `nohup` with `disown` and a respawn loop, tracks supervisor PIDs under `run/`, and exposes `start`, `stop`, `restart`, `status` and `report`.
Verified surviving across a tool-call boundary.

The operational conclusion stands regardless of the fix.
Gate 10 requires three distinct days of live operation, and that cannot be produced from an agent session.
It has to run on the operator's machine or the competition EC2 instance, which is what Section 7 of the plan requires in any case, and `deploy/` now carries a systemd unit and instructions for exactly that.

## live-scan-universe-confirmation

The universe rule was confirmed on live data that postdates every backtest used to choose it.

The channel logic was run against all 66 Roostoo-tradable cryptocurrencies on 700 freshly fetched 4h bars, roughly 117 days, net of the 5 bps maker fee.
The 22 names in the selected top-30 liquidity pool had a median Sharpe of 1.28 and were positive in 95.5% of cases, against 0.56 and 63.6% for the 44 outside it, with median returns of 18.7% and 5.2%.
A Mann-Whitney test of selected against the rest gives p=0.0021.

This matters because the liquidity rule was chosen at `DECISIONS.md#roostoo-universe-pool-size` on the 2025 period, and this window is later data, a different measurement, and one coin at a time rather than as a portfolio.
The rule reproduces on all three counts.

One column in the first version of the scan was mislabelled.
`roostoo_vs_binance_bps` compared a live Roostoo ticker against a bar close up to four hours stale, so its 300 to 400 bps readings measured price drift since that bar, not mirror error.
It is renamed `drift_since_bar_close_bps`. The bot's own mirror check uses fresh one-minute klines and has stayed below 6 bps throughout.

## trade-blotter

Order records alone do not show what the strategy earned, so `bot/blotter.py` reconstructs round-trip trades from them by FIFO lot matching.

The journal records intent and acknowledgement per order, which is what Screen 1 audits, but it cannot answer whether a position made money.
The blotter pairs each sell against the oldest open buy lot for that symbol, apportions both legs' fees to the matched quantity, and emits realised gross and net profit, return percentage, holding period and the role each leg filled as.
Lots still open are reported separately rather than marked to market, so realised and unrealised are never mixed in one figure.

Fees come from the venue's reported `CommissionPercent` where a real fill supplied one, and fall back to the configured schedule only for dry-run fills.
This matters because `DECISIONS.md#costs` records that the README and the organizer disagree about commission by a factor of eight, and the blotter is where the answer becomes visible once real fills exist.

Two accounting identities are checked and must hold: quantity bought equals quantity closed plus quantity still open, and quantity sold equals quantity closed.
Both held exactly on first evaluation, against 10 fills for bot A and 19 for bot B.
A breach means the blotter and the venue have diverged, which is a reconciliation failure rather than a reporting one.

First realised trades, both from bot B at 1h bars, were AVAX at +0.793% net over 1.06 hours and WLD at +0.319% net over 0.67 hours.
Fees consumed 12.4% of gross profit on those two, which is the cost drag of the fast configuration showing up in realised terms exactly as the backtest predicted and is the reason bot A was selected.

## fast-horizon-outcome

The operator asked for shorter-horizon bots that flip faster and scrape profits. Twenty configurations were declared at `config/fast_horizon.yaml` and tested, and the answer is that the channel rule dies below one hour for two independent reasons rather than one.

The first is the arithmetic the declaration named in advance.
Mean absolute bar return against a 10 bps round trip runs 1.41 times at 5m, 2.46 at 15m, 3.46 at 30m, 4.87 at 1h and 9.81 at 4h.
At five minutes the average move is barely larger than the cost of capturing it, so the strategy needs to be right about direction nearly every time simply to break even.

The second was not anticipated and matters more.
Gross Sharpe, measured before any cost at all, falls monotonically as the bar shortens: 1.38 at 4h, 1.26 at 1h, 1.15 at 30m, 0.45 at 15m and **negative 0.22 at 5m**.
The signal itself inverts. A five-minute breakout is not a weak edge being eaten by fees, it is noise that mean-reverts, and no fee schedule rescues a negative gross edge.

Net results at the 5 bps maker fee, on the five most liquid names from 2023, are 4h at a Sharpe of 1.24 and 45.0% a year, 1h at 0.68 and 19.5%, 30m at -0.01, 15m at -1.92 and -50.1%, and 5m at **-7.15 and -91.8%**, with a maximum drawdown of -100%.
At the 10 bps taker fee 5m returns -99.2% a year at a Sharpe of -14.01.
Trade frequency runs 32.5 a day at 5m against 0.64 at 4h, and annual cost drag 238% of NAV against 5%.

The universe chosen was the five most liquid names with 5m history, which is the most favourable case available for fast trading.
Failure there generalises; success there would not have.
Four-hour bars are the optimum of the tested range on every metric, and the ordering is monotonic, so there is no faster configuration worth building.

## mirror-materiality

The mirror kill switch counted single-tick rounding as price divergence, which on cheap coins is large enough to approach a halt on its own.

PEPE trades near 3.8e-06 with a tick of 1e-08, so one tick is 26.2 bps.
An observed deviation of 26.178 bps was exactly one tick, which is the smallest representable difference between the two feeds and carries no information.
`mirror_check` now reports `tick_bps`, the deviation expressed in ticks, and a `material` flag requiring the deviation to exceed two ticks, and the halt considers only material rows.

A second hypothesis was tested and rejected.
The spikes were initially attributed to comparing a live Roostoo tick against a one-minute Binance bar close up to sixty seconds stale, but `mirror_check` was already using the live price endpoint, so staleness is not the cause.
The 20 to 35 bps excursions are genuine transient divergence between the two feeds during fast moves, and AVAX at 21 ticks of deviation is real rather than an artifact.

## mirror-halt-hysteresis

A single-cycle mirror excursion would have liquidated the entire book, and the observed excursions come close enough to the threshold that this was a live risk rather than a theoretical one.

On a halt the target weight set is empty and orders are computed, so the bot flattens to cash.
That is correct behaviour for a genuine feed failure and catastrophic for a transient one, because it realises losses and surrenders every position the signal still endorses.
Measured material deviation has a median near 5 bps but reached 34.69 bps against a 50 bps threshold, which is 69% of the way to an unrecoverable action on a feed that returns to zero deviation seconds later.

The halt now requires the breach on two consecutive cycles.
The threshold itself is pre-registered and is not moved, which matters because raising it would weaken the control, whereas requiring persistence removes only the transient case the control was never meant to catch.
A genuine feed failure persists across cycles and still halts within one poll interval.

## live-monitoring-first-session

First live observations, all from roughly two hours of paper trading, and none of them a basis for changing the strategy.

What is working: zero errors and zero halts across 88 and 152 cycles, the blotter's accounting identities holding exactly, and the pre-registered spread filter firing correctly on a real case, skipping ENA at 5.01 bps against the declared 5.0 limit.
Two closed trades, AVAX at +0.793% net over 1.06 hours and WLD at +0.319% over 0.67 hours, both from bot B.

What the numbers do not support: anything at all.
Two trades is not a sample, a win rate of 1.0 is noise, and bot A has recorded one new-bar cycle in its entire run because a 4h bar closes six times a day.
The standing result across 351 trials is that short-sample optimisation reverses, and two trades is shorter than any sample that produced that finding.
The only figure worth carrying forward is that fees consumed 12.4% of gross profit on bot B's two trades, which is the fast configuration's cost drag appearing in realised terms exactly as the backtest predicted, and is confirmation of the existing selection rather than a reason to revisit it.

## sizing-sweep-outcome

Number of holdings and position size were swept across 17 declared configurations, and the result is that neither can be fitted from this data.

The fit window cannot discriminate.
Across every pool of 30 or 40 and every divisor from 10 to 30, the fit-window Screen 3 spans 4.370 to 4.395, a range of 0.025 on a statistic near 4.4.
That is noise, and any argmax taken from it is arbitrary.

Worse, the fit argmax is the holdout's worst.
Selecting on the fit window chooses a divisor of 10, the most concentrated setting, at a fit Screen 3 of 4.395 and a holdout Screen 3 of 2.169.
The holdout's best is a divisor of 25 at 2.810.
The Spearman rank correlation of Screen 3 between the two windows is 0.50, so the fit window is close to uninformative about which setting will work next.

The holdout does show a clean monotonic pattern, and it runs in opposite directions for the two screens.
Screen 3 rises as positions shrink, from 2.169 at a divisor of 10 through 2.623 at 20 to 2.808 at 25.
Probability of clearing the Screen 2 return proxy falls across exactly the same range, from 26.4% at 10 through 21.0% at 20 to 17.3% at 25.
This is the collinearity already recorded at `DECISIONS.md#beta-is-the-only-screen3-lever`, now measured on the sizing parameter rather than on a core-versus-sleeve blend.

Two findings are unambiguous and are adopted.
A pool of 20 is worse than 30 or 40 on every measure in both windows, so the pool stays at 30; 40 is indistinguishable from it and adds nothing.
Capping gross below 1.0 hurts, at holdout Screen 3 of 2.101 at a cap of 0.6 and 2.087 at 0.8 against 2.169 uncapped, so the cap stays at 1.0 where the no-leverage rule puts it anyway.

The divisor is not changed.
Moving to 25 would improve the holdout Screen 3 by 0.19 and cost 3.7 percentage points of qualification probability, and the only evidence for it comes from the window being used to judge it.
The pre-registered 1/20 sits mid-range on the holdout and is the single value in the grid that was not chosen by looking at either window, which is the only property that makes it defensible.

## book-is-mostly-cash

The sweep surfaced a property of the strategy that had not been stated plainly: it is usually not invested.

Mean gross exposure is 0.18 and the mean number of names held is 3.7 out of a pool of 30, so the book sits roughly 82% in cash across the out-of-sample record.
This is the mechanism behind the drawdown control and behind the bear-regime result at `DECISIONS.md#gate8-regime-outcome`, and it is also the reason probability of clearing a 5% fortnightly return is only 21%.

The live reading on 2026-09-19 of ten names and 0.50 gross is therefore unusual rather than typical, and follows from the same broad breakout that has 64 of 66 Roostoo names long.
Anyone reading the dashboard today should not treat 50% gross as the strategy's normal state.

## prospective-paper-lab

The operator requested a logic review, stronger signals if an edge exists, and simultaneous live-market horizon tests.
The review found that immediate dry fills, incomplete universe ranking and silent market-data loss make the existing shadow results unsuitable for this selection.
The evidence and remaining gaps are recorded in `results/logic_review_2026_09_19.md`.
An isolated public-data-only experiment is declared in `config/paper_lab.yaml` before its first forward cycle.
Four channel horizons, one 4h flow-confirmed entry candidate, and an executed BTC benchmark add six configurations to the append-only ledger.
The baseline competition configuration and preregistered thresholds are not changed.
No additional edge has been established.
The paper lab requires later observed quote crosses for fills, reserves cash including fees, atomically persists orders and wallets, and rejects incomplete data rather than converting it into a trading decision.
Forward reports suppress annualised metrics until 28 complete sampled days and never automatically promote a winner.
Simulated fills cannot satisfy the real-fill portion of Gate 10.
The 28-day reporting floor is a separate experiment rule, not a replacement for any registered gate or a claim of statistical sufficiency.

## fortnight-scoring-review-correction

The logic review found the missing Sortino annualisation still present in five independent fortnight scorers: bot_comparison, competition_window, donchian_lowtf, paper_ensemble and volume_sweep.
The fix to bot/report did not propagate to those copies.
They divided annualised mean return by daily downside deviation, inflating Sortino by sqrt(365) before clipping and artificially encouraging the apparent sign-indicator behavior.
All five now annualise downside deviation, include starting capital in the drawdown peak, and use sample standard deviation consistently with bot/report.
Regression tests call every implementation, compare with daily NAV accounting, and verify the closed-form Sortino of an alternating -1%, +2% return sequence.
Prior fortnight Screen 3 rankings and the collinearity claims that depend on them must be re-evaluated; raw-return qualification frequencies are unaffected by this scoring correction.
Corrected A/B results are written separately to results/bot_comparison_corrected.json so the old artifacts remain an audit trail.

## concentration-outcome

Concentrating into the best few names rather than holding everything that signals was tested across four point-in-time ranking rules and five position counts, and it produced the first configuration in this repo to improve both screens at once.

Ranking by trailing 20-bar return and holding the top three gives a holdout Screen 3 of 3.098 against the incumbent's 2.623, and a probability of clearing the 5% fortnightly proxy of 40.4% against 21.0%.
Holding the top five gives 2.957 and 36.3%.
Both beat the incumbent on Screen 3 and roughly double its qualification probability.

The mechanism is exposure rather than selection skill.
The incumbent holds 3.7 names at 0.18 gross and is therefore 82% cash, which is recorded at `DECISIONS.md#book-is-mostly-cash`.
Concentrating into three names at equal weight lifts mean gross to 0.56, so capital that was sitting idle is deployed.
More beta raises the right tail that Screen 2 needs, and the momentum ranking apparently picks well enough that Screen 3 does not deteriorate to pay for it.
This is the first measured exception to `DECISIONS.md#beta-is-the-only-screen3-lever`, and it is an exception because the constraint being relaxed is idle cash rather than risk appetite.

The ranking rule matters more than the count, and that is the part of this result with real support.
Momentum beats breakout, liquidity and low-volatility at every one of the five position counts tested, at holdout Screen 3 of 3.098, 2.957, 2.455, 2.278 and 2.706 for N of 3, 5, 8, 10 and 20.
Liquidity and low-volatility ranking collapse at small N, to 0.463 and 0.424 at three names, because neither has any relationship to which breakout is working.
A consistent ordering across five independent counts is mechanism, not a fitted point.

Three cautions apply and none of them is minor.

The fit window would not have found this.
Its argmax is breakout at ten names, which scores 2.394 on the holdout, while the holdout's best is momentum at three.
The fit-versus-holdout Spearman is 0.68, better than the 0.50 of the sizing sweep but still a weak predictor, so selecting momentum-3 because it won the holdout is holdout-fitting and must be labelled as such.

Drawdown roughly doubles.
Momentum at three names draws down 42.4% against the incumbent's 17.4%, and at five names 33.0%.
The full-history figure would be worse again, since `DECISIONS.md#gate8-regime-outcome` showed the 2023-onward window understates drawdown by about half.

Three names is not three names.
Mean holdings at N=3 is 1.7, because the channel rule is often long fewer than three of the pool at once.
A book that averages 1.7 positions is a concentrated directional bet whose fortnightly outcome is dominated by idiosyncratic moves in one or two coins, which is precisely the variance profile that makes a 14-day Sharpe meaningless.

## dashboard-breadth-is-not-the-book

The dashboard reporting 64 of 66 coins long while the bot holds ten positions is not an inconsistency, and the panel now needs to say so.

Market breadth scans the entire venue to give regime context; it is not the bot's book.
The bot trades a 22-name pool and only acts when a bar closes.
Bot A had recorded one new-bar cycle in its entire run at the time of the screenshot, because a 4h bar closes six times a day and the bot had been running about three hours, so its book is the decision taken at the 08:00 bar and nothing since.
Bot B, on 1h bars, had four new-bar cycles and moved its target from seven names to eight across them.

The lag is correct behaviour rather than a defect. Acting only on closed bars is what makes the live signal reproduce the backtest exactly, which is the property verified at `DECISIONS.md#bot-signal-parity`.

## bot-c-declaration

`bot_c_5names` runs the momentum-ranked top five alongside bots A and B rather than replacing A, and the reason for running rather than switching is stated in the config itself.

The configuration is holdout-informed.
`DECISIONS.md#concentration-outcome` records that the fit window's argmax was breakout at ten names, which scores 2.394 on the holdout, while the holdout's own best was momentum at three.
Choosing momentum at five is therefore a choice made after seeing the window used to judge it, and the only honest way to adopt it is to let it accumulate its own forward record next to the incumbent rather than assert it is better.
`meta.caution` in `config/bot_c_5names.yaml` carries that statement so it cannot be read without it.

Five names rather than three is deliberate and is not the holdout optimum.
Three scores 3.098 against five at 2.957, but three draws down 42.4% against 33.0% and averages 1.7 actual holdings against 2.3.
A book that averages under two positions is a single-name directional bet, and its fortnightly outcome is idiosyncratic in a way no risk-adjusted statistic over fourteen observations can express.
Giving up 0.14 of composite to halve the single-name concentration is a risk decision rather than a performance one.

Ranking is computed from the same bar matrix the signal uses, over the declared 20-bar lookback, and applies only to names already long.
It never introduces a position the channel rule did not select, so it can only subtract from the incumbent's book, never add to it.

## bot-c-ranked-parity

The ranked book was verified against its backtest before being allowed to trade, on the same standard applied to the plain channel at `DECISIONS.md#bot-signal-parity`.

The live path evaluates the channel state machine bar by bar and then calls `portfolio.rank_and_select`; the reference path computes the vectorised Donchian position and takes the top five by momentum with pandas.
Across 179 bars and 22 symbols, the two agree on all 3938 cells with zero mismatches, and both select a mean of 4.02 names.

Mean selection below five is expected rather than a defect.
The channel rule is frequently long fewer than five of the pool at once, and the ranking cannot manufacture a position the signal has not produced.

First live cycle ranked ten signalling names, kept ENA, AVAX, SUI, TAO and LINK, and placed five orders of which four filled.
ENA did not fill because the pre-registered spread filter rejected it at 5.01 bps against the 5.0 limit, which is the same control firing correctly that was recorded at `DECISIONS.md#live-monitoring-first-session`.

## concentration-timeframe-outcome

The momentum-ranked top-five logic was run across five bar intervals and three ranking lookbacks, and it produced the first selection in this repository that the fit window would have got right.

The fit-versus-holdout Spearman across the 15 configurations is **0.95**, and the fit argmax is the holdout argmax: 4h bars with a 40-bar ranking lookback, scoring 4.443 on the fit window and 3.409 on the holdout.
Every previous sweep in this repo had a fit window that either could not discriminate or actively pointed the wrong way, at 0.50 for sizing and 0.68 for the concentration rule.
A rank correlation of 0.95 across fifteen independent points, with the two argmaxes agreeing, is a different quality of evidence, and it is the reason this particular parameter is changed while the others were not.

Four-hour bars dominate at every ranking lookback tested, on both windows.
Holdout Screen 3 at the best lookback runs 3.409 at 4h, 2.380 at 8h, 1.845 at 1h, 1.833 at 12h and 0.624 at 1d.
The ordering is identical on the fit window.
This is consistent with `DECISIONS.md#donchian-lowtf-outcome` and `DECISIONS.md#fast-horizon-outcome`, which found 4h optimal for the channel rule itself, and it now holds for the ranking layer on top of it.

Daily bars are the clear failure case, at a holdout Calmar of -0.02 to 0.30 and a maximum drawdown near 57%.
A 20 or 40-day ranking lookback on daily bars is measuring a different regime from the one the 20-bar channel is trading, so the ranking actively fights the signal.

`bot_c_5names` is updated from a 20-bar to a 40-bar ranking lookback.
The 20-bar value was the worst of the three tested at 4h, at a holdout 2.957 against 3.199 at 10 bars and 3.409 at 40, and it was chosen before this sweep existed.
The change is journalled as `config_changed_mid_run` with both SHAs, which is the event a Screen 1 auditor should see, and it is being made now precisely because the prep window is when configuration changes are legitimate.

The distinction from `DECISIONS.md#bot-c-declaration` must not be blurred.
The choice of momentum ranking and of five positions remains holdout-informed and is still labelled as such.
Only the ranking lookback has support from both windows.

## no-additional-timeframe-bots

Bots at 8h, 12h and 1d are not being run, and the reason is that the evidence is not close.

The operator asked for the logic to be tested on other timeframes, and it was, across fifteen configurations.
Running live bots at intervals the backtest ranks well below 4h would spend supervision and attention on configurations already known to be inferior on both windows, and would add restart counters and journals that a reader must then discount.

One-hour operation is already observable through `bot_b_1h`, which runs the unranked channel at 1h, so the two intervals worth watching live are both covered.
If the 4h configuration degrades in forward testing, the ranked variants at 8h are the next candidates and their parameters are already measured.

## strong-retraced-outcome

**Zero of 24 configurations pass.** The state the operator identified live - a name that has run hard but sits just below its entry channel - is worse than simply requiring the new high, in every configuration tested.

The comparison that matters is against the `new_high` control, which applies the SAME strength filter but demands a new 20-bar high, so the only difference is the retrace. On the holdout the retraced arm loses to it in all 24 cells, by 1.17 to 2.85 of Screen 3. On `donchian_4h` at strength >= 30% the retraced arm scores +0.028 to +0.995 against the control's +1.52 to +1.59; on `momentum_top5_4h` it scores -0.183 to +2.390 against +2.24 to +2.85.

The `weak_retraced` control settles what the strength filter is doing. At the tightest retrace the two controls are close - +2.264 weak against +2.359 new-high on `donchian_4h` - so most of the performance in this family comes from the retrace window being narrow, not from the coin having been strong. Requiring 30% strength actively HURTS: it cuts entries from 467 to 166 and roughly halves holdout Screen 3.

Every arm also shows the fit-versus-holdout gap that has become this repo's signature. Fit Screen 3 sits between +3.49 and +4.39 for all 24, while holdout ranges -0.18 to +2.39. The fit window cannot discriminate here at all.

**The live observation that motivated this was real and the inference from it was wrong.** On 2026-09-20 the books held TRXUSDT at +1.0% over seven days while declining ENAUSDT at +52.4% and AVAXUSDT at +34.2%, both around 5% below their 20-bar high. That looked like the rule missing obvious winners. Measured across every name and the full history, buying that state is worse than waiting for the high - the pullback from a spike resolves downward often enough to erase the advantage of entering cheaper.

Twenty-four trials recorded, ledger 730 to 754. No live bot is changed.
## exit-walkforward-outcome

`DECISIONS.md#ratchet-outcome` left one question open: the holdout preferred `exit_bars` = 3 while the fit window preferred the live 10, so adopting 3 would have been selection on the test set. This runs the honest version - a process that re-picks the lookback on an expanding window using only past data, trades the next 90 days with that pick, and stitches the result.

Thirty-three blocks per book from 2018-08-17, choices of 3, 5, 7, 10 and 15 bars, minimum one year of training before the first pick.

**Re-selecting is worse than leaving the parameter alone, in both books.**

| book | walk-forward | fixed 3 | fixed 5 | fixed 7 | **fixed 10 (live)** | fixed 15 |
|---|---|---|---|---|---|---|
| donchian_4h | +2.822 | +3.010 | +3.170 | +3.029 | **+3.373** | +3.278 |
| momentum_top5_4h | +3.837 | +3.772 | +3.900 | +3.597 | **+3.896** | +4.017 |

On `donchian_4h` the walk-forward is the WORST of the six options, losing 0.55 of Screen 3 to the live setting and losing to every fixed alternative including the ones it was choosing between. On `momentum_top5_4h` it again loses to the live setting and carries the worst maximum drawdown of any arm at -46.6% against -35% to -41% for the fixed choices.

The pick distribution explains it. The process chose 15 bars in 17 of 33 blocks for `donchian_4h` and 20 of 33 for `momentum_top5_4h` - it kept selecting the LONGEST lookback, not the short one the holdout favoured. An honest process would rarely have held 3 at all, so the +3.183 holdout figure for `exit_bars` = 3 was never capturable.

**The live setting of 10 is well chosen on the long record**, ranking first or second of six on the full 2018-2026 span in both books. The fit-versus-holdout conflict at `#ratchet-outcome` is therefore not evidence that 10 is wrong; it is evidence that 2023-2025 and 2025-2026 disagree about the lookback and neither predicts the other.

This closes the exit-lookback question. `exit_bars` stays at 10, and the reason is now measured rather than defaulted: no selection rule tested beats not selecting.

No trials are added. Nothing was selected and no configuration was created; the walk-forward is a measurement of a PROCESS, and the five fixed settings are already in the ledger from `#ratchet-outcome`.

## coin-selection-does-not-persist

Tested 2026-09-20 after an operator request to trade only the coins with the most predictable patterns and the most exploitable counterparties.

Per-coin Sharpe under the live 20/10 channel rule was measured on the fit window and on the holdout, for the 38 names with enough history in both, net of 5 bps.

**The ranking does not persist. Spearman is +0.091 with p = 0.586**, which is indistinguishable from zero, and sign agreement is 27 of 38.

The direction of the failure is worse than mere noise:

| group, chosen on the FIT window | mean fit Sharpe | mean holdout Sharpe |
|---|---|---|
| top 8 coins | +1.60 | **+0.50** |
| bottom 8 coins | -0.26 | **+0.61** |
| all 38 coins | - | +0.43 |

**The eight worst coins in the fit window went on to beat the eight best.** Selecting names on past edge would have actively hurt, and holding everything liquid beat both halves of the selection.

BTCUSDT is the clearest single case: the best coin in the fit window at +1.93, and -0.31 in the holdout.

This is the same failure already recorded at `DECISIONS.md#sizing-sweep-outcome`, where the fit argmax was the holdout's worst setting, now measured on the cross-section rather than on a parameter. It is the quantitative case for keeping the point-in-time top-30-by-ADV universe rule exactly as it is: the rule exists to stop the book choosing names on history, and the cost of overriding it is measurable.

### What this does NOT refute

The result is about past RETURNS as a selector. It says nothing about selecting on who is trading, which is a different observable: `data/microstructure.py` records that the top 5% of trades carry 76.6% of BTC notional, and `data/futures.py` records funding, open interest and top-account positioning per name.

Those cannot be backtested here, because `/api/v3/depth` is a snapshot endpoint with no history and the futures ratio endpoints serve roughly 30 days. They are published by the scanner and can only be validated forward. That limitation was recorded before the data was integrated, at `DECISIONS.md#data-integration-2026-09-20`, and it still binds.

No trials are added: nothing was selected and no configuration was created.

## ratchet-declaration

Declared 2026-09-20 at `config/ratchet.yaml`, before any backtest, after a measurement of how much of each winner the exit surrenders.

Reconstructed on 2,966 completed `donchian_4h` trades and 2,747 `momentum_top5_4h` trades since 2023: winners realise +9.29% against a peak of +14.08%, keeping 66% of the peak, and the top 5% by peak realise +47.12% against +68.55%, surrendering 21 percentage points.
Mean give-back across all trades is 4.17pp against a mean realised return of +4.12%, so the exit costs roughly what the strategy earns.

The rule shortens the exit LOOKBACK as unrealised gain grows, latched so it can never widen again inside a trade. It is not a take-profit, because there is no ceiling and a winner can run indefinitely, and it is not a uniformly faster exit, because a losing position keeps the full base lookback.

**The control was declared as the whole test.** Every ratchet arm is scored against the uniform arm running that same tight lookback on every position, not against the live baseline, because a shorter stop can beat the baseline by accident and the question is whether the ASYMMETRY contributes anything.

## ratchet-outcome

**The asymmetry is worth nothing: 0 of 18 ratchet arms pass.**

Against its own matched uniform control the ratchet loses on the holdout in 13 of 18 cells, and where it wins the margin is small and unsupported by its neighbours. On `donchian_4h` every ratchet arm is beaten by its uniform equivalent, by up to 0.718 of Screen 3. Skew is lower than the matched control in all 18 cells, which is the declared kill criterion arriving directly.

The mechanism is therefore refuted as stated. Tightening only on winners does not protect accumulated gain better than tightening on everything; the benefit of a short lookback comes from the lookback, not from where it is applied.

### The control is the finding, and it fails the repo's own adoption standard

Shortening `exit_bars` from the live 10 to 3, uniformly, improves the holdout on every dimension at once:

| book | bars | fit S3 | hold S3 | skew | maxDD | kept share | cost drag |
|---|---|---|---|---|---|---|---|
| donchian_4h | **10 (live)** | **+4.381** | +2.622 | +1.96 | -17.7% | 0.577 | 4.5% |
| donchian_4h | 3 | +3.989 | **+3.183** | **+3.26** | **-13.3%** | **0.823** | 7.1% |
| momentum_top5_4h | **10 (live)** | **+4.385** | +2.953 | +2.40 | -33.0% | 0.566 | 20.1% |
| momentum_top5_4h | 3 | +4.319 | **+3.454** | **+3.66** | **-29.4%** | **0.830** | 23.7% |

Higher composite, higher skew, shallower drawdown and 25 percentage points more of each peak retained, with the extra turnover already charged.

**It is not adopted, because the fit window disagrees.** Both books score their best fit-window Screen 3 at the live setting of 10 and their best holdout at 3. `DECISIONS.md#concentration-timeframe-outcome` sets the standard that a change is adopted only when both windows agree, and `#sizing-sweep-outcome` measured what happens otherwise: the fit argmax was the holdout's worst setting.
Taking bars = 3 here would be selecting on the holdout, which is the single most repeated failure in this repository.
It is also the boundary of the declared grid, so the apparent optimum may lie outside what was tested and the estimate is an extrapolation.

### This does not contradict the exit-clock null, and the difference is worth keeping

`DECISIONS.md#exit-clock-outcome` found that checking the exit MORE OFTEN made holdout drawdown worse in all twelve arms. This sweep finds that a TIGHTER LEVEL checked at the same frequency makes it better.
Those are different interventions. The first releases a position part-way through a 4h bar on intrabar noise the bar close would have survived; the second still decides only on 4h closes, but against a 3-bar low rather than a 10-bar low. The clock is load-bearing; the lookback width is not.

Twenty-six trials are recorded, taking the ledger from 704 to 730. No live bot is changed.

### Two measurement defects were found and fixed inside this gate

`gates/concentration.stats` does not report skew, so the first run printed +0.00 for every arm on the declared kill criterion. Skew is now computed locally.
Kept-share was a mean of per-trade ratios and produced values such as -37, because a trade with a peak of +0.1% yields an arbitrarily large ratio. It is now an aggregate of realised over peak across trades whose peak reached at least 2%.

## meanrev-xs-declaration

Declared 2026-09-20 at `config/meanrev_xs.yaml`, before any backtest, after an operator request for a mean-reversion bot built on research rather than on a parameter search.

The design came from two papers rather than from a grid.
Dobrynskaya, *Cryptocurrency Momentum and Reversal* (2,000 largest coins, 2014-2020), finds momentum up to two to four weeks and significant reversal only **beyond one month**.
Zhang et al., *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets* (IRFA 78, 2021), finds daily and weekly reversal to be an **illiquidity** effect, with the largest and most tradeable coins showing daily and weekly **momentum** instead.

That second result is the important one for this repo, because the live pool is the top 30 names by ADV, which is exactly the segment the literature says should show momentum and not reversal at short horizons.
It is the most likely explanation for two nulls already recorded: `#scalp-meanrev-outcome` (54 configs, price-only, 5m to 30m) and `#flow-scalp-outcome` (72 configs, order-flow divergence), both run on the five most liquid names in the universe.
Neither tested the horizon or the liquidity segment where the published effect lives. This sweep tested both.

The falsification was declared as a **liquidity contrast** rather than a threshold: every configuration runs on the liquid sleeve (top 30 by ADV) and the illiquid sleeve (ranks 31-66), and every horizon also runs sign-flipped as momentum.
The literature predicts reversal wins on the illiquid sleeve at short horizons, momentum wins on the liquid sleeve there, and reversal wins on both beyond one month.

## meanrev-xs-outcome

**The mean-reversion hypothesis fails on this universe, and it fails in a way that partly validates the measurement.**

Reversal beats its own momentum control on both windows in **1 of 24 sleeve-horizon cells**, and that one cell contradicts the literature it was built from: liquid, one-day formation, seven-day hold, at +0.488 on the fit window and +0.186 on the holdout, where the papers predict momentum should win.

Of the 48 configurations, six are positive on both windows and **five of them are momentum**. The single reversal survivor is illiquid, 45-day formation, seven-day hold, at fit +1.460 and holdout +0.276.

### The liquid-sleeve prediction is confirmed, which is the reassuring part

At formations of one, three and seven days on the liquid sleeve, momentum beats reversal in five of six cells, exactly as Zhang et al. predict.
The sweep reproduces a known published result on the segment where it is documented, so the construction is not obviously broken. That is the check the sign-control arm existed to provide.

### The illiquid-sleeve prediction is not confirmed

Short-horizon reversal on the illiquid sleeve matches the prediction in only 4 of 12 cells, and the two clearest short-horizon cells run the wrong way: three-day formation with a one-day hold gives momentum +0.092 against reversal -0.750, and seven-day formation with a seven-day hold gives momentum +0.299 against reversal -0.103.
The published effect is measured across 1,160 to 2,000 coins including genuinely microcap names; the 63 names below the top 30 on a single venue are not that population, and this is the most likely explanation.

### The beyond-one-month prediction fails on the liquid sleeve entirely

All six cells at 30, 45 and 60-day formation on the liquid sleeve show momentum beating reversal, on both windows.
On the illiquid sleeve only the 45-day cell matches; 30 and 60 days do not, so the one match has no support from its neighbours and reads as noise.

### Two practical facts settle it independent of the statistics

**Daily rebalancing is arithmetically dead.** At a one-day hold, annual turnover is 554 to 574 times NAV and cost drag is **27 to 29% of NAV a year** at 5 bps. No configuration at that holding period can matter.

**The sleeve where the effect is supposed to live is largely untradeable here.** Against the live `max_spread_bps` of 5.0, a single tick already exceeds the limit for 27% of illiquid-sleeve names against 9% of liquid ones, with BONK at 33.7 bps, STO at 25.0 and SHIB at 18.6. The execution layer would refuse a large part of the book, which is the same skipped-order leak recorded at `#flow-scalp-outcome`.

### No bot is created

The best reversal configuration scores a holdout Screen 3 of +0.276 against +2.490 for `momentum_top5_4h` and +2.512 for `donchian_4h`, both already live. Building it would mean running something an order of magnitude worse than what exists, on the least tradeable part of the venue.

Forty-eight trials are recorded, taking the ledger from 656 to 704. The research was not wasted: it explains two earlier nulls that were previously unexplained, and it is the reason this one was cheap.

## competition-oos-declaration

Declared 2026-09-20 at `config/competition_oos.yaml`, after an operator request to test the live bots out of sample on Binance history under the competition's own framework and identify when each works.

The request said to optimise 14-day Sharpe, Sortino and Calmar across timeframes. That was not done, deliberately.
Taking the argmax of an out-of-sample composite is selection on the test set, and `DECISIONS.md#sizing-sweep-outcome` measured the consequence directly: the fit argmax was the holdout's WORST setting, at 2.169 against the holdout best of 2.810.
What is produced instead is the DISTRIBUTION of 1,345 rolling 14-day windows per book since 2023, plus a conditional analysis of which observable starting states precede good and bad windows.
Every conditioner is lagged one day, so a relationship found here could have been acted on rather than merely observed. Nothing is promoted and no trials are added; the ledger stands at 656.

## competition-oos-outcome

### The distribution, 1,345 windows each since 2023

| book | median S3 | P(ret>0) | P(ret>5%) | median ret | worst window |
|---|---|---|---|---|---|
| donchian_4h | +2.512 | 0.576 | 0.234 | +0.66% | -10.04% |
| momentum_top5_4h | +2.490 | 0.563 | **0.386** | +1.42% | **-20.74%** |
| donchian_1h | +2.189 | 0.550 | 0.188 | +0.48% | -13.40% |
| btc_hold | +2.150 | 0.557 | 0.303 | +0.86% | -29.76% |

Every book has p05 of -5.000 and p95 of +5.000: **both caps bind**, which is the sign-indicator property recorded in prior work, now confirmed on every configuration simultaneously. Within a fortnight the composite is close to a function of the sign of the return.

The two live books split cleanly by role. `donchian_4h` has the highest probability of a positive fortnight and the shallowest tail; `momentum_top5_4h` has the highest probability of clearing the Screen 2 return proxy, at 0.386 against 0.303 for BTC, and pays for it with a -20.74% worst window. That is the qualification-versus-composite tension of `#beta-is-the-only-screen3-lever` appearing as a choice between two live bots rather than as a parameter.

### Dispersion is the condition that matters, and it is specific to the strategy

Median Screen 3 by tercile of cross-sectional dispersion measured the day before the window opens:

| book | low | mid | high |
|---|---|---|---|
| donchian_4h | +0.49 | +2.28 | **+3.72** |
| donchian_1h | -0.07 | +1.29 | **+3.19** |
| momentum_top5_4h | -0.28 | +2.23 | **+3.69** |
| btc_hold | +2.31 | +1.44 | +2.42 |

Monotone for all three trend books and **absent for BTC hold**, which is what makes it a property of the strategy rather than of the market. In the bottom dispersion tercile the trend books are worth nothing at all - two of the three have a negative median composite and P(return > 0) of 0.493 to 0.507, a coin flip.

Realised BTC volatility ranks windows almost as well, and for `momentum_top5_4h` it is the stronger of the two: -0.90 in the low tercile against +3.65 in the high, with P(return > 0) moving from 0.478 to 0.712.

### What goes wrong

**Quiet, compressed markets.** Low dispersion and low volatility together are where every trend book fails, and it fails by being flat rather than by losing: median return -0.19% for the ranked book and +0.09% for `donchian_4h`, with the cost drag still being paid. The rule enters on breakouts that do not extend, pays 5 bps a leg, and gives the fortnight back in fees.

**Being long the wrong kind of strength.** The worst windows are -10% to -21% and they are not in quiet markets, they are in the high-dispersion bucket where the books are otherwise best. The same condition that produces the good windows produces the worst ones; dispersion widens the whole distribution rather than shifting it.

### The counter-intuitive result, and why it is not a reason to time the market

All four books, including BTC itself, score HIGHER with BTC below its 200-day average than above it: `momentum_top5_4h` at +3.48 against +1.09, `donchian_4h` at +2.98 against +2.06.

This is not evidence that bear markets are good. It is that in the 2023-2026 sample the sub-200DMA periods were also the high-volatility, high-dispersion ones, and volatility is the operative variable. The partition is confounded, and `#gate8-regime-outcome` already measured the strategy profitable in all three regimes, so no regime gate follows from it.

### Breadth is not the useful conditioner

Breadth shows no monotone relationship in any book - `donchian_4h` runs +2.39, +2.71, +2.51 across terciles. This matters operationally: the scanner publishes breadth prominently, and this says breadth is the wrong field to watch. **Dispersion is the field that carries the information**, and it is already published beside it.

## data-integration-2026-09-20

Three datasets were added on 2026-09-20 and each closes a limitation this repo had MEASURED, which is the only reason any of them is here.

**Futures positioning** (`data/futures.py`: funding, open interest, taker ratio, top-account ratio) closes `DECISIONS.md#correlation-cap-outcome`.
That sweep found no reweighting could raise effective bets past 1.32 from a baseline of 1.28, because the price correlation matrix had no structure left to exploit.
Crowding is a different observable and that null does not refute it.

**L2 book imbalance** (`data/microstructure.py:book`) and **trade profile** (`:trade_profile`) close the two halves of `DECISIONS.md#flow-scalp-outcome`.
That sweep found a real divergence effect - fit +9.26 bps against holdout +11.42, dose-responding to the flow threshold - that failed because bar-aggregated `taker_buy_quote` says nothing about resting liquidity and cannot separate one sweep from many small orders.
Measured on BTCUSDT the same day, **the top 5% of trades carried 76.6% of notional**, which is the quantity a bar-level taker ratio destroys.

### Limits recorded before use, not discovered later

`openInterestHist` and the ratio endpoints serve roughly 30 days, so anything built on them is validatable on a month rather than on years.
`/api/v3/depth` is a snapshot endpoint with **no history at all**, so book imbalance can only ever be validated forward.
That asymmetry is why all three are PUBLISHED by the scanner and none is fed to a sweep: a backtest of a dataset that does not exist historically would be a backtest of nothing.

### Nothing here gates a trade

`bot/regime.py` is untouched and the only live gate remains the per-coin cushion rule.
These fields are observability until a forward record exists, and no trials are added to the ledger, which stands at 656.

The first reading is already informative. On 2026-09-20 `AVAXUSDT` showed an open-interest z-score of 4.06 with OI up 15.3% over six bars and 73.9% of top accounts long, while being the largest position in both 4h books.
Whether that is a warning or noise is exactly what the forward record is for.

### Books restarted

All five live books were reset to 100,000 on 2026-09-20T08:11Z at the operator's request.
The prior record, including the -5,379 combined drawdown that motivated the day's work, is preserved at `live/archive/20260920T081118Z/` rather than deleted.

## scanner-declaration

Declared 2026-09-20 at `config/scanner.yaml`, before any backtest, in response to an operator observation that overall crypto was down while many individual coins were up.

The observation is confirmed. The live scan on 2026-09-20 found 53 of 66 venue names above their entry channel while all three live books were down 1.2% to 2.7%, with cross-sectional dispersion of 3.22% over six bars and a median coin return of -2.03%.
The problem the books have is not direction. It is that they hold 1.28 to 1.49 effective bets, measured at `DECISIONS.md#correlation-cap-outcome`, in a universe that is visibly dispersed.

`bot/scanner.py` classifies every name independently using the same 20-bar entry and 10-bar exit channel the live bots trade, and publishes `live/scanner/state.json` atomically.
It holds no capital and places no orders. One scan serves every executor, and a scanner defect cannot silently become a trade.

**It is not a market-regime timer, and that distinction is the point.**
`DECISIONS.md#gate8-regime-outcome` measured this strategy profitable in all three market regimes - bull +307%/yr, bear +20.4% at Sharpe 0.71, range +23.7% - so a market-wide gate could only remove exposure from periods that already earn.
Jev's regime arm is separately held to log-only for the same reason, and its live record is three judgments, one of which called "expanding" at 0.98 confidence during the 2026-09-20 drawdown.
Per-coin state is a different object.

### The control arm is the design

`bot/regime.py` defaults every executor to `always_on`, which returns the caller's target dict unmodified and is verified to leave the existing bots bit-for-bit unchanged.
A missing, stale or malformed scan degrades to `always_on`; it never degrades to holding nothing, because an infrastructure failure must not become a trading decision.

Two gated arms now run beside the controls they must be read against:

| arm | control | difference |
|---|---|---|
| `bot_e_cushion_4h` | `bot_a_4h` | blocks new entries with cushion below 2% |
| `bot_f_cushion_top5` | `bot_c_5names` | same gate on the momentum top-5 book |

The gate touches new entries only. It never gates a name already held and never touches exits, because the evidence against model-driven early exits is the strongest in this repository: eight ATR stop configurations lost, none of six take-profit variants beat baseline, and a faster exit clock made holdout drawdown worse in all twelve arms at `DECISIONS.md#exit-clock-outcome`.

**No backtest supports this gate.** It is running forward precisely because four sweeps on 2026-09-20 returned 162 nulls between them and each additional in-sample search raises the deflated-Sharpe hurdle any survivor must clear.
A lead over the control is not to be read before 28 complete days, matching the floor set at `DECISIONS.md#prospective-paper-lab`.
The scanner adds no trials to the ledger because it selects nothing; the two gated arms will be recorded when their forward record is scored.

## flow-scalp-declaration

Declared 2026-09-20 at `config/flow_scalp.yaml`, before any backtest, after an operator request for a fast scalper driven by price discrepancies, volume and order flow.

`DECISIONS.md#scalp-meanrev-outcome` had already killed 54 configurations of a price-only mean-reversion scalper, and that null is not re-litigated here.
It established that the median 5m bar does not pay a 10 bps round trip and that the extremity of a price deviation does not predict its reversion.
It did not test whether a deviation is CONFIRMED by flow, which is a different question.

Binance klines carry `taker_buy_quote`, so signed aggressor volume is observable per bar without book reconstruction: `ofi = 2 * taker_buy_quote / quote_volume - 1`.
The hypothesis is divergence rather than level. A price fall on net BUY aggression is a fall nobody is selling into and should revert; a fall on net SELL aggression is informed and should continue.
The sign-flipped continuation arm is tested alongside it as the falsification.

**A per-trade floor was pre-registered instead of a Sharpe threshold.** A configuration is interesting only if its mean gross return per trade exceeds 20 bps on BOTH windows, twice the LIMIT round trip.
This was fixed before any result was seen, because `#scalp-meanrev-outcome` had shown that net Sharpe at this horizon ranks configurations by how much they trade rather than by whether they earn.

## flow-scalp-outcome

**Zero of 72 configurations clear the floor**, but unlike the price-only sweep this one is not empty, and the distinction matters.

The divergence arm systematically beats its sign-flipped control.
Median holdout edge is -0.97 bps for divergence against -1.34 for continuation, and the maxima are +11.42 against +1.47.
The effect also shows a coherent dose-response: every one of the top four configurations sits at the strongest flow threshold tested, `ofi_z >= 2.0`, and 15m and 30m bars beat 5m, where aggregation is coarsest.
Fit and holdout agree in magnitude rather than reversing, which is rare in this repo: 15m at +9.26 fit against +11.42 holdout, 30m at +11.38 against +9.09.
So the mechanism appears to be real. It is simply too small and too rare to trade.

**The edge is carried by three trades and the median trade loses money.**
At 15m the holdout mean is +11.42 bps over 65 trades; dropping the best three leaves +3.48.
At 30m the holdout mean is +9.09 over 123 trades and +3.35 without its top three.
Median trade return is negative in three of the four window-interval combinations, at -30.54, -32.82 and -41.01 bps.
That is the payoff shape the 1.5-ATR target against a 1.0-ATR stop was always going to produce, and it is the direct opposite of the operator's stated goal of consistently taking profits.

It is also not a scalper by any reasonable use of the word.
The best configuration fires 65 times in 21 months, or roughly one trade every ten days across five symbols.

The honest summary is that bar-aggregated aggressor imbalance carries a small amount of genuine short-horizon information, that it survives out of sample where price-only extremity did not, and that at 3 to 11 bps per trade against a 10 bps round trip there is nothing here to trade.
Recovering more would require true order-flow imbalance from book updates rather than a per-bar taker share, which is the limitation recorded in the declaration's `failure_mode_to_watch`.

Seventy-two trials are recorded in `config/trials.yaml`, taking the ledger from 584 to 656. No live bot is created.

## exit-clock-declaration

Declared 2026-09-20 at `config/exit_clock.yaml`, before any backtest.
The entry, the 4h channel and the exit LEVEL are held fixed at the live bots' settings; only the frequency at which the fixed level is compared against price changes, to 2h or 1h.

The mechanism came from `DECISIONS.md#donchian-lowtf-outcome`, which measured the same twenty-day channel at Sharpe 1.99 on 1h bars against 0.86 on daily at identical turnover and cost drag, and attributed part of it to exit granularity - "a stop checked twenty-four times a day releases a losing position hours rather than up to a day after the level breaks."
That entry also named a second, confounded effect: the hourly channel is a strictly more selective ENTRY. The two were never separated, and this sweep separates them.

The declaration recorded the failure mode to watch: a faster check fires on intrabar noise the 4h close would have recovered from, which is what `DECISIONS.md#asymmetry-outcome` measured for ATR stops when all eight configurations lost.

## exit-clock-outcome

**Zero of 12 configurations pass, and the result inverts the thesis.**

Maximum drawdown, the statistic the change was supposed to improve, gets WORSE on the holdout in every fast arm.
`top5_momentum` runs -33.0% at the 4h baseline and -36.3% at a 1h exit clock; `all_signals_div20` runs -17.7% against -18.4%.
The 2h arms are no better, at -36.7% and -17.7%.

Holdout Screen 3 does rise for two arms - `top5_momentum` 1h/10 at 3.375 against 2.953, and `all_signals_div20` 1h/10 at 2.889 against 2.622 - but both FAIL the fit window, at 4.315 against 4.385 and 4.303 against 4.381.
Fit-window P(14d > 0) also falls in every 1h arm. No arm improves both windows on any of the three declared criteria simultaneously.

The declared failure mode is what happened.
A faster check releases a position into a dip the 4h close would have held through, and the channel then re-enters at the next 4h close at a higher price. This is `DECISIONS.md#asymmetry-outcome` arriving from a third direction: stops fail on this book whether they are ATR-based, take-profit-based, or the existing channel floor checked more often.
The exit clock is load-bearing rather than incidental, and the granularity half of `#donchian-lowtf-outcome` does not survive separation from the entry-selectivity half.

### Two look-ahead defects were found in this sweep's own code, and the second was only caught by a control

Both are the same mistake: **Binance bars are labelled by OPEN time, so the 4h row labelled 04:00 holds a close from 08:00.**

The first was in `signals/exit_clock.py`, which mapped each fast bar onto the slow bar with the same or an earlier label and so read up to four hours of future price. It produced `top5_momentum` holdout Sharpe 7.29, maximum drawdown of -11.9% and Screen 3 pinned at the 5.0 cap. It was caught because the reported turnover was identical to baseline, which is impossible if a faster clock is exiting earlier.

The second survived that fix, in `gates/exit_clock.py`, where the 4h momentum RANKING was carried onto the fast index with a label-matched `reindex(method="ffill")`.
It produced a holdout Sharpe of 3.72, a 114x return multiple and an apparently clean pass on both windows, and it was invisible to inspection because the 4h arms are immune - on the slow clock the reindex is a no-op, so only the fast arms were inflated.

It was caught by a falsification control rather than by reading the code.
**A random exit firing at the same rate as the real one, ignoring the stop level entirely, returned 27,594x against the real rule's 114x at Sharpe 7.65 against 3.72.**
A nonsense rule beating the real rule can only mean the harness is generating the return, and that is what sent the search back to the alignment.
A one-bar execution delay had moved the result by almost nothing (112.94x against 114.19x), so the delay test alone would have passed the broken code.

Both are now fixed by aligning on bar CLOSE times through `signals.exit_clock.to_fast`, which is verified to be the identity when the two clocks are equal, and `signals.exit_clock.position` is verified to reproduce `signals.donchian.position` exactly in that case.

`bot/feed.py` was audited and is clean: `closed_bars` filters on `close_time <= now`, so the live bots never see a forming bar.
`data.universe.pit_top_n` lags ADV by `.shift(1)` before the daily-to-4h forward fill, so the pre-existing gates do not carry this defect.

Twelve trials are recorded in `config/trials.yaml`, taking the ledger from 572 to 584. No live bot is changed.

## correlation-cap-declaration

Declared 2026-09-20 at `config/correlation_cap.yaml`, before any backtest, after a live measurement on the same day.
`bot_c_5names` held five names at 99% gross and had 1.49 effective bets; `bot_a_4h` held ten names at 50% gross and had 1.68.
Pairwise 1h return correlation across the held names was 0.551 over the prior 200 hours and 0.833 through the 00:00-04:00 UTC drawdown, in which BTC fell 1.06% while AVAX fell 6.90%, TAO 5.46% and ENA 4.85%.

The declaration's central feature is a control rather than a rule.
`DECISIONS.md#beta-is-the-only-screen3-lever` established that the composite and the qualification probability are collinear within a fortnight because both are produced by beta, and `DECISIONS.md#sizing-sweep-outcome` measured that capping gross below 1.0 hurts.
Any correlation rule that reduces exposure therefore moves Screen 3 up and P(Screen 2) down on its own, and a sweep reporting only Screen 3 would credit the rule for an effect a constant haircut produces.
So every arm that changes mean gross exposure is scored against a **beta-matched control**: the same baseline book scaled by one constant chosen so its mean gross over the window equals that arm's.

Three arms were declared. `scale` multiplies weights by a function of effective bets, which reduces gross and is confounded.
`reweight` sets weights inversely to each name's mean correlation to the rest of the book at **constant gross**, so it is the only unconfounded arm.
`cluster_cap` clusters at a correlation threshold and keeps at most N names per cluster, changing both composition and gross.

## correlation-cap-outcome

**Zero of 24 arms pass**, and the reason is that this book has no correlation structure left to exploit.

Mean effective bets is 1.28 at baseline on the holdout and no arm moves it past 1.32.
That is the whole result. `reweight`, the one arm that holds gross constant and can therefore only work by changing composition, raises effective bets from 1.28 to 1.31 and holdout Screen 3 from 2.953 to 3.000, which is inside the noise of every other comparison in this repo.
The prediction recorded in the declaration's `mechanism_at_risk` is confirmed: every name in a long-only book of crypto majors and large alts loads on the same factor, a reweighting cannot manufacture diversification that the covariance does not contain, and the only lever on this book's risk is its size.

**`cluster_cap` is the trap the design was built to catch, and it would have been adopted without the control and the two-window rule.**
On the holdout alone it looks decisive: `top5_momentum` at threshold 0.7 and one name per cluster scores 3.365 against a matched control of 2.819, and `all_signals_div20` at the same setting scores 3.043 against 2.533.
Both reverse on the fit window. `top5_momentum` scores 4.337 against a control of 4.390 there, and its fit P(14d > 0) is 0.573 against the control's 0.599.
A holdout-only reading would have produced the seventh reversing family in this repo.

The `scale` arm is the cleanest demonstration that exposure reduction is not diversification.
It leaves effective bets untouched, as it must, because effective bets is scale-invariant.
At exponent 1.0 on `all_signals_div20` it cuts mean gross from 0.296 to 0.064 and holdout Screen 3 falls from 2.622 to 1.835 while its matched control sits at 2.471, so the rule is worse than simply holding less by the same amount.
Its holdout P(14d > 0) rises to 0.570 against the control's 0.531, which is the collinearity behaving exactly as `#beta-is-the-only-screen3-lever` describes rather than a finding.

One reporting defect was found and fixed mid-sweep.
The first run reported effective bets computed on the weights entering each transform rather than leaving it, which made every arm show an identical figure and would have concealed the central question of whether any rule diversified.
`signals/correlation.py` now measures effective bets on the weights the book actually holds, and the sweep was re-run.

No live bot is changed. Twenty-four trials are recorded in `config/trials.yaml`, taking the ledger from 548 to 572.
The live observation that motivated the sweep stands and is not refuted: the books really do hold about 1.5 independent positions. What is refuted is that a correlation-aware weighting can fix it.

## scalp-meanrev-declaration

Declared 2026-09-20 at `config/scalp_meanrev.yaml`, before any backtest, in response to an operator request for a scalper with explicit take-profit and take-loss targets and a mean-reversion strategy.

The mechanism was taken from this repo's own measurements rather than assumed.
`results/fast_horizon.json` ran a Donchian breakout on 5m bars over BTC/ETH/SOL/XRP/DOGE and recorded a gross Sharpe of -0.2159 before any fee, against +0.4517 for the same rule at 15m.
A momentum rule with negative gross Sharpe is direct evidence that moves at that horizon revert, so the opposite sign has positive gross expectancy, and `DECISIONS.md#fast-horizon-outcome` already states it in words: a 5m breakout is noise that mean-reverts.

The declaration also recorded why a take-profit is the correct object here when `DECISIONS.md#take-profit-outcome` rejected one on the 4h trend book.
A trend has no terminal value, so capping it truncates the right tail that Sortino rewards.
A mean-reversion trade's thesis is that price returns to a reference level, so that level is the target and holding past it is holding past the edge.
The prior evidence against take-profits is not transferable and was not counted against this family.

The binding constraint was stated in advance as arithmetic rather than statistical.
`results/fast_horizon.json` measured a median absolute bar return of 8.823 bps at 5m, 15.537 bps at 15m and 21.447 bps at 30m, against a 10 bps LIMIT round trip and a 20 bps MARKET round trip.
The median 5m bar does not pay for its own round trip, so selectivity was designed in rather than tuned: entries fire only in the tail of the deviation distribution.

## scalp-meanrev-outcome

The family is a null on every configuration tested, and it fails on the constraint the declaration named in advance.

**Zero of 54 configurations have a positive holdout net Sharpe** at either end of the fee schedule.
The best is 30m z3.0 tp1.5 sl2.0 at -2.59, and the range across the grid is -2.59 to -21.36 at 5 bps.
Seven configurations have a positive holdout *gross* Sharpe, all at 5m, and their per-trade edge is between +0.26 and +0.67 bps against a 10 bps round trip.

The per-trade arithmetic is the whole result.
Mean gross return per trade on the holdout ranges from +0.67 bps to -14.52 bps across the grid.
Not one configuration earns a per-trade edge that covers even the LIMIT round trip, and the closest is short by more than 9 bps.
This is the outcome the declaration predicted, and it is a property of the horizon rather than of the parameters.

Selectivity does not rescue it, which falsifies the design's central premise.
Raising `entry_z` from 2.0 to 3.0 at 5m moves the holdout edge from -0.28 to -0.68 bps at tp1.0/sl1.0, and cuts trade count from 29,100 to 5,829 without improving the edge per trade.
A more extreme deviation is not followed by a proportionally larger reversion, so there is no threshold at which the rule clears its cost.

**A high fit-versus-holdout Spearman here is an artifact, and the distinction matters.**
On net Sharpe the rank correlation is +0.968, which looks like strong out-of-sample agreement and would ordinarily support selection.
On per-trade edge it is -0.108.
The reason is that net Sharpe at this horizon is dominated by cost drag, and turnover is almost perfectly stable across windows, so the fit window predicts how much a configuration will *trade* rather than whether it will *earn*.
Sign agreement on the edge is 22 of 54, worse than the 27 a coin flip would give.
Any future sweep in this repo that reports a high fit/holdout rank correlation on a cost-dominated metric should be checked against the same decomposition before the correlation is read as validation.

The fit window would also have chosen catastrophically.
Thirty-seven of 54 configurations show a positive edge on the fit window and only 7 do on the holdout, and the 15m and 30m blocks reverse sign almost uniformly: 15m z2.5 tp1.5 sl1.5 earns +3.35 bps on the fit window and -3.88 bps on the holdout.

The declaration's own kill rule fires independently of any of this.
It stated that measured skew worse than -1.0 makes the family undeployable regardless of Sharpe, and **52 of 54 configurations have holdout skew below -1.0**, ranging to -4.49.
That is the predicted failure mode: a bracket with a fixed stop on a reverting signal wins often and small and loses rarely and large, which is exactly the shape the competition's Sortino weighting punishes.

The same-bar ambiguity convention is not responsible.
Resolving a bar that touches both brackets in favour of the target instead of the stop moves the 15m z2.5 tp1.0 sl1.5 holdout edge from -0.19 bps to +2.08 bps, because only 29 of 938 trades are ambiguous.
Both readings are far below the 10 bps hurdle, so the pessimistic convention is not what kills the family and no optimistic reading rescues it.

No live bot is created. Fifty-four trials are recorded in `config/trials.yaml`, taking the ledger from 494 to 548.

## take-profit-outcome

Take-profit exits were tested across twelve configurations on the 4h momentum-ranked top-five book, and they do not help.

Not one of the six full-exit variants beat the no-take-profit baseline on the holdout.
They scored 1.725 to 3.194 against the baseline's 3.409, and the damage is largest at the tightest targets: a 3% target costs 1.30 of Screen 3 and an 8% target costs 1.69.
Five of the six half-exit variants also lost, and the single exception gained 0.142.

The mechanism predicted in the declaration is exactly what the numbers show.
Return skew falls from 2.38 at baseline to between 0.90 and 1.68 under every take-profit setting.
Screen 3 weights Sortino at 0.4, Sortino penalises only downside deviation, and the strategy's edge is an uncapped right tail.
Truncating that tail removes the thing the scoring function rewards, which is why tighter targets hurt monotonically more.

The one configuration that beat baseline is not adopted, for two reasons.
It is a 30% target taking half the position, which barely binds: mean holding period is 8.9 bars and annual turnover 224, both identical to baseline, so the rule is doing almost nothing and its +0.142 is noise around a book that hardly changed.
And the fit-versus-holdout Spearman across the grid is 0.29, the weakest of any sweep in this repo, so the fit window cannot select here at all.
Selecting on it would have chosen a 3% half-exit, which scores 2.473 on the holdout against the baseline's 3.409, destroying 0.94 of composite.

This is the same result as `DECISIONS.md#asymmetry-outcome` arriving from the opposite direction.
Stops failed because they cut positions during drawdowns a trend needs to hold through.
Take-profits fail because they cut positions during the advances a trend exists to capture.
The channel exit is already both the stop and the target, and adding either one on top of it makes the system worse.

No change is made to any bot.

## sizing-exit-terminal-review

The subsequent operator request combined Roostoo ticker verification, position sizing, clearer terminal monitoring and profit protection after a short live P&L reversal.
The declarations, methods, numerical findings and remaining limitations are recorded in `results/allocation_exit_review.md`.
Six bounded allocations and two controls were tested at two costs, followed by five exit rules at two costs; all configurations were registered before evaluation.
The sizing study charges drift turnover and executes at next opens rather than assuming free constant-weight rebalancing.
The exit study checks completed hourly closes, fills at following opens, and blocks re-entry after a full overlay exit until the selected state resets.
The earlier take-profit implementation could immediately re-enter while its selected mask stayed true, so its conclusions apply to that particular policy rather than every profit-protection mechanism.
Fixed 8% full and half targets underperformed the channel control in the later assessment.
The hourly floor improved recent Sharpe, Sortino, Calmar and drawdown, but deteriorated in the earlier fit period; it is forward-tested rather than promoted as a validated improvement.
Balanced 12 is the fit-only selection among balanced candidates; balanced 5 is an explicitly assessment-informed diagnostic, and neither dominates the incumbent under every cost and metric.
The new `paper_lab_v2` runs ten public-data-only independent portfolios, with v1 records retained separately and no authenticated exchange orders.
Balanced candidates exclude names above the unchanged spread threshold before ranking and enforce cash and slot reservations without crediting unfilled exits.
The terminal uses verified Roostoo pair mappings, includes price marks, actual and target weights, exit floors, concentration, exclusions, and separate historical versus forward metric sections.
Thirty-three tests passed, and browser checks verified strategy selection, research controls, native pair labels and the corrected mobile layout.

## competition-execution-hardening

The subsequent competition-readiness request exposed automatic retries of order-creation requests after ambiguous transport or response failures.
Order creation now fails without retry and the executor latches a submission block pending reconciliation; read-only query retries remain available.
This protection is in-memory only, so the authenticated runner remains blocked until durable restart-safe intent reconciliation exists.
Quote and quantity validation now rejects malformed, non-finite, crossed and untradable inputs before constructing an order.
Allocation validates policy bounds, uses the declared risk window and rechecks portfolio volatility after minimum-weight pruning.
The new read-only `bot.readiness` command checks freshness, pending reservations, mark-to-equity consistency and fill-to-wallet reconciliation without contacting a venue or enabling execution.
Its first inspection passed all ten current paper books while explicitly retaining competition deployment blockers.
No service restart or strategy promotion occurred; a changed lab fingerprint requires a separately identified experiment rather than overwriting prior provenance.
Details and release boundaries are in `results/competition_hardening_2026_09_20.md`.

## derisk-ramp-protection-outcome

`HANDOVER.md` section 4e measured what the end-of-window derisk ramp costs and said plainly that its benefit was unmeasured, because the drawdown column in that table came from the full daily series and therefore never saw the ramp fire.
A rule whose cost is measured and whose benefit is not will always look like a bad rule, so the ramp could not be decided on that evidence.
`gates/derisk_ramp.py` closes the gap by applying the ramp WINDOW RELATIVE: it tapers into the end of every rolling 14-day window exactly as it tapers into the end of the one real one, which is the only alignment that measures the rule actually deployed.
Declaration is `config/derisk_ramp.yaml`, no argmax is taken, nothing is promoted and the trial ledger is untouched.
The liquidation turnover the ramp itself causes is charged at the same 5 bps as every other trade, because measuring a protective rule without charging for the protection would repeat the error recorded at `#passive-fill-adverse-selection`.

The exact deployed ramp is the 68-hour linear taper from 2026-10-15T00:00Z to 2026-10-17T20:00Z, which is the final three days of the fourteen.
Holdout, `momentum_top3_full`, 614 windows, ramp off then on:

| | median ret | P(>5%) | P(>20%) | p05 ret | worst ret | median maxDD | P(maxDD <= -25%) | median Screen 3 |
|---|---|---|---|---|---|---|---|---|
| no ramp | 3.14% | 0.467 | 0.168 | -19.24% | -28.67% | -12.67% | 0.0912 | 3.066 |
| exact ramp | 2.10% | 0.435 | 0.160 | -18.45% | -25.81% | -11.82% | 0.0684 | 2.547 |

**The protection is real, it is measurable, and it is small.**
The worst 14-day window improves by 2.86 points, the fifth percentile by 0.79, and the probability of touching the 25% kill switch inside the window falls from 9.12% to 6.84%, which is 56 windows to 42.
Conditional on landing in the worst decile of windows the ramp helps 74.2% of the time, with a median gain of 1.43 points of return and 0.75 points of drawdown.
The same measurement on the control `momentum_top3_4h` agrees: kill-switch probability 6.84% to 4.72%, worst window -30.97% to -28.90%.
The stylised 2-day and 3-day variants reconcile with the cost table already in section 4e and differ from the exact ramp by less than this repo's declared noise threshold, so the ramp's exact span is not a lever.

**The cost is larger and it falls precisely where the prize is.**
Median return loses 1.04 points, P(>5%) loses 3.3 points, and the Screen 3 composite loses 0.519.
Screen 3 falls despite the ramp improving the Calmar denominator, because cutting exposure cuts the return that is the numerator of all three of Sortino, Sharpe and CAGR over the same fourteen days.
The ramp is therefore negative on BOTH screens, not a trade of one against the other.

Two findings here are counterintuitive and both matter.

The paired median change in return is **+0.365 points**, and the ramp improves 53.8% of individual windows, while the distribution's median falls by 1.04 points.
Both are true at once because the final three days of a crypto fortnight are slightly negative more often than they are positive, so cutting exposure usually adds a little, and occasionally subtracts a lot.
In the best decile of windows the ramp costs a median of 4.80 points.
That payoff profile - wins often and small, loses rarely and large - is short volatility on the right tail, and the right tail is the product being bought at Screen 2.

The mechanism is measurable directly and is not an inference from the paired counts.
Across the 614 holdout windows the final three days return a **median of -0.06% and a mean of +1.82%**, and are negative **50.5%** of the time.
The ramp forgoes a segment whose typical outcome is a fraction below zero and whose average outcome is strongly positive.
Giving up a right-skewed segment is a poor trade whenever the objective is the right tail, and at Screen 2 it always is.

Second, the protection operates entirely inside the region where the run has already failed.
Screen 2 advances the top 20 per region on raw return; every outcome below that cut scores identically, which is to say not at all.
Moving the worst case from -28.67% to -25.81% buys nothing on the objective, because both numbers are equally far from qualifying.
What the ramp actually does on the competition metric is move probability mass out of the right tail and into the range between -18% and -29%, where no prize exists.

**Verdict.** On the competition's stated objective the ramp is strictly negative and the case for removing it is now measured on both sides rather than on one.
It survives only as a risk preference the operator holds independently of the competition, or as an operational settlement rule, and the operator should decide it on that basis rather than on a return calculation.
No configuration is changed by this run, because the ramp is written into six frozen configs and changing a frozen declaration is an operator decision, not a gate's.

## ranking-lookback-mismatch

Found while building `gates/derisk_ramp.py` and reconciling it against the section 4e tables, which it initially missed by 0.6 points of median return.
`gates/concentration.rank_score("momentum", ...)` scored `close / close.shift(20) - 1`, a 20-bar lookback.
Every deployed momentum book ranks on `momentum_bars: 40`, and `bot/portfolio.rank_and_select` reads that setting.
So every gate that called `rank_score` without saying otherwise was scoring a book the bot does not trade.

Affected call sites: `gates/competition_oos.py`, `gates/exit_walkforward.py`, `gates/correlation_cap.py`, `gates/exit_clock.py` and `gates/ratchet.py`.
The later gates `gates/exit_review.py` and `gates/no_trade_band_live.py` hardcode `shift(40)` and were always correct, which is how the two conventions came to coexist unnoticed.

The fix keeps `rank_score`'s default at 20 so that no committed artifact changes silently, adds an explicit `bars` parameter, and pins `MOM_BARS = 40` at the call sites that model a deployed book.
`gates/exit_walkforward.py` and `gates/competition_oos.py` were re-run under the corrected lookback.

**Neither conclusion moves.**
Walk-forward exit selection still stitches to Screen 3 4.017 against a best fixed choice of 4.111 at `exit_bars = 15` and 4.106 at the live `exit_bars = 10`, a gap of 0.005 that is far inside noise, so `#exit-walkforward-outcome` stands and section 5 keeps `exit_bars = 10`.
`momentum_top5_4h` still dominates every other book on the competition framework, with P(>5%) 0.388 against 0.303 for BTC hold and 0.234 for `donchian_4h`, so `#competition-book-selection` stands.
The three nulls at `#correlation-cap-outcome`, `#exit-clock-outcome` and `#ratchet-outcome` were NOT re-run.
They rest on a 20-bar ranking and a future session should know that before citing them; re-running them costs no trials, because a re-measurement of an already-counted configuration is not a new search.

The general lesson is the one already in `CLAUDE.md`: a default value is a silent declaration.
`rank_score` declared a lookback by defaulting to one, and no config file ever agreed to it.

## compounding-outcome

The operator's objective is maximum 14-day portfolio return, and the stated route was better position sizing and recycling profits.
`config/compounding.yaml` declared the question and `gates/compounding.py` answers it with a bar-by-bar weight-state simulator that carries explicit positions rather than a target-weight vector, so it can charge the drift trades the vectorised harness has never seen.
The control reproduces `gates/concentration.net_daily` for `momentum_top3_full` to within **0.011 points** of holdout median 14-day return, and the declaration made that reconciliation a precondition for reading any other arm.
Eleven configurations were evaluated and ten were added to the ledger; the control is a re-evaluation of an already-counted config and is excluded under `#trial-counting-rule`.

**The framing first, because it removes most of the search space before any test runs.**
`max_gross` is 1.0 because the competition forbids leverage, not because a sweep chose it.
Profits are already recycled: `bot/run.mark` values the book mark-to-market every cycle and `target_weights` expresses every position as a fraction of that NAV, so a winning book automatically sizes its next position off a larger base.
There is no unexploited compounding in the sizing code.
With leverage unavailable and NAV-relative sizing already in place, "recycle harder" reduces to exactly two degrees of freedom: **how often the book is idle**, and **what happens to a winner's weight between signals**.

### Lever one: idle time. The hypothesis is refuted, and the reason matters.

`momentum_top3_full` is fully deployed whenever anything signals, so slot-level idle cash is already solved.
What remains is whole-book idle time: roughly 30% of bars produce no channel signal at all.
Three arms attacked it and all three lost on the holdout.

| arm | fit median | **hold median** | P(>5%) | P(>20%) | worst | median Screen 3 |
|---|---|---|---|---|---|---|
| control_rebalance | 4.08 | **3.11** | 0.467 | 0.168 | -28.70% | 3.049 |
| always_on_xs (no channel gate) | 4.16 | **1.41** | 0.414 | 0.177 | **-38.74%** | 1.517 |
| always_on_xs_drift | 4.32 | **1.18** | 0.414 | 0.197 | -36.60% | 1.579 |
| hybrid_fill (momentum fills empty slots) | 3.84 | **1.97** | 0.423 | 0.166 | -31.14% | 2.428 |

**The cash is not idle. The cash IS the position.**
The channel exit moves the book to cash precisely when the momentum names it ranks are falling, so the 30% is the exit rule's product rather than a drag on it.
Removing the entry gate does not add 30% more exposure to the same edge; it adds exposure with the stop removed, and the worst 14-day window goes from -28.70% to -38.74%.
`hybrid_fill` is the gentler version of the same mistake and fails the same way.
Note what the fit window did: every one of these arms is at or above the control on fit and far below it on holdout, which is the signature this repo has now recorded on concentration, on sizing and on take-profits.

### Lever two: the weight path. The only measurable effect in the sweep, and it is already deployed.

`bot/portfolio.deltas` suppresses any rebalance inside a 25% relative band, so a winner's weight is allowed to grow with its price.
The backtest has never modelled this: it resets every position to target on every bar, which silently trims winners and tops up losers.
**The deployed book and the measured book were different books.**

Paired against the control on 614 holdout windows, with a 14-day moving-block bootstrap at B=4000:

| arm | d median | p | d P(>20%) | p | d P(>5%) | p |
|---|---|---|---|---|---|---|
| drift_band_25 | +0.017 pp | 0.597 | **+1.95 pp** | **0.011** | -0.33 pp | 0.581 |
| no_trim | -1.418 pp | 0.033 | -3.26 pp | 0.089 | **-13.52 pp** | 0.000 |
| always_on_xs | +0.283 pp | 0.871 | +0.98 pp | 0.627 | -5.37 pp | 0.174 |
| always_on_xs_drift | +0.933 pp | 0.592 | +2.93 pp | 0.247 | -5.37 pp | 0.178 |
| hybrid_fill | 0.000 pp | 1.000 | -0.16 pp | 0.964 | -4.40 pp | 0.097 |

The drift band buys 1.95 points of P(>20%) at no measurable cost to the median or to P(>5%), and it is the only p below 0.05 that is not a loss.
**Read it with the correction: 15 tests were run, so Bonferroni takes that 0.011 to 0.165.**
The claim this supports is therefore modest and it is not a promotion: the live book's right tail is slightly better than every number previously recorded for it, and 43 independent windows cannot resolve how much better.

The band width was swept to test whether 0.25 is a real dial or an accident:

| band | fit median | hold median | P(>5%) | P(>20%) | worst | Screen 3 |
|---|---|---|---|---|---|---|
| 0.00 | 4.08 | 3.11 | 0.467 | 0.168 | -28.70% | 3.049 |
| 0.05 | 4.14 | 3.35 | 0.469 | 0.169 | -28.55% | 3.076 |
| 0.10 | 4.10 | 3.08 | 0.472 | 0.171 | -28.46% | 3.136 |
| **0.25 (live)** | 4.10 | 3.02 | 0.464 | **0.187** | -28.38% | 2.918 |
| 0.40 | 4.27 | 2.69 | 0.453 | **0.191** | -27.46% | 2.844 |
| 0.60 | 4.13 | 1.95 | 0.440 | 0.151 | -31.69% | 2.452 |
| 0.80 | 4.64 | 1.74 | 0.427 | 0.158 | -32.12% | 2.434 |

P(>20%) rises monotonically to 0.40 and then breaks down, while the holdout median falls monotonically from 0.05 onward and the FIT median rises to its maximum at the widest band.
So the dial is real in direction, it has an interior optimum, and past roughly 0.40 drift stops being convexity and becomes a stale portfolio.
The whole spread of P(>20%) across the sweep is 4 points against a standard error near 5.7 points at 43 independent windows, so **no band value is distinguishable from another** and the pre-registered 0.25 is left where it is.
Moving to 0.40 would cost 0.33 points of holdout median for 0.4 points of P(>20%), both inside noise, and the only evidence for it is the window used to judge it.

### What this closes

**No arm is promoted. The declared selection rule returns NONE and that is the honest result.**

The deeper finding is that every dial this repo has tested now moves along one frontier.
Concentration (`#max-return-levers-outcome`), the derisk ramp (`#derisk-ramp-protection-outcome`) and now the weight path and the deployment rule all trade median return against the far tail, in the same direction, with the fit window preferring the aggressive end and the holdout punishing it.
The dials do not create return. They reallocate it between the median and the tail.
Only two changes in this repo's history have improved both windows at once, and both are already live: the ranking rule at `#competition-book-selection` and full deployment at `#full-deployment-outcome`.

The practical consequence for the stated objective is that **further sizing work has no expected value**, and the remaining levers that add return rather than move it are the ones outside the strategy: fee confirmation, worth about 3% of NAV on this turnover, and fill quality, which needs the API keys.
Both are in `ORGANISER_QUESTIONS.md` and neither is a backtest.

## live-excursion-outcome

Operator observation from the dashboard: the books give back too much, with a stated mechanism - that these coins are strongly momentum-driven and strongly correlated at short horizons, so peaks are common and identifiable.
`gates/live_excursion.py` tests it on the LIVE minute-resolution price paths of positions this repo actually held, reconstructed from the per-cycle `marks` added at `HANDOVER.md` section 4c.
This is not a repeat of `#take-profit-outcome` or `#ratchet-outcome`, which tested exit rules on 4h history. Same question, independent data.
Every number is deduplicated to symbol-episodes, because seven correlated books holding ENAUSDT at once is one observation and not seven: 96 closed round trips collapse to **57 episodes across 22 symbols**.

### The observation is correct and the size of it is larger than expected

| | median |
|---|---|
| maximum favourable excursion | **+2.77%** |
| realised return | **+0.85%** |
| capture, realised over MFE | **0.33** |
| maximum adverse excursion | -0.75% |
| where the peak fell in the hold | 0.49 |

Summed across the 57 episodes the give-back is **171.5 points of position return**.
The median position hands back two thirds of its best moment, and the worst cases are stark: ENAUSDT reached +12.8% and was closed at +2.7%, with its peak **5% of the way into a 36-hour hold**.

### Every rule that books it loses, measured on those same paths

Trailing stops and fixed targets replayed on the observed paths, exit charged 5 bps, no re-entry:

| rule | mean | median | fired | beats actual | vs actual |
|---|---|---|---|---|---|
| **actual exits** | **+1.91%** | +0.85% | - | - | - |
| trail 0.5% | +0.52% | -0.10% | 55 | 24/57 | -1.39 pp |
| trail 1.0% | +0.48% | -0.20% | 47 | 22/57 | -1.43 pp |
| trail 1.5% | +0.56% | -0.08% | 39 | 17/57 | -1.35 pp |
| trail 2.0% | +1.47% | +0.32% | 36 | 16/57 | -0.44 pp |
| trail 3.0% | +1.98% | +0.50% | 29 | 15/57 | +0.07 pp |
| trail 5.0% | +1.95% | +0.85% | 15 | 10/57 | +0.04 pp |
| target 2% | +1.18% | **+1.95%** | 33 | 16/57 | -0.73 pp |
| target 3% | +1.16% | **+2.02%** | 27 | 12/57 | -0.75 pp |
| target 8% | +2.02% | +1.07% | 13 | 5/57 | +0.12 pp |
| target 12% | +2.05% | +0.85% | 7 | 6/57 | +0.14 pp |

**Candidates by the declared rule: NONE.**
A tight trail cuts mean return by roughly two thirds.
The four rules with a positive mean delta gain +0.04 to +0.14 points, fire on 7 to 29 of 57 episodes and win on 5 to 15 of them, so they are loose enough to be doing almost nothing and their edge is noise.

**The 2% and 3% targets are the trap and they deserve naming.**
They raise the MEDIAN outcome from +0.85% to about +2.0% while cutting the MEAN from +1.91% to +1.17%.
A book running them would show more winning trades, more closed trades and a better-looking blotter while making less money.
That is `#take-profit-outcome` reproduced on live data from the opposite direction, and it is exactly what "we are not booking enough profits" feels like from the dashboard.

### Why it cannot work: the give-back is real but it is not separable

**The trades with the most to book are the ones that peak last.** MFE against peak position in the hold is Spearman **+0.434, p=0.001**, the only significant relation in the study.
So any rule tight enough to catch ENAUSDT's peak at 5% of its hold also truncates SUIUSDT, which ran to +21.2% with its peak at 89% of a 32-hour hold and was captured at 0.85.

And nothing observable early tells the two apart:

| predictor | target | Spearman | p |
|---|---|---|---|
| return in first 30 min | peak position | -0.141 | 0.294 |
| return in first 60 min | peak position | -0.167 | 0.216 |
| return in first 60 min | give-back | +0.001 | 0.994 |
| return in first 60 min | final realised return | **+0.215** | 0.109 |

The first-hour move does not predict an early peak.
If anything it leans the other way: a fast start predicts a BETTER final return, median +1.34% against +0.35% for a slow start.
So the instinct "it ran up quickly, take the money" is pointed at the wrong trades.

### The stated mechanism is inverted on both halves, measured

24 symbols, 1,252 minutes of live marks:

| horizon | mean cross-sectional correlation |
|---|---|
| 1 minute | 0.350 |
| 15 minutes | 0.381 |
| 60 minutes | 0.407 |
| 240 minutes | 0.414 |

**Correlation is WEAKEST at the shortest horizon and rises with it**, which is the Epps effect, not the premise.
The first principal component explains **41.1%** of 1-minute variance, so 59% of what these coins do minute to minute is idiosyncratic and there is no single pattern to time.

The momentum half fails too.
Mean lag-1 autocorrelation of 1-minute returns across 24 names is **-0.029**: mildly mean-reverting, not trending.
That is the same sign and roughly the same size as `#scalp-meanrev-outcome` and as arXiv:2608.21888 in `RESEARCH_SHORT_HORIZON.md`, which measured 1.3 bps of edge against a 5 bps round trip across 183 pairs.
A -0.029 autocorrelation is far below any tradeable threshold at 10 bps.

### What is adopted

Nothing. No exit rule is added and no book changes.

The value of this run is that an independent dataset agrees with the history.
`#take-profit-outcome` killed targets on 4h bars across 26 configurations; this kills them again on live minute paths the bot actually traded.
Two datasets, different resolutions, same answer: **the channel exit is already both the stop and the target, and the give-back is the price of the right tail, not a defect in the exit.**

**Sample limits, stated plainly.** About 44 hours, one market regime, 57 independent episodes. That is enough to refute a claim of a large obvious effect and nowhere near enough to establish one. If the next regime differs, this study says nothing about it.

## alpha-flow-declaration

Operator instruction, 2026-09-22: do not treat the existing rules as fixed, build a bot that books profits and churns them back into capital, drive selection from correlation and coin selection, find the trading logic in volume, gamma exposure and order flow, use exploitable alternate data, and ship it for forward testing.
This entry records what was measured before building, because the build had to be aimed at something.
53 selectable configurations were evaluated and added to the ledger, which now stands at 525 rows. Declared nonsense controls are not counted.

### The selection axis, measured and exhausted

`taker_buy_quote` is cached for the full history, so aggressor-side order flow is directly computable as `(2*taker_buy_quote - quote_volume)/quote_volume`.
`#flow-scalp-outcome` only ever tested it at 5, 15 and 30 minutes, so 4h to 3 days was untested.

Cross-sectional Spearman IC against forward returns, fit window:

| feature | 4h | 24h | 3d |
|---|---|---|---|
| ofi_1 | -0.002 (t -0.6) | -0.001 (t -0.3) | -0.004 (t -0.9) |
| ofi_6 | -0.000 (t -0.1) | -0.005 (t -1.0) | -0.004 (t -0.8) |
| ofi_18 | -0.002 (t -0.4) | -0.005 (t -1.2) | +0.005 (t +1.1) |
| vol_surge | -0.006 (t -1.3) | -0.006 (t -1.2) | -0.011 (t -2.3) |
| avg_trade_z | -0.003 (t -0.6) | -0.003 (t -0.7) | +0.003 (t +0.8) |

**Order flow has no cross-sectional information at these horizons.** Nothing reaches |t| of 1.3 except a volume-surge reading that is negative, which is the wrong sign for a momentum book.

As ranking rules inside the channel-gated set, holdout median 14-day return against the live rule's 3.12%:

| ranker | hold median | worst | Screen 3 |
|---|---|---|---|
| **momentum_40 (live)** | **3.12** | -28.67 | **3.066** |
| mom_x_ofi | 2.70 | -29.71 | 2.861 |
| ofi_18 | 1.61 | -37.54 | 2.490 |
| ofi_6 | 0.85 | -36.31 | 1.539 |
| low_beta | 0.62 | -43.76 | 1.445 |
| vol_surge | 0.37 | -0.00 | 0.891 |
| avg_trade | 0.27 | -32.55 | 0.670 |
| idio_40 (correlation residual) | 0.10 | **-67.09** | 0.409 |
| high_beta | -0.68 | -46.74 | -0.519 |

The one combination worth naming is `mom_x_ofi`, which reaches P(>10%) of 0.334 against momentum's 0.321 while losing 0.4 points of median. It is not better and it is not adopted.

**Why coin selection is structurally a weak lever here, in one number.** Mean correlation of each name to the equal-weight universe return at 4h is **0.835**, with a p10 of 0.698 and a p90 of 0.945.
Roughly 16% of a coin's 4h variance is idiosyncratic, so selecting between names is mostly selecting how much beta to hold, and selecting ON the residual is actively destructive at a -67% worst window.
This is the mechanism behind `#coin-selection-does-not-persist`, which observed the same thing from the outside.

### Funding-rate crowding: the strongest fit signal in the repo, and it does not replicate

A funding panel was built from Binance perpetuals and cached at `data/cache/alt/funding_panel.parquet`: **10,731 timestamps by 51 names back to 2020**, about 24 names per timestamp. This repo had never used it.

Cumulative 18-bar funding against forward 3-day returns scores IC **-0.068 with t = -7.1** on the fit window, three times the magnitude of anything else measured here and the economically right sign: crowded longs pay to be long, and then underperform.

It fails three ways.

**It does not replicate.** Inside the perp-covered universe the 24h IC goes from -0.054 (t -5.8) on fit to **+0.008 (t +0.6)** on holdout. The sign flips and the significance is gone. At 3 days it partly survives at -0.040 (t -3.0) but no book built on it makes money.

**Coverage is non-random.** Only **46% of fired candidates have a perpetual listing** and 55% of bars have no coverage at all, because perps exist for the majors and not for the rest. A veto built on it therefore removes the majors and concentrates the book into thin names: every threshold takes holdout median from 3.12% to at best 1.15% and the worst window from -28.7% to about -51%.

**The nonsense control settles it.** Vetoing the LEAST crowded names instead reproduces the baseline exactly, at 3.12% and an identical -28.67% worst window. A real signal would have hurt there. A coverage artifact does exactly what was observed.

**And the covered universe is a worse universe on its own.** Trading only perp-listed names, with no veto at all, takes holdout median to **-1.44%** and the worst window to -54.5%. That is `#roostoo-universe-pool-size` again: a filter inside an already-filtered list removes the names carrying the book.

The time-series version does not work either. Market-wide funding in the top quintile precedes a **+0.599%** mean next-24h universe return on fit and **-0.004%** on holdout.

### Booking profits: all three forms tested, and the result is not what was expected

Tested in the bar-by-bar weight-state simulator from `#compounding-outcome`, which carries explicit positions and charges every trade it generates.

**Recycling into the same target is arithmetically a rebalance.** Every ladder that books a slice and immediately redeploys it across the same equal-weight target lands within 0.09 points of the control on holdout median and pays fees for the privilege: 3.07% to 3.10% against the control's 3.11%. Selling a slice of a winner and buying it straight back is not booking a profit, it is a round trip.

**Redeploying into NEW names is worse than holding the cash.** On every pairing tested, funding the next-ranked fired names with skimmed cash lost to simply letting the cash idle: 2.44 against 3.59, 1.92 against 3.47, 2.78 against 3.15, 2.85 against 3.52, 2.42 against 3.34. It dilutes the book into lower-ranked names.

**Skimming into cash improved both windows, and then the control took most of it back.** A ladder that skims 40% of a position each time it gains 5% from its reference, holding the proceeds, takes fit median 4.08 to 5.00 and holdout median 3.11 to **3.59**, with median drawdown -12.67 to **-8.43** and mean gross 0.699 to **0.511**.

Two things must be said about that before anyone reads it as alpha.

The return gain is **not significant**: paired block bootstrap on 43 independent holdout windows gives p = 0.14 on the median delta, and p between 0.54 and 0.92 for the neighbouring settings.
And the drawdown gain is **reproduced by a random-timing nonsense control** that skims at the same hazard rate with no reference to price, landing at a median drawdown of -11.2 to -11.4 against the control's -12.67, on gross of 0.62.
So the drawdown improvement is exposure reduction, not timing, and what remains is a median improvement inside noise.

The frontier is visible across the grid exactly as it is everywhere else in this repo: tight steps raise the median and cut P(>20%) from 0.168 to 0.134, loose steps raise P(>20%) to 0.199 and cut the median to 2.44.

### Alternate data: what exists, and why most of it cannot be backtested at all

| source | what it gives | history |
|---|---|---|
| Binance `taker_buy_quote` | true aggressor imbalance | **full**, already tested above, null |
| Binance funding | positioning cost | **full**, tested above, does not replicate |
| Binance open interest | leverage build-up | **30 days only** |
| Binance long/short account ratio | retail positioning | **30 days only** |
| Deribit option OI and IV | **dealer gamma exposure** | **snapshot only, no history at all** |

`data/options.py` computes dealer gamma from Deribit, which carries essentially all crypto option open interest. It parses strike and expiry from the instrument name, prices Black-Scholes gamma off `mark_iv`, and aggregates to a net figure in dollars of hedging demand per 1% move, plus the gamma flip strike. First reading: BTC net GEX **-425m per 1%** across 645 instruments with the flip at **80,000** and spot at 86,487, so dealers are short gamma and hedging with the move rather than against it.

The dealer-short-calls convention is an assumption that cannot be verified from public data, and the sign of every number depends on it. That is stated in the module.

**None of this is tradeable yet and that is the whole point.** A series with no out-of-sample window cannot be validated before it is collected, so `config/alpha_flow.yaml` carries `alt_data.trades_on_it: false`. The collector runs every 15 minutes and journals each snapshot so that a dataset exists in 30 days. That is the only honest route from "gamma exposure sounds exploitable" to "gamma exposure is or is not exploitable here".

### What was built

`config/alpha_flow.yaml`, `bot/alpha_flow_run.py`, `bot/alt_data.py`, `data/options.py`, and `tests/test_alpha_flow.py`.

The bot is `momentum_top3_full` plus the skim ladder at 5% and 40%, with booked cash idling, subclassing `Bot` so cold-start suppression, the drift band, kill switches, mirror checks and markout instrumentation are inherited unchanged. Its control is `momentum_top3_full`, identical in every other respect. It is wired into `run_bots.sh` as `alphaflow` and is running.

It is deployed as a **forward test on operator instruction**, not as a validated improvement, and `config/alpha_flow.yaml` says so in `meta.honest_status_of_the_skim`.
What to watch is stated there too: if the skim is only reducing exposure, the forward return will track the control while gross sits near 0.51, and nothing has been gained.

### Amendment 2026-09-22: the ladder was not booking consistently, and the fix was the slice not the step

Operator: "I want it to book profits consistently."
Measured on the 59 live symbol-episodes, the original 5% step fired on only **36% of positions and the median position booked zero times**, so the ladder was not doing what it had been asked to do.

Firing rate by step, live episodes:

| step | episodes that book | median skims per episode |
|---|---|---|
| 1% | 80% | 2 |
| 2% | 58% | 1 |
| 3% | 46% | 0 |
| 5% (original) | 36% | 0 |
| 8% | 22% | 0 |

**Tightening the step alone is the one thing in this whole grid that is significantly harmful.** Holdout P(>20%) against the control: 1% takes it 0.168 to 0.070 at **p=0.004**, 2% to 0.093 at **p=0.022**, 3% to 0.103 at **p=0.046**. Every median-return delta in the same grid sits at p between 0.68 and 0.95. So the only statistically real effect of booking harder is the loss of the right tail, which is the thing Screen 2 qualification depends on.

**Cutting the slice at the same time removes the cost.** Booking more often but taking less each time:

| setting | skims | d median | p | d P(>20%) | p |
|---|---|---|---|---|---|
| 5% x 40% (original) | 1,970 | +0.332 pp | 0.681 | -0.0342 | 0.266 |
| **3% x 15% (adopted)** | **2,989** | +0.329 pp | 0.678 | **-0.0081** | **0.732** |
| 3% x 25% | 2,989 | +0.277 pp | 0.742 | -0.0293 | 0.268 |
| 2% x 15% | 3,952 | -0.103 pp | 0.908 | -0.0195 | 0.429 |

`3% x 15%` books **52% more often than the original setting while its right-tail delta is four times smaller and less significant than the original's own**. Consistency was bought from the slice size, not from the tail.

Amended before the bot held any position, so no forward evidence was invalidated. `2% x 15%` remains available if more frequency is wanted: 58% of positions book with a median of one skim, at d P(>20%) of -0.0195, p=0.43 - still not significant, but twice the tail cost for no median gain.

## rsi-band-outcome

Operator request: test buying the RSI cross up through 50 and selling at 70, on smaller timeframes, on coins filtered to those that follow the pattern.
`config/rsi_band.yaml` declared it, `gates/rsi_band.py` ran it, artifact `results/rsi_band.json`. Three configurations, ledger now 528.
15-minute bars for the 55 names that have ever been in the PIT top-30 were downloaded for this (`data/cache/panel_15m.parquet`), because only five symbols were cached at 5m and five names is not a cross-section.

`signals/rsi.py` is Wilder's RSI with Wilder's SEED, validated against the published 33-point series at 70.46 and 66.25 against the book's 70.53 and 66.32, the residual being rounded intermediates in the published table.
This matters: a bare `ewm(adjust=False)` seeded from the first change is a faster indicator that crosses 50 more often, and the entire signal here is a level cross.

### The rule, holdout, all coins

| interval | trades/day | win rate | mean GROSS | mean net @10bps | median net | median hold | reached RSI 70 |
|---|---|---|---|---|---|---|---|
| 15m | 99.6 | 0.381 | **-0.36 bps** | -20.36 bps | -30.68 bps | 0.8h | **11%** |
| 1h | 23.7 | 0.382 | **-1.33 bps** | -21.33 bps | -43.04 bps | 3.0h | **12%** |
| 4h | 5.7 | 0.383 | +9.36 bps | -10.64 bps | -64.59 bps | 12.0h | **14%** |

**At 15m and 1h the rule is negative BEFORE costs.** That is a stronger result than the usual cost failure in this repo: there is no gross edge to lose. At 4h there is a small gross edge of 9.36 bps and it does not survive a 10 bps round trip.

**The rule almost never does what it is named after.** Only 11 to 14% of trades ever reach RSI 70. The other 86 to 89% exit on the opposite cross, RSI falling back through 50, which is the losing leg. The win rate is 0.38 at every interval.

Note the shape: median net is far worse than mean net at every interval, so the mean is being carried by a thin right tail of trend continuations. That is a trend-following payoff wearing an oscillator's clothes, and the 50-to-70 band truncates exactly the tail that pays. It is `#take-profit-outcome` again, arrived at from a third direction.

### The coin filter does not survive its own selection, and the control proves it

The filter was fitted on the fit window, ranked by mean net basis points per trade with a minimum of 10 trades per coin, and applied to the holdout. The bottom quartile was carried forward as a nonsense control.

| interval | FIT top | FIT bottom | HOLDOUT top | HOLDOUT bottom | persistence rho |
|---|---|---|---|---|---|
| 15m | +4.02 | -22.63 | **-20.19** | -19.71 | **-0.109** |
| 1h | +12.55 | -50.37 | **-22.91** | -25.42 | **-0.002** |
| 4h | +58.40 | -50.63 | **-36.92** | **-14.46** | **-0.024** |

In the fit window the filter looks devastating: at 4h the top quartile averages +58.40 bps per trade against -50.63 for the bottom, a spread of 109 bps.
Out of sample the entire spread is gone, and at 4h it **inverts**: the coins the filter rejected beat the coins it selected by 22 bps per trade.
Per-coin rank persistence is -0.109, -0.002 and -0.024. All three are zero or negative.

This is an independent replication of `#coin-selection-does-not-persist` on a completely unrelated rule. That entry measured Spearman 0.091 at p=0.586 on the channel book and found the eight worst coins beating the eight best; this finds the same thing on an oscillator band across three timeframes.
**"Filter the coins that follow this pattern" is not a strategy, it is a description of the fit window.** The pattern does not belong to the coin.

### Verdict

**Candidates by the declared rule: NONE.** Nothing is adopted and nothing is deployed.
The rule fails the cost screen at all three intervals and fails it before costs at two of them, and the coin filter that was supposed to rescue it has zero out-of-sample content.

Useful by-products kept: `signals/rsi.py` with a validated Wilder implementation and seven tests, and a 15-minute panel for the traded universe that did not exist before.

## booking-flattened-the-book

A defect I introduced on 2026-09-22 while making the skim ladder a shared capability, caught within minutes by its own telemetry, and worth recording in full because it has two distinct causes and the second is the more dangerous one.

### What happened

Operator asked for booking across the fleet, so the ladder moved out of `bot/alpha_flow_run.py` into `bot/booking.py` and the base `Bot` began applying it to any config carrying a `booking` block.
Booking is an intrabar exit, so `trades_every_cycle()` was made to return true whenever booking is enabled.

At 16:03:38 UTC, on a cycle that was **not** a bar close, `donchian_4h_cushion`, `donchian_1h` and `momentum_top5_cushion` sold their entire books.

### Cause one: an empty target is not "no opinion", it is "sell everything"

`bot/run.py` computes `channels = evaluate_book(...) if fresh else {}`.
On a cycle that is not a bar close, `channels` is empty by construction, so `compute_target` returns `{}`.
That was harmless while `trades_every_cycle()` was false, because `deltas` was never called on those cycles.
Turning it true made `deltas({}, current)` run every minute, and `deltas` correctly reads an empty target against a held book as a full liquidation.

The fix is to carry the held book forward on a non-fresh cycle rather than computing a target from channels that were never evaluated, and to let only the ladder move it.

**The general lesson: a flag that changes WHEN a function is called can be as destructive as changing what it returns.** Nothing about `compute_target` or `deltas` was wrong. The damage came from calling a correct function at a moment its precondition did not hold.

### Cause two: the no-trade band silently ate every skim

Caught by the regression test written for cause one, not by observation, and it would have been much harder to find in the wild.

`bot/portfolio.deltas` suppresses any move inside a 25% relative band, which is correct for price drift and is why `#live-rebalance-chases-drift` exists.
A 15% skim on a held position is a move of 15% of that weight, which is **inside** the 25% band.
So every skim the ladder generated would have been suppressed, and the booking bots would have run for days generating skim events in the journal while never placing a single order.

That failure mode is worse than the liquidation. The liquidation was loud and immediate. This one would have looked exactly like a working system: skims logged, no orders, weights unchanged, and a forward A/B that quietly measured nothing.

`deltas` now takes a `force` set. A skim is a deliberate trade of a declared size, not drift, so it is exempt from the band.

### Damage and repair

Paper only, dry run, no real orders. Three books were flattened and `momentum_top5_cushion` was left **stuck**: its channel state still said seventeen names were held while it had no position, so it could never re-enter until each of those channels exited and broke out again.
State was reconciled to actual holdings on all three, `skim_refs` cleared, and a `state_repair` record written to each lifecycle journal.
Their forward records carry a discontinuity at 2026-09-22T16:03Z and should not be read across it.

### What is now guarded

`tests/test_booking_cycle.py`, five tests:
- carrying the book forward emits no orders when nothing has gained
- an empty target against a held book IS a full liquidation, asserted as a fact so the guard above has a stated reason
- a skim inside the band is suppressed WITHOUT `force` and placed WITH it
- booking is enabled on exactly the four books that declare it
- every gated control is left without booking

### Which books carry booking, and which deliberately do not

| book | booking | why |
|---|---|---|
| `alpha_flow` | ON | the declared booking forward test |
| `donchian_4h_cushion` | ON | not a control; confounded with the cushion treatment, stated in its config |
| `momentum_top5_cushion` | ON | not a control; same confound, stated in its config |
| `donchian_1h` | ON | a comparison book and nobody's control, so it confounds nothing |
| `donchian_4h` | **off** | control for `donchian_4h_cushion` |
| `momentum_top5_4h` | **off** | control for `momentum_top5_cushion` |
| `momentum_top3_4h` | **off** | control for `momentum_top3_full` |
| `momentum_top3_full` | **off** | control for `alpha_flow` |
| `scalper_live` | **off** | it already exits on target, stop and time; a second exit rule on top would fight the first |

Four controls are left clean on purpose. Turning booking on everywhere would give the operator what was asked for and destroy every forward comparison in the repo at the same time, which is a trade nobody stated and I am not making silently.

## booking-on-every-bot

Operator instruction 2026-09-22, after being shown what it costs: **enable booking on every bot, controls included.**

The cost was stated before the change and is restated here so no future reader mistakes the result for a measurement.
Four books were clean controls: `donchian_4h` for the cushion arm, `momentum_top5_4h` for its cushion arm, `momentum_top3_4h` for `momentum_top3_full`, and `momentum_top3_full` for `alpha_flow`.
**From 2026-09-22 every one of those pairs measures its own treatment ON TOP OF booking rather than against a no-booking baseline.** No reading may be carried across that boundary, and the boundary is recorded in each config's `booking.control_status_lost`.
`alpha_flow`'s reason for existing is gone with it: it was the booking arm against a non-booking control, and now every book is a booking book. It continues as the alt-data collector.

`scalper_live` is included with a stated interaction: it already exits on its own target, stop and time clock, so the ladder is a second profit-taking rule layered on the first and the two will sometimes fire on the same move.

All nine books run the identical declared ladder, 3% step and 15% slice, `recycle: false`, asserted by `tests/test_booking_cycle.py`.

### The third defect, found in the same session as the first two

`bot/booking.py` seeded a reference price only where `held <= 0`, which is the fresh-entry branch.
A position that already existed when booking was switched on therefore had no reference, and `ref = refs.get(sym) or px` silently recomputed the reference as the CURRENT price on every cycle.
`px >= ref * 1.03` is then never true, so **every pre-existing position could never book, ever.**

Observed directly: `donchian_4h` held 18 positions with 0 skim references.

This is the same failure class as the no-trade band in `#booking-flattened-the-book`: a system that logs activity, places no orders and measures nothing, while looking healthy from the outside. The `or px` idiom is what hid it, because a missing value and a valid value took the same code path.

The fix seeds the reference lazily from the current mark, so a pre-existing position starts its ladder from the moment booking is enabled. Verified after restart: 18 holdings, 18 references, on every book.

### Three defects in one feature, and what that says

The ladder is roughly forty lines and it shipped three distinct bugs: an empty target read as a liquidation, a deliberate trade eaten by a drift suppressor, and a reference that was never persisted. None was a logic error inside the ladder itself. All three were interactions with machinery that was already correct - the cycle's freshness contract, the no-trade band, and the state file.

**The lesson is about where to look.** Every one was found by asking "what does this new flag change about when existing code runs", not by re-reading the new code. Two of the three were caught by tests written for the first one. The thing that would have hidden all three in production is that a suppressed trade and a trade that was never wanted look identical in a journal.

`bot/run.py` now carries `target_from_channels()`, which is false for `bot/scalper_run.py`, because carrying holdings forward between bar closes would have silenced every intrabar stop and target that book has.

## testnet-live

Operator asked for the bots to place real orders on Binance paper trading. `config/testnet_live.yaml` now runs authenticated against `testnet.binance.vision` and is placing real orders against a real matching engine. `./run_bots.sh testnet`.

### What had to be built first

`bot/run.py` opened with `if not settings.dry_run: raise RuntimeError("live_orders_blocked_until_restart_reconciliation_is_implemented")`.
That guard was correct and it blocked Roostoo as much as testnet, so it was on the competition's critical path regardless of this request.

The window it stood for is small and real. `Executor.send` makes an HTTP call and then journals the result. A process that dies in between leaves an order that may exist at the venue with nothing local knowing it, and the next start recomputes a target from stale holdings and submits again.

`bot/intents.py` closes it. The intent is written and **fsynced before** the call, resolved after, and every unresolved intent is settled against the venue on startup before a single new order may be sent. If any cannot be settled the submission block stays on and the reason is journalled.

Venue matching differs and the difference is not cosmetic. Binance accepts `newClientOrderId`, so an intent maps to an order **exactly**, and `query_by_client_id` is used. Roostoo's `place_order` has no such field, so an unresolved Roostoo intent can only be matched on pair, side, quantity and a timestamp window. That path reports `matched_by: heuristic` and is never silently treated as certain. Both clients now take `client_order_id` so the executor has one signature.

### Four live-only defects, none of which a dry run can produce

**1. An empty universe meant "adopt everything".** `adopt_wallet` restricts to `self.universe`, but on a book that has never persisted state the universe is empty, and empty fell through to unrestricted. Binance testnet seeds accounts with several hundred non-zero balances, so the bot adopted **487 positions and submitted 469 orders in one cycle**, reading equity as $444,275. The universe is now resolved before the wallet is read, and a wallet read with no universe adopts nothing and says so.

**2. A resting order locks the asset, and holdings do not show it.** The bot sold a position, the LIMIT rested, `holdings` still showed the full quantity, and the next cycle sold it again. The venue answered `-2010 insufficient balance` fifteen times and the error-rate kill switch **halted the book**. `Executor.refresh_pending` now lists resting orders once per cycle and `send` skips a pair that already has one. A dry run can never show this because `apply_dry_fill` settles instantly.

**3. Binance requires `symbol` on a cancel and Roostoo does not.** `sweep_unfilled` cancelled by order id alone, which produced `-1105 Parameter 'symbol' was empty` on every sweep and walked the error rate back toward the kill switch. The pair is now passed, which satisfies both venues.

**4. `wallet_positions` counts `free + lock` as holdings.** Correct for valuation, wrong for sizing a sell. Defect 2 masks it for now because a pair with a resting order is skipped entirely; it is recorded here because the moment partial fills appear it will matter on its own.

This is exactly what `CLAUDE.md` says the interim venue is for: a backtest multiplies weight vectors and never formats an order. Every one of these four is invisible until an order reaches a real exchange.

### What the testnet book is and is not

It is `donchian_1h`'s rule and ladder pointed at a different venue, with its own journal, so the nine paper records are untouched. Pool cut to 12 names. Mirror check disabled, because testnet prices are synthetic and diverge from mainnet by far more than the 50 bps deviation limit.

**Read fills and rejections. Never read returns.** Testnet prices are not real prices, the account holds about 9,600 USDT against the 100,000 every paper book assumes, and P&L here means nothing.

One book, not nine, for a reason: `adopt_wallet` treats the venue wallet as authoritative, and all nine bots share a single testnet API key. Pointing them all at it would have each bot claim the whole wallet and try to rebalance the others' positions away. Nine live books needs nine API keys.

### Still blocked on Roostoo

`.env` carries both Roostoo lines commented out and marked NOT YET ISSUED. Setting `ROOSTOO_DRY_RUN=0` there would fail every authenticated call, cross the 0.25 error-rate kill switch within about five cycles, and a halt empties the target set, which flattens the book. Question 3 of `ORGANISER_QUESTIONS.md` is what unblocks it.

Also noted from the public endpoint: `exchangeInfo` reports `InitialWallet: {"USD": 50000}` while every config and backtest here assumes **100,000**. Worth confirming with the organisers - it halves every notional and could put small positions under the minimum order size.

## declaration-anchors

Eight frozen configs cite a `*-declaration` anchor in this file that was never written: `#concentration-declaration`, `#concentration-timeframe-declaration`, `#fast-horizon-declaration`, `#paper-lab-v3-declaration`, `#sizing-sweep-declaration`, `#strong-retraced-declaration`, `#take-profit-declaration` and `#testnet-mirror-scope`.

Found 2026-09-22 by `tests/test_doc_anchors.py`, which now fails the build on a citation that resolves to nothing.

**They are not being written retroactively.** A declaration is a claim made BEFORE a test runs, and inventing one after the fact is the exact failure the declare-before-you-test rule exists to prevent. Writing them now would produce eight entries that look like pre-registrations and are not.

**The declaration each one refers to is the config file itself.** `config/<family>.yaml` carries `meta.declared_before_any_backtest`, the mechanism, the failure mode and the decision rule, and the gate refuses to run if that flag is false. The outcome then lands here under `#<family>-outcome`. The configs were written expecting a matching entry on this side and none was ever made.

So the convention, stated plainly for the first time:

- **the declaration lives in `config/<family>.yaml`**, before any backtest, enforced in code
- **the outcome lives in `DECISIONS.md#<family>-outcome`**, after
- a `*-declaration` anchor in this file is only warranted when the reasoning did not fit in the config, as with `#ratchet-declaration`, `#meanrev-xs-declaration`, `#flow-scalp-declaration` and the others that do exist

The dead references are left in the frozen configs rather than edited, because amending a frozen declaration to fix a footnote is a worse precedent than a footnote that points at this entry. `tests/test_doc_anchors.py` carries them as a known-dead allowlist naming this anchor, so a NEW dead reference still fails.

## positioning-history

Written 2026-09-23. **The claim that open interest and long/short ratios have 30 days of history was a limit of the REST API, not of the data.**
`DATA_SOURCES.md`, `data/futures.py`, `bot/alt_data.py` and `config/alpha_flow.yaml` all stated it, and `#alpha-flow-declaration` used it to rule positioning out of any fit-and-holdout test.
`data.binance.vision` archives the same fields at 5-minute resolution from 2021-12-01, including delisted contracts: open interest in USD, top-trader account and position long/short, all-account long/short, and the futures taker buy/sell volume ratio.
Funding and hourly premium-index klines are archived monthly from 2020.
`data/vision.py` reads all three and caches one hourly parquet per perpetual under `data/cache/vision/`.
`data/macro.py` adds three market series that also have real history: Deribit DVOL hourly from 2021-03, DefiLlama total stablecoin supply daily from 2017, and the Coinbase BTC-USD premium over Binance BTCUSDT hourly from 2021.

### The 46% coverage figure was a construction artifact

`#alpha-flow-declaration` said only 46% of fired candidates have a perpetual listing, so any funding veto strips the majors.
Its panel had 51 columns keyed on SPOT names, which gave it no row for BONK, PEPE, SHIB or FLOKI, whose perps list as `1000X`.
With spot names mapped to perps through `data.vision.perp_symbol`, all 55 Roostoo-tradable names that have ever been in the PIT top 30 have a perp, and positioning data covers **89.5% of live candidate-bars in 2022, 98.9% in 2023-24 and 99.9% in 2025-26**.
The funding null itself survives the correction (see the outcome below); the reason given for it does not.

### Three stamping defects, found before the numbers were read

1. **The archive writes 0.0 where no reading was recorded.** BTC and ETH open interest read zero for hours on 2022-03-07. Its log is `-inf`, which silently turned every 180-day z-score it touched into NaN or infinity, and the first run's `crowding` correlations came back `NaN` on the fit window. `vision.panel` now treats any non-positive metrics value as missing. `tests/test_positioning.py`.
2. **The taker ratio's `create_time` is the START of its 5-minute volume bucket.** The row created at 20:00 covers 20:00-20:05. An hourly bucket closed on the right handed each 4h bar five minutes of future taker flow. **It manufactured the only significant positive per-coin reading in the run**: `taker_ls_24h` holdout IC at 24h was **+0.025, t=+2.35** with the leak and **-0.003, t=-0.30** without it.
3. **The REST series stamped T equals the archive row created at T-5 minutes** for open interest and both long/short ratios, measured directly on 2026-09-21. A right-closed bucket therefore also misaligned the live and backtest features by one reading.

Both 2 and 3 have the same fix: an hourly bucket `[T-1h, T)` stamped T, so the :55 reading is the last one a bar closing at T may see.
After the fix, `bot.alt_data.positioning` reproduces `gates.positioning_edges.features` at a past hour to within **5e-7 on open interest, 5e-9 on premium and 4e-4 on the ratios** (REST rounds ratios to four decimals). Evidence at `results/positioning_live_parity.txt`.
Funding agrees to within 6% on ENA, because the gate evaluates its 72-hour window at the last settlement and the live collector at the bar close; stated, not material.

The lesson generalises the open-time bar rule in `CLAUDE.md`: **every archive field has its own stamp convention, and a single field's convention can leak even when its neighbours do not.** Measure each against a live source before trusting a join.

## positioning-edges-outcome

Declaration: `config/positioning_edges.yaml`, written before any backtest; one post-hoc follow-up declared in the same file under `followup` after the main run was read.
Harness: `gates/positioning_edges.py` and `gates/squeeze_priority.py`. Artifacts: `results/positioning_edges.json`, `results/squeeze_priority.json`.
Ledger 969 -> **980** (ten declared arms, one post-hoc arm).

**The base book is `momentum_top3_full` with the deployed 3% x 15% ladder**, because every live book runs the ladder now and a no-booking control no longer exists anywhere.
The simulator steps hourly and reproduces the live cycle: entries and the rank at 4h closes, `min(want, held)` so a held name is never topped up while booking is on, the 25% drift band on everything but a deliberate skim, and the ladder checked every hour.
With the ladder and the band switched off it reconciles to `gates.concentration.net_daily` at **0.008pp of holdout median** with a daily-return correlation of 0.99998.

Three windows: **2022 (pre)**, which no positioning signal had ever been scored on and which contains LUNA and FTX; fit 2023-24; holdout 2025 to 2026-09-19.

### Result: nothing passes. No trading or booking rule changes.

Median 14-day return and P(>5%), deployed ladder on every arm:

| arm | 2022 | 2023-24 | 2025-26 |
|---|---|---|---|
| **control** | **-0.78 / 0.263** | **+4.91 / 0.498** | **+3.42 / 0.433** |
| X1 breakout needs rising OI | -1.83 / 0.159 | +3.24 / 0.456 | +3.01 / 0.435 |
| X2 funding veto, as-of | -0.78 / 0.263 | +5.13 / 0.505 | +3.51 / 0.436 |
| X3 top-trader vs retail tilt | -0.64 / 0.263 | +2.95 / 0.428 | +2.26 / 0.393 |
| X4 negative-funding priority (post-hoc) | -1.47 / 0.271 | +4.89 / 0.496 | +2.26 / 0.425 |
| M1 crowding gate, 0.5x | -0.23 / 0.289 | +4.30 / 0.481 | +3.46 / 0.438 |
| M2 washout BTC sleeve | -1.07 / 0.271 | +5.01 / 0.501 | +3.32 / 0.438 |
| M3 implied-below-realised gate | -0.56 / 0.266 | +4.91 / 0.498 | +3.51 / 0.433 |
| M4 Coinbase discount gate | -0.50 / 0.260 | +5.02 / 0.503 | +2.84 / 0.425 |
| M5 stablecoin contraction gate | -0.81 / 0.177 | +3.76 / 0.459 | +2.73 / 0.407 |
| B1 book crowded winners | -0.70 / 0.280 | +4.50 / 0.485 | +2.47 / 0.391 |
| B2 book on market crowding | -0.93 / 0.263 | +4.89 / 0.496 | +3.42 / 0.433 |

The declared rule required improving median AND P(>5%) on all three windows. **No arm does.**

**The nearest miss is M1**, the market crowding gate: better in 2022 (+0.55pp, P(>5%) 0.263 -> 0.289) and marginally better on holdout (+0.04pp), worse on fit (-0.61pp), and it beats its own run-length-preserving random-timing control by 0.7pp on holdout.
It is recorded, not deployed. The gate fires 10.6% of the time and the per-window paired median delta is zero by construction for a rare gate, so the declared p-value test cannot distinguish it from nothing; a rule that needs a better test to pass is not one that passed.

**X2 is the earlier funding null, re-run on the corrected data, and it is still a null.** Removing high-funding names is a small gain on fit and holdout and does nothing in 2022, where the veto never fires.

**B1 and B2 are the booking arms, and booking on positioning is harmful or inert.** B1 costs 0.95pp of holdout median and 0.042 of P(>5%); B2 fires 34 times in nearly five years.

### The one robust observation, and why it is not a rule

The X2 nonsense control inverted the veto: remove the LOWEST-funding candidates instead.
It cost **1.5 to 2.0pp in 2022, 0.3 to 1.4pp in 2023-24 and 2.2 to 3.7pp in 2025-26**, at each of three removal fractions (6.3%, 10%, 20%), nine of nine cells, while removing the highest-funding candidates was neutral.
Mean 3-day forward return by funding quintile among live candidates is flat and non-monotone in every window, so the effect is not in the average candidate; it is in the few runners a concentrated top-3 book lives on.

X4 was declared to see whether that could be turned into a rule by PROMOTING negative-funding breakouts. It cannot: median falls 0.69pp in 2022 and 1.16pp on holdout, p=0.44, while P(>20%) rises slightly everywhere (0.026 -> 0.035, 0.196 -> 0.210, 0.160 -> 0.165).
Random priority for the same share of candidates is far worse again (holdout median +0.46%), so negative funding carries information relative to noise, but **momentum already captures it**: the squeeze runners are worth keeping, not promoting.
**The operational consequence is a prohibition, not a rule: never add a veto that can remove negative-funding breakouts.**

### Diagnostics, for the record

Cross-sectional IC at 24h and 3 days inside the PIT top 30, t from the non-overlapping IC series:

- `funding_3d` is negative in all three windows at 3 days (-0.052, -0.073, -0.015) and significant only on fit (t -3.7). Same shape as `#alpha-flow-declaration`.
- `top_vs_global_24h` is significant on holdout only (-0.042, t -2.1 at 3 days) and absent in 2022 (the top-trader position ratio starts later). X3 used it with the positive sign its mechanism predicted, and lost.
- Nothing else reaches |t| of 2 on more than one window.

Market series against forward equal-weight and BTC returns, non-overlapping samples:

- **Coinbase premium** is positive against BTC's 3-day return in all three windows (t +1.1, +2.9, +1.3). It is the only series with the same sign everywhere. M4 used its extreme tail as a gate and lost; the linear relationship is too weak to size on.
- **DVOL change and implied-minus-realised** are positive against 14-day equal-weight return on fit (t +2.5) and holdout (t +1.2 to +1.4) and not in 2022.
- Aggregate open interest, aggregate funding and stablecoin supply have no stable sign.

These are twelve features by three horizons by three windows. The number of cells above |t| of 2 is what chance would supply.

### What was built and what changed in the bots

- `data/vision.py`, `data/macro.py`: the history above, cached and point-in-time stamped.
- `bot/alt_data.py`: the collector now logs each per-coin feature and each market input **in the gate's own definition**, with perp symbol mapping, so the competition fortnight produces a forward log comparable row for row with these tables. `trades_on_it` stays false.
- The collector now runs on a **daemon thread**. A collection is about six HTTP calls per symbol at a 20-second timeout each, and it used to run inline in the cycle, so a slow venue could have stalled order management for minutes. `collect` now starts a worker when due and hands over each finished snapshot exactly once; an exception becomes a journalled `error` field, never a raise.
- No change to any book's signal, rank, sizing or ladder.

### Sources on the operator's list that were not tested, and why

| source | reason |
|---|---|
| Order-book depth | no free spot history; the futures `bookDepth` archive starts 2023 and depth is not the binding constraint under a 5 bps spread gate |
| Individual Binance trades | carry nothing the cached `taker_buy_quote` columns do not, and those are null at `#alpha-flow-declaration` |
| Hyperliquid | funding and OI for the same names as Binance on a shorter history |
| Dune, exchange flows, token unlocks, DEX | paid keys, or no point-in-time history for these 55 names |
| Google Trends, Reddit, social | not point-in-time: Trends rescales its whole history on every query, so any backtest on it leaks |

## live-validation-2026-09-23

Operator: "test the bots and strats on live data." Every deployed book was run through the live code path on the live bar, then compared with what the vectorised rule holds on the same live bars.

### The validation gate could not run

`gates/live_validation.py` still loaded `config/bot_a_4h.yaml`, deleted in the 2026-09 rename, never applied the momentum rank so it had never validated a ranked book, and probed for a `RuntimeError` guard that `bot/intents.py` replaced. It now runs every deployed book through `universe.select`, closed bars, the channel state, `rank_and_select`, `target_weights` and `Executor.prepare`, and checks each against the backtest: channel cells, the momentum rank against `gates.concentration.rank_score`, gross, passive limits, the spread gate, venue quantity step, notional. Nine books, nine passes.

**Its first rewrite produced a false alarm worth recording.** It reported Roostoo 18 bps off Binance at the median with 20 of 23 names materially off, which would halt books through the mirror kill switch. Three direct reads at the same moment gave **0.0 bps**. The gate had taken Roostoo quotes before validating nine books and compared them minutes later with fresh Binance prices. The harness, not the venue. It now re-reads the ticker immediately before the comparison.

### The defect: live channel state advanced one bar at a time and never caught up

`bot/strategy.evaluate` moved a persisted `held` flag forward using ONLY the latest bar. Any bar close the process did not see was lost for good: downtime, a crash and respawn, a book started mid-trend, a name that joined the universe after its breakout. The book then sat flat through a trend the backtest held, until the next fresh 20-bar high.

`bot/verify.signal_parity` could not see this, because it replays every bar in order, which is exactly what the live bot does not do.

Measured live on 2026-09-23 against the rule run over 300 live bars, dust excluded:

| book | rule holds | live holds (excluding dust) | missing | held but not in the rule's set |
|---|---|---|---|---|
| donchian_4h | 19 | 16 | BTC, ETH, PEPE | none |
| donchian_4h_cushion | 19 | 7 | 12 names | none |
| donchian_1h | 6 | 2 | ADA, TRUMP, UNI, XRP | none |
| momentum_top5_cushion | 5 | 4 | ARB, NEAR, PEPE, SUI | **ADA, WLD, XLM, about 20k dollars each** |
| alpha_flow | 3 | 2 | SUI, UNI | **ADA, 33k dollars** |

The last column is the same defect one step on: a ranked book that never saw most of the fired set ranked its top N from the few names it had, so it holds names the rule would have ranked out.

**The forward A/B pairs were measuring start times, not treatments.** `donchian_4h_cushion` held 7 names against its control's 16 because it was started later, not because of its cushion.

**Economically, over a fortnight, it is noise.** Scored on 14-day windows, a book that starts flat and enters only on fresh breakouts against one that starts holding what the rule holds: median delta **0.00pp** on fit and holdout for both `donchian_4h` and `momentum_top3_full`, P(>5%) within 0.011, P(>20%) within 0.010. Breakouts on 4h bars come often enough that a flat book catches up within a day or two. So this is a fidelity defect that corrupts forward evidence and restart behaviour, not a return lever, and no trial is added.

### The fix

`bot/strategy.replay_book` replays the backtest's own `signals.donchian.position` over the fetched matrix to get the state at the previous bar, then applies `evaluate` to the latest bar so `action` still reads enter, exit, hold or flat. `Bot.cycle` fetches `REPLAY_BARS = 150` bars and uses it at every bar close.

The window was measured, not chosen: replaying from flat over N bars against the full-history state at 400 random timestamps, 2023 onward, gave **zero mismatches at every N from 60 to 300 on 4h** (53,312 cells) and one mismatch in 54,079 at N=60 on 1h, zero from 100. 150 carries margin.

Any disagreement between the replayed and the persisted state at a bar close, other than a same-bar entry or exit, is journalled as `channel_state_resynced`, so a resync is visible rather than silent.

After the fix the gate's parity check covers 2,967 cells per 4h book with 0 mismatches, and every 4h book fires the same 19 names.

**Consequence at the next bar close after the restart:** books that were missing names buy them at that close, at a price later than the backtest's entry. That is the unavoidable cost of catching up, it is paid once, and it is the same cost a fresh book pays at the competition start.

### Smaller findings

- **Dust.** Sells rounded down to the venue step leave residues such as 0.0099999 AVAX, about 0.11 dollars, counted as holdings. Below `min_notional` so never traded; a comparison of holdings must exclude them.
- **RTK's `grep` wrapper returns "0 matches" for an alternation pattern** (`a|b`) that plain grep finds. Use `rtk proxy grep -E` when searching for more than one name.

### The biggest gap: the ranked books' edge sits in names live execution refuses

Found in the same live test. `PEPEUSDT` was refused 75 times across the fleet with `spread_exceeds_limit`. Its Roostoo tick is **20.6 bps**, and Roostoo quotes one tick wide, so its spread can never be under the 5 bps execution gate. The rule fires on it, the rank selects it, the order is refused, and the slot sits in cash until the next bar close, when it happens again.

`#spread` says spread was meant to be a **universe filter** at 5 bps. Neither the backtest universe (`gates.concentration.context`) nor the live one (`bot.universe.select`) applies it. Only execution does. So every gate in this repo scored these names at fee-only cost, and no live book can hold them.

The momentum rank concentrates on exactly these names. The filter removes only **0.2% to 0.4% of selected name-bars**, yet in the holdout it removes 23 distinct names while selected, including PEPE, BONK, FLOKI, SHIB, 1000CHEEMS, TRUMP, WIF, TAO, ARB, NEAR and ADA at their low-price moments.

Median 14-day return and P(>5%), vectorised, current tick size in bps at each bar's price:

| book | assumed by every gate (fee only) | + half tick per side | + full tick per side | + 2 ticks per side | tick-filtered universe | **live today** (refused slot idles) |
|---|---|---|---|---|---|---|
| momentum_top3_full, holdout | 3.12 / 0.467 | 2.96 / 0.464 | 2.74 / 0.453 | 2.35 / 0.441 | 1.41 / 0.428 | **1.20 / 0.420** |
| momentum_top3_full, fit | 4.10 / 0.476 | 3.92 / 0.474 | 3.77 / 0.470 | 3.42 / 0.466 | 4.08 / 0.477 | 4.17 / 0.477 |
| momentum_top5_4h, holdout | 1.28 / 0.370 | 1.16 / 0.366 | 0.98 / 0.366 | 0.74 / 0.358 | 0.75 / 0.347 | **0.69 / 0.344** |
| donchian_4h, holdout | 0.27 / 0.210 | 0.26 / 0.208 | 0.24 / 0.208 | 0.21 / 0.205 | 0.04 / 0.195 | **0.02 / 0.195** |

Three readings.

1. **The live ranked book is worth about 1.2% holdout median, not 3.1%.** Nearly two thirds of the headline number was earned in names the bot is not allowed to buy.
2. **Paying their spread is better than excluding them.** Even at two full ticks per side, which overstates the cost of a passive order at the touch, the book keeps 2.35% against 1.41% filtered. The fit window agrees on the direction for the paid-spread arms and shows no loss from filtering, so the effect is concentrated in 2025-26, when the meme names led.
3. **Which way to fix it is an execution-rule decision and is left to the operator.** The candidates: accept a one-tick quote regardless of its size in bps, since one tick is the venue's floor and cannot be an abnormal spread, and keep refusing anything wider than the larger of 5 bps and one tick; or apply the tick filter to the universe, so live matches a lower backtest exactly. The first also raises a fill question the backtest cannot answer: a buy on a one-tick-wide book cannot improve inside the touch, so it posts at the bid and fills only when the market comes to it, and an unfilled order is cancelled after 15 minutes and not retried until the next bar close.

Reproduce with `python3 -m gates.tick_universe`; `tick_bps = PairSpec.tick / close` at each bar, using the venue's current tick.

**Operator decision, 2026-09-23: trade them.** `Executor.prepare` now always accepts a one-tick quote, and still refuses any quote wider than both `max_spread_bps` and one tick, so an abnormal widening is refused exactly as before (ARB at two ticks, 9 bps, still is). A plan accepted only because it is one tick wide carries `wide_tick: true`.
A dry-run fill on such a plan is charged at the FAR side of the quote, not at the bot's own passive price, because a paper fill at the touch on a 20 bps tick would book the whole tick as profit on every round trip. That makes the paper books conservative relative to the passive order the venue will actually see, which matches the backtest's paid-spread arms.
`tests/test_bot_safety.py` covers the one-tick acceptance, the two-tick refusal, a tight name never being flagged, and the far-side paper fill.
**Still unmeasured, and only measurable with Roostoo keys:** how often a passive buy at the bid of a one-tick book fills inside the 15-minute timeout. An unfilled entry is not retried until the next bar close.

### The collector had been running once per 4h, not every 15 minutes

Found by checking the running process after restart: zero `alt_data` snapshots. `bot/alpha_flow_run.py` collected inside `compute_target`, and since booking was enabled on 2026-09-22 `Bot.cycle` calls `compute_target` only at a bar close. The collector declared at 900 seconds therefore ran once per 4h bar, and nothing in any log said so. Collection now happens in a `cycle` override after the base cycle, every cycle, throttled and threaded by `bot/alt_data.Collector`. The fourth instance of `CLAUDE.md`'s "a flag that changes WHEN a function is called" in this repo.

## lowtf-paper-bots

Operator instruction, 2026-09-23: "reset all bots and add lower timeframe paper bots."
Five paper bots added: `donchian_30m`, `donchian_15m`, `momentum_top3_1h`, `momentum_top3_30m`, `momentum_top3_15m`.
Each is the deployed rule with identical parameters **in bars** (20/10 channel, 40-bar momentum, top 3, full deployment, the 3% x 15% ladder), so it is the same rule on a faster clock and nothing was fitted.

They were measured before launch on the same basis as every other book since `#live-validation-2026-09-23`: 5 bps fee plus each coin's own tick per side, PIT top-30 universe carried to the fast clock at bar close. `gates/lowtf_paper_bots.py`, `results/lowtf_paper_bots.json`. Holdout median 14-day return, fit in brackets:

| bot | median | P(>5%) | worst | turnover per 14d | fee + tick drag per 14d |
|---|---|---|---|---|---|
| donchian_1h (existing) | +0.17 (+0.42) | 0.205 | -13.9 | 13.1x | 0.86% |
| donchian_30m | -0.45 (-0.84) | 0.168 | -12.4 | 26.0x | 1.72% |
| donchian_15m | -2.42 (-2.46) | 0.096 | -16.7 | 51.3x | 3.39% |
| momentum_top3_1h | -5.04 (+0.40) | 0.301 | -38.9 | 93.5x | 6.28% |
| momentum_top3_30m | -9.94 (-6.26) | 0.290 | -38.1 | 188.1x | 12.62% |
| momentum_top3_15m | **-21.32** (-21.37) | 0.112 | -50.4 | 384.1x | **25.85%** |

**All five fail, and the ranked ones fail by cost.** A 40-bar momentum rank re-sorts on every bar, so turnover doubles each time the clock halves, and at 15m the book pays a quarter of its capital every fortnight. The live bots' 25% drift band will suppress some of that churn, which the backtest does not model, so the live figures may come in less bad; they will not come in positive on this evidence. This is the repo's standing result that faster is worse (`CLAUDE.md`, "Faster is not better here"), now measured on the deployed books.

They run on paper only, as forward evidence, on explicit operator instruction. Never candidates, never promoted, nobody's control. Each config carries its backtest verdict in `meta` and a falsification line. Five trials added.

The 30m and 15m numbers use the 55-name 15m cache, which covers every Roostoo-tradable name that has been in the top 30; the 1h numbers use the full 264-name panel.

### Found on the first fresh start: a full-deployment book could not afford its last buy

Minutes after the reset, `momentum_top3_15m` placed three buys of about 33,330 dollars each and held two. The third, WLD, cost 33,326 plus the 5 bps fee against 33,311 of cash left. `apply_dry_fill` refused it silently, while the order journal had already recorded it as a `dry_run` fill. The book believed it had bought a name it did not hold, the blotter reconstructs from that journal, and a real venue would have rejected the same order for insufficient balance. It is also why the pre-reset `momentum_top3_full` sat at 0.68 gross on two names.

`Bot.cycle` now sends sells before buys and passes every buy through `Bot.fit_to_cash`, which shrinks it so notional plus fee fits the cash available, or skips it as `insufficient_cash` if what is left is under the venue minimum. A paper fill that is still refused is journalled as `dry_fill_refused` instead of vanishing. Full deployment therefore runs at about 0.9995 gross instead of 1.0, which no gate can distinguish.

**Open, live venues only:** on a real venue a sell is a resting limit order, so its cash arrives only when it fills. A rotation that sells A and buys B will buy less B than intended, and because a held name is never topped up while booking is on, B stays underweight until it exits. Dry run cannot show this; it needs Roostoo keys to measure.

The fleet was reset a second time at the same moment, on this code, so every book's record starts clean. The first reset's state is archived beside the pre-reset state.

## log-review-2026-09-23

Operator: "analyze the logs till now, the profits, logic gaps, what is going right, what is going wrong." Full write-up at `results/log_review_2026-09-23.md`, produced by the new `gates/log_review.py`, which reuses `bot.blotter.build` for round trips and adds benchmarks over the same hours, exposure-matched equal-weight returns, uptime, missed bar closes, booking effect and per-coin attribution.

The finding that outranks the rest: **the pre-reset books were offline 55% of their 60 hours** (33 to 34 hours of gaps, 8 or 9 of about 15 4h closes missed), because the Mac sleeps (`pmset` `sleep 1`, repeated sleep/wake through three nights). That is an operations problem, not a code one, and every missed close was also a trigger for the channel-state defect fixed at `#live-validation-2026-09-23`.

Every book lagged an equal-weight basket scaled to its own gross: channel books by about 1pp, momentum books by 5 to 10pp, with the momentum losses concentrated in ARB and ENA while the rally was led by NEAR, TAO, SUI and PEPE, the last of which no book could buy. None of this is a performance result: 60 hours, one regime, four defects.

Also fixed from the post-reset logs: RLUSD inside the testnet universe, because the stablecoin list existed twice and predated it. One list now, four stablecoins added, test `test_live_and_backtest_share_one_stablecoin_list_and_it_covers_rlusd`.

## competition-wf-outcome

Declaration `config/competition_wf.yaml`, harness `gates/competition_wf.py`, robustness `gates/lock_robustness.py`, artifacts `results/competition_wf.json` and `results/lock_robustness.json`. Ledger 985 -> 991 declared, plus 11 sensitivity rows excluded from the Sharpe family.

**The target was set from outside evidence before any number was computed.** Past Roostoo competitions: the IMC x Roostoo Labs top three finished +20.5%, +8.1% and +5.7%, and the SG vs HK round-one leader had +17%, with team numbers past 126. Third place at +5.7% puts the 20th per region near 0 to 3%. So qualifying needs a positive fortnight, and winning needs about +17 to 20%. The primary objective is P(14-day return > 2%); P(> 15%) is reported as the winning level.

**Every window is out of sample for its arm.** Each arm is one declared rule with nothing fitted, scored on every 14-day window starting at 00:00 UTC, in 2022, 2023-24 and 2025-26 separately, on an hourly simulator that reproduces the live cycle (4h selection, ladder, drift band, no top-up) with the fee plus each coin's tick per side and 10 bps plus tick on shorts. The simulator reproduced `gates.positioning_edges.simulate` to **0.0pp**, and the intrabar arm collapsed to the control exactly when its hourly triggers were switched off (leak check **0.0**).

| arm | P(>2%) 2022 / 23-24 / 25-26 | median | P(>15%) | worst | verdict |
|---|---|---|---|---|---|
| C0 momentum_top3_full | 0.36 / 0.57 / 0.53 | -0.73 / +4.43 / +2.91 | 0.08 / 0.27 / 0.22 | -31 / -28 / -29 | control |
| C1 donchian_4h | 0.12 / 0.42 / 0.34 | -0.54 / +0.87 / +0.34 | 0.00 / 0.04 / 0.03 | -4 / -5 / -9 | control |
| S1 short sleeve in bear regime | 0.37 / 0.53 / 0.47 | -2.39 / +3.36 / +1.06 | 0.10 / 0.23 / 0.19 | -27 / -31 / -35 | **fails** |
| S2 intrabar entry | 0.37 / 0.55 / 0.51 | -0.59 / +3.99 / +2.36 | 0.10 / 0.29 / 0.23 | -28 / -27 / -29 | **fails** |
| S3 channel ensemble | 0.33 / 0.57 / 0.48 | -0.63 / +4.87 / +1.14 | 0.10 / 0.28 / 0.22 | -21 / -21 / -37 | **fails** |
| **S4 target lock +5%, keep 0.3** | **0.56 / 0.69 / 0.68** | **+3.17 / +5.13 / +5.01** | 0.00 / 0.09 / 0.06 | -31 / -28 / -29 | **passes** |
| S5 half C0, half C1 | 0.30 / 0.53 / 0.49 | -0.49 / +2.76 / +1.84 | 0.01 / 0.15 / 0.12 | -18 / -17 / -18 | fails |
| WF monthly selection | 0.56 / 0.68 / 0.68 | +3.17 / +5.10 / +5.01 | | | picked S4 in 56 of 60 months; not independent evidence |

The short sleeve loses in every period, and its random-regime control does about as well as it does, so the regime flag carries nothing. The intrabar entry is not better in any period that matters. The ensemble cuts the worst window in 2022 and 2023-24 and then has the worst window of all in 2025-26.

**The target lock is robust, and it is not alpha.** It is a barrier on the qualification objective: most fortnights touch +5% at some point even when they do not finish there, and locking converts touches into finishes. Robustness, none of it used to choose:
- every lock level (3, 5, 7, 10%) and every retained exposure (0, 0.3, 0.5) raises P(>2%) in every period; the declared 5%/0.3 sits inside the plateau, not at its peak (3%/0.0 is higher, and was not chosen);
- at doubled tick costs it holds (2025-26: 0.669 against the control's 0.514);
- at six start hours the gain is the same to within 0.02;
- Screen 3 among qualifying windows is unchanged (medians 4.8 to 5.0, the composite's cap binds either way), so it does not cost the finalist ranking;
- the worst window is unchanged, because a window that never reaches +5% never locks.

**The price is the winning tail**: P(>15%) falls from 0.08/0.27/0.22 to 0.00/0.09/0.06. The lock maximises the chance of qualifying and gives up most of the chance of a +17% to +20% fortnight. Which of those the competition rewards more is the operator's call, and it turns on the region's actual cut.

### Forward test on the live feed

`config/momentum_top3_lock.yaml`: `momentum_top3_full` plus the lock, with a rehearsal window 2026-09-23T08:00Z to 2026-10-07T08:00Z, compared against the running `momentum_top3_full` from the same moment. It tests the mechanics that no backtest can: the window anchoring its starting equity once, the lock firing on the live equity, the forced de-risk passing the drift band, later entries being capped, and a restart inside the window remembering all of it (`lock_state` in the state file). `bot/lock.py`, `tests/test_target_lock.py`.

**Nothing is changed on the deployed books.** Whether the competition book runs the lock is a decision for the operator after the forward week.

## literature-edges-outcome

Declaration `config/literature_edges.yaml`, harness `gates/literature_edges.py`, artifact `results/literature_edges.json`. Ledger 1002 -> 1007. Screened from papers and practitioner posts for a stated mechanism, an hourly-or-longer horizon, point-in-time data, and no overlap with a dead family. Scored on the competition engine (`#competition-wf-outcome`) against `momentum_top3_full`, whose idle cash averages 36.8% since 2022, which is what the four overlays trade.

**All five fail. No new edge.**

| arm | source | P(14d > 2%) vs C0, by period | standalone evidence | why it fails |
|---|---|---|---|---|
| N1 BTC 22:00-00:00 UTC | SSRN 4081000, 2015-21 sample | 0.366/0.561/0.515 vs 0.361/0.571/0.525 | net per night -6.0, +0.2, **-6.5 bps (t -2.74)** | the published anomaly is gone after publication; 22:00 ranks 12th, 3rd and 17th of 24 start hours |
| N2 Monday Asia open | Concretum 2025 | 0.344/0.579/0.504 | -14, +15, **-37 bps** per Monday | Sunday-start ranks 2nd, 5th, 6th of 7 days; it was a property of a trend strategy's P&L, not of BTC drift |
| N3 ETF-flow momentum | SSRN 6592830, 2024-01 to 2025-04 | in paper 0.520 vs 0.501, **post-publication 0.542 vs 0.560** | +88 bps (t 1.98) in the paper's own period, **+29 bps (t 0.73) after it** | reproduces the paper in-sample and decays out of it; a permuted flow sign does as well (0.513, 0.549), so the gain was exposure |
| N4 trend-factor rank | Fieberg et al., JFQA | 0.264/0.501/0.489 | | the multi-horizon average ranks toward slow names and gives up the concentration that makes the tail, the declared failure mode |
| N5 liquidation-flush reversal | industry, no peer-reviewed source | 0.361/0.564/0.517, worst -35.5 vs -28.5 | 23 episodes in five years | too rare to matter, deepens the worst window, random triggers do as well |

**Diagnostic, BTC-to-alt lead-lag:** after a BTC move, alts underperform BTC slightly over the next 1 to 4 hours in 2022 and 2023-24 (corr -0.02 to -0.05, t about -2 to -2.7) and not at all in 2025-26 (t 0.2 to 0.3). No catch-up to trade, and what little there was has gone.

The pattern across the five is the same one this repo keeps finding: effects that were real in their authors' samples either decay after publication (N1, N3) or were never a property of price at this universe's liquidity (N2, N6), and the ones that change what the book holds cost it the concentration that produces its right tail (N4). The target lock (`#competition-wf-outcome`) remains the only change of any kind to pass on every period, and it is a change to the objective's shape, not a new signal.

## intraday-structure-outcome

Declaration `config/intraday_structure.yaml`, harnesses `gates/intraday_structure.py` (history) and `gates/live_structure.py` (live feed), artifacts `results/intraday_structure.json`, `results/intraday_structure_pairs.csv`, `results/live_structure.json`. Ledger 1007 -> 1010. Operator request: find hidden alphas on smaller time frames from the live feed and the literature, with correlation pairs and momentum named.
The 1h cache was topped up to 2026-09-23T04:00Z before the run (68 live names; the other 196 are delisted and stop where they stopped).

**All three arms fail. No new edge.**

| arm | source | result | why it fails |
|---|---|---|---|
| S1 intraday time-series momentum (00:00 UTC bar predicts the 23:00 bar, BTC, idle cash) | Shen, Urquhart and Wang 2022; Wen et al. 2022 | net per hold **-8.7, -6.3, -7.0 bps** (t -1.7, -2.7, -3.4); GROSS already negative at -3.7, -1.3, -2.0 bps | there is no first-hour momentum in the 24-hour market at hourly resolution; hour 0 ranks 16th, 15th and 3rd of 23 predictor hours |
| S2 cointegrated pairs, 1h, 12 most liquid names, Engle-Granger filter, entry \|z\| > 2.5 | Fil and Kristoufek 2020; Tadi and Witzany 2025 | 180 / 1,147 / 1,038 trades, gross **+9.0, -16.9, -0.8 bps**, net **-8.3, -34.1, -19.4 bps** (t -0.3, -3.9, -2.8) | spreads that pass a 30-day cointegration test do not revert: 48% of trades exit on the \|z\| > 5 stop and only 20% on reversion. The shifted-partner control is worse in 2022 and 2023-24 and slightly better in 2025-26, so there is no structure to harvest even before 30 bps of round-trip cost |
| S3 quiet-market gate on C0 (flat when 24h dispersion AND BTC 7-day vol are both below their 90-day 33rd percentile) | `#competition-oos-outcome` dispersion terciles | P(14d > 2%) 0.364 / 0.574 / **0.507** vs C0 0.361 / 0.571 / 0.525; median +0.23 / 4.35 / **2.50** vs -0.73 / 4.43 / 2.91 | helps 2022, costs 2025-26. The gate is flat 16% of the time in episodes of about 4 bars; the declared failure mode fired: compression precedes the breakouts the book earns on |

The S3 random-gate control (same flat fraction and episode length, 20 seeds) scores P(>2%) 0.354 / 0.544 / 0.483, so the real gate is better than random but not better than no gate.

**Diagnostic D1, alt hour-of-day.** No UTC hour moves the equal-weight pool, or the pool net of BTC, by 10 bps in any period, let alone all three. The most stable effect is **03:00 to 05:00 UTC, where the pool beats BTC by 1 to 4 bps an hour in every period** (t up to 2.8), the same Asian-morning window the BTC literature reports as weak for BTC. It is a real regularity and a quarter of one round trip. Recorded, not traded.

**Diagnostic D2, live 1m feed, 72 hours to 2026-09-23T05:10Z, 23 names.**
- BTC's 1-minute return against each alt's next minute: median correlation **-0.017**, a slight reversal, not a lead.
- After a BTC minute beyond 2 standard deviations, the median alt moves **+3.3 bps** in BTC's direction over the next 5 minutes, against a 10 bps round trip.
- Minute-of-hour absolute returns are highest in minutes 0 to 3, and quarter-hour minutes run 1.08x the others: the quarter-hour effect of arXiv:2607.09426 is visible on the live feed, and is a volatility effect worth about 0.5 bp of direction on its authors' own numbers.
- The first principal component explains 47.6% of 1-minute variance.

**Diagnostic D3, live correlation structure at the same time.** Average pairwise 30-day hourly correlation across the pool is **0.508, at the 4th percentile of the past year**: coins are unusually decorrelated, which is the high-dispersion condition `#competition-oos-outcome` finds the trend books do best (and worst) in. One large cluster (BTC, ETH, SOL, XRP, BNB, DOGE, ADA, SUI, LINK, AAVE, PEPE) and twelve singletons, including all three names the ranked book wants. TRX is the only low-beta name (0.17); every other alt runs a BTC beta of 0.8 to 1.9.

### A live execution leak found while monitoring

`momentum_top3_full` targeted ARB at a third of the book from the 2026-09-23T00:00 bar and holds none of it: the execution layer refused it 22 times across 12 books since the reset, every time for `spread_exceeds_limit` at 8.1 to 8.6 bps against `max_spread_bps` 5.0. ARB's quote is two ticks wide (tick 0.0001 at 0.249), so its half-spread is one tick, which is exactly what every backtest already charges. ARB rose 6.4% after the first refusal, about 2% of `momentum_top3_full`'s equity, and the book sat at 38% cash.
`#live-validation-2026-09-23` kept the two-tick refusal on the premise that a spread wider than one tick is an abnormal widening. Twenty-two refusals over six hours is ARB's normal spread, not an abnormal one. Whether to accept a spread up to two ticks, or to measure "abnormal" against each name's own trailing spread, is an execution-rule decision left to the operator, and no running book was changed.

### What this settles for smaller time frames

Five independent lines now agree: this repo's scalp, flow and RSI sweeps; arXiv:2608.21888; arXiv:2607.09426; and D1 and D2 here. Every regularity found below the 4h bar in liquid crypto (reversal, quarter-hour flow, hour-of-day drift, BTC-to-alt lag) is real and is 0.5 to 11 bps, against a 10 bps round trip. The only lever that has ever moved these books is which names they hold and how concentrated they are, at 4h.

## execution-gaps-2026-09-23

Operator request: fill the gaps `#intraday-structure-outcome` found, with the competition in mind. Operator decisions on 2026-09-23: accept quotes up to two ticks wide, and restart the whole fleet together on the fixes before the 08:00Z bar close so the lock rehearsal and its control both start on them. Seven defects, each reproduced from the live journals and captured by a failing test before it was fixed.

**1. A normal two-tick spread was refused.** ARB quotes two ticks wide (8.1 to 8.6 bps against `max_spread_bps` 5.0) and was refused 22 times across 12 books, while every backtest held it. The backtest charges one tick per side, which is exactly the half-spread of a two-tick quote, so a two-tick quote is inside the modelled cost. `bot/execution.NORMAL_SPREAD_TICKS = 2`: a quote up to two ticks is accepted whatever it is in bps and marked `wide_tick` when above the bps limit, so its paper fill pays the far side; three ticks or wider above 5 bps is still refused as abnormal. Tests: `test_a_two_tick_quote_is_accepted_and_filled_at_the_far_side`, `test_arb_at_its_normal_two_tick_spread_is_tradeable`, `test_a_three_tick_quote_wider_than_the_limit_is_still_refused` (which replaces the two-tick refusal test of `#live-validation-2026-09-23`).
The paper lab and the scalper keep their own stricter filters; neither is a candidate.

**2. A missed entry was not retried until the next bar close.** Between closes a booking book carried only its HELD weights forward, so any name the close wanted and did not get (refused, unfilled, cancelled after 15 minutes) stayed out for the whole bar: four hours on the 4h books. `bot/run.carry_target` now adds each such name back on every cycle, `bot/run.next_pending` keeps the list (replaced at each close, cleared on a halt, never containing a cold-start-suppressed entry), retries only while at least 1% of equity is cash, and the list persists across a restart inside the same bar. The pre-existing carry path is unchanged when nothing is pending. Tests: `tests/test_entry_retry.py`.

**3. A lot-step residue blocked re-entry.** An exit sells the holding rounded down to the lot step and leaves a residue (0.001 AAVE, about $0.15). When AAVE's channel re-entered at 03:00Z the booking ladder's never-top-up rule, `min(want, held)`, capped the new target at the residue's weight of 1.5e-06, so `donchian_15m` held nothing of a name its rule held. The same residue sat under BNB, ZEC and ENA in `donchian_15m` and UNI in `momentum_top3_15m`. `bot/portfolio.current_weights` now treats a holding below `DUST_NOTIONAL` = $10 (the fleet's `min_skim_notional`, the smallest trade it already considers worth making) as flat. Tests: `test_a_lot_step_residue_is_not_a_held_position`, `test_a_re_entry_over_a_dust_residue_gets_its_full_weight`.

**4. The resting-order guard could never match on Roostoo.** `Executor.send` refuses to re-send while an order rests, by looking the order's SYMBOL (`ARBUSDT`) up in the venue's pending PAIRS with the slash removed. Binance testnet's pair is `ARBUSDT` and matches; Roostoo's is `ARB/USD`, which becomes `ARBUSD` and never matches, so on Roostoo every cycle would have re-sent a resting order, and the retry of item 2 would have made that every minute. It now matches on the pair as well. Test: `test_a_resting_roostoo_order_is_matched_by_its_pair_not_its_symbol`. Live-only and invisible in dry run, like the defects of `#testnet-live`.

**Monitoring.** `gates/live_validation.py` now FAILS a book whose target the venue rule refuses (`no_target_refused_by_venue_rule`); before, ARB was listed under `skipped` and the book passed. `gates/execution_gaps.py` reads each book's journals and reports what its last close wanted against what it holds, the pending retries, and every skipped order by reason; `--watch N` streams one line per new gap. At 05:34Z before the fix it found 6 of 15 books with a gap: `momentum_top3_4h` and `momentum_top3_full` 33 points of gross short (ARB), `momentum_top5_cushion` 20 points, `donchian_4h_cushion` 5.5, `donchian_15m` (the AAVE residue), and `momentum_top3_lock`, which is empty only because it cold-started and waits for its first close.

**5. Target gross could exceed the 1.0 cap by rounding.** `portfolio.target_weights` rounded each weight to eight decimals, so 21 names at 1/21 summed to 1.00000005 and `live_validation` failed `gross_within_cap` on `donchian_4h`, `donchian_4h_cushion` and `donchian_30m` the first time more than 20 names fired together. Weights now round DOWN. Test: `test_gross_never_exceeds_the_cap_when_rounding_many_names`.

**6. A live book decided on a stale wallet (found by the gap monitor 20 minutes after the restart).** In live mode the wallet was read only at the END of a cycle. `testnet_live`'s retry placed a passive BTC buy at 06:00:29Z that filled 25 seconds later; the 06:01:03Z cycle saw no open order and still the pre-fill holdings, and bought the same $800 again. Both filled on Binance testnet (orders 5427053 and 5427263). Before the retry, intermediate cycles only ever placed booking SELLS, so the race had no buy to duplicate. A live cycle now reads the wallet first, before it marks or decides. Test: `test_a_live_cycle_reads_the_wallet_before_it_marks_or_decides`. Dry-run books never read a wallet and are unaffected.

**7. A live book's cash was read from the wrong stablecoin.** `bot/state.wallet_positions` counted any of the venue quote, USD or USDT as cash and kept whichever it saw last. The Binance testnet wallet holds 112,776 USDT, which the bot spends, and a seeded 10,000 USD, which it never touches; cash read 10,000.0 on every cycle, so each buy added its value to equity without taking it from cash. `testnet_live`'s equity rose by exactly the order size on every buy (06:01 and 06:02Z, the duplicate BTC buys of item 6) and fell on every sale, which is its -84% "return" and -12% "drawdown" in `gates.log_review`: an accounting artifact, not trading. Cash is now read in the venue's own quote only, taken from its pair names (`bot/run.venue_quote`: USDT on testnet, USD on Roostoo, both verified live), and other stablecoins are reported, not adopted. Tests: `test_cash_is_read_in_the_venue_quote_only`, `test_the_venue_quote_comes_from_the_venue_pairs`. The Roostoo competition account starts as pure USD, so it was exposed only if it ever held a second stablecoin.

None of the seven changes the signal, the ranking or the sizing rule. Each makes the live book hold what the backtest already holds.

## execution-timing-outcome

Declaration `config/execution_timing.yaml`, harness `gates/execution_timing.py`, artifacts `results/execution_timing.json` and `results/execution_timing_legs.parquet`, minute paths cached at `data/cache/exec_timing_1m.parquet`. Ledger 1010 -> 1011. The question: can the sub-4h structure of `#intraday-structure-outcome`, too small to trade as a signal, be harvested as execution by delaying the order a few minutes after the 4h close?

**Null, and the opposite sign.** 12,919 legs (C0 and `donchian_4h` entries and exits, 2023-01 to 2026-09, plus 4,004 random-sign control legs), each with the 60 one-minute closes after its 4h close. Mean benefit of delaying k minutes, bps (t):

| book, period | k=1 | k=3 | k=5 | k=15 | k=60 |
|---|---|---|---|---|---|
| momentum_top3_full 2023-24 | -1.1 (-2.7) | -1.0 | -1.0 | -1.1 | -4.4 |
| momentum_top3_full 2025-26 | -2.2 (-4.2) | -2.2 | -1.8 | -2.8 | -7.7 |
| donchian_4h 2023-24 | -3.4 (-8.6) | -4.3 | -3.7 | -4.7 | -8.0 |
| donchian_4h 2025-26 | -4.8 (-10.8) | -4.4 | -3.5 | -4.0 | -7.8 |
| random control 2025-26 | -0.1 | -0.5 | +0.1 | +0.7 | -1.4 |

Price keeps moving in the direction of the trade after a 4h close, most strongly after breakout ENTRIES (`donchian_4h` -4.8 to -6.5 bps at one minute, t -8 to -9), and most of it lands in the first minute. The declared failure mode fired: this is the book's own momentum, and every delay pays it. No delay is adopted.

**What it shows instead: the backtest's fill is optimistic by the close-to-order latency.** Every backtest fills at the 4h close, and no live bot can act before that close is known. At one minute that is 1.65 bps a leg on C0 and 4.1 bps on `donchian_4h`. At 53.6 legs a fortnight and a mean held weight of 0.458, C0 gives up about **0.4pp per fortnight** that its backtest never charged, against a 2.91% holdout median; `donchian_4h` about 0.13pp. Every relative comparison in this repo is unaffected because every arm fills the same way; the absolute levels are that much high. The only lever left is acting sooner, and the limit is the close itself.

**The latency the fleet actually ran at was far worse than one minute, and the cause was the machine, not the code.** Bar-close to signal, from the journals of 2026-09-22/23: median 486 s on `donchian_4h`, 491 s on C0, 550 s on `donchian_1h`, maximum about 50 minutes. The Mac was on battery and slept from 2026-09-22T21:04Z to 2026-09-23T04:04Z; the books cycled only in maintenance wakes every 15 to 30 minutes, with one 1.9-hour hole. `caffeinate` asserts `PreventUserIdleSystemSleep`, which does not hold a machine on battery. At the curve above, a five-minute delay costs 2 to 4 bps a leg before counting missed closes. **For the competition, uptime is worth more than any timing rule: run the competition book on EC2 (`deploy/README.md`) or on mains power with the lid open.**

## drawdown-brake-outcome

Operator: "we are facing drawdowns, what is the issue, what insights, how can we tune it to withstand those." Declaration `config/drawdown_brake.yaml`, harness `gates/drawdown_brake.py`, artifacts `results/drawdown_brake.json` and `results/drawdown_readout.json`. Ledger 1011 -> 1013.

### What the live drawdowns are

Since the reset (2026-09-22T20:48Z to 06:00Z) every book is up, +0.2% to +5.4%, with maximum drawdowns of 1.0% to 2.8%. The deepest are the concentrated momentum books, and they are happening now: from 03:30Z the pool fell 0.5% (BTC -0.2%) and the three-name books, at BTC betas of 1.5 to 1.9 (`#intraday-structure-outcome` D3), turned that into 1.5 to 2.8%. UNI (-2.8%) and NEAR carry most of it in `momentum_top3_full`, DOGE and UNI in `momentum_top3_1h`. The channel books, 16 to 22 names each, lose 1.1 to 1.4% spread thinly across all of them. **This is the book's beta and concentration doing what they are sized to do, not a defect.**
The larger live shortfall is against the market, not a drawdown: every 4h book trails an equal-weight basket by 2 to 6 points over the same hours, because ARB, the best name in the pool (+14.2%), was refused (`#execution-gaps-2026-09-23`), and the fleet was asleep for seven of the nine hours. The 15m and 30m books lead on these nine hours; their backtests lose to costs (`#lowtf-paper-bots`) and nine hours says nothing against that.
The pre-reset drawdowns (up to -7.0% on `momentum_top3_full`) are explained at `#log-review-2026-09-23`: 55% downtime and three defects since fixed.

### How deep a normal fortnight goes

`results/drawdown_readout.json`, the competition engine, existing arms, no new trial. 2025-26:

| book | median 14d | P(>2%) | P(>15%) | median in-window maxDD | P(maxDD < -15%) | worst window |
|---|---|---|---|---|---|---|
| momentum_top3_full | +2.91 | 0.525 | 0.224 | -12.1 | 0.303 | -28.5 |
| + target lock | +5.01 | 0.677 | 0.055 | -7.2 | 0.104 | -28.5 |
| momentum_top5 fixed + lock | +4.16 | 0.656 | 0.003 | -5.4 | 0.039 | -20.0 |
| donchian_4h | +0.35 | 0.340 | 0.029 | -3.5 | 0.000 | -8.7 |

A 1.5 to 2.8% drawdown is a small fraction of the ranked book's median fortnight. Three in ten fortnights see worse than -15% at some point.

### The drawdown brake: null

B1: once a window is 8% below its start, hold at most 0.5 gross for the rest of it. B2: the same on top of the lock. Both reconcile exactly with `windows_hourly` when off (max gap 0.0, after the reconciliation caught a cost-ordering defect in the harness's first version).

| 2025-26 | median | P(>2%) | P(>15%) | worst | P(maxDD < -15%) | fires |
|---|---|---|---|---|---|---|
| top3_full | +2.91 | 0.525 | 0.224 | -28.5 | 0.303 | |
| B1 | +1.19 | 0.475 | 0.201 | -24.7 | 0.243 | 36.5% of windows |
| top3 + lock | +5.01 | 0.677 | 0.055 | -28.5 | 0.104 | |
| B2 | +4.45 | 0.622 | 0.055 | -19.0 | 0.057 | 27.2% |

Both lower P(>2%) and the median in every period, so both fail. What they buy is real and is only the tail: the worst window improves 4 to 10 points. The random-hour control (the same cut, at a random hour in the same windows) keeps MORE of P(>2%) than the brake does (0.498 against 0.475 for B1; 0.645 against 0.622 for B2): **cutting right after an 8% loss is worse than cutting at random, because this book's in-window drawdowns tend to recover.** A third of all fortnights touch -8%, and most come back. The declared failure mode fired, and it is the same finding as `#derisk-ramp-protection-outcome` and the ratchet and take-profit nulls from the other side.

### What withstands drawdowns, on this evidence

- Not a stop on the book: every exposure cut tested after a loss (brake, ramp, ratchet) sells the recovery.
- The lock is the only rule that passed, and it halves the median drawdown (-12.1 to -7.2) by banking gains, not by cutting losses; it gives up P(>15%).
- Breadth is the only thing that cuts the worst window without a timing rule: top5 -20.0, `donchian_4h` -8.7, against -28.5, paid for in median return.
- The competition-level choice is therefore between the three rows of the readout, and it is the operator's: win (top3, no lock), qualify (top3 + lock), or survive (top5 + lock).

## decorrelated-directional-outcome

Operator: "find uncorrelated coins so we can define entry and exit based on directions, as we are currently losing to market beta." Declaration `config/decorrelated_directional.yaml`, harness `gates/decorrelated_directional.py`, artifact `results/decorrelated_directional.json`, live map `results/live_structure.json`. Ledger 1013 -> 1016.

**All three fail. Choosing coins for low correlation adds nothing that a random choice does not, and hedging beta out costs the return the competition ranks on.**

| 2025-26 | median 14d | P(>2%) | P(>15%) | worst | median maxDD | Screen 3 |
|---|---|---|---|---|---|---|
| C0 | +2.91 | 0.525 | 0.224 | -28.5 | -12.1 | 2.99 |
| U1 decorrelated third, 20/10 channel long AND short | -0.08 | 0.298 | 0.011 | -13.5 | -4.6 | -0.28 |
| U2 the same, long only | +0.55 | 0.339 | 0.015 | -10.3 | -3.3 | 2.75 |
| U3 C0 with a BTC short at its trailing beta | +1.75 | 0.485 | 0.102 | -13.8 | -6.5 | 3.04 |

- **U1 and U2 are indistinguishable from a random third of the pool** (random: P(>2%) 0.300 and 0.246 in 2025-26, median +0.11 and 0.00), so the low-correlation filter carries no information about which trends pay. What looks like safety, a shallower worst window, comes from holding 1/10 per name and, in U1, longs and shorts cancelling. The short leg does not add return in any period (U1 below U2 in two of three).
- **The decorrelated set is not uncorrelated.** Its mean 30-day correlation to BTC is 0.44 to 0.64 against the pool's 0.63 to 0.72, the ranking persists only moderately (Spearman 0.57 month to month), and the names most often in it in 2025-26 are TRX (67% of bars), ZEC, FORM, TUT, CRV and TON: a low-beta stablecoin-like chain plus thin mid-caps whose trends are small.
- **U3 is the interesting one and still fails.** Hedging C0's trailing beta (mean 0.53 to 0.79) halves the worst window (-28.5 to -13.8) and the median drawdown, keeps Screen 3 level (3.04 vs 2.99), and wins in 2022, the down year. But it lowers the median and P(>2%) in 2023-24 and 2025-26 and cuts P(>15%) from 0.22 to 0.10. That is `#beta-is-the-only-screen3-lever` measured directly: the return the book earns in up markets IS the beta.

**Live, 2026-09-23T07:13Z.** Only TRX is actually decorrelated (beta 0.17, 1-minute correlation 0.18) and it has no trend (40-bar momentum +2.6%). NEAR, ARB, PEPE, ZEC, AVAX and UNI show low minute-level correlation this week (0.21 to 0.37) while running 30-day BTC betas of 1.2 to 1.8: short-horizon independence is not fortnight-level independence.

**What "losing to market beta" is, on the live evidence.** Since the reset the market rose and the books under-held it (ARB refused, seven hours asleep), then a 0.5% dip hit three high-beta names; `#drawdown-brake-outcome`. Beta is what the book is paid for. The only tested way to shed its downside that keeps the median is the target lock. U3 plus the lock was not declared here and is not claimed.

## podcast-edges-outcome

Operator-supplied transcript of a crypto fund manager (mid-frequency, Hyperliquid) describing his edges, with the request to turn it into a high-Sharpe strategy with the best hyperparameters. Declaration `config/podcast_edges.yaml`, harness `gates/podcast_edges.py`, artifact `results/podcast_edges.json`. Ledger 1016 -> 1020. His own parameters were used and none were searched.

**None passes. The equal-weight stack is the closest, and it is the drawdown trade again.**

| 2025-26 | median 14d | P(>2%) | P(>15%) | worst | median maxDD | Screen 3 |
|---|---|---|---|---|---|---|
| C0 | +2.91 | 0.525 | 0.224 | -28.5 | -12.1 | 2.99 |
| P1 hold within 5 days of a 20-day high (daily) | +2.21 | 0.507 | 0.188 | -25.3 | -8.0 | 3.13 |
| P3 top third by market-adjusted volume growth | +1.31 | 0.460 | 0.094 | -21.0 | -8.3 | 2.40 |
| P2 thirds of C0, P1, P3 | +2.18 | 0.507 | 0.154 | **-17.0** | -8.7 | 3.11 |

- **P1** is a real trend rule: a 10-day-stale copy of it loses most of its edge (P(>2%) 0.449, median +0.73), and it beats C0 in 2022. It holds 4.2 names on average and trails C0's median in 2023-24 and 2025-26. It is the same family as the deployed channel on a slower clock, less concentrated, and pays for its shallower drawdown with the tail.
- **P3** carries information in 2023-24 and 2025-26 (the permuted control scores P(>2%) 0.473 and 0.415, the real rank 0.541 and 0.460) but less than momentum; it fails every period against C0.
- **P2** improves the worst window by 11.5 points and Screen 3 slightly, and loses median and P(>2%) in two of three periods. The claimed diversification does not arrive: hourly correlations between C0, P1 and P3 are 0.60 to 0.64, because all three are long-only large-cap books whose returns are mostly the same beta. The source's Sharpe 2 comes from combining signals that are long AND short, including carry, on a perp venue.
- **P4, shorting small-cap 20-day highs, was not tested on the first run.** Its set came out empty because the history held only Roostoo-listed and delisted names; that exposed the data gap recorded at `#universe-completeness`, and the re-run below tests it.

**Re-run on the complete universe (`#universe-completeness`), which is the authoritative result.** Same code, same parameters, 676 names. 2025-26 (2023-24 in brackets):

| | median 14d | P(>2%) | P(>15%) | worst |
|---|---|---|---|---|
| C0 | +2.43 (+2.30) | 0.514 (0.516) | 0.201 | -30.2 (-36.2) |
| P1 | +2.12 (**-0.07**) | 0.506 (0.437) | 0.147 | -25.3 |
| P3 | +0.77 (+2.34) | 0.433 (0.512) | 0.104 | -21.0 |
| P4 C0 plus small-cap pump shorts | +2.01 (+2.04) | 0.502 (0.503) | 0.188 | -34.0 (-38.1) |
| P2 thirds | +1.72 (+1.72) | 0.486 (0.492) | 0.118 | **-17.1** |

All four fail. P1 collapses in 2023-24 once the real top 30 is ranked. P4 now has a population (Roostoo names ranked 31 to 80), and the sleeve on its own is a loser: P(14d > 2%) of 0.04 to 0.07 and a worst fortnight of -39% in 2023-24, the squeeze the speaker himself warns about; random shorts on the same names do as well (P(>2%) 0.505 against 0.502). The stack still buys a shallower worst window with median, and its books still correlate 0.59 to 0.65.

What the transcript confirms rather than adds: big beat small (the pool rule), trend works on the top decile and inverts below it, equal weight is hard to beat, fancy construction is fragile, and signals that wiggle too much need better execution than a daily or 4h book has. The edges it describes that this book cannot use are carry (no funding on Roostoo spot or Roostoo shorts), small-cap and new-listing shorts (Roostoo lists 43 names ranked 31 to 200 by Binance volume today, but none has point-in-time history here yet), and venue-specific inefficiencies.

## universe-completeness

**The research universe was not the universe the live bot ranks, and the deployed book's recorded returns were overstated because of it.**

`data/universe.working_set` held Roostoo's tradable names plus every DELISTED Binance USDT name, and nothing else. The live bot (`bot/universe.select`) ranks the whole live Binance USDT market by 30-day median dollar volume, takes the top 30 and trades the Roostoo intersection. So every live name Roostoo does not list, 431 of Binance's 496 USDT pairs on 2026-09-23, including BCH (#9 by volume), DASH (#27), INJ, TIA, ETC and OP, was absent from history, and in every backtest the Roostoo names ranked higher than they would have against the real market. Found while the small-cap sleeve of `#podcast-edges-outcome` came out empty.

Fixed 2026-09-23: 412 of the 417 missing non-leveraged, non-stable live names downloaded at 1h from the archive (5 had no archive: AGPUB, AMCB, CYPHB, EWYB, XVS), the 1h panel, the daily panel and every `flow_*` panel rebuilt at 676 names, and `working_set` now returns tradable, delisted and live names (test `test_the_research_universe_includes_live_names_that_roostoo_does_not_list`). The previous derived caches are kept at `data/cache/_pre_universe_fix/` so every earlier number remains reproducible. Artifact `results/universe_completeness.json`.

The same books on the complete universe (median 14d, P(>2%), worst window):

| book | 2022 | 2023-24 | 2025-26 |
|---|---|---|---|
| momentum_top3_full, before | -0.73 / 0.361 / -31.1 | +4.43 / 0.571 / -27.8 | +2.91 / 0.525 / -28.5 |
| momentum_top3_full, complete | -1.18 / 0.347 / -31.1 | **+2.30** / 0.516 / **-36.2** | **+2.43** / 0.514 / -30.2 |
| + target lock, complete | +2.82 / 0.548 / -31.1 | +4.45 / 0.650 / -36.2 | +4.75 / **0.674** / -23.4 |
| donchian_4h, complete | -0.59 / 0.119 / -3.5 | +0.93 / 0.370 / -7.5 | -0.04 / 0.305 / -8.0 |

- The ranked book's edge survives and is smaller: its 2023-24 median halves and its worst window deepens by 8 points.
- The target lock's advantage survives almost unchanged (P(>2%) 0.674 against 0.677 before), so on corrected data it is the largest single lever this repo has, not one among several.
- The pool held 6.2, 13.6 and 15.6 tradable names a bar in 2022, 2023-24 and 2025-26: in 2022 most of the real top 30 was not on Roostoo.
- **Every relative verdict recorded before this date was measured like for like on the same (incomplete) data and stands as a comparison. No absolute return level recorded before this date should be quoted without this correction.** The two that matter most are `#competition-wf-outcome` (the lock) and `#competition-book-selection`, whose ordering is unchanged here.

## short-paper-books

The venue-short plumbing and the two long/short paper books declared in `config/short_paper_books.yaml` on 2026-09-23, at the operator's request after `#competition-wf-outcome` showed the S1 short sleeve failing all three periods.
Shorts go through `/v6/short_open`, `/v6/short_close` and `/v6/short_positions` (`venue/roostoo.py`), cost 0.1% of position value per side with no maker discount (`#plan-correction-shorting`), and are never topped up or laddered (`bot/booking.py`).
`bot/portfolio.py` fills only the slots the longs leave free with shorts ranked by most negative 40-bar momentum, under the BTC-below-180-bar-mean regime; `signals/donchian.py` and `gates/short_paper_books.py` share one breakdown implementation so the book and its backtest cannot drift apart.
Status on 2026-09-23: the backtest in `gates/short_paper_books.py` has not been run and `momentum_top3_ls` and `donchian_4h_ls` never started; the operator stopped the whole fleet the same day (`#ml-mvp-declaration`).
Whether short collateral also appears under the USD lock balance is unverified until Roostoo keys arrive; `gates/short_smoke.py` checks it before any live short.

## ml-mvp-declaration

Declared 2026-09-23, before any number was computed, from `ML_RESEARCH_PLAN.md`; the frozen parameters are `config/ml_mvp.yaml`.
The operator stopped the whole fleet the same day so the bots can be modified after this research.
The model is one global Ridge regression on nine features (4h, 1d and 7d return, 7d volatility, dollar-volume change, 1d taker imbalance, BTC and ETH 1d return, breadth), each cross-sectionally ranked at the decision time, predicting the next-12h return minus the universe mean, divided by the decision-time volatility.
The universe is the daily point-in-time top 30 Binance USDT coins by prior 30-day median dollar volume with 90 days of history, stablecoins and leveraged tokens excluded, drawn from all 676 names (`#universe-completeness`).
Decisions are taken at 4h closes every 12h and filled at the close of the next 1h bar, so every simulated fill is one hour after the information it uses.
The simulator is new (`ml_research/mvp.py`), drift-aware, and charges the fee, half the tick spread and 2 bps slippage on every traded notional; it does not reuse `portfolio/backtest.py`.
Five expanding folds score 2024 H2 to 2026 Q3, each with the prior six months choosing the Ridge penalty; all five are development evidence because this repo has studied those dates.
The decision rule, the random-score nonsense control and the failure mode are written in the config and are not moved after the run.

## ml-mvp-outcome

**Null. Both ML arms fail the rule declared at `#ml-mvp-declaration`, so LightGBM is not run.**
Artifacts: `results/ml_mvp/report.md`, `results/ml_mvp/report.json`, `results/ml_mvp/experiments.jsonl`; 2 trials added to `config/trials.yaml`.

| arm | pooled net Sharpe | momentum control | Sharpe wins | fold log excess vs momentum | return at 2x costs by fold |
|---|---|---|---|---|---|
| ridge_long | -0.38 | -0.30 | 3/5 | -0.014, +0.010, +0.037, -0.070, +0.014 | -2.6%, -17.9%, -10.9%, -27.7%, +9.1% |
| ridge_long_short | -0.77 | -0.30 | 2/5 | -0.021, -0.066, +0.029, -0.092, +0.003 | -9.7%, -28.3%, -17.9%, -33.4%, +6.8% |

- **The model ranks, and the book does not monetise the rank.** Rank IC against the next-12h relative return is +0.051, +0.008, +0.076, +0.070, +0.076 (t 3.2 to 4.3 in four of five folds), but the quintile spread lives in the BOTTOM quintile (2026 Q3: -45 bps against +8 bps for the top), so a five-name long book collects little of it and two shorts cannot carry 20 bps round trips.
- **It relearns momentum.** Every fold's largest coefficients are +7d return and -7d volatility, with a small negative 4h-return (last-bar reversal) term; the long book overlaps the 7-day momentum control and adds 30 to 70% more turnover.
- **The long/short arm is worse than long-only in four of five folds**, the same failure S1 met at `#competition-wf-outcome`.
- **Negative control behaves.** Random scores through the same construction score median net Sharpe -1.09, -2.82, -3.46, -4.76, -0.02; both arms beat it in every fold, so the simulator is not handing out returns.
- **Reconciliation.** `btc_hold` in the new simulator returns +50.04% in 2024 H2 against +49.74% from raw BTC closes over the same span; the gap is the one-hour fill lag and one entry cost. `tests/test_ml_mvp.py` checks hold, drift, short, turnover and look-ahead arithmetic on synthetic data.
- **Universe defect found and fixed before the verdict above.** The repo's stablecoin list misses `UUSDT` (0.5% annual vol), `KGSTUSDT`, gold (`XAUTUSDT`), `WBTCUSDT`, `USDSBUSDT` and every Binance tokenized equity (a `B` suffix, listed from 2026-06-11, `#tokenized-stocks`). The first run admitted them; `UUSDT` drew a 20% inverse-vol weight. The fix changed only 2026 H1 and Q3; the table is the corrected run and both runs fail. The same day `data/universe.STABLES` gained the five non-equity names; none is listed on Roostoo, but each took a slot in the Binance-wide top-30 ranking the bots trade the intersection of. Tokenized equities in that ranking are still unhandled on the bot side.
- **Sizing context.** The declared 15% volatility target holds about 0.2 to 0.3 gross in crypto, which is why every book's absolute return is small; BTC hold beats every sized book in rising folds. This is a research sizing, not a competition sizing.

## book-diagnosis-2026-09-23

Operator request, 2026-09-23: keep only the most successful books, diagnose where they win and lose, and find how to use both long and short sides on lower timeframes.
Harness `gates/book_diagnosis.py` on the `#competition-wf-outcome` engine, artifact `results/book_diagnosis.json`; diagnosis only, no trial.
Contributions below are summed hourly weight times return in percentage points, not compounded.

**Kept:** `momentum_top3_full` (the return engine), `momentum_top3_lock` (the only arm that passed every period) and `donchian_4h` (the shallow-drawdown book); `testnet_live` stays as execution evidence.
**Retired from the fleet:** both cushions, `donchian_1h`, `momentum_top5_4h`, `momentum_top3_4h`, the five lower-timeframe books (`#lowtf-paper-bots`, all fail by cost) and the two long/short books (`#short-paper-books-outcome`).

Where `momentum_top3_full` wins and loses (2022 / 2023-24 / 2025-26):
- **It is a BTC-beta book.** Fortnights when BTC falls more than 10%: median -8.0 / -8.4 / -1.6%; when BTC rises more than 10%: +10.6 / +15.8 / +14.6%. Window beta to BTC's 14-day return 0.56 / 1.12 / 0.44.
- **All the money is in trades held 3 to 7 days**: +97 / +367 / +319 pp. **Trades closed inside a day lose** -112 / -234 / -214 pp, and they are 53 / 65 / 67% of all trades. They are failed breakouts and rank churn; which breakout fails is not known at entry.
- **Exits:** channel exits win 25 / 26 / 22% of the time, rotations 69 / 56 / 54%. Win rate is 42 to 44% with an average win of +4.5 to +5.3% against an average loss of -2.5 to -3.0%: a trend book that lives on its payoff ratio.
- **Cost:** 17.8 / 61.8 / 59.1 pp of fee and tick, about a fifth of gross in the up periods.
- **Concentration:** in 2025-26 five names made 86% of net, ZEC alone 82.6 pp; wide-tick names made 35% (`#live-validation-2026-09-23`). The 2025-26 edge rests on very few coins, and coin-level edge does not persist (`#coin-selection-does-not-persist`).
- **Idle capital:** mean gross 0.50 / 0.66 / 0.66.
- **Hour of day:** no hour moves the book beyond about ±9 bps, which is noise (`#intraday-structure-outcome`).

`donchian_4h` is the same trend engine at 1/20 per name: beta 0.09 to 0.27, worst window -3.5 to -8.1%, median fortnight -0.6 / +0.9 / 0.0%. It never loses much and never wins the competition.

**Forward drift from the 4h close, flagged names against the pool (bps, bull / bear BTC regime):**
- Ranked holdings: +28 / +33 / +22 at 24h in bull hours; this is the long edge.
- Fresh breakdowns, the short-side mirror of the entry: -5 / +7 / +5 at 24h in bull, -5 / 0 / -7 in bear. **No short edge at the rule's own signal.**
- Bottom-3 momentum in bull hours: -35 / -18 / -18 at 24h against the pool, the only short-side pattern consistent across all three periods, but it is relative: in absolute terms it rose +20 bps in 2023-24.
- **At a 1h horizon every family drifts -8 to +18 bps**, against a round trip of 10 bps plus tick on spot and 20 bps plus tick on shorts. The signals pay out over one to three days, which is why every faster clock has lost by cost.

## short-paper-books-outcome

`gates/short_paper_books.py`, artifact `results/short_paper_books.json`, run 2026-09-23 on the complete universe. The shared breakdown function reproduced the inline loop with 0 cell mismatches.
**D1 (donchian_4h plus the bear-regime breakdown short sleeve) fails**: median -0.26 / +0.96 / -0.28 against C1's -0.59 / +0.93 / +0.02, worst window -7.6 / -16.5 / -12.3 against -3.5 / -7.5 / -8.1, and its random-regime control matches it (P(>2%) 0.197 / 0.358 / 0.332 against 0.20 / 0.40 / 0.32).
S1 re-scored on the complete universe also fails again: median -2.44 / +1.54 / +0.63 against C0's -1.18 / +2.30 / +2.24.
Both `_ls` books are retired without ever having started.

## weak-short-bull-outcome

Declaration `config/weak_short_bull.yaml`, chosen AFTER the forward-drift read in `#book-diagnosis-2026-09-23`, so no period is out of sample for the choice. Harness `gates/weak_short_bull.py`, artifact `results/weak_short_bull.json`. One trial.
W1 shorts the pool's weakest 40-bar momentum names into the ranked book's free slots while BTC is above its 180-bar mean; shorts are held on 14% of bars.

| | median 2022 / 23-24 / 25-26 | P(>2%) | P(>15%) | worst |
|---|---|---|---|---|
| C0 momentum_top3_full | -1.18 / +2.30 / +2.24 | 0.35 / 0.52 / 0.51 | 0.09 / 0.21 / 0.20 | -31.1 / -36.2 / -28.3 |
| W1 | +1.40 / +1.44 / +3.05 | 0.47 / 0.48 / 0.53 | 0.09 / 0.17 / 0.20 | -19.3 / -27.5 / -32.5 |
| W1 random shorts, 20 seeds | +0.16 / +0.45 / +1.81 | 0.41 / 0.45 / 0.50 | | |

**Fails**: it loses median and P(>2%) in 2023-24, the strongest bull run, exactly the declared failure mode (laggards rise in absolute terms when everything rises).
It helps 2022 and 2025-26 and cuts the worst window in two periods, but random shorts in the same slots recover about half the 2022 gain, so much of that is simply less net long exposure, the same thing the lock does more cheaply.
No lower-timeframe arm was declared: the 1h drift above cannot pay a round trip.

## topdown-ls-declaration

Declared 2026-09-23 before any number was computed; frozen parameters `config/topdown_ls.yaml`, shared rule `signals/topdown.py`.
Operator request: long the up momentum, short the down momentum, top down, with position sizing, take profits and a heatmap of the Roostoo universe.
Layer 1, market: breadth is the share of the top-30 pool with positive 40-bar momentum; bull when breadth is at least 60% and BTC is above its 180-bar mean, bear when breadth is at most 40% and BTC is below it, neutral otherwise.
Layer 2, side budgets: bull 1.0 long and no shorts; neutral 0.6 long and 0.3 short; bear no longs and 0.6 short, less than the long budget because shorts cost twice the fee and squeeze.
Layer 3, coins: up to 3 longs from live 20/10 Donchian breakouts with positive momentum, strongest first; up to 3 shorts from live 20/10 breakdowns with negative momentum, weakest first.
Layer 4, sizing: inverse 42-bar volatility within each side, at most 0.40 per name, 1.0 gross.
Layer 5, exits and take profit: a name leaves when its channel exits, it drops out of its side's top 3, or its side's budget goes to zero; the deployed 3% x 15% skim ladder runs on both sides (a short covers 15% each time price falls 3% from its reference).
Ablations T1_long (no shorts), T1_equal (equal weight) and T1_noTP (no ladder) isolate each layer; the nonsense control block-shuffles the regime.
Prior evidence against it is written in the config: every short sleeve here has failed and take-profit targets are a dead family.

## topdown-ls-outcome

Harness `gates/topdown_ls.py`, artifact `results/topdown_ls.json`, declaration `#topdown-ls-declaration`.
The signed-weight engine reproduced `gates.competition_wf.book_hourly` on C0 to 0.0 per hour before any arm was read.

| arm | median 2022 / 23-24 / 25-26 | P(>2%) | P(>15%) | worst | mean gross |
|---|---|---|---|---|---|
| C0 momentum_top3_full | -1.18 / +2.30 / +2.24 | 0.35 / 0.52 / 0.51 | 0.09 / 0.21 / 0.20 | -31.1 / -36.2 / -28.3 | 0.50 / 0.66 / 0.66 |
| T1 top-down long/short | -0.31 / +0.56 / -1.94 | 0.36 / 0.42 / 0.31 | 0.04 / 0.12 / 0.04 | -12.6 / -22.1 / -24.0 | 0.43 / 0.57 / 0.56 |
| T1_long, no shorts | -0.55 / +0.92 / -0.93 | 0.24 / 0.44 / 0.29 | 0.04 / 0.13 / 0.04 | -10.9 / -21.8 / -22.2 | 0.24 / 0.40 / 0.33 |
| T1_equal, equal weight | -0.42 / +0.70 / -1.50 | 0.35 / 0.46 / 0.33 | 0.05 / 0.13 / 0.07 | -13.3 / -24.3 / -25.5 | |
| T1_noTP, no ladder | -0.36 / +0.88 / -2.43 | 0.39 / 0.46 / 0.34 | 0.10 / 0.16 / 0.09 | -13.5 / -26.1 / -27.0 | |
| T1 with shuffled regime, 20 seeds | -0.04 / -0.63 / -0.69 | 0.36 / 0.36 / 0.35 | | | |

**Fails.** It loses median and P(>2%) to C0 in 2023-24 and 2025-26, and in 2025-26 the shuffled regime does better than the real one.
What each layer did:
- **The regime layer is the main cost.** It spends 34% of the time in bear and 36% in neutral, where it cuts or removes the longs; `#book-diagnosis-2026-09-23` found C0 made most of its 2025-26 money while BTC was below its mean. Without shorts the gated book holds 0.24 to 0.40 gross and trails C0 everywhere.
- **Shorts** raise P(>2%) over the long-only gated book in 2022 (0.36 against 0.24) and slightly in 2025-26, and cost median in 2023-24 and 2025-26. They are on in 50 to 63% of bars.
- **Inverse-volatility sizing** is worse than equal weight in every period: it tilts to the calm names, and the momentum edge sits in the volatile ones.
- **The ladder** (take profit) trims the right tail (P(>15%) 0.04 to 0.12 against 0.10 to 0.16 without it) and helps median only in 2025-26.
- **What it does buy is a shallower worst fortnight**: -12.6 / -22.1 / -24.0 against -31.1 / -36.2 / -28.3.

It runs as the dry-run paper book `topdown_ls` (`bot/topdown_run.py`) on operator instruction; it is not a competition candidate.
The heatmap at `/heatmap` on the dashboard (`bot/heatmap.py`) shows every Roostoo crypto listing with the same regime, budgets and picks the book uses.

## lowtf-5m-paper-bots

Operator instruction, 2026-09-23: keep 5m, 15m, 30m and 1h books running to confirm a short-term bot for trading volume and short-frame returns.
The six books of `#lowtf-paper-bots` are restarted from 100,000 beside the three 4h books, and two 5m books are added: `donchian_5m` and `momentum_top3_5m`, the same rules with identical parameters in bars.
The 5m books are **not backtested**: the 5m cache holds five symbols, not a cross-section. Every slower clock of both rules failed by cost, and turnover roughly doubles each time the clock halves, so the prior is a loss.
All eight are paper forward evidence, never candidates. Each 5m config states its falsification: below its 15m sibling over the same 14 live days means the faster clock only added cost.
The 4h books' first entries, held back by the restart safety rule (`#cold-start-chases-the-bar`), were queued once as pending entries on the operator's instruction so they fill at the next cycle through the existing retry path (`#execution-gaps-2026-09-23`), at a mid-bar price.

## lowtf-shorts

Operator instruction, 2026-09-23 ~17:15Z: add shorting to the eight short-term paper books (`#lowtf-5m-paper-bots`).
Each config gains the S1 short block, unchanged except that it runs on the book's own clock: while BTC is below its 180-bar mean, 20-bar breakdowns whose long channel is not live fill the slots the longs leave free, weakest 40-bar momentum first, and close above the prior 10-bar high.
Shorts are laddered (`booking.shorts: true`, cover 15% every 3% fall) and never topped up; 0.1% per side on Roostoo.
Evidence against it, recorded rather than hidden: the same sleeve failed on the 4h books (`#competition-wf-outcome`, `#short-paper-books-outcome`), breakdowns showed no forward edge at any horizon (`#book-diagnosis-2026-09-23`), and at 1h and faster the drift is below the 20 bps short round trip. On the 1h/30m/15m/5m clocks the 180-bar regime spans 7.5 days, 3.75 days, 45 hours and 15 hours.
The books keep their state across the change, so the journal records `config_changed_mid_run`; readings before about 17:15Z on 2026-09-23 are long-only.
Paper forward evidence only.

## lowtf-breadth-shorts-declaration

Operator choice, 2026-09-23 ~17:35Z, after TRUMP (-9%) and LINK (-5%) were not shorted by every short-term book: replace the S1 sleeve on the eight short-term books with a breadth switch and dedicated short slots. Declared before any number was computed.
**Switch:** shorts are allowed while fewer than 40% of the tradable pool have positive 40-bar momentum on the book's own clock (replacing BTC below its 180-bar mean, which on 1h bars needs a 7.5-day turn).
**Slots:** shorts get their own slots, 3 on the momentum books and 20 on the Donchian books, instead of the slots the longs leave free; the gross cap of 1.0 scales both sides together.
**Candidates:** names in a live 20-bar breakdown, not in a live long channel, with negative 40-bar momentum, weakest first. Exit, 0.1% fee, never topped up and the 3%/15% ladder are unchanged.
Mechanism: in a broad sell-off most coins trend down together for hours, and a short book collects that drift while the long book is empty. Failure mode: the same as every earlier short sleeve here, fast rebounds and a 20 bps round trip against drift that `#book-diagnosis-2026-09-23` measured at under 18 bps in the first hour.
Scored on the `#lowtf-paper-bots` harness (`gates/lowtf_breadth_shorts.py`) against the long-only rule on the same clock, 2023-24 fit and 2025-26 holdout, no ladder in either arm; nonsense control: the breadth switch block-shuffled. Paper forward evidence whatever the result, on operator instruction.

## lowtf-breadth-shorts-outcome

Harness `gates/lowtf_breadth_shorts.py`, artifact `results/lowtf_breadth_shorts.json`; declaration `#lowtf-breadth-shorts-declaration`. Median 14-day return, long-only -> with breadth shorts (worst window in brackets):

| book | fit 2023-24 | holdout 2025-26 | shuffled switch, holdout | cost drag per 14d with shorts |
|---|---|---|---|---|
| donchian 1h | +0.17 -> -2.09 | +0.09 (-13.7) -> +0.36 (-27.8) | +0.01 | 2.4% |
| donchian 30m | -0.81 -> -4.93 | -0.68 -> -3.37 | -2.63 | 4.8% |
| donchian 15m | -2.36 -> -8.90 | -2.49 -> -8.79 | -6.43 | 9.6% |
| momentum 1h | -0.90 -> -8.35 | -4.99 -> -8.05 | -8.02 | 11.0% |
| momentum 30m | -7.24 -> -20.69 | -10.88 -> -17.59 | -15.88 | 21.8% |
| momentum 15m | -20.41 -> -37.56 | -23.05 -> -36.20 | -32.76 | 44.7% |

**Fails on every book in the fit period and on five of six in the holdout.** The one holdout gain (donchian 1h, +0.27pp) doubles the worst window and reverses in the fit.
The switch is on 44% of the time, so shorts roughly double turnover, and the drag column is what they cost. The shuffled switch loses less than the real one on four books, so the breadth timing adds nothing either.
The long-only arm reproduced the recorded `#lowtf-paper-bots` holdout medians to within 0.07-0.23pp on the Donchian books and 0.06-1.73pp on the momentum books (the 15m momentum book drifts most; the caches were rebuilt at `#universe-completeness` after that record), so the comparison is like for like within each row.
The 5m books were not scorable (no 5m cross-section). All eight books keep running on paper on operator instruction.

## lowtf-contenders-declaration

Operator choice, 2026-09-23 ~18:20Z, after the short-term books held 6 names at 16.7% (momentum 5m) and 12 to 18 names at 5% (Donchian): hold only the strongest contenders, sized by strength. Declared before any number was computed.
**Rule (`signals/contenders.py`, shared by backtest and live):** candidates are live 20/10 breakouts with positive 40-bar momentum (long) and, while fewer than 40% of the pool have positive momentum (`#lowtf-breadth-shorts-declaration`), live 20-bar breakdowns with negative momentum and no live long channel (short). All candidates are ranked together by the size of their 40-bar momentum; the 3 largest are held, each weighted in proportion to that size, at most 50% per coin, excess spread over the others, gross at most 1.0.
Exits, the 3%/15% ladder on both sides, never topping up and costs are unchanged.
It replaces the rule on `momentum_top3_1h/30m/15m/5m`; the four short-term Donchian books are retired because under this rule they would be the same book.
Mechanism: the strongest trends carry the momentum edge (`#book-diagnosis-2026-09-23`: top-5 names made 86% of net), so concentrating on them and sizing by strength should keep the edge while cutting the weak marginal names that mostly pay costs. Failure mode: concentration trades median against tail on this repo (`#max-return-levers-outcome`: top 2 cut the median, top 1 turned negative), strength-weighting leans into the most extended moves, and on fast clocks the ranking reshuffles every bar.
Scored with `gates/lowtf_contenders.py` on the `#lowtf-paper-bots` harness against the long-only momentum rule and the breadth-short rule on the same clock; nonsense control: the same selection with sizes drawn at random. Paper forward evidence whatever the result.

## lowtf-contenders-outcome

`gates/lowtf_contenders.py`, `results/lowtf_contenders.json`; declaration `#lowtf-contenders-declaration`. Median 14-day return (fit 2023-24 / holdout 2025-26):

| clock | long-only momentum | breadth shorts, own slots | top-3 contenders by strength | random sizes, same names | contenders cost drag per 14d |
|---|---|---|---|---|---|
| 1h | -0.90 / -4.99 | -8.35 / -8.05 | -9.81 / -9.69 | holdout -15.93 | 11.3% |
| 30m | -7.24 / -10.88 | -20.69 / -17.59 | -22.52 / -18.18 | holdout -29.29 | 22.7% |
| 15m | -20.41 / -23.05 | -37.56 / -36.20 | -38.99 / -37.60 | holdout -53.71 | 46.8% |

**Fails against the long-only rule on every clock and period**, and is marginally worse than the breadth-short rule it replaced. It holds 2.7 names at 0.92 gross on average.
**Sizing by strength does carry information**: random sizes over the same names lose 6 to 16 points more, so the strongest trends are the better bets. The loss comes from the short side and the fast clock, not from the concentration.
Live note: a held position is never topped up, so a name already held at a small weight keeps it even when its strength now calls for more (momentum_top3_5m held ZEC at -0.168 against a -0.372 target at 18:20Z). Declared unchanged, as on every book.
The four momentum short-term books run the rule on paper from 2026-09-23 ~18:20Z; the four short-term Donchian books are retired (`live/_archive/retired-lowtf-donchian-20260923/`).

## lowtf-exhaustion-declaration

Operator observation, 2026-09-23 ~18:30Z: the short-term books short coins that already look stretched and may reverse; confirm shorts by the probability they fall further. Declared before any number was computed.
**Measure:** stretch z = (close - 20-bar mean) / 20-bar standard deviation of the close, on the book's own clock, at the bar the position would open.
**Diagnostic:** for short candidates (live breakdown, negative 40-bar momentum, no live long channel, tradable pool) and for long candidates (live breakout, positive momentum), bucket z at (-inf,-3], (-3,-2.5], (-2.5,-2], (-2,-1.5], (-1.5,-1], (-1,1), [1,1.5), [1.5,2), [2,2.5), [2.5,3), [3,inf); report per bucket the count, P(the price is lower / higher after 1, 4 and 12 bars) and the mean forward P&L in bps for the side, before costs. On 1h, 30m and 15m; 2023-24 fit, 2025-26 holdout.
**Filter rule, chosen on the fit period only:** an entry is skipped if its z bucket's fit-period mean P&L at 4 bars is below zero for that side and clock. The skip set is frozen and then scored on 2025-26.
**Arm:** the top-3 contenders rule (`#lowtf-contenders-declaration`) with the filter applied to both sides, against the unfiltered rule on the same harness. Decision: adopt on the live short-term books only if the filtered arm beats the unfiltered one in the holdout median and P(>5%) on at least two of the three clocks.
Mechanism: short-horizon crypto moves overshoot and mean-revert after capitulation-sized drops, so the most stretched breakdowns should have the worst odds of continuing. Failure mode: in trend legs the most stretched names are the strongest trends, and the filter removes the best shorts; `#book-diagnosis-2026-09-23` found the ranked book's money in exactly the extended runners.

## lowtf-exhaustion-outcome

`gates/lowtf_exhaustion.py`, `results/lowtf_exhaustion.json`; declaration `#lowtf-exhaustion-declaration`.
**Breakdown shorts have less than even odds of continuing at every stretch level, and the odds fall as the stretch grows.** 1h, 2023-24, price lower after 4 bars: 38% below -3 sd (-29 bps), 41% at -2.5 to -2 (-19 bps), 46% at -1.5 to -1 (-8 bps), 49% within ±1 sd (+1 bps). 30m and 15m show the same shape; in 2025-26 every bucket sits near 50%. The operator's observation is right, and the continuation edge on the short side at these clocks is nil even where the move is not stretched.
Longs are the mirror: breakouts that are MORE stretched do better at 12 bars (1h fit +36 to +77 bps at z above 1.5), which is momentum, so only a few thin long buckets were skipped.
Frozen skip sets (fit mean P&L at 4 bars below zero): 1h shorts below z -1 and longs in [-1.5, -1); 30m shorts below z 1.5, i.e. all shorts; 15m shorts below z 1, i.e. effectively all shorts, and longs in [-2, -1.5) and at z 3 or more.
Contenders holdout median, unfiltered -> filtered: 1h -9.69 -> -6.37 (P>5% 0.23 -> 0.28), 30m -18.18 -> -7.97 (0.10 -> 0.22), 15m -37.60 -> -18.60 (0.04 -> 0.13). **Passes the declared rule on 3 of 3 clocks and is adopted** on the live short-term books from 2026-09-23 ~18:45Z; the 5m book uses the 15m set (no 5m history).
Read plainly: the filter improves the books mostly by blocking the shorts, and the filtered books still lose (long-only momentum holdout: 1h -4.99, 30m -10.88, 15m -23.05). On lag: live decisions fire a median 16 to 23 seconds after each bar close; the slow part is the exit rule (a short closes only above the prior 10-bar high), not the bot.

## live-audit-2026-09-24

Operator request: make sure there are no false signals or false returns and the bots work in real time. Read-only audit `gates/live_audit.py`, artifact `results/live_audit.json`, over the first 21.5 hours of the three short-term contender books.
**False signals, found and fixed.** Recomputing every recent bar-close decision from Binance on the exact window the bot saw, 9 of 40 (5m), 3 of 26 (15m) and 2 of 21 (30m) disagreed. Two per book predate the stretch filter (expected). The rest are real: `bot.feed.bar_frame` fetched each symbol once with no retry and silently dropped any symbol whose request failed, so the bot ranked a partial universe. Dropping NEAR reproduces the live 15m decision at 12:15Z exactly, and dropping TRX the 30m decision at 05:00Z. Most failures follow a wake from sleep, but the 12:15Z one happened while online. The same defect applies to every book, the 4h books included.
Fix: `bar_frame` retries a failed symbol twice with backoff; `feed.data_gaps` reports symbols with no bars or a last bar older than the newest; `Bot.cycle` defers a bar close while any universe symbol is missing or stale (journalled as `data_incomplete` in the errors stream) and retries on the next poll, for at most three cycles per bar so a genuinely dead symbol cannot freeze a book. Tests `tests/test_data_gaps.py`.
Correction the same day: each symbol was cut at its own fetch time, so a bar closing mid-download reached some symbols and not others and the gap check flagged most of the universe as stale at bar closes (deferring one poll and filling the errors stream). `bar_frame` now cuts every symbol at one instant; no false `data_incomplete` since 15:46Z.
**Returns, slightly optimistic, now quantified.** A normal-spread paper fill is booked at the bot's own passive limit price at once (113 of 141 fills on the 5m book). Charged at the far side instead, equity is lower by 1,341 (5m), 255 (15m) and 78 (30m) USD: about 1.2%, 0.2% and 0.1% of equity. Wide-spread names were already charged the far side. Marks use Roostoo's LastPrice.
**Real time.** When awake, decisions fire a median 23 s (5m), 35 s (15m) after the bar close; the 30m median of 370 s and every p90 above a minute come from waking after sleep. The books were online 20% of the 21.5 hours, because the Mac slept on battery. That, not the code, is the largest distortion in every live number so far.

## accel-declaration

Operator request, 2026-09-24: add shorter-horizon momentum, research acceleration rather than momentum, and build an agile smaller-timeframe book that takes longs and shorts on clear logic. Declared before any number was computed.
**Literature.** Chen, Yu & Wang (2017, J. Financial Markets, SSRN 3009059): the curvature of a quadratic fit to the formation-period price path predicts returns; accelerating winners outperform and accelerating losers underperform, momentum profit +51% (US stocks, monthly). Ardila, Forrò & Sornette (2021, Physica A, SSRN 2645882): acceleration as the first difference of successive returns (the Gamma factor) beats momentum in two thirds of parameterisations, and is procyclical and transient. Against: "Momentum, Acceleration, and Reversal" (JOIM) finds accelerated rises unsustainable and followed by reversal; Wen, Bouri, Xu & Zhao (2022, Econ. Modelling) find crypto intraday momentum AND reversal, reversal after jumps; this repo's own stretch table (`#lowtf-exhaustion-outcome`) and the NSE short-horizon study found stretched moves revert. The sign is therefore the question, and the control tests it.
**Signals, per coin on the book's own clock (all on closed bars):** short momentum m_s = log return over 12 bars; mid momentum m_m = log return over 48 bars; acceleration A = (return over the last 12 bars) - (return over the 12 bars before those), divided by the 48-bar standard deviation of bar returns times sqrt(12).
**Rule (`signals/acceleration.py`, shared by backtest and live):** long candidate if m_m > 0, m_s > 0 and A > 0 (an uptrend that is speeding up); short candidate if m_m < 0, m_s < 0 and A < 0, and fewer than 40% of the pool have positive m_m (the breadth switch of `#lowtf-breadth-shorts-declaration`). All candidates ranked together by |A|; enter the top 3; a held name stays while it is still a candidate on its own side and ranks in the top 5; weights proportional to |A|, at most 50% per coin, gross at most 1. It exits as soon as its trend or its acceleration flips, which is what makes it faster than the 10-bar channel exit.
**Arms:** A1 the rule; A2 the rule plus the frozen stretch filter of `#lowtf-exhaustion-outcome` for that clock. Both on 1h, 30m and 15m, 2023-24 fit, 2025-26 holdout, `#lowtf-paper-bots` harness and costs, no ladder. Six trials.
**Controls:** C the live contenders rule with its stretch filter (the current short-term books); N the sign-flipped rule (long decelerating uptrends, short decelerating downtrends), which wins if acceleration reverses.
**Pre-registered diagnostic:** cross-sectional rank IC of A against the next 4- and 12-bar return, within trend-aligned names, per clock and period.
**Decision rule:** an arm is a candidate for the short-term books if its holdout median AND P(>5%) beat C on at least two of three clocks, its fit median beats C on those same clocks, and it beats N on those clocks. Whatever the result it runs on paper on operator instruction; a failed arm is never a competition candidate.

## accel-outcome

`gates/accel.py`, `results/accel.json`; declaration `#accel-declaration`. Six trials, all fail.
**Acceleration reverses at these clocks.** Rank IC of acceleration against the next return, within trend-aligned names (fit / holdout): 1h 4-bar -0.008 (t -2.6) / -0.016 (t -4.8); 30m 4-bar -0.019 (t -8.3) / -0.008 (t -3.4); 15m 4-bar -0.021 (t -13.0) / -0.018 (t -11.2), 12-bar -0.016 / -0.023 (t -14.3). Crypto at 15m to 1h sits with "Momentum, Acceleration, and Reversal" and this repo's NSE study, not with the monthly-equity findings of Chen, Yu & Wang or Ardila, Forrò & Sornette.
Median 14-day return (fit / holdout):

| clock | live contenders (control) | A1 acceleration | A2 + stretch filter | N sign-flipped |
|---|---|---|---|---|
| 1h | -8.13 / -6.37 | -10.64 / -13.89 | -9.66 / -14.40 | -16.50 / -14.82 |
| 30m | -7.22 / -7.97 | -28.50 / -27.87 | -14.95 / -14.63 | -28.80 / -30.82 |
| 15m | -18.91 / -18.60 | -47.37 / -49.17 | -27.99 / -29.27 | -49.85 / -53.10 |

No arm beats the control on any clock. The sign-flipped control, which bets on the reversal the IC shows, also loses: an IC of -0.02 is far below the cost of trading on it, because exiting whenever acceleration flips re-trades far more often than the channel rule.

## accel-guard-declaration

Operator instruction, 2026-09-24: launch acceleration books on paper anyway, with strong logic that overlaps the successful systems, and robust, agile longs and shorts. Declared before any number was computed; replaces A1/A2 for the paper books.
**Rule (`signals/acceleration.guard_targets`):** the live contenders rule (`#lowtf-contenders-declaration`: 20/10 Donchian breakout or breakdown, 40-bar momentum sign, breadth switch below 40% for shorts, top 3 across both sides by |momentum|, weight proportional to |momentum|, cap 50%, gross 1) with its frozen stretch filter (`#lowtf-exhaustion-outcome`), plus an acceleration guard used in the direction `#accel-outcome` measured: with A the 12-bar acceleration in volatility units (`#accel-declaration`) signed to the position's side, a **new** entry is refused when A > 2.0 (a blow-off, which reverses), and a **held** position is closed early when A < -1.5 (a sharp deceleration against it) instead of waiting for the channel exit. Both thresholds are fixed a priori, not fitted.
Clarification before any result was read (caught by `tests/test_accel_guard.py`): a name closed early for deceleration re-qualified as a new entry on the same bar, which made the early exit a no-op; a new entry is therefore also refused while A <= -1.5.
Mechanism: the channel and the momentum rank are the parts of this repo that carry an edge; acceleration carries a small reverse signal, so it is used only to avoid the tail it says reverses and to leave earlier when a move stalls. Failure mode: the early exit re-trades often at 15m and 5m and costs more than it saves, as every faster exit tested here has.
Scored as G on the `#lowtf-paper-bots` harness against the live contenders rule on 1h, 30m and 15m; decision rule as `#accel-declaration`. Runs on paper as `accel_15m` and `accel_5m` whatever the result. Three trials.

## accel-guard-outcome

`gates/accel.py` (arm G), `results/accel.json`; declaration `#accel-guard-declaration`. Fails on every clock. Median 14-day return (fit / holdout), control = live contenders with its stretch filter:

| clock | control | G guard | G cost drag per 14d |
|---|---|---|---|
| 1h | -8.13 / -6.37 | -9.93 / -6.30 | 11.9% |
| 30m | -7.22 / -7.97 | -8.98 / -9.51 | 12.2% |
| 15m | -18.91 / -18.60 | -20.85 / -21.51 | 25.7% |

The guard is close to the control and slightly worse: the early exit on deceleration adds about 2 to 3 points of cost per fortnight and saves less than that. It cuts the 30m holdout worst window (-34.2 against -129.2) but not the others. As with every faster exit here, leaving early costs more than it saves.
Runs on paper as `accel_15m` and `accel_5m` (`bot/accel_run.py`) from 2026-09-24 on operator instruction; never a candidate.

## let-winners-run-declaration

Operator request, 2026-09-24, after `#book-diagnosis`-style log review of the short-term books: about 40% of exits kept running more than 1% within the next hour (ONDO +13.5% after a 15m exit) and the books averaged only 21-25% weight in the day's top mover. Declared before any number was computed.
Base C: the live contenders rule with its frozen stretch filter (`#lowtf-contenders-declaration`, `#lowtf-exhaustion-outcome`), simulated bar by bar with the live mechanics: 25% no-trade band, a held position never topped up, the 3%/15% skim ladder on both sides, 5 bps plus tick on spot and 10 bps plus tick on shorts (`gates/let_winners_run.py`).
**Arms:** W1 sticky: a held name keeps its slot for as long as it is still a candidate on its side (live channel, momentum sign, and the breadth switch for shorts); new names fill only free slots, so nothing is rotated out for a stronger name. W2 no ladder: C without skims. W3: W1 and W2 together.
Mechanism: the log losses came from rotation churn among the same leaders and from skimming straight runs; a runner that stays in its channel should be allowed to keep running. Failure mode: stickiness keeps a fading name and blocks a fresh leader, the ladder is the only thing that banks gains before a reversal, and `#rotation-hysteresis-outcome` found stickiness inert at 4h.
On 1h, 30m and 15m, 2023-24 fit, 2025-26 holdout. Decision: an arm is adopted on the short-term books if it beats C in holdout median AND P(>5%) on at least two clocks and its fit median beats C on those same clocks. Three trials.

## let-winners-run-outcome

`gates/let_winners_run.py`, `results/let_winners_run.json`; declaration `#let-winners-run-declaration`. Median 14-day return, P(>5%) and turnover per fortnight (fit / holdout), bar-by-bar with the live mechanics:

| clock | C live | W1 sticky | W2 no ladder | W3 sticky, no ladder |
|---|---|---|---|---|
| 1h | -5.86 / -5.08, P5 0.20 / 0.26, turn 93 | **-2.67 / -3.34, P5 0.25 / 0.32, turn 62** | -6.71 / -5.53 | -4.65 / -3.29 |
| 30m | -5.08 / -5.56, P5 0.23 / 0.25, turn 123 | **-3.65 / -3.39, P5 0.24 / 0.28, turn 86** | -6.16 / -6.54 | -3.78 / -4.64 |
| 15m | -14.68 / -14.78, P5 0.10 / 0.10, turn 258 | **-10.29 / -10.09, P5 0.13 / 0.17, turn 175** | -17.39 / -16.77 | -12.86 / -12.20 |

**W1 (sticky slots) passes on all three clocks and is adopted** on `momentum_top3_1h/30m/15m/5m` (5m by extension, no 5m history) from 2026-09-24. It improves the median by 1.4 to 4.7 points, raises P(>5%) in every period, cuts turnover about 30% and shallows the worst window on 1h and 15m. W3 also passes but is weaker than W1 on median in five of six cells; **removing the ladder (W2) hurts everywhere**, so the skims stay: they bank gains that the channel exit would give back.
Read plainly: rotating out of a held leader for a marginally stronger name was a real cost at fast clocks (the 4h null at `#rotation-hysteresis-outcome` does not carry down), but the books still lose at the median after costs on every clock. No nonsense control was declared for this test.

## breakout-quality-declaration

Operator request, 2026-09-24: a stronger sense of breakouts, support/resistance and reversals, for better entries and exits. Three changes to the live short-term rule, declared before any number was computed. Base L: the live contenders rule with its stretch filter and sticky slots (`#let-winners-run-outcome`), on the `gates/let_winners_run.py` bar-by-bar simulator with the ladder.
**B1 higher-timeframe alignment:** a new long may open only while the coin's 4h 20/10 Donchian long channel is live (last closed 4h bar, carried to the fast clock at 4h close); a new short only while its 4h 20/10 breakdown state is live. Held names are unaffected. Mechanism: the 4h channel is the only signal here with an edge after cost; fast breakouts against it are the ones that fail inside a day. Control: the same filter using another coin's 4h state (a fixed random permutation of coins), which keeps the share and timing of "on" but breaks the link to the coin.
**B2 volume confirmation:** a new entry needs the entry bar's quote volume at least 1.5 times its 20-bar median. B2t (1h only, where taker data exists): additionally taker-buy share above 0.5 for a long, below 0.5 for a short. Mechanism: a real break of a level brings volume and aggressor flow; a thin poke does not. Control: a random mask with the same pass rate per clock.
**B3 failed-breakout exit:** a held position is closed if, within 4 bars of entry, the close returns through the level it broke (long: back below the prior 20-bar high at entry; short: back above the prior 20-bar low), and the name may not re-enter until its channel has reset. Mechanism: a close back inside the range is a trap and usually precedes the reversal; today's exit waits for the 10-bar extreme. Control: a plain 4-bar time stop (exit if below entry price after 4 bars), which tests whether the level matters rather than just exiting losers early.
Fixed parameters, not fitted. Clocks 1h, 30m, 15m; 2023-24 fit, 2025-26 holdout. Decision per arm: adopt if it beats L in holdout median AND P(>5%) on at least two clocks, its fit median beats L on those clocks, and it beats its control's holdout median on those clocks. Four configurations recorded as trials: B1, B2, B2t, B3.

## breakout-quality-outcome

`gates/breakout_quality.py`, `results/breakout_quality.json`; declaration `#breakout-quality-declaration`. Median 14-day return (fit / holdout), P(>5%) holdout, against L = live sticky contenders:

| clock | L live | B1 4h alignment | B1 control | B2 volume | B2 control | B3 failed-breakout exit | B3 control |
|---|---|---|---|---|---|---|---|
| 1h | -2.67 / -3.34, 0.32 | **-1.57 / +0.46, 0.38** | -1.72 / -2.07 | **-1.32 / -0.42, 0.33** | -2.93 / -3.49 | -6.13 / -6.87 | -4.24 / -4.85 |
| 30m | -3.65 / -3.39, 0.28 | **-1.86 / +1.19, 0.34** | -2.51 / -1.16 | -3.45 / -2.56, 0.28 | -3.56 / -1.77 | -6.16 / -6.59 | -4.02 / -4.17 |
| 15m | -10.29 / -10.09, 0.17 | -5.67 / -4.63, 0.19 | -5.60 / -4.48 | **-8.39 / -8.28, 0.21** | -9.14 / -9.09 | -15.63 / -14.78 | -11.70 / -11.98 |

**B1 passes (1h, 30m) and gives the first positive holdout medians on these clocks** (+0.46, +1.19). At 15m it is no better than its permuted control, so there its gain is fewer trades, not the 4h link. **B2 passes (1h, 15m)**, smaller; at 30m it loses to its random-mask control. B2t (volume plus taker direction, 1h only) -0.51 holdout, no better than B2. **B3 fails everywhere**: exiting on a close back through the broken level re-trades more (turnover +70 to +90%) and does worse than a plain time stop; failed-looking breakouts often resume.
Confirmation run before deployment, declared here before it ran: B1 and B2 together (one trial), required to beat L on the same terms on at least two clocks before both go live together; otherwise only B1 goes live.
Confirmation result (`results/breakout_quality_b12.json`): B1 and B2 together beat L on all three clocks: 1h +0.94 / +2.32 (P(>5%) 0.40), 30m -0.71 / +1.09, 15m -4.27 / -4.02, with turnover cut by half to two thirds. **The 1h book is positive in both fit and holdout for the first time on a short-term clock.** Both confirmations went live on `momentum_top3_1h/30m/15m/5m` at 2026-09-24 ~17:19Z (`signals.contenders.entry_confirmation`, config `htf_confirm`, `volume_confirm: 1.5`); B3 is not deployed.

## short-htf-declaration

Operator request, 2026-09-24: breakout confirmation on shorter timeframes than 4h. Declared before any number was computed.
Arm S: the live rule (sticky contenders + B2 volume + B1 alignment) with the alignment channel taken on a clock four times the book's own instead of 4h: 15m book -> 1h channel, 30m book -> 2h channel (1h book unchanged at 4h). Same 20/10 channel, same carry at the higher bar's close. Scored on 15m and 30m against the live B1+B2 rule on the `gates/let_winners_run.py` simulator.
Decision (non-inferiority, because the gain sought is faster reaction, not return): adopt on a clock if its holdout median is no more than 0.5 points below the live rule's and its holdout P(>5%) no more than 0.02 below. One trial.
Result (`results/short_htf.json`): **not adopted.** 15m with a 1h channel: holdout -5.14, P(>5%) 0.20 against the live -4.02, 0.25; 30m with a 2h channel: -0.25, 0.29 against +1.09, 0.34. Both fail non-inferiority; the 4h channel carries the confirmation, and it needs no 4h of uptime because the bot reads 4h history from Binance at each decision.

## idle-cash-declaration

Operator request, 2026-09-24: realised profit (skims, rotations) idles in cash because a held name is never topped up, and with entry confirmation the short-term books sat 29% invested. Declared before any number was computed.
Base: the live short-term rule (sticky contenders + stretch filter + 4h alignment + volume confirmation, ladder), `gates/let_winners_run.py` simulator.
**I1:** at a bar close where the book's gross is below 0.5, a held name whose 4h channel still agrees with its side (the B1 alignment condition) may be topped up to its target weight; otherwise the no-top-up rule stands. Skim references are unchanged. **I1c control:** the same top-up whenever gross is below 0.5, without the alignment condition.
Mechanism: in a confirmed 4h trend the held leader is the best use of idle cash, and topping up only when the book is mostly cash limits the fee churn that made recycling a loss at `#alpha-flow-declaration`. Failure mode: buying back what the ladder just sold, at a higher price, right before the reversal the ladder was protecting against.
1h, 30m, 15m; decision: adopt if I1 beats the base in holdout median AND P(>5%) on at least two clocks, its fit median beats the base there, and its holdout median beats I1c there. One trial.
Result (`results/idle_cash.json`): **fails, not adopted.** Topping held leaders back up while the book is under half invested lowers the median on every clock (1h holdout +2.32 -> +0.95, fit +0.94 -> +0.19; 30m +1.09 -> +0.63; 15m flat), deepens the worst window and adds 7 to 10% turnover. I1 and I1c are nearly identical because held names almost always still agree with their 4h channel, so the alignment condition adds nothing. The idle cash is doing work: it is what the ladder banked before the pullback, and buying it back pays the fees and the pullback. Consistent with `#alpha-flow-declaration`.

## idle-cash-new-entry-declaration

Operator request, 2026-09-24, after `#idle-cash-declaration` failed: make booked profit compound by using it. Declared before any number was computed.
**I2:** when a NEW position opens (it has passed the 4h alignment and volume confirmation), the cash left idle after held positions and the new entries' normal targets is added to the new entries in proportion to their targets, each capped at 50% of equity, gross at most 1. Held positions are still never topped up, so nothing the ladder sold is bought back. Control I2c: the same idle cash added to new entries only when the book is at least half invested (so it tests whether sizing up is the effect, not timing).
Mechanism: a freshly confirmed breakout is the rule's best current opportunity, so profit banked from the last runner is put straight into the next one. Failure mode: larger entries into breakouts that fail inside a day (the losing half of trades) and concentration into single names at the 50% cap.
1h, 30m, 15m against the live rule; decision as `#idle-cash-declaration` with I2c in place of I1c. One trial.
Result (`results/idle_cash_new_entry.json`): **fails, not adopted, but close to neutral.** Median change (fit / holdout): 1h +0.94 / +2.32 -> +0.67 / +2.02; 30m -0.71 / +1.09 -> -0.82 / +1.11; 15m -4.27 / -4.02 -> -4.66 / -4.30. It adds 8 to 10% turnover and leaves P(>5%) and P(>10%) unchanged; I2c is indistinguishable, so there is no timing effect either. Larger new entries earn about what they cost: the rule's edge is in which names it picks, not in how much cash it deploys.

## min-hold-5m

Operator instruction, 2026-09-24: a minimum hold on the 5m books. Across all live books, trades held under 15 minutes made +71 USD gross and -1,295 net on 49 trades (average 4.8 bps gross against 12.2 bps fees), while 15-60 minute holds made +2,696 net (gap review at 18:32Z).
**Rule (`min_hold_bars: 3` on `momentum_top3_5m`, `momentum_top3_5m_allcash`, `accel_5m`):** a new position is kept for at least 3 bars (15 minutes) whatever the rotation, channel, momentum-sign or acceleration exit says; it keeps its side and last strength-based weight. Skims and kill switches still act. The length is set from the live log, not fitted; there is no 5m cross-section to backtest, so it is judged on live data: it should cut the 5m books' sub-15-minute trades to zero and their fee share, without lowering return against the 15m books over the next 14 live days.

## allcash-5m-no-htf

Operator instruction, 2026-09-24 ~18:50Z: `momentum_top3_5m_allcash` had placed no trade since launch because no 5m breakout had a live 4h channel (0 of 1-4 candidates per bar over the prior hour). Its 4h alignment check (`htf_confirm`) is switched off; the volume confirmation, stretch filter, sticky slots, minimum hold and idle-cash absorption stay. It is now a two-way live experiment against `momentum_top3_5m` (same rule with the 4h check): no 5m history exists to backtest it, and at 15m the 4h check's gain was mostly fewer trades (`#breakout-quality-outcome`). Judged on 14 live days: return and fee share against its twin.

## stop-and-reverse-declaration

Operator request, 2026-09-24 ~19:10Z: when a trend reverses, flip the position to benefit on the other side. Declared before any number was computed.
**R (`signals.contenders.reverse_on_exit`, shared by backtest and live):** when a position held at the previous bar is gone at this bar AND the close broke its channel (long: close below the prior 10-bar low; short: close above the prior 10-bar high), a position of the opposite side opens on the same coin at the size it had (at most 50%), and is held until its own channel exit (short: close above the prior 10-bar high; long: below the prior 10-bar low) or 24 bars, whichever comes first, or until the base rule wants the coin again. Rotation exits do not reverse. Gross is capped at 1 by scaling.
Mechanism: a leader that loses its channel after a run is where the measured reversal (`#accel-outcome`) and the failed-continuation odds (`#lowtf-exhaustion-outcome`) concentrate. Failure mode: channel breaks in a leader are often pullbacks inside a larger trend (the 4h books' edge), so the reversal short is squeezed; shorts pay double fees.
Base: the live rule on 1h, 30m and 15m (sticky, stretch filter, 4h alignment, volume), `gates/let_winners_run.py` simulator. Decision: adopt on the short-term books if R beats the base in holdout median AND P(>5%) on at least two clocks and its fit median beats the base there. Reported also: the reversal leg's own P&L. One trial.
Result (`results/stop_and_reverse.json`): **fails badly on every clock; not deployed.** Median 14-day return (fit / holdout): 1h +0.94 / +2.32 -> -3.64 / -1.39; 30m -0.71 / +1.09 -> -5.42 / -2.57; 15m -4.27 / -4.02 -> -10.22 / -10.26. The reversal leg on its own compounds to -73% to -98% over each period. A leader losing its short-term channel is mostly a pullback inside a continuing trend (the 4h edge), so the flipped short is squeezed; the reversal the operator sees live is real on the day it happens but does not pay on average.

## lowtf-lock-declaration

Operator request, 2026-09-24: test the target lock on the short-term books. Declared before any number was computed.
Base: the live short-term rule (sticky, stretch filter, 4h alignment, volume confirmation, ladder) on 1h, 30m and 15m from the `gates/let_winners_run.py` simulator, compounded to hourly returns. Arm K: the `#competition-wf-outcome` S4 lock applied by `gates.competition_wf.windows_hourly` exactly as for the 4h books: in every 14-day window from 00:00 UTC, once the window is up 5%, the rest of it runs at 0.3 of its exposure, charging the de-risk cost. Decision, as S4: K passes on a clock if it raises P(>2%) AND the median in both the fit (2023-24) and holdout (2025-26) periods and its worst window is no more than 5 points worse; adopt on the short-term books if it passes on at least two clocks. The lock trades the winning tail for qualification; P(>15%) is reported. One trial.
Result (`results/lowtf_lock.json`): **passes on all three clocks; adopted.** Median 14-day return and P(>2%) (fit / holdout): 1h +1.15 / +2.31, 0.47 / 0.52 -> **+4.21 / +4.67, 0.61 / 0.65**; 30m -0.69 / +1.16, 0.37 / 0.46 -> **+2.66 / +3.95, 0.54 / 0.64**; 15m -4.12 / -4.05, 0.23 / 0.34 -> **-1.88 / +1.34, 0.36 / 0.46**. Worst windows unchanged; Screen 3 medians rise on every clock. The price, as at 4h: P(>15%) falls to 0.02-0.04. Live on the eight short-term books from 2026-09-24 ~19:30Z, 14-day window anchored at the equity on activation (the 4h lock's mechanics, `bot/lock.py`).

## no-htf-15m-5m

Operator instruction, 2026-09-24 ~19:30Z: drop the 4h alignment check on the 15m and 5m books (`momentum_top3_15m`, `momentum_top3_15m_allcash`, `momentum_top3_5m`; `momentum_top3_5m_allcash` already at `#allcash-5m-no-htf`); they had been flat since ~18:15Z because no 5m/15m breakout had a live 4h channel. Supported at 15m by `#breakout-quality-outcome`: B1's 15m gain was no better than its permuted control, while B2 (volume only) passed at 15m. The 1h and 30m books keep the 4h check, where it beat its control. Volume confirmation, stretch filter, sticky slots, minimum hold (5m), ladder and target lock stay.

## path-forensics-2026-09-25

`python3 -m gates.path_forensics [--parity BOOK ...]` (read-only; writes `live/forensics/trades.csv`, `decisions.csv`, `parity.csv`).
Live data 2026-09-23 16:08Z to 2026-09-25 05:40Z, 13 books, 370 closed rows = 281 positions, books online about 25% of the time.
Sample is about 1.5 trading days and two symbols (ONDO, LTC) carry the profit, so nothing here is a validated edge; these are defects and hypotheses.

Findings, defects first:
1. **Hold age and sticky slots come from the simulated path, not the book's real entries.** `signals.contenders.targets` re-simulates the last 181 bars each close; after downtime the book buys names the simulation "entered" several bars earlier, so the 3-bar minimum hold has already run out and sticky protection does not apply. Seen 2026-09-25 05:25Z on both 5m books: PUMP and TAO bought on the wake-up decision (bar 05:15, simulated entry 05:05) and sold 47 s later on the 05:20 bar, PUMP flipped long to short.
2. **Catch-up entries lose.** Positions opened on a decision more than one bar after the close: 65, net -6,115, win 40%; on time: 216, net +8,220, win 44%. Downtime turns the rule into a late-entry rule the backtest never scored.
3. Rolling-window re-seed is NOT a defect: `--parity` on 5m/15m/30m/1h, 120 consecutive windows each, 0 rows rewritten.
4. Exits: channel-break exits -16,109 on 67 positions (median giveback 2.2% from the best point, 45% of them higher 4h later, so not premature, just late); displacement +13,378 on 199; ladder skims well timed (price 0.5% lower 4h after the skim).
5. Positions that were ever +1% in favour: 110, net +42,428; positions that never were: 170, net -40,380, median hold 32 min. Adverse excursion does not separate them early (median MAE -0.8% vs -0.6%), and every early-exit family already failed (`#breakout-quality-outcome` B3, `#take-profit-outcome`, `#reversal-reentry-outcome`), so no exit change is proposed.
6. Shorts: 42 rows, net -5,195, win 45%, consistent with "no short edge at any clock".
7. Time of day: 12-16Z entries +21,714 (34 positions, 76% win, the ONDO/LTC trend); 16-20Z -18,732 (127 positions, 33% win, BTC chopping +/-0.5% an hour). One day each; a session filter would need a pre-registered test, not this sample.
8. Lone-candidate entries (one name takes the 0.5 cap) made +13,242 on 15 positions; the near-zero-momentum PUMP case is real but not a loss source so far.
9. First cut of this analysis showed "re-entry after a quick win" at +32k and 79% win; that was ladder skims counted as new trades. At position level it disappears (51 positions, -1,951). Analyses of `bot.blotter` rows must collapse skims first.

Candidate fixes, for the operator (execution-path changes, not made by the agent):
- A. On a catch-up decision (more than one bar late), open no new position whose simulated entry is older than the latest bar; held names and exits act as usual. Addresses 1 and 2.
- B. Count the minimum hold from the book's real fill time, stored in state, not from the simulated path. Addresses 1.
- C. Uptime (EC2 or mains power with sleep disabled) removes most of 1 and 2 at the source.

## catch-up-and-live-min-hold

Operator instruction 2026-09-25: implement fixes A and B from `#path-forensics-2026-09-25`. These are execution guards on the live books, not a signal change; the backtests are unchanged because a backtest never misses a bar.
Scope: every `bot.contenders_run` book (`momentum_top3_1h/30m/15m/5m` and their `_allcash` twins) and both `bot.accel_run` books, through `bot.entry_guard.GuardedTarget`.
**A (catch-up entry guard):** a decision is a catch-up when the book skipped at least one bar since its previous processed bar, or when it runs more than one bar after the close. On a catch-up, a name the book does not hold (at least 1% weight on the same side) is not opened if the rule's simulated path already held it on the previous row; a name that is new on the latest row still opens, held names and exits act as usual, and the freed weight stays in cash. Journal: `stale_entry_blocked` in signals.
**B (live minimum hold):** the book stamps each real position with the decision bar its order went out on (`opened` in state, persisted). While a position is younger than `min_hold_bars` bars by that stamp (the 5m books and `accel_5m`, 3 bars), it is kept at its current weight and side even when the target drops or flips it; the rest of the target is scaled so gross stays at most 1. The ladder, lock and kill switches still act after it. Positions open before the change carry no stamp and are not held by B. Journal: `live_min_hold` in signals.
Case both guards stop: 2026-09-25 05:25Z, 5m books woke and bought PUMP and TAO from bar 05:15 (simulated entry 05:05, so A blocks them); had they been bought, B keeps them through bar 05:25 instead of selling at 05:20 and flipping PUMP short.
Judged on live data: `stale_entry_blocked` and `live_min_hold` events, and catch-up P&L in `python3 -m gates.path_forensics`, over the next 14 live days.

## live-audit-parity-fix-2026-09-25

`gates/live_audit.py` recomputed `signals.contenders.targets` without the entry confirmation (volume, 4h channel) that went live 2026-09-24 ~17:19Z, and over decisions made under older configs, so it reported 23-39 mismatches in 40 bars. It now applies `entry_confirmation` with the 4h bars closed at the decision time and scores only decisions made under the book's current config sha, on all eight contenders books. Result 2026-09-25 ~06:50Z: 162 decisions, 0 mismatches; the live books do what the rule says.
Losses since the current rules (2026-09-24 19:30Z to 06:40Z): 68 positions, net -10,073, win 40%; 43 never reached +1% in favour; channel-break exits -11,949 on 21. The market moved a median 0.5% per 6h after the 12-18Z trend; the 15m and 5m clocks had negative holdout medians before they went live (`#breakout-quality-outcome`), so this is the rule in chop, not a defect.
Separate defect found while checking fills: on battery the Mac takes short DarkWake naps, a cycle can start inside one and finish up to an hour later on the prices it fetched before sleeping. Example: `momentum_top3_5m` cycle stamped 01:06:28Z decided on bar 00:05 and sold ENA at 0.2299 while Binance traded 0.2353-0.2365. 50 of 737 paper fills sit more than 20 bps outside Binance's 2-minute range (27 over 50 bps, up to 2.3%); adverse 6,026 USD against favourable 5,268, so the net P&L distortion is small but individual trades are wrong. Fix is uptime; a guard that refuses to send orders when the cycle's data is older than a poll or two is proposed, not implemented.

## stale-cycle-guard

Operator instruction 2026-09-25, after `#live-audit-parity-fix-2026-09-25`: add the stale-data guard if it improves the books and suits them.
Evidence it targets the defect and nothing else: of 737 paper fills, all 50 that sit more than 20 bps outside Binance's 2-minute range (and all 6,026 USD of adverse deviation) came from cycles that followed a gap of more than 120 s; the 437 fills in normal cycles average 0.2 bps from Binance with zero adverse cost.
Rule (`bot.run.stale_cycle`, every book, since it lives in `Bot.cycle`): before each order the cycle compares the wall clock with the monotonic clock since it fetched its bars and quotes. The monotonic clock stops while the Mac sleeps (checked on this machine: 1,026 h monotonic against 2,702 h of uptime), so their difference is time asleep. If the cycle slept more than 5 s, or has run more than 300 s in all, it sends no further order, journals `stale_cycle_aborted` in orders, and rolls the bar back so the next poll re-decides it on fresh data. When nothing was sent it also restores the ladder references, the lock state and the entry-guard stamps it had changed.
Why not a plain elapsed-time limit: a normal cycle that refreshes its universe took 63 s to reach its orders in the end-to-end test, so a 90 s wall-clock limit would abort healthy cycles on a slow network. On an always-on host the guard never fires.

## accel-5m-retired-2026-09-25

Operator instruction 2026-09-25 ~09:05Z: stop `accel_5m`. It failed its backtest (`#accel-guard-outcome`) and ran only as operator-kept paper. Live over 16.9 h (45% online): -3.3% (final equity 96698.98), 87 closed rows at 34% win, fees 1,680 against a losing gross, and only 45% of each winner's best excursion kept, the worst of the fleet (`#path-forensics-2026-09-25`). `accel_15m` (+4.0%) keeps running.
Removed from `run_bots.sh` CONFIGS, `bot/dashboard.py` BOTS, `gates/live_validation.py` BOOKS and `gates/path_forensics.py`; live data moved to `live/_archive/retired-accel5m-20260925/`; `config/accel_5m.yaml` kept for the record.

## fleet-review-2026-09-26

Live 2026-09-23 16:08Z to 2026-09-26 09:31Z (65 h). Online since 2026-09-25 07:00Z: 6.5 h of 26.5 h; the Mac slept 2026-09-25 13:53Z to 2026-09-26 09:21Z (19.5 h, `stale_cycle_aborted` slept_s 70,105) with every position frozen.
Returns: 15m +9.2%, 30m +9.0%, 5m +8.7%, accel_15m +8.7%, 30m_allcash +6.4%, full +2.7%, lock +2.5%, 1h_allcash +2.3%, donchian_4h +1.4%, 15m_allcash +0.1%, 1h -2.3%, 5m_allcash -2.8%.
Right: longs +46.7k on 461 rows; ladder skims +33.7k on 197 exits (price 0.1% higher 4h later, so banking not premature); winners that reached +1% kept all but a median 1.13%; entries after a >4% hour in the trade's direction +24.7k at 89% win (45 rows, mostly ONDO); on-time entries +41.1k against catch-up entries -0.4k.
Wrong: shorts -6.1k on 44 (no edge, as before); NEAR -10.4k on 60 rows across books; the 5m clock.
Sleep-window counterfactual (rule replayed on the bars the frozen books missed, starting from the frozen positions, no ladder, fees 0.10% / 0.05% per side): 30m +3.7 / +4.0% against +0.7% frozen; 15m -0.1 / +0.9% against -3.0% frozen; 1h -0.15% against -1.3%; 5m -6.1 / -3.7% against -3.1% frozen. Sleep cost the 30m and 15m books about 3 points each and the 1h book about 1; the 5m rule loses money even when awake in this window (176 rebalancing bars in 19.5 h).
Guards: `stale_cycle_aborted` 4 (all real sleeps, nothing sent), `stale_entry_blocked` 23 names (6 with a 4h outcome: +1.7% after 1h, +0.1% after 4h; too few to judge), `live_min_hold` 0.
Open questions for a pre-registered test, not changes: the frozen stretch filter skips long entries at z >= 3 while the live >4%-hour entries were the best bucket.

## lowtf-long-only-clocks-declaration

Operator request 2026-09-26: find the best-working strategies, diagnose them, make them better. Declared before any number was computed; `config/lowtf_long_only_clocks.yaml` holds the rule, arms, control and pass rule.
Diagnosis on live data (`#fleet-review-2026-09-26`, positions collapsed from skims): the best books (15m +9.2%, 30m +9.0%, accel_15m +8.5%, 30m_allcash +6.4%) are long trend-capture engines. ONDO and LTC (ENA for accel_15m) are 89-130% of each book's net and the rest nets about zero; holds over 4 h made +7.1k to +11.2k per book while 1-4 h holds lost (failed breakouts). Shorts lost wherever they traded: 15m -751, 5m -1,180, 1h -4,425 (its longs made +2,163); accel_15m trades no shorts.
Candidates considered and not tested, with reasons: removing the z >= 3 long stretch skip (settled parameter, frozen on fit, `#lowtf-exhaustion-outcome`; live >4%-hour entries are 45 rows mostly ONDO); a minimum hold on 15m/30m (the losing bucket is 1-4 h, which a sub-hour hold does not touch); take-profit, exit-clock, ratchet and failed-breakout exits (dead families); topping up idle cash (`#idle-cash-declaration`, `#idle-cash-new-entry-declaration`).
Tested: long-only on the 15m and 30m live rules, with the 1h run as a reconciliation against `results/lowtf_confirmed_long_only.json`.

## lowtf-long-only-clocks-outcome

`gates/lowtf_long_only_clocks.py`, `results/lowtf_long_only_clocks.json`; declaration `#lowtf-long-only-clocks-declaration`. Reconciled: the 1h arms reproduce `results/lowtf_confirmed_long_only.json` exactly (gap 0.0).
Median 14-day return 2022 / 2023-24 / 2025-26 (Sharpe 2025-26, turnover per 14 days):

| clock | L_live | LO long-only | NC shifted switch | verdict |
|---|---|---|---|---|
| 1h | -1.07 / +1.10 / +2.25 (1.56, 36) | -0.44 / +1.23 / +2.83 (2.05, 24) | -3.21 / +0.28 / +1.51 | **passes every period, nonsense control loses** |
| 30m | -1.91 / -0.75 / +1.09 (1.04, 44) | -2.81 / -0.76 / +1.10 (1.12, 43) | -2.25 / -0.70 / +1.06 | fails, no change |
| 15m | -8.64 / -8.41 / -8.32 (-2.00, 143) | -8.53 / -7.72 / -7.85 (-1.84, 138) | -8.76 / -8.23 / -8.17 | fails |

Why: shorts are 24% of position-bars at 1h but only about 2% at 30m and 15m, where the frozen short stretch skips and the entry confirmation already block almost every short, so removing them changes nothing there.
Diagnosis of the live leaders: the 15m live rule (4h check off) has a median of about -8% per fortnight in every period, 143 turnover per fortnight and a -97% max drawdown in 2025-26; its +9.2% live is one ONDO/LTC trend. With the 4h check on, the same rule scored -4.27 / -4.02 (`#breakout-quality-outcome`), about 4 points a fortnight better, from lower turnover rather than the 4h link itself. The 30m rule is the only short-term clock with a positive recent history (+1.09 median 2025-26, Sharpe 1.04).
Adopted for forward paper: 1h long-only, which already runs as `momentum_top3_1h_long` (another session's book). No running book was changed.

## lowtf-clock-ensemble-declaration

Operator request 2026-09-26: make the short-term signals more robust and scale into what is working. Declared before any number was computed; `config/lowtf_clock_ensemble.yaml` holds mechanism, failure mode, arms, nonsense control and pass rule.
Why this and not more capital: scaling the current 15m rule scales a historical -8% per fortnight (`#lowtf-long-only-clocks-outcome`); an 80/20 slow/fast capital mix already cut drawdown but not the median (`results/lowtf_portfolio_mix.json`). The live diagnosis says the profit is runners every clock holds and the loss is lone fast breakouts plus churn, which is what a clock-agreement average addresses. Not a re-test of `#competition-wf-outcome`'s channel ensemble, which varied channel lookbacks on one clock.

## lowtf-clock-ensemble-outcome

`gates/lowtf_clock_ensemble.py`, `results/lowtf_clock_ensemble.json`; declaration `#lowtf-clock-ensemble-declaration`. **Fails, not adopted.**
Median 14-day return 2022 / 2023-24 / 2025-26 (worst window 2025-26, turnover per 14 days): C15 -8.64 / -8.41 / -8.32 (-39.5, 143); C30 -1.91 / -0.75 / +1.09 (-22.2, 44); C1h long-only -0.46 / +1.21 / +2.81 (-22.8, 24); **E_mean -2.43 / -1.14 / -1.94 (-13.6, 49)**; NC shifted -3.69 / -3.63 / -4.56 (-18.6, 58).
The mechanism is real but not enough: E beats the average of its components by 0.76 points a fortnight and the shifted control loses 1.36, so clock agreement carries information, and it cuts the worst fortnight to about -13% in every period (against -16% to -40% for the components). It loses to C1h long-only and C30 on median and P(>2%) in every period because the 15m component is a -8% a fortnight drag that averaging dilutes but does not remove.
Conclusion for scaling the short-term signal: the best short-term signal on history is the 1h rule long-only (Sharpe 1.72 / 2.05 in 2023-24 / 2025-26), already running as `momentum_top3_1h_long`. A 1h + 30m ensemble without the 15m leg would be a new, post-hoc trial chosen after seeing these numbers and must be declared as such before it is run.

## short-term-shorts-off-2026-09-26

Operator instruction 2026-09-26: turn shorts off on the short-term books and keep the profit ladder on.
Evidence: live, 46 short trades across the short-term books netted -6,164 (1h -4,425 at 33% win, 5m -1,214, 15m -751, 5m_allcash -291, 30m +517); on history the short side has no edge at any clock (`#lowtf-breadth-shorts-outcome`, `#lowtf-contenders-outcome`), and long-only passes at 1h (`#lowtf-long-only-clocks-outcome`).
Change: `short.enabled: false` on `momentum_top3_1h/30m/15m/5m`, their four `_allcash` twins and `accel_15m`; the 3%/15% ladder, target lock and every other parameter unchanged. `momentum_top3_1h_long` (another session's) was already long-only; the 4h books never shorted.
Two code fixes came with it. `bot.execution.Executor.prepare` refused every short order when shorts were off, which would have stranded the open AVAX shorts on the 15m books forever; it now refuses only `SHORT_OPEN`, so a held short closes at the next bar close. `signals.acceleration.guard_targets` ignored the book's short switch; it now takes `cfg["shorts"]`, and `bot.accel_run` passes the book's setting.

## signal-quality-2026-09-26

`python3 -m gates.signal_quality`, `results/signal_quality.json`. Diagnostic, selects nothing. Every NEW long entry of the live rules (shorts off) on history, forward return from the entry bar's close; `edge` is net of the eligible universe's equal-weight mean on the same bar; costs 2 x 5 bps plus 2 ticks.
- **Accuracy is below a coin flip at every clock**: hit rates 0.46-0.52 against a universe base rate of 0.48-0.50; after costs 0.31-0.51. The books earn on payoff asymmetry (live payoff 1.3-8.3x), not on being right more often.
- **Signal-to-noise per signal is small and grows with horizon and clock**: best 4h (edge +30 to +85 bps at 12 h-3 d, SNR 0.06-0.09, t 2.3-3.2) and 1h (edge +19 to +75 bps at 4-24 h, SNR 0.04-0.09, t 1.5-3.6); 30m +3 to +41 bps (t 0.9-2.4); 15m +0.7 to +19 bps (t 1-2.9), and only at 24 h. At the fast clocks' own horizons (1-4 bars) the edge is 0-7 bps against about 12 bps of cost, so net per-signal returns are negative until the position has been held about a day.
- **The filters carry most of the signal**: the live rule against the raw 20-bar breakout at the same clock, 12-16 bar horizon: 1h +33.4 vs +13.0 bps (2023-24), +30.7 vs +1.7 (2025-26); 30m +10.6 vs 0.0, +9.5 vs +3.0; 15m +3.1 vs +0.2, +4.7 vs +1.6. Whipsaw (positions of 3 bars or fewer) falls from about 33% to 18-27%.
- **Cross-sectional IC of 40-bar momentum among breakout candidates is negative at every clock and horizon (-0.03 to -0.10)**: among coins already breaking out, the strongest momentum does slightly worse next. This conflicts with `#lowtf-contenders-outcome` (strength sizing beat random sizes by 6-16 points in the portfolio) and is a hypothesis for a declared test (equal or inverse-strength sizing), not a change.
- 4h: 25% of top-3 selections last one bar and 48% three bars or fewer.
Live counterpart (positions, 2026-09-23 to 09-26): win rates 40-73%, payoff 1.3-8.3, profit factor 0.73-6.5; no book has t above 2 except `donchian_4h` (2.39 on 9 positions).

## short-term-lock-off-2026-09-26

Operator instruction 2026-09-26: the best books should be able to reach +20k, so the target lock is off on `momentum_top3_1h/30m/15m/5m` and their four `_allcash` twins. The lock fires 5% above the equity at the window start (2026-09-24 00:00Z) and then holds 0.30 gross, which capped `momentum_top3_30m` near +12.9k and had already locked `momentum_top3_30m_allcash` at 30% gross since 2026-09-25 08:56Z. `momentum_top3_lock` keeps its lock as the test of the lock itself. The ladder, shorts-off and every other rule are unchanged; the stored lock state stays in the state files and is ignored while the lock is disabled.

## burst-books-declaration

Operator instruction 2026-09-26: a shorter-timeframe, higher-risk strategy judged on the live market, not on backtests. Declared before the books ran. Two paper books, `burst_5m` and `burst_15m`, on the existing `bot.contenders_run` engine, configs `config/burst_5m.yaml` and `config/burst_15m.yaml`.
Rule: long-only; 20/10 Donchian breakout with positive 40-bar momentum; new entries need 1.5x volume (no 4h check); **top 2** by momentum at up to 50% each (full deployment in two names); **no stretch cap on longs** (the frozen z >= 3 skip removed, so the book chases strength); idle cash from skims and exits goes into each new entry (`absorb_idle`); sticky slots; minimum hold 6 bars on 5m and 4 bars on 15m (30 min and 1 h), counted from the real entry (guard B); the 3%/15% ladder; no target lock; catch-up and stale-cycle guards and the 25% drawdown kill switch as on every book.
Basis, all live: runners entered while already moving hard carried the fleet (entries after a >4% hour +24.7k at 89% win); shorts lost -6.2k; sub-hour holds on fast clocks lost to fees (5m holds under 1 h -2.1k on 81 positions); the volume filter carries most of the entry signal.
Known risk, stated once: the closest backtested relative (15m contenders, 4h check off) is about -8% a fortnight, and concentration beyond top 3 raised the far tail but lowered the median on history (`#max-return-levers-outcome`). The operator has chosen live evidence over that record.
Judged on live results only: stop a burst book if after 14 live days (2026-10-10) it is below `momentum_top3_15m` over the same days, or if it trips the 25% drawdown kill switch.

## rally-capture-15m-2026-09-26

`python3 -m gates.rally_capture`, `results/rally_capture_15m.json`. Diagnostic on 15m highs and lows, every new long entry of the live 15m rule (9,397 in 2023-24, 8,401 in 2025-26), entry at the bar close, costs 2 x 5 bps plus 2 ticks, a bar reaching both target and stop counted as the stop.
- Typical entry, both periods alike: median best move +0.45% within 1 h, +0.9% within 4 h, +1.6% within 12 h, +2.3% within 24 h; the median worst move over the same spans is about the same size (-0.5%, -0.95%, -1.7%, -2.4%). P(reach +1% within 4 h) 0.47-0.48, +2% 0.26, +3% 0.15-0.16.
- No fixed target/stop is reliably positive for the typical entry: 2025-26 every one of 35 combinations is negative after costs (best -5.9 bps); 2023-24 only wide targets with no stop are positive (+8%: +9.1 bps, t 1.97). High hit rates are a trap: +0.5% is reached 86% of the time within 24 h and still loses 13-16 bps a trade. Every stop level lowers the expected value.
- Entries after a >2% hour (about 12-14% of entries) are the capturable ones: median best move +2.2% within 4 h and +4.7% within 24 h; P(+2% within 4 h) 0.52-0.54, P(+3% within 24 h) 0.65-0.66, P(+5%) 0.48, P(+8%) 0.31-0.32. Every target of 1.5% or more is positive in both periods without a stop; +3% (hit 65-66%, median 8-8.5 h): +16.0 / +8.4 bps; +8%: +32.6 / +20.4 bps (t 1.88 / 0.92, so not yet significant, but the same sign in both periods and in live, `#fleet-review-2026-09-26`).
Consistent with `#take-profit-outcome` (fixed targets cost the right tail) and the ratchet-stop null: the edge is in letting the strong entries run, not in a tighter exit.

## burst-strong-and-equal-weight-declaration

Operator instruction 2026-09-26: implement insights 1 and 3 as separate strategies and bots, keep every existing book running, and remove the useless books from the dashboard. Judged on live paper results; declared before either book ran.
**`burst_strong_15m` (insight 1, control `burst_15m`):** `burst_15m` plus one entry condition, `contenders.entry_confirmation` with `prior_return_bars: 4`, `prior_return_min: 0.02`: a new long needs the close more than 2% above the close one hour earlier. Held names are never forced out by it. Basis: `#rally-capture-15m-2026-09-26` (median 24 h rally +2.3% -> +4.7% for such entries, positive after costs in both periods for targets of 1.5% or more) and the live >4%-hour entries (+24.7k, 89% win).
**`momentum_top3_15m_eq` (insight 3, control `momentum_top3_15m`):** `momentum_top3_15m` exactly as it runs live (long-only, no lock, ladder) with `equal_weight: true`: the chosen names split the book equally (at most 50% each) instead of in proportion to 40-bar momentum. Same names chosen, only the sizing differs. Basis: `#signal-quality-2026-09-26` (negative momentum IC among candidates at every clock) against `#lowtf-contenders-outcome` (strength sizing beat random sizes), hence an A/B, not a switch. Insight 3 was not applied to the burst books because with two names and a 50% cap they are already equal-weight.
Each differs from its control by exactly those keys (`tests/test_burst_strong_and_eq.py`). Stop rule for both: below its control over the same days after 14 live days (2026-10-10).
**Removed from the dashboard and stopped (live data in `live/_archive/retired-2026-09-26/`):** `momentum_top3_1h`, an exact rule duplicate of `momentum_top3_1h_long` since shorts went off (final equity 97,936, its loss was the shorts); `momentum_top3_15m_allcash` (99,263) and `momentum_top3_5m_allcash` (100,630), idle-cash arms that trailed their twins by about 9 and 12 points and had negative realised P&L. The winning arms `momentum_top3_30m_allcash` and `momentum_top3_1h_allcash` stay; `momentum_top3_1h_allcash` is now shown against `momentum_top3_1h_long`, the same rule without idle-cash absorption.

## short-accel-declaration

Operator instruction 2026-09-26: a short-only bot based on the data insights, negative momentum and acceleration as trend confirmation. Live paper, judged on live results; declared before it ran.
Stated once: on history the short side has no edge at any clock (`#lowtf-breadth-shorts-outcome`, `#lowtf-contenders-outcome`, `#topdown-ls-outcome`) and live the short-term books' shorts lost -6,164 on 46 trades before shorts were switched off (`#short-term-shorts-off-2026-09-26`); acceleration as a stand-alone signal reverses at 15m-1h (`#accel-outcome`). The operator has chosen to test it live.
**`short_accel_15m`** on the contenders engine (`sides: short`, switch always on): a candidate is a coin in a 20-bar breakdown (close below the prior 20-bar low) with negative 40-bar momentum and no live long channel. A NEW short also needs, on the entry bar: the coin's 4h 20/10 breakdown live (4h downtrend); 1.5x volume; the close more than 2% below the close 1 hour (4 bars) earlier (the move already under way, the short mirror of `#burst-strong-and-equal-weight-declaration`); and side-signed acceleration (`signals.acceleration.features`, 12/48 bars) in (0, 2]: the fall is speeding up but is not a capitulation spike, which `#accel-outcome` shows reverses. Top 2 by |momentum| at up to 50% each with idle cash absorbed into new entries; sticky slots; minimum hold 4 bars (1 h) from the real entry; no stretch skips. Exit when the close is above the prior 10-bar high; the ladder covers 15% each time the price falls 3% below its reference; shorts are never topped up; MARKET orders at 0.1% per side; no target lock; 25% drawdown kill switch.
Stop rule: stop it after 14 live days (2026-10-10) if its return is negative, or at once on the kill switch. It runs beside the long-only fleet, so a falling market that hurts the longs is where it should earn.

## live-hold-time-2026-09-26

Operator instruction 2026-09-26: from live data only, find the best closing time and take profit, add a 12 h hold bot, and optimise the shorter-holding bots. Live positions 2026-09-23 to 09-26 (315 positions after collapsing ladder skims), each replayed on Binance 5m bars from its real entry; costs 0.1% round trip; "drift" is the equal-weight return of every universe coin bought at the same moments over the same span.
- **Take profit:** no fixed target beats the actual exits on average. All books: actual +0.77% a position; a +1% target +0.16, +2% +0.22, +3% +0.45, +5% +0.72, +8% +0.81. The best case, about +5% on the 15m and 30m/1h books, adds about 0.1 point a position: noise. Small targets cap the runners.
- **Peak and giveback (medians):** 5m books peak +0.6% after 0.2 h and give back 0.9%; 15m +1.0% after 0.5 h, 1.4%; 30m/1h +4.2% after 2.2 h, 2.4%; 4h +6.5% after 9.9 h, 4.9%.
- **Long closing times:** closing every position T hours after entry, all books: 2 h +0.70%, 4 h +0.73%, 8 h +1.21%, 12 h +2.08%, 24 h +4.79%, against drift +0.38, +0.45, +0.90, +1.69, +4.07. Most of the long-hold gain was a rising market; the selection edge over drift grows from +0.3 points at 2 h to +0.7 at 24 h.
- **Short closing times (fast books):** edge over drift for 5m books -0.02 (0.5 h), +0.03 (1 h), +0.38 (2 h), +0.38 (3 h), +0.28 (4 h), +0.23 (6 h); best return per hour held at 2 h (+0.39%/h). 15m books -0.03, +0.09, +0.35, **+0.50 (3 h)**, +0.33, -0.16. The books close at a median 0.5 h (5m) and 1 h (15m), before their edge appears.
Caveats: three days, a rising market, horizons chosen after seeing the data.
Books added (live paper, each differs from its control only in `min_hold_bars`, enforced by `tests/test_hold_time_books.py`; guard B counts the hold from the real entry, and a held position stays through rotation and channel exits, while the ladder and kill switches still act): `momentum_top3_15m_hold12h` (48 bars) and `momentum_top3_15m_hold3h` (12 bars), control `momentum_top3_15m`; `momentum_top3_5m_hold2h` (24 bars), control `momentum_top3_5m`. Stop rule: below its control over the same days after 14 live days (2026-10-10).

## desk-dashboard-2026-09-26

Operator request 2026-09-26: the dashboard was cluttered and needed too much scrolling; build a clean, insightful one. `/` now serves `bot/desk.html` on a compact `/api/desk` payload (`bot/desk.py`, about 81 KB against the full view's 680 KB); the previous page moved to `/full`, and `/heatmap` and `/analysis` are unchanged.
One screen at 1512x900 with no page scroll (checked with a headless Chrome render, all 18 books visible): header with live count; five numbers (fleet net split into realised and open, books up/down, leader, market breadth, health); books grouped by role (core 4h, short-term momentum, burst, A/B tests, short) with sparkline, return, net, realised, open, split bar, invested, holdings coloured by open P&L, and for A/B arms the lead or lag in points against the control measured from the arm's own start; a side column with fleet coin exposure, recent activity in the viewer's local time, and health alerts that count only real faults (network blips and deferred data gaps are retried by the cycle and shown only when frequent). Clicking a book opens a drawer with its equity curve over its whole life, open positions with P&L per coin, key stats and recent closed trades. Below 1100 px the layout stacks; below 700 px secondary columns hide (no horizontal page scroll at 420 px).
Backend additions to `bot.dashboard.bot_state`: `equity_curve` (30-minute closes over the book's life), `marks`, `meta.description`, `faults_last_hour`.

## full-roostoo-pool-live-replay-2026-09-26

Operator question 2026-09-26: would the bots make more trading all of Roostoo's coins instead of the top-30 pool? Live-window replay 2026-09-23 16:00Z to 2026-09-26 ~18:00Z: the live long-only rules of `momentum_top3_30m`, `15m` and `5m` run on Binance bars with the `gates.let_winners_run` simulator (ladder, drift band, 5 bps fee plus each coin's tick, no spread beyond the tick), once on the 25-coin pool and once on all 64 tradable Roostoo crypto with bars (stocks, PAXG, halted OMNI/TON excluded). Same rule, same window, only the pool differs.
| book | pool 25: return / max DD / coins traded | all 64: return / max DD / coins traded |
|---|---|---|
| 30m | +12.79% / -3.2% / 10 | +12.35% / -3.9% / 15 |
| 15m | +11.16% / -5.0% / 20 | +7.89% / -10.6% / 36 |
| 5m | +0.22% / -7.5% / 25 | -5.65% / -12.4% / 54 |
Adding the 39 thinner names lowers return and roughly doubles the drawdown at every clock, worst on the fast ones, before the wider real spreads on those names are even charged. Consistent with `#roostoo-universe-pool-size` on history (the venue list ranked on its own admits its thinnest names: Sharpe -0.15 against 1.56). Not adopted; the pool stays the top 30 by Binance volume intersected with Roostoo.

## wide-pool-book-declaration

Operator instruction 2026-09-26: keep the highest-profit short-term momentum rule and let it also run on the whole Roostoo pool to catch edge cases. `momentum_top3_30m` (+12.06% live, the best short-term book) is unchanged; `momentum_top3_30m_wide` is its exact copy with `strategy.universe_mode: venue_all` (`bot.universe.select`): every tradable Roostoo crypto pair still printing Binance bars (64 on 2026-09-26) instead of the top 30 of Binance by volume intersected with Roostoo (25). Every other setting is identical (`tests/test_wide_pool.py`). Paper, live-judged, shown on the desk as an A/B arm against `momentum_top3_30m`.
Known risk, stated once: the live-window replay put the whole pool at +12.35% against +12.79% for the 25-coin pool at 30m with a deeper drawdown (`#full-roostoo-pool-live-replay-2026-09-26`), and on history ranking inside the venue list admits its thinnest names (`#roostoo-universe-pool-size`). Wide-spread names are charged the far side by the paper fill rule (`max_spread_bps: 5`).
Stop rule: below `momentum_top3_30m` over the same days after 14 live days (2026-10-10), or the 25% drawdown kill switch.

## parallel-fetch-2026-09-26

Operator approval 2026-09-26 after a feed check: Roostoo quotes were fresh (0.1-0.3 s old) and tracked Binance at a median 0-2 bps, but the books acted a median 27-48 s after a bar close (worst about 60 s) and cycled every ~36 s against a 30 s poll, because `bot.feed.bar_frame` downloaded each symbol's bars one after another. It now fetches `FETCH_WORKERS = 8` symbols at a time on a pooled session; the single cut instant, the retry of failed symbols and the `data_gaps` reporting are unchanged (`tests/test_parallel_fetch.py`). Measured on 182 15m bars: 25 symbols 6.82 s -> 1.11 s, 64 symbols 18.16 s -> 1.94 s. Total request count is unchanged; Binance weight in use was 976 of 6,000 a minute before the change.

## bar-close-alignment-2026-09-27

Operator approval 2026-09-27, the second half of `#parallel-fetch-2026-09-26`. After the parallel download the books still acted 7-35 s after a bar close because a close was only noticed at the next 30 s poll. `Bot.loop` now sleeps `bot.run.next_sleep`: the regular poll, or until 2 s after the book's next bar close if that is sooner, so every close is decided about 3-5 s after it happens. Poll cadence between closes is unchanged; a close with incomplete data is still deferred and retried at the next poll (`incomplete_hold`). Tests: `tests/test_bar_close_alignment.py`.

## unrealised-giveback-2026-09-27

Operator question 2026-09-27: where did the unrealised gains vanish? 340 closed live positions to 2026-09-26 ~19:00Z (ladder skims collapsed), peak open gain = best excursion x notional on 5m Binance bars, giveback = peak minus banked net. Summed peaks 197,960, banked 48,084, given back 149,876 (a per-position measure; peaks are not simultaneous and cannot all be captured).
- **Host sleep: 57% of the giveback** (85,053) came from 134 positions whose hold spanned a gap of more than 10 minutes in the book's cycles, e.g. `momentum_top3_15m` NEAR peaked +5.3% and closed -565 after the 19.5 h sleep, `momentum_top3_30m_allcash` NEAR peaked +12.3% and banked +1,523.
- By exit: displaced by a stronger name 50%, channel break 44%; the 10-bar exit is late by design.
- By book: `momentum_top3_5m` 31% (46,904 given back of 56,707 peak), `momentum_top3_15m` 17%, `accel_15m` 16%; the 30m book kept 48% of its peaks.
- By coin: NEAR 22% (peak 25,454, banked -7,053), ENA 16%, LTC 13%.
- **Runners keep their gains; the non-runners bleed.** The 88 positions that were ever +3% banked 97,126 of 139,485 peak (70%); the other 252 peaked 58,475 in total and banked -49,042.
Consistent with `#live-hold-time-2026-09-26` (no take-profit helps) and `#fleet-review-2026-09-26` (sleep cost 30m/15m about 3 points): the levers are uptime and fewer weak entries (`burst_strong_15m`, the hold-time twins), not tighter exits.

## short-pullback-declaration

Operator instruction 2026-09-27, after the 17:25-19:20Z altcoin pullback (median coin -0.46% over 2 h, 21 of 25 pool coins falling, BTC flat) in which `short_accel_15m` did not fire: of 25 coins, 17 were below their 15m 20-bar low, 8 of those with negative 40-bar momentum, 1 (TRX) with a 4h breakdown and 0 falling more than 2% in an hour. `short_pullback_15m` is `short_accel_15m` without the 4h breakdown and the falling-hour filters: it shorts 15m breakdowns with negative momentum, 1.5x volume and accelerating non-blow-off downside, also inside 4h uptrends. Everything else identical (`tests/test_short_accel.py`); control `short_accel_15m`.
Stated once: shorting pullbacks inside uptrends is where the fleet's shorts lost -6,164 live and every historical short test failed; a perfectly timed short of the held coins over that pullback would have netted about +0.3% after the 0.2% round trip. Live paper test on operator decision. Stop rule: negative return after 14 live days (2026-10-11) or the 25% drawdown kill switch.

## cycle-watchdog-2026-09-27

Found 2026-09-27 04:42Z: `short_accel_15m` and `momentum_top3_5m_hold2h` were alive but had not written a cycle for 33 and 17 minutes, each holding ESTABLISHED Binance (CloudFront) sockets; every HTTP call in the cycle carries a timeout, so the block is below that (likely a stalled TLS read after the host slept on battery). The supervisor only respawns a worker that exits, so a frozen one stays frozen. `Bot.start_watchdog` (continuous mode only) now exits the process with code 3 when one cycle has run more than 240 s on the monotonic clock (machine sleep does not count), journalling `watchdog_exit` in lifecycle; the supervisor respawns it within 10 s from saved state. `tests/test_cycle_watchdog.py`.

## retired-2026-09-27

Operator instruction 2026-09-27: retire the two clear losers. `momentum_top3_30m_wide` (whole-pool universe, `#wide-pool-book-declaration`) lost 3.09 points against `momentum_top3_30m` in about 11 h, as the live-window replay predicted (`#full-roostoo-pool-live-replay-2026-09-26`); `momentum_top3_15m_hold12h` (`#live-hold-time-2026-09-26`) lost 3,253 since the fleet peak, its 12 h hold keeping positions through the altcoin pullback. Stopped, removed from `run_bots.sh`, the dashboard, the desk and the gates; live data in `live/_archive/retired-2026-09-27/`; configs and the `universe_mode` option kept for the record. The hold3h and hold2h twins keep running.

## rally-capture-score-2026-09-27

Operator question 2026-09-27: do the bots pick up momentum and capture the rally? Live only: every rally of at least 4% from a 15m low to a later high within 24 h in the 25-coin pool, 2026-09-23 16:00Z to 2026-09-27 ~05:30Z: 58 rallies on 22 coins, median 8.8%. Per book, detection = held the coin during the rally, capture = banked net over (first position notional x rally size); long positions only.
| book | rallies detected | median capture | entries inside a rally |
|---|---|---|---|
| donchian_4h | 26% | 64% | 54% |
| momentum_top3_1h_allcash / 1h_long | 23% | 54% / 42% | 70% |
| momentum_top3_30m_allcash / 30m | 26% / 28% | 37% / 25% | 75% / 81% |
| momentum_top3_full / lock | 16% | 27-29% | 33% |
| momentum_top3_15m | 41% | 6% | 78% |
| accel_15m | 56% | 0% | 65% |
| momentum_top3_5m | 64% | -1% | 64% |
Fast clocks see most rallies and keep almost none of them (a 10-bar exit of 50 min to 2.5 h is shaken out by the first pullback); slow clocks keep 25-64% of the rallies they catch but catch only 16-28%. No book detects more than two thirds.
Added `momentum_top3_15m_slowexit`: `momentum_top3_15m` exactly as live with `strategy.exit_bars` 10 -> 40 (exit below the prior 40-bar = 10 h low, about the 1h book's exit): fast entry, slow exit. One knob (`tests/test_hold_time_books.py`); control `momentum_top3_15m`; stop rule below its control after 14 live days (2026-10-11). Distinct from `#exit-clock-outcome` (which made the 4h book's exit faster) and from the fixed minimum holds (this exit still follows price).

## binance-rate-guard-2026-09-27

2026-09-27 05:04-05:05Z Binance answered 429 then 418 (IP ban, Retry-After 70 s, used weight 4,650 of 6,000 a minute): heavy one-off analysis scripts (path forensics, the rally scan) ran on top of the 19 books' synchronised bar-close fetches. Binance escalates repeat 418 bans from minutes to days, which during the competition would stop the book. `bot.feed.binance_get` now carries every live Binance call: on 429/418 it records Retry-After and fails further calls immediately without touching the network until it passes; at 4,800 used weight a minute it pauses to the next minute. The cycle's existing retry and data-gap deferral handle the failures. Operating rule: heavy analysis scripts are not run while the fleet is fetching at a bar close, and are run one at a time. `tests/test_binance_guard.py`.

## desk-closed-trades-2026-09-27

Operator request 2026-09-27: show recent closed trades and their P&L on the desk so they can be tracked in one place.
The Books card has a second tab, Closed trades: every book's closed trades newest first, with the book, coin, entry and exit price, size, hold, net P&L and net %, filtered by window (1h, 6h, 24h, all), book group and book, and a summary of count, net, wins and losses, win rate, fees, best and worst.
The snapshot now carries every trade closed in the last 48 h per book (at least 60), not the last 60, because a 5m book closes about 60 a day.
A book whose list is still truncated sets where the feed stops being complete, and the page says so instead of silently mixing a busy book's partial history with a quiet book's full one.
Display only; no trading path reads it.

## closed-trade-kinds-2026-09-27

Operator request 2026-09-27: review the last hour and improve.
The Closed trades tab counted every FIFO slice as a trade, so a rebalance that sold part of ENA to fund a FIL entry read as an ENA loss although most of the position was still held.
Each closed slice now carries `exit_kind`: `exit` when the fill leaves the position flat (below the 1 USD residue), `skim` when a booking-ladder skim for the same coin was journalled within 30 s of the fill, otherwise `trim`.
The desk tags each row and breaks the window's P&L down by kind.
Fleet to 2026-09-27 16:58Z: skims 260 slices +51,783 net (fees 962), trims 252 +4,656 (fees 3,469), full exits 607 -9,000 (fees 16,342).
FIFO attribution explains part of this: a skim books the gain on the oldest shares, and the exit books the remainder from the same entry price after any giveback, while every loser that never reached +3% ends as an exit.
It is still the plainest live evidence so far that the realised profit is harvested by the ladder and that the exit leg, with most of the fees, is where it leaks.
Display and reporting only; no trading path reads the label.

## roostoo-keys-2026-09-30

Roostoo issued two key pairs on 2026-09-30: a TEST pair on the general portfolio and a COMPETITION pair for round 1.
Both live in the gitignored `.env` as `ROOSTOO_TEST_*` and `ROOSTOO_COMP_*`; a config's `meta.keyset` picks one, so only the book whose config names `comp` can reach the competition account (`bot.settings.credentials`).
The official FAQ (read 2026-09-30) says the main round started 2026-09-30 and the first trade is due 2026-10-01 20:00 GMT+8 (12:00 UTC); limits are 30 calls a minute across every endpoint, EC2 in Sydney via Session Manager, an open-source GitHub repo, every change committed, and no manual stop, override or discretionary trade.
The competition key answered `/v3/balance` with `not yet a member of this competition` at 14:05Z; the test account holds 50,000 USD (`InitialWallet` 50,000, so the 100k on the event page is not this venue's number).

`gates/roostoo_smoke.py` ran the full order lifecycle on the TEST account (`results/roostoo_smoke_test.json`):
- MARKET orders are TAKER at `CommissionPercent` 0.001 (0.10%), fee in USD; a resting LIMIT is MAKER at 0.0005 (0.05%). This answers organiser questions 1 and 2.
- A MARKET BTC buy and sell filled at exactly the quoted ask and bid, zero slippage.
- A sub-1 USD order is rejected as `quantity error`.
- A LIMIT buy at the bid filled within 30 seconds.
- A short opens at MaxBid with a 0.10% open fee and a 0.10% close fee; collateral sits in the USD `Lock` and `ShortCollateral` fields of the spot wallet.

Four live-API mismatches were found and fixed; each would have broken the live book while every paper book looked fine:
1. `/v3/balance` returns `SpotWallet` and `MarginWallet`, not the README's `Wallet`; `balance()` raised a KeyError, so the bot could never read its cash.
2. `/v3/query_order` lists orders under `OrderMatched`, not `OrderDetails`, and reads `pending_only` only as the string `TRUE`; the bot never saw its own resting orders, so it re-sent sells and never cancelled stale limits.
3. The same endpoint answers `Success: false, no order matched` when nothing matches; the adapter raised, so every sweep of an idle book counted an error toward the error-rate kill switch.
4. `bot.intents._heuristic` never looked inside `OrderDetails`, so after a crash an order that did reach the venue was recorded as never sent.

A fifth defect sat in the live cycle: while the wallet cannot be read the book marked equity from its 100,000 default, and the first real read (50,000) looked like a 50% drawdown, which trips the 25% kill switch.
Now a live cycle with no readable wallet journals `wallet_unavailable`, writes no equity and places nothing (`bot.run.Bot.cycle`).
Regression tests replay the exact live payloads: `tests/test_roostoo_live_shapes.py`, `tests/test_entry_retry.py`.

The Data Sources Pack (read 2026-09-30) lists Binance Vision, CryptoDataDownload and CoinAPI.
The research already uses Binance klines and the Vision archives; CDD's breadth, funding and on-chain series belong to families `FINDINGS.md` records as dead, so nothing new is tested.
It did add one resilience fix: every public Binance call now fails over to `data-api.binance.vision` (same endpoints) on a connection error or 403/451/5xx, so the bars survive a regional block or outage on EC2 (`data.binance.rest_get`); 418/429 are never retried elsewhere.

## competition-book-2026-09-30

Operator decision 2026-09-30: the competition book is `momentum_top3_30m`, target lock OFF ("go all in").
Evidence at decision time (`gates.fleet_review`, 166 h live paper, online only 31%): +9.17%, max drawdown -9.2%, 83 trades, 72% of trades winners, 1.6k fees; the best return per unit of drawdown in the fleet.
Its 2026-09-23 backtest verdict (`#lowtf-paper-bots`) was a FAIL before the later confirmation rules (`#breakout-quality-outcome`, `#let-winners-run-outcome`); this is a forward-evidence choice, not a backtest pass, and is recorded as such.

`config/competition.yaml` copies every rule parameter from `config/momentum_top3_30m.yaml` unchanged and differs in three places only: it is not paper, `meta.keyset: comp`, and the derisk ramp is moved past the window because the round end date is unconfirmed (FAQ 2026-09-30 versus the event page's 2026-10-17) and the venue auto-liquidates at the end.
`config/competition_rehearsal.yaml` is the identical rule on the TEST account, so real fills are measured beside the competition book; `momentum_top3_30m` stays as the paper control of both (`bot/dashboard.py` CONTROL_OF).
Both start with `./run_bots.sh live`, which sets `ROOSTOO_DRY_RUN=0` for those two configs only.

## competition-exit-declaration

Declared in `config/competition_exit.yaml` and committed (857ea2f) before any number was computed.
Operator request 2026-09-30: draw insights from the fleet's most successful trades and modify and scale the competition strategy for a high return.
Live paper evidence (2,297 closed lots, 20 books, 2026-09-22..30): lots held under 2 h netted -74.9k and lots held over 4 h +81.1k; skim-ladder sales netted +103.4k at a 99% win rate while channel exits netted -105.1k; longs +13.4k, shorts -12.4k; entries at 04-12Z earned and 16-24Z lost; AAVE, AVAX and ONDO carried most of the profit.
Only the hold-time pattern has a mechanism the record has not already killed: a 10-bar exit on 30m sells the routine post-breakout pullback.
Hour-of-day (`#intraday-structure-outcome`), concentration (`#max-return-levers-outcome`), clock ensembles (`#lowtf-clock-ensemble-outcome`), shorts and idle-cash redeployment (`#idle-cash-declaration`) are dead families and were not re-tested; coin identity is not forecastable.

## competition-exit-outcome

`python3 -m gates.competition_exit`, `results/competition_exit.json`: NULL, the competition rule keeps `exit_bars` 10.
| arm (30m, every 14-day window) | fit median | holdout median | holdout P(>5%) | holdout P(>10%) | holdout worst |
|---|---|---|---|---|---|
| C0 live, exit 10 | -0.76% | +1.13% | 0.35 | 0.19 | -22.3% |
| E20 exit 20 | +0.70% | +0.11% | 0.29 | 0.16 | -22.2% |
| E40 exit 40 | +0.44% | +0.16% | 0.29 | 0.19 | -23.1% |
| H6_ctrl price-blind 3 h hold | -0.38% | +0.58% | 0.33 | 0.21 | -19.9% |
| S15_slowexit (15m, exit 40) | -4.27% | -4.59% | 0.24 | 0.12 | -31.5% |
Slower exits win the fit period and lose the holdout, and lose to the price-blind control there; the live split between short and long holds was mostly a rising market and survivorship (a position lasts long because it kept rising).
The 15m slow-exit book is worse than C0 everywhere, so its live +7.5% is not evidence for switching clocks.
Honest expectation for the competition book on 2025-26 history: median fortnight +1.1%, a 35% chance of beating +5% and 19% of beating +10%, worst fortnight -22%.
Five trials recorded in `config/trials.yaml`.

## desk-competition-only-2026-09-30

Operator request 2026-09-30: the desk dashboard shows only the competition books from now on.
`/` (`bot/desk.py` `DESK_GROUPS`) lists `competition` and `competition_rehearsal`; totals, activity, alerts and the closed-trade feed are computed on those alone, and a "Competition account" tile shows whether the account is active.
The paper fleet keeps running and stays visible on `/full`.

## adaptive-clock-declaration

Declared in `config/adaptive_clock.yaml` and committed (22b147d) before any number was computed.
Operator request 2026-09-30: the bot should be dynamic, keep learning, identify patterns and adapt to the market.
Coin-level adaptation is dead (`#coin-selection-does-not-persist`); the one untested form with a mechanism is strategy momentum across clocks: hold, each day, the clock (15m, 30m, 1h, same contenders rule) whose trailing return was best.

## adaptive-clock-outcome

`python3 -m gates.adaptive_clock`, `results/adaptive_clock.json`: NEAR-MISS, not adopted; the competition book stays on 30m.
All arms are simulated on one 15m grid (30m and 1h weights carried by close time), so C0 here (+0.90% holdout) differs slightly from `#competition-exit-outcome` (+1.13%, native 30m grid).
| arm | fit median | holdout median | holdout P(>5%) | holdout P(>10%) | holdout worst | clock share |
|---|---|---|---|---|---|---|
| C0 30m always | -0.75% | +0.90% | 0.33 | 0.19 | -22.4% | 30m 100% |
| AD7 best trailing 7 d | +0.77% | +1.17% | 0.30 | 0.20 | -28.6% | 1h 47%, 30m 37%, 15m 16% |
| AD3 best trailing 3 d | -0.61% | -0.29% | 0.24 | 0.14 | -25.8% | 1h 42%, 30m 36%, 15m 22% |
| RND_ctrl random daily | -3.13% | -1.18% | 0.33 | 0.22 | -28.4% | even |
AD7 passes three of five conditions (holdout median, fit median, beats random) and fails two (holdout P(>5%) 0.30 < 0.33; worst -28.6% is 6.3 points below C0, beyond the 5-point limit).
Clock persistence is real but weak: the trailing 7-day clock ranking correlates 0.13 (Spearman) with the next day's.
The random control shows switching itself is expensive (turnover 73 against 44 per fortnight); AD7's gain over it is selection, and its loss in the tail is switching into the fast clock just before trends end.
Seven trials recorded (with `#competition-exit-outcome`'s five, twelve today).

## paper-fleet-stopped-2026-09-30

Operator delegated the call 2026-09-30 ("we will work on the competition bots only"): every paper book, the Binance testnet book, the source hub, scanner, paper lab and the other session's `momentum_top3_1h_long` launchd job were stopped; configs, state and journals stay on disk and restart with `./run_bots.sh start` or `launchctl bootstrap`.
Still running: `competition`, `competition_rehearsal`, the paper twin `momentum_top3_30m` (same rule, the live books' control on the dashboard), the dashboards and keep-awake.
`run_bots.sh` CONFIGS now defaults to `momentum_top3_30m` alone; the old list is `PAPER_FLEET` (`./run_bots.sh fleet` restarts it).

## best-trades-study-2026-09-30

Operator request 2026-09-30: check the other bots and study the most profitable trades. Diagnostic only; nothing selected, no trial spent.
Paper fleet final (stopped 2026-09-30 ~16:00Z, `gates.fleet_review`): best `momentum_top3_5m` +9.9%, `momentum_top3_30m` +7.9%, `momentum_top3_15m` +5.7%, `momentum_top3_30m_allcash` +5.6%, `momentum_top3_15m_slowexit` +5.1%; worst `momentum_top3_1h_allcash` -12.3%, `momentum_top3_1h_long` -9.8%, `momentum_top3_15m_hold3h` -6.6%, both short books -3.5% and -5.9%; all online only ~31% of the time.
Method: 2,297 closed lots collapsed to 1,114 long positions, grouped into 418 entry clusters (same coin within 2 h across books) so one move held by nine books counts once; twelve entry features rebuilt from Binance 15m bars closed before each entry (1h/4h/24h/3d return, 1h volume against its 24h median, distance from the 24h and 80h high, 24h volatility, cross-sectional 24h rank, breadth, BTC 24h return, hour).
- **Profit is a few big trends.** 34% of entry clusters win; winners average +2.14% and losers -1.30% (payoff 1.65). The top 5% of clusters earned 71% of all gross gains, the top 10% 89%, the top 20% 98%.
- **Best and worst entries look the same at entry.** Both extreme quintiles had high momentum (cross-sectional rank 0.86 and 0.83) and above-normal volume (1.5x and 1.7x); the difference is what happened after entry.
- The strongest separators were breadth (Spearman -0.115) and BTC 24h return (-0.108): the best entries came when the whole market was less extended. At n = 418 that is z = 2.35, below the 2.87 a twelve-feature Bonferroni test needs, so it is not significant. It also belongs to dead families: ranking on the residual is destructive (`idio_40`, -67% worst window) and market crowding gates are null (`#positioning-edges-outcome`). Not tested further.
- Winners were held a median 5.5 h and losers 2.2 h, which is the exit rule at work, not a choice; slower exits were tested and are null (`#competition-exit-outcome`).
Implication: the rule earns by being in the market when one of a handful of big trends starts. The lever that matters is not a filter but never missing those entries, which is uptime (the fleet was offline ~69% of the time); EC2 is the fix.

## scalper-adaptive-declaration

Operator instruction 2026-09-30: a short-term scalper with dynamic adjusting, making trades, on paper side by side with the competition book.
Evidence stated before launch: no 5m history is cached, so the book is untested; sub-15-minute trades had no gross edge live (+4.8 bps against 12.2 bps of fees, `#min-hold-5m`); fixed 5m books lost in the offline replay (`#fleet-review-2026-09-26`); the adaptive-clock analogue on 15m/30m/1h was a near-miss (`#adaptive-clock-outcome`).
Rule (`config/scalper_adaptive.yaml`, `bot/scalper_adaptive_run.py`): the bot runs on 5m bars; every 60 minutes it replays the live contenders rules of `momentum_top3_5m`, `momentum_top3_15m` and `competition` (30m) on the last 7 days of Binance bars with `gates.let_winners_run.simulate` (ladder, 5 bps fee, tick) and trades the clock with the best trailing return, keeping the current clock unless another leads it by at least 1 point.
A slower clock's weights reach the 5m book by bar close time (`signals.exit_clock.to_fast`); its minimum hold is converted to 5m bars; entry guard, ladder and kill switches are inherited unchanged; long only, lock off.
Paper only. Side-by-side controls on the desk: the fixed-clock twins `momentum_top3_5m`, `momentum_top3_15m`, `momentum_top3_30m`.
Stop rule: after 7 live days, if it trails the best fixed-clock twin on return, it is stopped.
`bot.feed.closed_bars` now pages backwards past Binance's 1,000-bar limit so a 7-day 5m window can be read.

## heatmap-running-books-2026-09-30

The heatmap's L/S badges read the last cycle of every registered book, stopped ones included, so after the paper fleet stopped it showed eight books long ENA and shorts on PUMP, AVAX and SOL that no running book held.
`bot.heatmap.live_books` now counts only books whose last cycle is under 10 minutes old; real holdings at 16:20Z were SUI (3 books), ENA (2), PUMP (1), TRUMP (1).

## signal-scan-2026-09-30

Operator question 2026-09-30, from the heatmap: are the momentum timeframes giving signals, and how agile are the bots. Tool: `python3 -m gates.signal_scan` (per clock: pool coins in a breakout, fresh breakouts, momentum, volume multiple, what blocks each, what the rule holds).
Scan at 16:20Z: 5m 23 of 25 coins in a breakout (rule holds PUMP, SUI, TRUMP); 15m 3 (holds ENA, SUI); **30m 7, every one blocked by the 4h confirmation** (WLD +8.6%, ENA +7.7%, ZEC, SUI), so the competition rule is in cash; 1h 20, all blocked by the 4h confirmation except its sticky TRX; 4h 6 (holds PUMP, AAVE, XLM).
**Reaction speed:** with the Mac awake every book decides 6 to 14 s after its bar closes; the long gaps on 2026-09-30 were machine sleep until 13:52Z, restarts at ~16:00Z, and one 3-minute stall while backtests loaded the CPU (run research beside the fleet one job at a time).
**Signal speed:** on the day's biggest pool movers, measured from each coin's 24 h low, the first 20-bar breakout fired after this share of the eventual move: 5m 12-31%, 15m 20-41%, 30m 20-59%, 1h 42-88% (PUMP 81% on 5m, never on slower clocks). Faster clocks see moves earlier; `#rally-capture-score-2026-09-27` records that they keep less of them.
**The 4h confirmation over the last 7 days** (live-rule simulation, fees and ticks): 30m +5.1% with it against +12.5% without; 1h -3.2% against +0.4%; 15m (which runs without it) -2.4% with it against +11.6% without. On 2023-26 history the same filter is what made the 30m rule positive (`#breakout-quality-outcome`: 30m holdout median -3.39% without, +1.19% with, beating its permuted-coin control; 1h -3.34% to +0.46%).
Reading: this was a week of intraday bursts that 4h channels did not confirm. One week against 20 months of holdout does not overturn the filter; the competition rule keeps it. The adaptive scalper already covers this state, since its pool includes the 15m rule without the filter, and it chose 15m at its first selection.

## walkforward-live-declaration

Operator instruction 2026-09-30: validate walk-forward in the live market, not on a backtest; find what works on the current timeframe and conditions.
`wf_live` (`config/wf_live.yaml`, run by `bot/scalper_adaptive_run.py`, PAPER): every 60 minutes it replays 16 variants of the live contenders rule (5m, 15m, 30m, 1h clocks, each with the 4h confirmation on or off and the 1.5x volume confirmation on or off; each clock's base config is its live book's) on the last 3 days of Binance bars with the backtest's simulator (ladder, 5 bps fee, tick), trades the leader, and keeps the current variant unless another leads by 1 point.
The walk-forward record is the point: at every re-selection the `walkforward` journal stream stores what EVERY variant earned from the previous selection to now, on bars that did not exist when the previous pick was made. `python3 -m gates.wf_report` summarises it: the pick's cumulative forward return against the mean variant, the best-in-hindsight variant and the fixed competition variant (`30m|htf1|vol1.5`), and the pick's average rank.
`cash` is a seventeenth candidate scored at 0%: when every variant lost over the window the book stands aside instead of trading the least-bad loser (added before any forward record existed, after the first selection found all 16 variants negative over the last 3 days: best `1h|htf0|vol0` -0.22%, the competition variant `30m|htf1|vol1.5` -7.90%).
A 3-day window chases current conditions and will switch often; with 16 candidates the best trailing score is biased upward, which is exactly what the forward record measures.
Stop rule: after 7 live days, if the pick's cumulative forward return is not above the mean variant's, live selection adds nothing and the book stops.

## hedge-explorer-declaration

Operator instruction 2026-09-30: take the trades, hold them, and adjust as per our profits so we learn about the market conditions.
`hedge_explorer` (`config/hedge_explorer.yaml`, `bot/hedge_explorer_run.py`, PAPER): capital is split across the same 16 variants as `wf_live` plus cash, starting equal. The book holds the capital-weighted blend of every variant's current target, so every entry any variant takes is taken at that variant's share, and each position is held and exited under its own variant's rule (20-bar breakout, 10-bar exit, sticky slots, ladder); a 3-bar (15-minute) live minimum hold applies to the blend.
Every 60 minutes each variant's share is multiplied by exp(0.5 x its return since the previous update, in percent), renormalised, and floored at 1% so no variant stops being explored (the Hedge rule of Freund and Schapire, whose regret against the best variant in hindsight grows only with the square root of time). Returns are measured on bars closed after the previous update, so the weights learn only from the live market.
The `hedge` journal stream records every update: each variant's return, the book's weighted return, the equal-weight mean, and the weights before and after; the desk shows the top weights.
Difference from `wf_live`: that book puts everything in one variant (winner takes all); this one keeps a portfolio and moves it gradually, so it takes many more, smaller trades.
Stop rule: after 7 live days, if its return is not above the equal-weight blend of the same variants, the learning adds nothing.

## burst-drivers-declaration

Declared in `config/burst_drivers.yaml` (caad329) before any number, with the exit test added as a declared addendum (ed867e0) after the driver results and before any exit number.
Operator request 2026-09-30: exploit short-term burst trends; find whether sudden upward moves are caused by spiked volume or other factors; go all in on such trends, keep Sharpe smooth and book profits.
Event: a pool coin up at least 2% over three 5m bars, detected at the 5m close, one per coin per hour; 30 days of Binance 5m bars to 2026-09-30 17:15Z, discovery = first 15 days, validation = last 15.

## burst-drivers-outcome

`python3 -m gates.burst_drivers --cache <5m parquet>`, `results/burst_drivers.json`: NULL on every driver and every exit. 573 bursts (209 discovery, 364 validation, so bursts nearly doubled in the recent half).
**What happens after a burst** (net of 0.10% round trip, from the detection close): +15 min +0.19% / -0.11%; +1 h -0.08% / -0.08%; +4 h +0.45% (t 1.4) / +0.13% (t 0.7); 40-46% of bursts are higher 1-4 h later. Mean best price within 4 h +4.1% / +3.3%, so the upside after detection exists but is given back.
**Drivers** (top against bottom tercile of +4 h net return, discovery then validation): volume spike +1.75 (t 2.3) then -0.03; aggressive buying (taker share) -0.56 then +0.92; BTC moving at the same time -1.39 (t -2.1) then +0.09; market breadth -1.78 (t -2.6) then -0.30; prior 4 h momentum +2.23 (t 3.1) then -0.11; breaking the 24 h high +1.41 (t 2.1) then -0.51; trade size +0.34 then -1.12 (t -2.3); burst size -0.39 then -1.10 (t -2.2). None keeps its sign with |t| >= 2 in both halves. In the first half a volume-backed, coin-specific burst that broke the 24 h high after a rising 4 h did continue; in the last 15 days none of that holds.
**Exits** (mean net per trade, discovery / validation; random entries with the same exits in brackets): take-profit +1.5% no stop +0.36% (t 2.6) [-0.02] / -0.00% [+0.20]; +2% no stop +0.47% (t 3.0) [+0.19] / -0.01% [+0.06]; +3% no stop +0.36% / +0.08% (t 0.5); every -1.5% stop variant is worse, and negative in validation at t -2.1 to -3.3. No combination is positive with t >= 2 in validation, so no burst book is built.
Reading: the burst regime changed around 2026-09-15; bursts became more frequent and stopped following through. Stops cut the Sharpe rather than smoothing it. The live learning books (`#walkforward-live-declaration`, `#hedge-explorer-declaration`) are the mechanism that detects when breakouts start paying again. Eighteen trials recorded.

## burst-rider-override-2026-09-30

Operator instruction 2026-09-30 ("go ahead"), overriding the pre-registered rule of `#burst-drivers-outcome`, which built no burst book: the burst rider runs as one more style inside `hedge_explorer`, where it receives capital only if it earns in the live market.
Rule (`signals/burst_rider.py`): on 5m bars, buy at the close of a bar whose 3-bar return is at least +2%, at most 3 names at 1/3 each, one entry per coin per hour; close at the first later bar whose high reaches +2% above the entry close, or after 48 bars (4 h). No stop (every stop variant was worse in both halves).
Known gaps stated once: the study assumed a resting limit filled at exactly +2%; the blended book sells at that bar's close instead, and the hourly Hedge update scores the arm on closes. In the study's recent half the rule was break-even (-0.01% a trade), so expect its share to shrink unless bursts start following through.
`hedge_explorer` now has 18 arms: 16 breakout variants, the burst rider and cash; the new arm enters at an equal share and existing shares are renormalised.

## progress-review-2026-09-30

Operator instruction 2026-09-30: analyse the bots' logs on a timely basis to track progress: trades, fills, booked profits, Sharpe, Sortino, Calmar.
`python3 -m gates.progress` runs every hour under `./run_bots.sh progress` and reviews every book that cycled in the last 10 minutes: total and 24 h return; hourly Sharpe and Sortino annualised by sqrt(24 x 365) and return over maximum drawdown (Calmar-like, not annualised), all shown only after 24 h of marks, since a day of equity annualised explodes; orders sent, order failures and stale cancels, fill rate; closed trades, win rate, realised P&L, fees; profit-ladder sales (booked profits) and their P&L; uptime on a 5-minute grid; faults, with recovered network blips counted separately (`bot.dashboard.transient`).
Output: `results/progress/latest.json` and one row per book per hour appended to `results/progress/history.jsonl`; alerts for uptime under 90%, fill rate under 90%, a 24 h drawdown beyond -5%, or more than 20 real faults. The desk shows Sharpe, Sortino and return over drawdown per book from the latest review.
First review (17:27Z): `momentum_top3_5m` Sharpe 6.1, Sortino 11.3, return/DD 1.2 over its week; `momentum_top3_30m` 5.6, 9.7, 0.9; `momentum_top3_15m` 4.6, 7.9, 0.5; the three books were online about 44% of the last 24 h (morning Mac sleep); every order in every book filled.

## paper-reset-2026-09-30

Operator request 2026-09-30: every bot should count from the latest start, not from earlier runs.
At 17:34Z the six paper books (`momentum_top3_5m`, `momentum_top3_15m`, `momentum_top3_30m`, `scalper_adaptive`, `wf_live`, `hedge_explorer`) were stopped, their journals and state moved to `live/_archive/reset-20260930T1732Z/`, and all six restarted together from 100,000, so their returns, ratios and learning weights share one start. Before the reset the fixed-clock books counted from 2026-09-23 (+9.8%, +5.9%, +7.9%); the learning books from 16:08-16:45Z the same day.
`competition_rehearsal` is not reset: its equity is the Roostoo test account's own wallet (started 14:22Z). `competition` has not traded.
A shell loop moved only one of the six directories on the first attempt (the `rtk` wrapper also listed the archive as empty); the books were stopped again within two minutes, the rest moved with an explicit script and verified, and the brief restart of `momentum_top3_5m` is archived as `momentum_top3_5m_restart_stub`.

## dynamic-bot-4h-2026-10-01

Operator instruction 2026-10-01 (00:10 IST): keep ONE dynamic bot whose holding style changes with market conditions, from 5 minutes to 4 hours, under the existing strategy logic.
`wf_live` is that bot. Its grid gained the 4h clock (`config/wf_live.yaml`: the 30m competition rule's contenders parameters and 20/10 channel on 4h bars, volume confirmation on or off; the 4h confirmation is skipped on 4h, where it only repeats the book's own breakout), so it now scores 18 styles (5m, 15m, 30m, 1h with each filter combination, 4h with and without volume) plus cash every hour on the last 3 days and trades the leader with the 1-point switch margin (`#walkforward-live-declaration`).
A 3-day window holds only about 18 4h bars, so a 4h score reflects one or two positions; that is accepted as part of letting the market choose.
`scalper_adaptive` (a 7-day subset of the same choice) and `hedge_explorer` (the capital-blend learner, with the burst rider) were stopped and archived with `wf_live`'s first hour to `live/_archive/dynamic-consolidation-20260930T1842Z/`; configs and code stay for revival. `wf_live` restarted fresh at 18:43Z; the fixed 5m, 15m and 30m books keep their 17:34Z start as baselines, alongside `competition_rehearsal` and the waiting `competition` book.

## dynamic-bot-shorts-and-ride-2026-10-01

Operator instruction 2026-10-01: a bot that sits in cash cannot make profits; allow shorting when conditions favour it, and ride a coin that is up about +2% and strong for a further +5-6%.
The dynamic bot's menu (`config/wf_live.yaml`) gained three styles, chosen like every other only when they earned most over the last 3 days: `short|15m` and `short|1h`, the live `short_pullback_15m` rule (short-only 20/10 breakdowns with negative momentum, 1.5x volume, accelerating but not blown-off downside, sticky, 4-bar minimum hold) on 15m and 1h bars; and `ride|+5%|24h`, the burst rider (`signals/burst_rider.py`) buying a +2% 15-minute jump and holding for +5% or 24 hours, at most 3 names. Shorts are enabled on the book (Roostoo short: MARKET both legs, 0.1% a side; the ladder books shorts too). 21 styles plus cash.
Evidence stated once: short books lost on live paper (`short_accel_15m` -3.5%, `short_pullback_15m` -5.9% over 2026-09-26..30) and breakdown shorts continue less than half the time (`#lowtf-exhaustion-outcome`); a +5% take-profit on bursts was +0.24% / +0.08% a trade at a 4 h horizon (`#burst-drivers-outcome`, not significant), and entries after a >2% hour reach +5% within 24 h about 48% of the time (`#rally-capture-15m-2026-09-26`). Letting the live window choose is the operator's answer to that record; cash remains a choice because it beats every losing style.
The live target now always replays the chosen style's own bars for at least its maximum hold (`bars_needed`), so a 24 h ride is not dropped by a short replay window. `wf_live` restarted fresh with the new menu; its first 18-style hour is archived.

## confirmations-and-residual-declaration

Operator instruction 2026-10-01: add order-flow and futures confirmations to the dynamic bot, and strip the high cross-coin correlation out with PCA or whatever works best. Declared before any number was computed; the live 3-day window is the judge, as for every menu style (`#walkforward-live-declaration`).
New menu styles in `config/wf_live.yaml`, each on the 30m and 1h clocks with the 1.5x volume confirmation and no 4h confirmation:
- `flow|*` order flow: a new long needs taker-buy quote volume above 50% of the entry bar's quote volume (aggressive buyers), a new short below 50%. Mechanism: breakouts carried by market orders reflect urgent demand; passive-fill rallies are thin. Nearest record: `B2t_vol_taker` on 1h (`#breakout-quality-outcome`), fit better, holdout slightly worse, worst window shallower.
- `oi|*` futures open interest: a new long needs the coin's perpetual open interest (USD, Binance `openInterestHist`, read at or before the bar close) to have risen over the last 4 bars. Mechanism: price up with open interest up is new money entering; price up with open interest down is short covering, which fades. Nearest record: positioning features were null as rankers and gates at 4h (`#positioning-edges-outcome`); never tried as an entry confirmation on 30m/1h.
- `resid|*` residual breakout: the contenders rule run on each coin's market-neutral price, built from log returns minus beta times the equal-weight market return, beta an exponentially weighted estimate with a 3-day half-life using only bars before the current one; positions and P&L stay in the real coins. Mechanism: when about 84% of 4h variance is common (`#coin-selection-does-not-persist`), a raw breakout is mostly the market moving; a residual breakout is the coin moving on its own. Nearest record: ranking on a correlation residual at 4h was destructive (`idio_40`, -67% worst window); this uses the residual only for the breakout signal on faster clocks.
The equal-weight market return stands in for the first principal component; `python3 -m gates.market_structure` measures how close they are, and reports the live correlation structure: variance share of the first three components, the effective number of independent bets, each coin's beta and residual momentum, and clusters of coins that move together.
Selection bias grows with the menu (27 styles plus cash on 3 days of data); the forward record in the `walkforward` journal is what measures it.

## market-structure-2026-10-01

First `python3 -m gates.market_structure` (2026-09-30 ~19:00Z, 25-coin pool, last 7 days of 1h returns): the first principal component explains 60% of variance (second and third 4% each), mean pair correlation 0.56, effective independent bets 2.7 of 25; the equal-weight market return tracks the first component at 0.99, so the residual styles' equal-weight factor is the first component in practice. Over the last 30 days (72 h windows every 12 h) the first-component share ranged 42% to 77%; 65% now.
One block of ten moves as one (correlation >= 0.7): ADA, BNB, BTC, DOGE, ETH, PEPE, SOL, TAO, TRUMP, XRP; ARB and UNI pair. Strongest market-neutral 24 h moves: WLD +6.9%, NEAR +5.9%, ENA +5.6%; weakest AAVE -4.2%, FIL -4.0%, AVAX -3.0%. Most market-driven by R^2: DOGE 0.85, ADA 0.83, PEPE 0.77, SOL 0.76, XRP 0.74.
Practical reading: three positions inside the big block are one bet, not three. The hourly review loop now reruns this analysis and the desk shows the factor share, effective bets, the block and the residual leaders.
First menu scores with the new styles (19:02Z, last 3 days): cash 0.00%; `1h|htf0|vol0` -0.17%; `oi|1h` -0.23%; `resid|30m` -0.69%; ride -1.20%; `flow|30m` -3.00%; `flow|1h` -3.21%; `resid|1h` -4.54%; `oi|30m` -5.23%. The dynamic bot restarted fresh with 27 styles plus cash; the 21-style hour is archived.

## pick-across-blocks-2026-10-01

Operator instruction 2026-10-01: add the pick-across-blocks style to the dynamic bot. Motivated by `#market-structure-2026-10-01` (2.7 effective bets among 25 coins; ten coins move as one block), so three positions inside one block are one bet.
`signals/blocks.py`: blocks are average-linkage clusters of trailing log-return correlations (a pair joins at correlation >= 0.7), recomputed every 12 bars from the preceding `window_bars` only (144 bars = 3 days on 30m, 72 = 3 days on 1h). The contenders rule runs with room for 8 names; each bar keeps held names first, then the strongest, at most one per block and 3 in all, sized by strength with the 0.5 cap.
Menu arms (`config/wf_live.yaml`): `blocks|30m` = the competition rule exactly plus block diversity; `blocks|1h` = the 1h rule without filters (the menu's best recent style) plus block diversity. 29 styles plus cash. Distinct from the correlation cap tested earlier (`config/correlation_cap.yaml`), which limited pairwise correlation among held names on the 4h book; this clusters the pool and diversifies across clusters on 30m/1h. Judged by the live window like every menu style.

## five-minute-slower-exit-2026-10-01

Operator instruction 2026-10-01 00:50 IST: make the 5m bot hold longer to stop the whipsaws. After the 17:34Z reset `momentum_top3_5m` closed 4 trades in 15-35 minutes at a 10-bar (50-minute) low, net -1,146.
Recent-data check with the live rule and simulator (5m bars, fees and ticks; small and noisy, not a validation): 10-bar exit with the 15-minute minimum hold -5.23% over the last 7 days / -8.75% over the last 3 (max drawdown -13.0%); 24-bar exit -1.60% / -13.70%; **36-bar exit +13.55% / -6.94% (-10.7%)**; 10-bar exit with a price-blind 2 h hold +6.57% / -4.43% (-8.0%). Live history cautions against price-blind holds: the `momentum_top3_5m_hold2h` twin finished 2026-09-24..30 at -1.2% against the plain book's +9.9% (`#fleet-review-2026-09-26`, final fleet review in `#best-trades-study-2026-09-30`).
Change: `config/momentum_top3_5m.yaml` `strategy.exit_bars` 10 -> 36 (exit below the prior 3-hour low), minimum hold unchanged at 3 bars; the book restarts on its saved state. The dynamic bot's 5m styles read the same config and pick this up at its next restart; the slower exit on the 30m competition rule remains null (`#competition-exit-outcome`).

## levels-tool-2026-10-01

Operator request 2026-10-01: use technical charts to find the best entry and exit points. No charting platform is connected, so `python3 -m gates.levels` computes the chart levels from Binance bars for every held coin and the five strongest market-neutral coins (`#market-structure-2026-10-01`): the breakout triggers the rules use (prior 20-bar high on 30m and 1h), the exits they use (prior 10-bar low on 30m, prior 36-bar low on 5m), and context (1h ATR(14), 24 h VWAP, 24 h high and low, 1h RSI(14)), each as a distance from the current price. Indicator-based entry and exit rules were tested before and were null (`#rsi-band-outcome`, `#take-profit-outcome`), so the levels describe the strategy's own triggers rather than adding new ones.

## decision-point-2026-10-01

Operator instruction 2026-10-01: launch 3-4 Sonnet sub-agents to research the market conditions, strategies and data points, integrate them into one structured decision point, and feed it into the trading bots.
Four agents ran in parallel, each read-only on the repo and writing one JSON file to `results/agent_research/`: regime (trend, chop, direction, volatility, dispersion, breakout follow-through by clock), strategies (which menu styles are working live and in the dynamic bot's window), datapoints (order flow, open interest, funding, premium, volume: current readings and 14-day point-in-time informativeness in two halves), risk (concentration, gross and per-coin caps, shorts, target lock, drawdown brake, Screen 3).
`python3 -m gates.decision_point` merges them with fixed code into `results/decision/latest.json`: only style ids on the dynamic bot's menu survive, cash is always allowed, shorts drop if the risk review blocks them, order-flow and open-interest styles drop if the data review finds them uninformative, `max_gross` is clamped to [0.25, 1.0], and the file expires after 12 h; missing or malformed inputs fall back to the full menu. No language-model output reaches a bot unvalidated, and no model runs inside the trading loop.
Consumer: the dynamic bot (`wf_live`, `adaptive.use_decision_point: true`) restricts its hourly choice to the allowed styles and scales its target gross by `max_gross`; its journal records which decision was in force. The competition book does not read the decision file; wiring it there is an operator decision after the paper result is seen.

## decision-point-outcome-2026-10-01

First merge (2026-09-30 19:29Z, valid to 2026-10-01 07:29Z), `results/decision/latest.json`: regime **chop** (confidence 0.6); allowed styles `1h|htf0|vol0`, `30m|htf0|vol0`, `blocks|1h`, `resid|30m` and cash; `max_gross` 0.9; shorts off; order-flow and open-interest styles off.
Agent findings behind it: regime - 1h efficiency ratio median 0.047 over 7 days, equal-weight pool -3.6% over 3 days with 80% of coins down inside a +31.5% 14-day advance, 0% of coins above their 4h 20-bar high, breakout follow-through falling with clock speed (5m 42% n=2776, 15m 41%, 30m 39%, 1h 34% n=176, 4h 15% n=46), volatility 1.07x its 30-day median, dispersion compressed (2.8% against 4.2%). Strategies - cash beat all 29 styles over 3 days; last 7 days of paper: 37.5k fees on 4.8k gross (n=1,570), exits under 1 h lost 28.9k at a 63% whipsaw rate while holds over 3 h earned 65k; whipsaw rate by clock 5m 27%, 15m 25%, 30m 9%, 1h 4%, 4h 0%; so all 5m and 15m styles were disabled. Data points (1,665 breakouts, 14 days, two halves) - taker share and funding inconsistent across halves, open interest, premium and volume multiple null in both; no confirmation allowed. Risk - shorts fail 5 of 6 holdouts (off); max gross 0.9 and 0.4 per coin (judgement calls, not tested); block diversification not supported; drawdown brake fails its nonsense control; target lock recommended ON for the competition book (a judgement call against the operator's current choice, so not applied).
Conflict resolved by the fixed merge: the regime agent favoured fast breakouts on follow-through rate, the strategies agent disabled them on net P&L after fees and whipsaws; the merge follows the strategies allow-list, which is P&L-based. The 0.4 per-coin cap is recorded but not enforced (no bot hook yet). `wf_live` applies the decision from its next hourly selection.

## restart-stale-entry-2026-10-01

Found 2026-10-01 01:05 IST from the operator's question about `momentum_top3_5m`'s open profit. After the 5m exit change (`#five-minute-slower-exit-2026-10-01`) and restart at ~19:20Z, the book bought PUMP and NEAR (about 49k each) at 19:25Z although neither was a fresh signal: PUMP closed 1.8% below its prior 20-bar high on 0.47x volume, NEAR 1.2% below on 1.68x. With the looser exit the rule's replayed path held both from breakouts that fired earlier, and the catch-up guard (`#catch-up-and-live-min-hold`) only blocks such stale entries after skipped or late bars, not after a restart. The trades happened to work (PUMP +1.5%, NEAR +0.1% at 19:35Z), but they were late entries, not genuine signals.
Fix (`bot/entry_guard.py`): the first decision after any process start is treated like a catch-up decision, so a name the path entered before the latest bar and the book does not hold is not bought; held positions are untouched. Test: `tests/test_entry_retry.py`. All contenders-engine books were restarted to load it, positions kept.

## stress-harness-declaration

Operator instruction 2026-10-01: launch three sub-agents to analyse the three best bots in depth and try to break them by strict analysis, so they are stronger for live markets; build a harness and specialised tools around the bots first.
Declared in `config/stress_harness.yaml` before any number was computed. `gates/stress.py` replays a book's exact live rule (the contenders engine with the book's config, shorts off, the ladder, maker fees and ticks, through `gates/let_winners_run.simulate`) and applies failure scenarios that model how the live books actually fail: taker fees, extra slippage, one-bar-late fills, offline blocks, missing closes at decision time, one-bar flash wicks and permanent gaps on the largest held coin, and a one-at-a-time parameter neighbourhood. Metrics are the competition's 14-day windows (fit, holdout, recent) and a daily P&L split by BTC regime.
Break rule (fixed): a period breaks when the median 14-day return is at or below zero, loses more than half of the baseline median, the worst window is below -25% (the live max-drawdown kill) or the median window drawdown is worse than -15%. Nonsense control: the identity scenario must reproduce the baseline exactly.
A break names a weakness to fix; it never licenses a parameter change on its own.
The three books: `competition` (real money, 30m), `momentum_top3_15m` (15m baseline) and `wf_live` (the dynamic selector, replayed by its agent on top of this harness).

## crash-shorts-declaration

Operator question 2026-10-01: why not short the most obvious downtrend when the whole market is down; after the record of failed short sleeves was shown, the operator asked for the one untested case, shorts only in a true crash regime.
Declared in `config/crash_shorts.yaml` before any number was computed. The switch is BTC down more than 5% over the last six closed 4h bars (the `crash` label of `gates.stress.regimes`), not breadth, so it is on for a few percent of bars rather than in ordinary chop. Arms on 30m and 1h: a short-only crash book, the competition rule, and the competition rule with crash-gated shorts competing for its slots; shorts pay 0.10% a side. Nonsense control: the same flag shifted 30-180 days, 20 seeds.
Decision rule (fixed): at least 20 crash days in each period or the verdict is insufficient; otherwise the combined book must match the competition rule's median 14-day return and stay within 2 pp of its worst window on both fit and holdout, and the short-only book's crash-bar P&L must be positive and beat 18 of 20 shifted flags. A pass earns a paper book only.

## stale-rebuy-2026-10-01

Found 2026-10-01 by two red-team agents independently (`results/stress/m15_agent/REPORT.md` L1, `results/stress/competition_agent/REPORT.md` L4/L5) and confirmed in code: `bot/entry_guard.py` dropped stale path entries only on the first decision after a start or on a catch-up decision, so on the next on-time bar the rule's path still held the name, the book did not, and the book bought it one bar late.
Live cost: every one of 10 late entries in the 15m book's journal followed a `stale_entry_blocked` or `cold_start_entry_suppressed` for the same symbol one decision earlier; the 9 closed ones all lost (mean -131 bps, -5,399 USD), against +71.5 bps for on-time entries. ENA, PUMP and SUI after the 2026-09-30 17:34Z reset were the 15m book's whole -1.24k. The rehearsal bought TRX one bar late after its 14:22Z cold start, which is exactly how the competition account will start on activation.
Fix: the stale-entry drop runs on every decision; the only exception is an entry the previous on-time decision wanted and did not fill (it stays in `pending_entries` and may be retried). The same fix closes the dynamic bot's style-switch case (a switch bought positions the new style had entered days earlier; `tests/test_stress_wf.py`). Tests: `tests/test_entry_retry.py`, `tests/test_stress_m15.py`, `tests/test_stress_competition.py`, `tests/test_stress_wf.py`.

## offline-replay-2026-10-01

Operator question 2026-10-01: had the bots been online overnight, what would they have caught. The Mac slept on battery from about 20:40Z to 05:15Z (books online 28-51% of 24 h). `python3 -m gates.missed_replay` replays each book's exact live rule on Binance bars from 2026-09-30 17:34Z, starting flat with stale path entries removed, and marks entries that fell in offline gaps (`results/missed_replay.json`).
Replay vs actual to 05:15Z: competition rule +0.12% vs -0.30% (4 trades, all entered while offline); 30m +0.12% vs -0.43%; 15m +0.35% vs -2.04%; 5m (36-bar exit) +1.07% vs -2.03% (13 trades, 11 while offline). The best signals were all overnight: AAVE broke out 02:00-03:00Z (+1.8% to +3.3%, still open), TRUMP on 5m +4.0% (peak +9.0%), DOGE +1.2%. The gap is sleep plus the stale-entry bug (`#stale-rebuy-2026-10-01`), not the rule.
The operator's reading: about +1% overnight is far below a leaderboard pace. Agreed; the rule is flat about half the time and earns only in up days (`results/stress/competition_agent/REPORT.md` S7).

## wf-ride-unblocked-2026-10-01

Operator instruction 2026-10-01 05:30Z: the dynamic bot has not traded; do not be so stringent, ride the waves wherever we can and take the setups. `wf_live` had been in cash since 2026-09-30 19:13Z because the research decision point (`#decision-point-outcome-2026-10-01`) allowed only four styles, all below cash plus the 1 pp switch margin, while the momentum ride led the whole menu (+6.0% over 3 days at 20:15Z, +1.9% at 01:02Z).
Change (paper only): `adaptive.use_decision_point` false and `switch_margin_pp` 1.0 -> 0.25 in `config/wf_live.yaml`. Takes effect on the bot's next restart. Caveat on record: the ride's history test was not adopted (`#burst-drivers-outcome`), so this is forward evidence on paper, judged by `gates.wf_report` like every pick.

## crash-shorts-outcome

FAIL on both clocks, every check (`results/crash_shorts.json`, `python3 -m gates.crash_shorts`). Crash days: 50 fit, 38 holdout, so the evidence floor was met.
Short-only crash book, summed log P&L over crash-flag bars: 30m -86.7% fit / -25.5% holdout, 1h -64.4% / -45.3%; the same flag shifted to random dates lost far less (median -13.3% / -11.9% on 30m, -6.1% / -8.6% on 1h) and beat the real flag in 18-20 of 20 seeds. The timing is worse than random: a crash confirmed on a closed 4h bar is shorted near the low and squeezed on the rebound, the failure mode the declaration named.
Combined book vs the competition rule (median / worst 14-day): 30m holdout +0.38% / -31.8% vs +1.13% / -22.3%; 1h holdout +1.95% / -27.4% vs +2.80% / -22.8%. Shorts stay off everywhere.
The first run was void, not a result: the arms inherited the competition config's frozen short stretch filter and long-side confirmations, which blocked almost every short (zero short P&L, combined book identical to the baseline). The code was corrected to the declared rule before any number was read as a result; its four `config/trials.yaml` rows are void and the four later rows are the trials.
Not a test, a lead only: the competition rule run unchanged on 1h bars scored holdout +2.80% and recent +6.05% median 14-day return against +1.13% and +0.19% on 30m, consistent with `#lowtf-long-only-clocks-outcome` (long-only passes only at 1h).

## overnight-patterns-2026-10-01

Operator question 2026-10-01: what were the missed gains overnight, and which minute-level patterns could we have used. `python3 -m gates.overnight_patterns` on 1m Binance bars for the 25-coin pool, 2026-09-30 20:00Z to 2026-10-01 06:54Z (`results/overnight_patterns.json`); descriptive and in-sample, one night.
Missed gains: the equal-weight pool rose +2.1% (median coin +1.7%, BTC +0.7%); the live rules replayed from 20:00Z: 30m +1.27% vs +0.09% (paper) and +0.5% (rehearsal), 5m +0.91% vs -0.2%, 15m -0.14% vs -1.13% (`python3 -m gates.missed_replay --start 2026-09-30T20:00Z`). Perfect-foresight best legs (unattainable): TRUMP +11.0% (22:04-02:59Z), ENA +7.6%, AAVE +6.8%, NEAR +6.6%, PUMP +6.4%.
Structure: the night was two market-wide bursts, 22:04-22:09Z (six of the ten best legs started then) and 02:30-02:33Z (TRUMP, AAVE and AVAX in the same minutes); alt minute returns move with BTC in the same minute (median correlation 0.58) and not after it (lag 1-5 minutes -0.05 to +0.01), so there is no BTC lead to trade.
Minute triggers against the base rate of entering any coin at any minute (net +0.63% at 4 h, 68% positive, the whole market rose): every trigger lost over the next 15 minutes (net -0.16% to -0.35%, 11-27% positive: minute jumps mean-revert first); at 4 h only the 1%-jump-with-3x-volume trigger beat the base rate (+1.38%, n=9), the others did not (2% jump -0.55% n=5, 2h-high break with 2x volume +0.49% n=27, with buyers >60% +0.14% n=60, coin-specific 1% jump 0.00% n=34). n=9 on one night is noise; a declared multi-month 1m test would be needed before any use.

## competition-1h-declaration

Operator instruction 2026-10-01: test the 1h rule for the competition book. Declared in `config/competition_1h.yaml` before the new numbers were computed, with its contamination stated: the 1h long-only rule already passed `#lowtf-long-only-clocks-outcome` on the same periods, its medians were printed by the crash-shorts run, and its forward paper book (`momentum_top3_1h_long`) finished 2026-09-24..30 at -9.8% against +7.9% for the 30m book (both online ~31%).
Arms: the live competition contenders block on 30m (control) and on 1h. New evidence: paired 14-day deltas with a block bootstrap, the stress scenarios, a random-coin control (same timing and weights, random pool coin) and a fully-online replay of both rules on Binance bars from 2026-09-19 to now. Six fixed conditions; failing any one means not recommended. Either way, moving the real-money book is the operator's decision.

## competition-1h-outcome

NOT RECOMMENDED: condition 6 fails; conditions 1-5 pass (`results/competition_1h.json`, `python3 -m gates.competition_1h`).
History favours 1h. Median 14-day return, 30m vs 1h: fit -0.76% vs +1.06%, holdout +1.13% vs +2.80%, recent +0.19% vs +6.05%; paired median delta +1.67 pp (p 0.15), +1.54 pp (p 0.027), +3.91 pp (p 0.002). Holdout P(>5%) 0.35 vs 0.40, worst -22.3% vs -22.8%, Screen 3 +2.13 vs +3.29. 1h is far more cost-robust: taker fees leave its holdout median at +1.54% (30m breaks at -0.80%), 10 bps slippage +0.43% (30m -2.67%); only the 15% gap shock breaks it as it breaks 30m. It beats all 20 random-coin controls (their medians -2.75% to -0.28%).
The only unseen data disagrees sharply: a fully-online replay of both rules on Binance bars, 2026-09-19 to 2026-10-01 07:00Z, gives 30m +9.92% (max drawdown -11.4%, 75 trades) and 1h -12.80% (max drawdown -17.5%, 47 trades). The forward paper week agreed in direction (`momentum_top3_1h_long` -9.8% vs `momentum_top3_30m` +7.9%, 2026-09-24..30, both online ~31%).
Reading: the historical advantage is real in the paired test but was selected on periods already used; in the current two weeks the 1h rule's slower entries and exits lost badly while 30m caught the moves. One 12-day window is one draw (1h's historical worst fortnight is -22.8%), so this is not proof that 1h is worse, but the declared rule was fixed in advance and it fails. The competition book stays on 30m.

## cancel-both-args-2026-10-01

Found live 2026-10-01 07:06Z on the rehearsal book (real orders, TEST keys). Two LIMIT sells rested past the 300 s timeout; `Executor.sweep_unfilled` cancelled them with `cancel_order(order_id=..., pair=...)`, and Roostoo rejected both: "only allow none or one argument of order_id / pair". Two failed cancels against five attempts gave an error rate of 0.40, past the 0.25 kill, so the book halted, emptied its target and sold AAVE, TRUMP and ETH, and stayed halted (the lifetime error rate never falls once flat; `results/stress/competition_agent/REPORT.md` L9). The competition book runs the same code and would have done the same the first time a maker order took longer than five minutes to fill.
Fix (`venue/roostoo.py`): cancel by order id alone when an id is given, by pair alone otherwise, and refuse a call with neither (which the venue reads as cancel everything). Tests: `tests/test_roostoo_cancel.py`. The Binance testnet client, which needs both, is unchanged. The error-rate gate's lifetime counting and liquidation on a venue error remain open (`#stale-rebuy-2026-10-01` lists the other red-team fixes).

## live-faults-2026-10-01

Operator instruction 2026-10-01: apply the red-team fault fixes. Each restores intended behaviour; no signal, sizing or exit rule changed. Found by the competition red-team agent (`results/stress/competition_agent/REPORT.md` L1b, L2, L6, L7b, L9) and, for the error-rate gate, confirmed live on the rehearsal book (`#cancel-both-args-2026-10-01`).
- Error rate (`bot/execution.py`): the failed share of the last 40 venue calls (orders, queries and cancels all count), zero before 8 calls; it was lifetime order errors over order attempts, so one failed query after four orders read 0.25 and the rate never fell once the book was flat.
- Freeze, not liquidate (`bot/risk.py`, `bot/run.py`): an error-rate, stale-ticker or mirror breach freezes the book (no orders, pending entries cleared); only the drawdown kill still empties the target. Selling everything through a failing venue or on untrustworthy prices turned a data fault into a loss.
- Mirror check (`bot/run.py`): runs over the universe and every held coin; a coin missing a price breaches only if the book holds it. A zero LastPrice on any unheld universe coin used to make the check incomplete and, after two cycles, liquidate the book.
- Marks (`bot/run.py`): a held coin with no quote or a zero quote keeps its last known mark (persisted) instead of being valued at zero, which read as a phantom drawdown.
- Held coins outside a refreshed universe (`bot/run.py`): the wallet adoption keeps them, so they stay marked and the rule sells them at the next decision; they used to vanish from holdings and equity.
- Pending orders after a failed query (`bot/execution.py`): every pair with an order sent within the limit timeout counts as pending, so a resting buy is not sent again.
- Ambiguous submission (`bot/run.py`): reconciliation re-runs every live cycle and lifts the block when every intent is settled; after 10 unsettled cycles the process exits so the supervisor restarts it. One timed-out order used to block every later order, exits included, for the life of the process.
Not changed (operator decisions in the red-team report): the drawdown halt stays permanent within a process, exits stay passive maker orders.
Tests: `tests/test_stress_competition.py` (the former reproductions now assert the fixed behaviour), `tests/test_bot_safety.py`.

## retired-2026-10-01

Operator instruction 2026-10-01 07:55Z: retire the 15m and 5m paper books. Since the 2026-09-30 17:34Z reset `momentum_top3_15m` finished -3.96% (14 exits, 7% won, -2.96k of it on holds under 2 h) and `momentum_top3_5m` -3.12% (22 exits, 41% won, -2.97k on holds under 2 h); the red-team harness puts the 15m rule at a -7.9% median 14-day return after costs (`results/stress/m15_agent/REPORT.md`). Both stopped, removed from the default `run_bots.sh` CONFIGS, live data moved to `live/_archive/retired-2026-10-01/`. Their configs stay: the dynamic bot's 5m and 15m styles read them.

## best-signals-2026-10-01

Operator request 2026-10-01: check the best signals and learn from them. `python3 -m gates.best_signals` (`results/best_signals.json`) reads 14 entry features at each competition-rule trade's entry close (closed trades: 2,911 fit, 2,347 holdout, 582 recent) and relates them to the trade's net return, per period. Descriptive; the holdout and recent periods have been used before, so any rule drawn from this needs its own declaration.
The top 10% of trades earn 78% / 82% / 86% of all gross gains (fit / holdout / recent): the result is a few big trends, and more so lately.
The best trades entered coins already running hard and volatile. Top 10% vs the rest, holdout medians: prior 24 h +5.4% vs +2.7%, 40-bar momentum +5.7% vs +2.3%, own move against the pool over 4 h +1.9% vs +0.9%, 24 h realised volatility per bar 0.81% vs 0.53%, close above the 4h 20-bar high by 1.1% vs 0.35%; recent is the same.
The same features lower the typical trade: their rank correlation with the trade's return is negative in every period (realised volatility -0.21 / -0.21 / -0.24, prior 4 h -0.17 / -0.18 / -0.22, momentum -0.17 / -0.17 / -0.17, residual -0.15 / -0.18 / -0.18), while their top quintile has the highest mean in holdout and recent (+1.1% to +2.7% per trade) but not in fit. Extended, volatile entries lose a little more often and carry the rare large winner: the payoff asymmetry, not a filter.
No stable relation: entry volume multiple (beyond the 1.5x gate), BTC 24 h return, breadth, the number of coins breaking out together, hour of day.
Reading: the rule's existing momentum sizing already leans toward these trades; a filter on them would cut trade count and keep the tails, and its mean benefit is absent in fit. Candidate for a declared test only: a stronger tilt of size toward high residual strength and volatility, judged on fit first.

## strength-tilt-declaration

Operator instruction 2026-10-01: proceed with the next steps from the best-signals study. Declared in `config/strength_tilt.yaml` before any number was computed. Two sizing tilts on the competition rule, same names and timing: toward the held name strongest against the pool over 4 h (T_res), and toward the most volatile held name (T_vol), each renormalised to the rule's gross and capped at 0.5; nonsense control: random [1, 2] tilts, 20 seeds. Judged on fit first because the study found no mean benefit there: an arm passes only with +0.25 pp on the fit median, no loss on the holdout median, worst windows within 2 pp, and a fit median above 18 of 20 random tilts. A pass earns a paper twin only.

## fill-quality-2026-10-01

Operator instruction 2026-10-01: measure execution quality before deciding on marketable exits (the one transferable point of the HRT AI Labs post, which studied execution; `#best-signals-2026-10-01` and the stress harness show the edge depends on maker fills). `python3 -m gates.fill_quality` reads the rehearsal account's own order history from Roostoo (one read-only call; `results/fill_quality_competition_rehearsal.json`).
Strategy orders 2026-09-30 14:22Z to 2026-10-01 07:06Z (12, excluding the BTC smoke-test orders): every one filled as MAKER at 0.05%. Buys filled in 0.0-9.6 s; sells took 11-370 s (median about 25 s), one of six (ETH, 07:00Z) past the 300 s timeout, the order whose failed cancel tripped the halt (`#cancel-both-args-2026-10-01`). Fills were 0.0 to 2.3 bps better than the quoted mid on both sides.
Reading: entries are fast and cheap; the only execution risk is a slow exit while a coin falls. Escalating an exit to a marketable order after one timeout would cost about 5 bps on roughly one exit in six; it remains an operator decision.

## strength-tilt-outcome

FAIL, both arms (`results/strength_tilt.json`, `python3 -m gates.strength_tilt`). Median 14-day return fit / holdout / recent: C0 -0.76% / +1.13% / +0.19%; residual tilt -0.67% / +1.02% / -0.20%; volatility tilt -0.83% / +1.03% / -0.16%. Neither lifts the fit median by 0.25 pp nor holds the holdout median; worst windows are within 2 pp; both beat most random tilts on fit (random medians -1.19% to -0.72%) only because random reweighting is slightly worse than the rule's own momentum sizing.
Why the effect is tiny: the rule holds two or more names only about 30% of the time (flat 51%, one name 19%, `results/stress/competition_agent/REPORT.md` S4), so reweighting among held names rarely changes anything, and the asymmetry of `#best-signals-2026-10-01` lives in which trade becomes a big trend, not in the size given to it. Sizing tilts are closed for this rule.

## adaptive-recent-2026-10-01

Operator direction 2026-10-01: do not take history as the bible, conditions have changed; we want something that adapts on our time frame to the latest market. Tested on the latest market only: `python3 -m gates.adaptive_recent` rebuilds the dynamic bot's 27 styles (open-interest styles excluded) with the live code on Binance bars, replays the hourly follow-the-leader selection point in time from 2026-09-19 to 2026-10-01 08:00Z, and compares it with the fixed competition rule, the mean style, cash and 200 random hourly pickers (`results/adaptive_recent_*.json`).
Result (fresh-entry selector, the live behaviour / inheriting selector): lookback 3 d, margin 1 pp -7.99% / -11.49% (27 switches); 1 d -29.03% / -20.54% (46); 7 d -4.23% / -5.04% (21); 3 d with a 3 pp margin +5.87% / -2.65% (13). Fixed competition rule +9.80%; mean style -4.41%; random hourly picker median -4.35%; cash 0. Best styles in hindsight: momentum ride +16.97%, 30m without the 4h filter +15.40%, residual 30m +11.06%, competition rule +9.80%; worst: short 15m -30.93%, 5m with the 4h filter -24.78%.
The historical replay of the same selection (`gates/stress_wf.py`, `results/stress/wf_agent/run_recent.log`, cumulative log return) agrees: fit +32.7% vs mean style +8.1%, holdout -82.2% vs +14.9%, recent (2026-06..09) +8.7% vs +6.7% (p 0.39), with switching costs of 41.8%, 41.6% and 10.5%.
Reading: in the current market style leadership does not persist; a style tops the trailing table after its run, and switching buys the end of it. Fewer switches lose less (the 3 pp margin is best), and none beats holding the competition rule. The rule adapts by itself (the breakout and momentum rank move into whichever coin is running). The dynamic bot's 0.25 pp margin (`#wf-ride-unblocked-2026-10-01`) is the churn-prone end of this range; it stays paper.

## ride-and-blend-declaration

Operator instruction 2026-10-01: run the ride and the 30m blend as paper books, after `#adaptive-recent-2026-10-01` showed the momentum ride as the best style in hindsight over 2026-09-19..10-01 (+16.97%) and switching between styles losing. `config/ride_5m.yaml`: the ride style alone, always on (bot.scalper_adaptive_run with a one-style menu, no cash). `config/blend_30m_ride.yaml`: a fixed 50/50 blend of the competition rule on 30m and the ride (bot.hedge_explorer_run with eta 0 and no cash arm, so the weights never move). Both were chosen on the same window that made them look good, so they are forward evidence only; falsification after 7 live days is in each config. The competition book is unchanged.

## regime-ls-declaration

Operator instruction 2026-10-01: make the bot market-regime aware, classify the regime correctly, short when the market bleeds (the heatmap showed every coin falling over the last hour) and take the longs when the regime switches. Declared in `config/regime_ls_30m.yaml` before any number was computed, paper only.
Regime (`signals/regime_ls.py`): on 30m bars, the equal-weight return of the tradable pool over 8 bars and the share of coins that rose over the same 8 bars. Raw DOWN at -1% or worse with at most 25% rising; raw UP at +1% or better with at least 75% rising; otherwise NEUTRAL. The state turns DOWN after 2 consecutive raw DOWN bars and leaves after 2 that are not.
Book (`bot/regime_ls_run.py`): the competition contenders rule on 30m with the 4h confirmation and the short stretch filter off; in DOWN no new longs and breakdown shorts on (20-bar low, negative 40-bar momentum, top 3 across both sides by strength, exit on the 10-bar high or when DOWN ends); outside DOWN the long rule as usual.
Prior evidence is against it: every short sleeve tested so far failed (`#lowtf-breadth-shorts-outcome`, `#topdown-ls-outcome`, `#crash-shorts-outcome`). It runs forward because the operator asked; it stops after 7 live days if it trails `momentum_top3_30m` or its shorts lose in total.
First look after declaration (2026-10-01 08:25Z, live Binance bars 2026-09-19..10-01, flat start, information only): regime book +12.95% (max drawdown -12.2%) against the same long rule without the switch +10.38% and the competition rule +6.78%; regime shares NEUTRAL 62%, UP 24%, DOWN 14% (12 DOWN spells); 25 shorts, mean +0.21%, 32% won. One window of twelve days decides nothing; the forward paper book does. All three paper books started 08:28Z.
Operator decision 2026-10-01 08:40Z: the dynamic bot's switch margin goes from 0.25 pp to 3.0 pp, the best setting of the recent-market test (fewest switches, +5.87% with fresh entries against -7.99% at 1 pp); paper only.

## residual-spread-declaration

Operator instruction 2026-10-01: find a way to profit in the current correlated sell-off, where the long books sit in cash; test the market-neutral residual spread. Declared in `config/residual_spread.yaml` before any number was computed. Long the 2 coins strongest against the equal-weight pool and short the 2 weakest, 0.25 each, held while they stay in the top or bottom 5, on 30m bars, residual over 4 h (RS8) or 24 h (RS48); shorts pay 0.10% a side. Primary gate is the unseen recent window on live Binance bars (positive return, drawdown better than -10%, beats 45 of 50 random spreads), plus a positive 2025-26 holdout median on history. A pass earns a paper book only.

## residual-spread-outcome

FAIL, both arms (`results/residual_spread.json`, `python3 -m gates.residual_spread`).
Recent live window 2026-09-19 to 2026-10-01 09:30Z: 4 h residual -17.72% (max drawdown -19.5%; long leg +2.57%, short leg -20.27%), 24 h residual -17.56% (-18.0%; long -8.20%, short -10.88%). History median 14-day return fit / holdout / recent: 4 h -15.8% / -19.6% / -23.9% at about 200x turnover per 14 days; 24 h -3.7% / -2.4% / -1.3%.
Both beat all 50 random spreads, but that control is weak: random scores reshuffle every bar and pay fees on enormous turnover (median -63%), so beating it says little.
Reading: shorting the coins weakest against the pool loses because they rebound against it; the losers of the last 4-24 h are the next hours' relative winners, the same short-horizon reversal that killed acceleration (`#accel-outcome`). Only the strongest-coin long leg on 4 h was positive, which the long rules already capture. Market-neutral residual spreads are closed.

## replay-decomposition-2026-10-01

Operator question 2026-10-01 12:05Z: the bots that made 13-17% in the replays, what were their strategies, and plug the insight into the current ones. Decomposition of the replay on live Binance bars 2026-09-19..10-01 12:00Z (flat start; first half to 2026-09-25 12:00Z, second half after; last 3 days):
| style | total | first half | second half | last 3 d | trades | top-3 trades' share of P&L |
|---|---|---|---|---|---|---|
| momentum ride (5m) | +19.43% | +19.54% | -0.09% | -0.78% | 36 | 0.71 |
| residual 30m | +11.70% | +6.79% | +4.60% | -4.03% | 124 | 0.99 |
| regime long/short 30m | +12.88% | +15.61% | -2.37% | -10.80% | 125 | 0.75 |
| 30m, 4h filter off, volume 1.5x | +10.55% | +11.99% | -1.28% | -5.79% | 100 | 0.96 |
| 30m, no filters | +7.96% | +9.00% | -0.95% | -8.35% | 121 | 1.33 |
| competition rule (30m, 4h filter on) | +6.72% | +11.92% | -4.64% | -7.80% | 75 | 2.04 |
Reading: every style made its money in the trending first week (ENA, UNI, SUI, AVAX, AAVE legs) and was flat to negative since; the last three days lost for all. There is no style that earned in the current chop; the alpha the operator sees in the replays is the first week's trend. Two styles held up better in the second half than the competition rule: residual 30m (the only one positive in both halves) and 30m with the 4h filter off (less give-back, and it took the ADA and ARB legs the filter blocked this morning, `#best-signals-2026-10-01`). Both start as paper books (`config/resid_30m.yaml`, `config/htf0_30m.yaml`), chosen on this window and so forward evidence only; the ride already runs as `ride_5m`.

## ride-trigger-2026-10-01

Operator instruction 2026-10-01 12:20Z: make sure the bots take trades, most sit in cash. Two findings first. The ride books are in cash mostly by design: the replayed ride is invested 100% of the time (3 names held up to 24 h), but a live book started at 08:28Z does not buy positions its rule opened earlier (`#stale-rebuy-2026-10-01`) and waits for a fresh trigger. And the trigger threshold matters in chop: on live bars 2026-09-19..10-01, ride with a 0.75 / 1.0 / 1.5 / 2.0% trigger returned +28.5 / +28.8 / +12.2 / +19.8% in total, +19.4 / +3.6 / +2.6 / -1.1% in the second (chop) half, +4.5 / +1.3 / +0.7 / -0.2% over the last 3 days and -1.5 / -1.6 / +0.8 / +0.7% over the last day: noisy and non-monotonic, so the middle 1% was chosen, not the best-looking 0.75%. `config/ride1_5m.yaml` runs it as a paper book beside `ride_5m`; it stops after 7 days if it trails `ride_5m`. The competition book is unchanged: forcing entries on its rule was what lost money for the 5m and 15m books.
