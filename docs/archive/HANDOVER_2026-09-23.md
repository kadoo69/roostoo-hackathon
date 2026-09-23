# HANDOVER - Roostoo competition bot

Written 2026-09-20T12:50Z at the end of an execution session.
`CLAUDE.md` holds durable conventions, `DECISIONS.md` holds the evidence trail.
This file is the **state snapshot** and is the first thing a fresh session should read.

The previous handover's protocol has been executed. This one records what it produced and what is left.

---

## 1. Stop-first rules

**Gate 4 is settled as unrecoverable. Do not spend research on it.**

The last handover left an open judgement: whether the honest denominator for the Deflated Sharpe was the raw ledger of 754 or a smaller count of genuinely independent selection decisions.
That question is now answered and the answer is that it does not matter.

A counting rule was written and committed **before** the resulting number was computed, then applied uniformly to the whole ledger.
It is at `DECISIONS.md#trial-counting-rule` and it is executable at `core.config.trial_counts_by_family`.
It reduces 754 to **470** in the Sharpe family.
DSR moves from 0.8009 to **0.8445**, against a required 0.95.

The gate would need N <= 94, which no honest reading of this ledger reaches.
The other two levers close by arithmetic rather than judgement:

- more observations would need **3,579 daily bars, about 9.8 years**, against the 1,358 held
- a higher Sharpe would need **2.498 annual** against the 2.206 measured, and confirming fees moves Sharpe by about 0.11 per 5 bps at most

The raw Sharpe of 2.206 is real and the strategy may well work.
What is established is that this sample cannot distinguish it from the best of 470 null draws at 95% confidence, and the submission must say exactly that.

**The practical consequence: since no trial count can pass this gate, the marginal DSR cost of a further sweep is no longer the reason not to run one.**
The reason not to run one is that seven families in a row returned nulls.
If a sweep is run, it is because it has a stated mechanism, not because it might rescue a gate. It cannot.

---

## 2. What is running, what is frozen

Live as of 13:25Z. **All six books were restarted on instrumented code at 13:20Z**, which resumes forward-evidence accumulation (priority 2 below):

| process | pids | notes |
|---|---|---|
| `momentum_top3_4h` | 26688 / 26691 | holds 2 names, **-0.717%** over 36 cycles. The only live book. Built for Screen 2 qualification, not Screen 3, and it is the arm that bets fees are cheap. |
| `bot.scanner` | 30414 / 30416 | **ONE supervisor.** The duplicate is killed and the guard that let it happen is fixed. |
| `paper_lab_v8` | 32039 / 32041 | 13 candidates at `fee_bps: 10.0`, **now supervised**. |
| `bot.dashboard` | - | port 8787 (this repo), 8790 (the jev fork) |

Frozen, state preserved in place, snapshotted to `live/frozen/20260920T120709Z`, resumable with `./run_bots.sh start`:

`donchian_4h` (+26.70), `donchian_1h` (-42.02), `momentum_top5_4h` (+122.37),
`donchian_4h_cushion` (+43.76), `momentum_top5_cushion` (+161.34).

`./run_bots.sh compare` now prints an **age** column and marks a frozen book `NOT TRADING`.
It previously printed all five as though they were live, because a frozen book keeps its state file and its equity and hours read identically to a working one.

The separate repo `~/roostoo-jev` still runs 4 bots.
Process patterns are absolute-path scoped in **both** repos so they cannot kill each other. Do not revert that.

---

## 3. What this session changed

**Scanner duplicate, fixed at the cause.**
`run_bots.sh scanner` guarded on `pgrep -f "$ROOT/.*bot\.scanner"`, but `$ROOT` reaches the supervisor as a TRAILING `bash -c` argument and the worker's argv was a bare `python3 -m bot.scanner` with no path in it at all.
Neither process could ever match, so every invocation started another supervisor.
Both now carry `$ROOT` ahead of the module name, and `bot.scanner --root` verifies it against the checkout and exits 2 on a mismatch.
Verified by running the start command twice and confirming the second refuses.

**Paper lab reverted to 10 bps as `paper_lab_v8`.**
Reasoning at `DECISIONS.md#paper-lab-v8-fee-revert`.
v7 had run 0.5 hours, so no forward evidence was lost. The fee is inside the experiment hash, so this is a new root and not an edit.

**The paper lab is supervised for the first time.**
`./run_bots.sh paperlab` and `./run_bots.sh labstop
./run_bots.sh scalper      # start the supervised paper scalper
./run_bots.sh scalperstop
./run_bots.sh scalpreport  # forward per-trade record; the MEAN is the criterion`.
Its only product is elapsed time against `min_comparison_days: 28`, so a silent death costs days that nothing can backfill. It had been running bare.

**`bot/paper_lab.py` no longer defaults `--config` to a fixed path.**
It defaulted to `config/paper_lab.yaml`, which is v1, so `--report` with no arguments silently described a root nothing had written to in weeks.
This is the same defect already fixed once in `bot/compare.py`.
It now discovers the newest `config/paper_lab_v*.yaml`.

**`momentum_top3_4h` was invisible to every reporting surface.**
It was live but absent from `BOTS` and from `CONFIGS`, so neither `status` nor `compare` mentioned it. Both show it now.

**`CLAUDE.md` named configs that no longer exist.**
It listed `config/bot_a_4h.yaml` as the selected live configuration; that file was deleted in the rename to `donchian_4h`.
`config/paper_lab_v2.yaml` is a frozen declaration that still points at it, which is what produced 274 crash-loop tracebacks in `live/paper-lab.err`. It is archived and can never be re-run.

**Lint is clean across `bot/ signals/ gates/ data/ core/ tests/`**, 33 pre-existing errors fixed. The only one touching a signal path was a pure local rename in `signals/families.py` (`l` to `low`), confirmed by diff.

**Tests: 90 passed**, up from 84. Six cover the counting rule, including that the three families partition the ledger exactly.

---

## 4. Blockers no research resolves

`ORGANISER_QUESTIONS.md` is written and ready to send. It is the highest-value action available and costs zero trials.

- `.env` still reads `ROOSTOO_API_KEY` **NOT YET ISSUED**. Everything is paper.
- `costs.confirmed: false`, deadline **2026-10-01**. Worth ~3% of NAV on the ranked book's ~400x turnover.
  Note what confirming costs does NOT do: it makes the numbers real, it does not make Gate 4 pass. See section 1.
- Derisk ramp fires **2026-10-15 -> 2026-10-17**.
- Gate 10 needs three distinct days of live operation from a real terminal or EC2.

---

## 4c. Markout instrumentation, 2026-09-20

`#markout-instrumentation`. The literature exposed a gap the backtest cannot close: `portfolio/backtest.py` prices passive fills at fee plus zero spread, and no backtest can measure the price path after a fill it assumed happened.

Added, at zero trial cost and with no change to any signal, sizing or execution rule:
- reference quote at submission (`ref_bid/ask/mid/spread_bps`) - unrecoverable if not captured at the time
- per-cycle `marks`, scoped to held plus recently-traded symbols so exits still have forward marks
- `bot/markout.py`, surfaced per bot on the dashboard at 60s/300s/900s/3600s

**Read the dry-run caveat before reading any number.** In dry run every order fills at its own limit by assumption, so no fill is ever declined and fill selection is not being measured. The module detects this and refuses the adverse-selection claim, reporting "entry timing" instead. The real measurement needs real fills, so it is blocked on the API keys.

First readings, **not yet readable**: `donchian_1h` shows entry edge +1.10 bps and a 60s mean of -18.94 bps on **3** fills against a stated minimum of 30.

## 4b. Literature review, 2026-09-20

`RESEARCH_SHORT_HORIZON.md` reviews the short-horizon crypto literature against this repo's own nulls.

**The main value is negative and that is the point.**
arXiv:2608.21888 measures 15-minute reversal across 183 Binance pairs with a permutation null and a frozen holdout, and finds a gross edge peaking at **1.3 bps against a 5 bps round trip**, with thresholding making it worse not better and 5-minute bars worse still.
That is a near-verbatim independent reproduction of `#scalp-meanrev-outcome`.
This repo's 54-config and 72-config scalping sweeps were not implementation failures. They found the truth.

**Do not rebuild any sub-hourly family.** The edge there is a property of the horizon, not of the parameters.

Two mechanisms were worth testing and both are recorded:

- `#rotation-hysteresis-outcome` - **null.** The one transferable idea from arXiv:2606.00060, a cost-aware filter on the rank-rotation decision. It cannot bite because `lambda * 10bps` is trivial against 40-bar momentum dispersion; turnover falls 1 to 6% and every effect is 4 to 10x below this repo's own declared noise threshold.
- `#passive-fill-adverse-selection` - **a real gap in the cost model, bounded and small.** `portfolio/backtest.py` prices every LIMIT fill at fee plus ZERO spread. arXiv:2502.18625 says passive fills are adversely selected by construction. Bracketing it costs `donchian_4h` at most 0.042 Sharpe. Fee confirmation is worth ~3x more, so the priority order below is unchanged.

## 4d. Returns are the primary objective, confirmed from the rules

Operator confirmed the official criteria 2026-09-20: **Screen 2 advances the top 20 per region ranked on `(Final - Initial) / Initial`**; Screen 3 (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar) scores only survivors. **Returns first, composite second.**

`#full-deployment-outcome` re-scored every candidate on that metric rather than on Screen 3. `momentum_top3_4h` wins every right-tail measure and beats `donchian 1/3` at identical 0.72 gross with a shallower worst case, so the ranking produces the tail rather than the exposure. BTC hold carries full gross and has a ten-times thinner tail at P(>20%). This confirms `#competition-book-selection` on the metric that actually decides it.

**The largest remaining drag is idle cash.** `momentum_top3_4h` averages 0.72 gross because only 2 of 3 slots typically fire. `momentum_top3_full` spreads across whatever signalled and lifts holdout median 14-day return **1.92% -> 3.12%** with drawdown flat, improving the right tail on BOTH windows - the only thing this session found that does.

**Its cost: fit-window drawdown goes -31.8% to -49.2% while holdout stays flat.** That configuration can produce a ~50% drawdown; the holdout just did not contain the path. Calmar is 0.3 of Screen 3, so this may hand back in Screen 3 what it buys in Screen 2. Right trade only while qualification binds.

Live as a **gated arm against `momentum_top3_4h`**, identical otherwise. `full_deployment` is opt-in and OFF by default, so every other book is byte-identical. Not readable for 28 days.

## 4e. MAXIMISING PORTFOLIO RETURN - the reasoning, the evidence, and what is left

This is the operator's stated primary objective and the section a fresh session should read before touching sizing.

### The objective, precisely

Screen 2 advances the **top 20 per region** ranked on `(Final - Initial) / Initial`. Screen 3 scores only survivors.
So the target is **not** expected return and **not** Sharpe. It is **P(finishing in the right tail of the field over one specific fortnight)**.
Three consequences follow, and every decision below turns on them:

1. **Median return is the wrong statistic.** A book with a higher median but a thinner tail qualifies less often. Score P(>5%), P(>10%), P(>20%).
2. **Cash is a cost with no offsetting benefit** on this metric. Volatility is only punished at Screen 3, which a non-qualifier never reaches.
3. **Variance is not the enemy; LEFT-tail variance is**, and only because a 60% loss ends the run. Right-tail variance is the product being bought.

### Where the return actually comes from, measured

The decomposition, all on holdout 14-day windows:

| lever | from | to | P(>10%) | verdict |
|---|---|---|---|---|
| ranking rule | donchian 1/3 | momentum top3, **same 0.72 gross** | 0.233 -> 0.288 | **the ranking, not the exposure, produces the tail** |
| deploy idle cash | fixed 1/n | full deployment | 0.288 -> 0.321 | **adopted, live as `momentum_top3_full`** |
| concentration | top3 | top2 / top1 | see below | **rejected** |
| BTC floor when flat | 14.5% cash | 0% cash | 0.321 -> 0.347 | **undecided, depends on the cut** |
| derisk ramp | off | 2 days | 0.321 -> 0.301 | **costs ~1pp of median return** |

### L1 Concentration: top3 is the optimum and going further is overfitting

| config | fit median | **hold median** | hold P(>20%) | hold worst | hold maxDD |
|---|---|---|---|---|---|
| top5 full | 2.88 | 2.38 | 0.178 | -32.1% | -40.3% |
| **top3 full** | 4.10 | **3.12** | 0.168 | -28.7% | -43.3% |
| top2 full | 4.71 | **0.44** | 0.182 | -30.9% | -49.2% |
| top1 full | 3.85 | **-2.56** | 0.220 | **-57.9%** | **-81.8%** |

**The fit window keeps improving while the holdout collapses.** That is the textbook overfitting signature and it is unambiguous here: top2 holdout median falls 3.12 to 0.44, top1 goes NEGATIVE at -2.56% with an 81.8% drawdown.

Note the trap: **P(>20%) keeps RISING** all the way to top1 (0.168 -> 0.182 -> 0.220). A reader optimising only the far tail would pick top1 and be destroyed. The far tail rises because the book becomes a lottery ticket, not because it gets better. **top3 is the floor of concentration. Do not go below it.**

### L2 BTC floor: a bet on where the qualification cut lands

`momentum_top3_full` sits in **100% cash 14.5% of the time** because nothing signals. Holding BTC instead:

| | hold median | P(>5%) | P(>10%) | P(>20%) | maxDD |
|---|---|---|---|---|---|
| top3 full | **3.12** | **0.467** | 0.321 | 0.168 | **-43.3%** |
| top3 full + BTC floor | 2.63 | 0.454 | **0.347** | **0.182** | -51.4% |

It **lowers the median and raises the far tail**, costing 8 points of drawdown. Which is better depends entirely on where the top-20 cut falls:

- cut near **5%** -> no floor wins (0.467 vs 0.454)
- cut near **10% or higher** -> floor wins (0.347 vs 0.321)

**Read this table with the correction in the ranked list above.** It measures the floor against the market. A rank is scored against the FIELD, and BTC is the asset the field is most likely to be holding, so a constant floor is the "mimic the crowd" move and the literature says that is right only while already above the cut.

**This is not resolvable from data.** It needs question 6 of `ORGANISER_QUESTIONS.md`: how many advance per region and how large is the field. Until then the floor is NOT adopted, because it costs 8 points of drawdown against Calmar for a benefit that is conditional on an unknown.

### L3 The derisk ramp costs about 1 point of return

`risk.derisk_multiplier` ramps exposure to zero from 2026-10-15 to 2026-10-17, the final 2 days of a 14-day window:

| | hold median | P(>5%) | P(>20%) |
|---|---|---|---|
| no ramp | **3.12** | **0.467** | **0.168** |
| 2-day ramp | 2.09 | 0.432 | 0.161 |
| 3-day ramp | 1.60 | 0.419 | 0.155 |

**The 2-day ramp costs 1.03 points of median 14-day return and 3.5 points of P(>5%).** It is 14% of the competition window spent flat.

**The protection has now been measured. See section 4f. The short version: it is real, it is small, and it lands where the prize is not.**

### Current state and what is actually running

| book | role | sizing |
|---|---|---|
| `momentum_top3_full` | **the return-maximising candidate**, gated arm | top3, full deployment, 0.85 gross |
| `momentum_top3_4h` | its control | top3, fixed 1/3, 0.72 gross |
| `momentum_top5_4h` + cushion | second-best tail, lower drawdown | top5 |
| `donchian_4h` + cushion | best Sharpe, **worst qualifier** at 0.30 gross | 1/20 |
| `donchian_1h` | small-timeframe comparison | 1/20 |
| `scalper_live` | operator override after a failed backtest | 10%/trade |

### Ranked list of what is left, highest expected value first

1. **Answer questions 6 and 7** (where the cut falls, and whether rank is observable during the run). Question 6 decides whether `donchian_4h` is the better book after all. Question 7 decides whether the BTC floor can be made rank-conditional instead of constant, which is the form the contest literature says is correct: mimic the field when ahead, diverge when behind, and in a crypto contest BTC **is** what the field holds. The section 4e comparison below measures the floor against the MARKET, which is not what a rank is scored against. Zero trials, larger than any backtest available. `RESEARCH_PORTFOLIO_RETURN.md` section 1.
2. ~~Measure the derisk ramp's protection~~ **Done 2026-09-21, section 4f.** Both sides measured: the protection is real and small, the cost falls on the right tail, and the rule is negative on both screens. The decision is now the operator's, not a measurement's.
3. **Let the `momentum_top3_full` A/B run.** It is the only change this session that improved the right tail on both windows; 28 days is the gate.
4. **Do not raise concentration past top3, do not shorten the clock, do not add an exit rule.** Each is settled in section 5 with its own evidence.

### The one-line answer

**`momentum_top3_full` is the return-maximising configuration available today**: momentum-ranked top 3 of the PIT top-30 pool, fully deployed across whatever signals, 4h channel, gross capped at 1.0. Holdout median 14-day return 3.12% against 1.92% for the live book, P(>10%) 0.321, and the first change this session to improve both windows. Its risk is a fit-window drawdown of 49% that the holdout did not produce, and that risk is the price of the ticket.

## 4f. The derisk ramp, both sides measured, 2026-09-21

`DECISIONS.md#derisk-ramp-protection-outcome`, artifact `results/derisk_ramp.json`, gate `gates/derisk_ramp.py`, declaration `config/derisk_ramp.yaml`. Zero trials: no argmax, nothing promoted.

Section 4e measured the ramp's cost and flagged that the benefit was unmeasured, because the drawdown column there came from the full daily series and never saw the ramp fire. The new gate applies the ramp **window relative**, tapering into the end of every rolling 14-day window exactly as it tapers into the end of the one real one, and charges the liquidation turnover the ramp itself causes at the same 5 bps as every other trade.

Holdout, `momentum_top3_full`, 614 windows:

| | median ret | P(>5%) | P(>20%) | p05 ret | worst ret | median maxDD | P(maxDD <= -25%) | median Screen 3 |
|---|---|---|---|---|---|---|---|---|
| no ramp | 3.14% | 0.467 | 0.168 | -19.24% | -28.67% | -12.67% | 0.0912 | 3.066 |
| ramp | 2.10% | 0.435 | 0.160 | -18.45% | -25.81% | -11.82% | 0.0684 | 2.547 |

**The protection is real.** Worst window improves 2.86 points, kill-switch probability inside the window falls 9.12% to 6.84%, and conditional on the worst decile the ramp helps 74.2% of the time for a median 1.43 points.

**Three things make it a bad trade on this competition's objective anyway.**

1. **It is negative on BOTH screens, not a trade of one for the other.** Screen 3 falls 3.066 to 2.547, because cutting exposure cuts the return that is the numerator of Sortino, Sharpe and CAGR alike. Improving Calmar's denominator does not pay for that.
2. **Its payoff profile is short the right tail.** The paired median change is **+0.365 points** and it improves 53.8% of windows, yet the distribution's median falls 1.04. Both are true because the final three days of a crypto fortnight are slightly negative more often than positive: the ramp wins often and small, loses rarely and large, and costs a median 4.80 points in the best decile. Measured directly: across the 614 holdout windows the final three days return a median of **-0.06%** and a mean of **+1.82%**, negative 50.5% of the time. The ramp gives up a right-skewed segment, and the right tail is the product.
3. **The protection operates entirely where the run has already failed.** Screen 2 scores every outcome below the cut identically. Moving the worst case from -28.67% to -25.81% buys nothing, because both are equally far from qualifying. What the ramp does on the competition metric is move mass out of the right tail into the -18% to -29% range, where no prize exists.

**What is NOT changed and why.** The ramp is written into six frozen configs. Changing a frozen declaration is an operator decision, not a gate's, and section 4e's instruction was to decide it deliberately once both sides were measured. Both sides are now measured. The operator decides.

**The literature points at a third option neither side of this table contains.** Browne's optimal deadline policy goes risk-free when the TARGET is reached, not when the clock runs out. A state-triggered derisk keeps the protection and stops paying for it in every window that never needed it. It is untested here. See `RESEARCH_PORTFOLIO_RETURN.md` section 1.

---

## 4g. Sizing and profit recycling, tested and closed, 2026-09-21

`DECISIONS.md#compounding-outcome`, gate `gates/compounding.py`, declaration `config/compounding.yaml`, artifact `results/compounding.json`. Ten trials added, ledger now 461 rows. **Nothing promoted.**

Operator objective was maximum 14-day return via better sizing and recycling profits. The framing kills most of the search before any test runs: `max_gross` is 1.0 because the competition forbids leverage, and profits are ALREADY recycled, because `bot/run.mark` marks the book to market every cycle and every weight is a fraction of that NAV. There is no unexploited compounding in the sizing code. What is left is two degrees of freedom: **idle time** and **the weight path between signals**.

**Idle time: hypothesis refuted, and the reason is the useful part.** `momentum_top3_full` produces no signal at all on about 30% of bars. Three arms attacked it; all three lost on the holdout while matching or beating the control on FIT.

| arm | fit med | **hold med** | P(>5%) | P(>20%) | worst |
|---|---|---|---|---|---|
| control (rebalance to target each bar) | 4.08 | **3.11** | 0.467 | 0.168 | -28.70% |
| no channel gate, pure cross-sectional momentum | 4.16 | **1.41** | 0.414 | 0.177 | **-38.74%** |
| the same with the drift band | 4.32 | **1.18** | 0.414 | 0.197 | -36.60% |
| channel entries plus momentum filler for empty slots | 3.84 | **1.97** | 0.423 | 0.166 | -31.14% |

**The cash is not idle, the cash IS the position.** The channel exit holds cash exactly when the ranked names are falling. Removing the gate does not buy 30% more of the same edge, it buys exposure with the stop removed, and the worst fortnight goes -28.70% to -38.74%. Do not re-test this family.

**Weight path: the only measurable effect, and it is already what runs live.** `bot/portfolio.deltas` suppresses any rebalance inside a 25% relative band, so winners' weights grow. The backtest never modelled that - it resets to target every bar, trimming winners and topping up losers. **The deployed book and the measured book were different books.** Paired on 614 holdout windows with a 14-day moving-block bootstrap: the band adds **+1.95 points of P(>20%) at p=0.011**, with the median and P(>5%) unchanged (p=0.597, p=0.581). Fifteen tests were run, so Bonferroni takes that to 0.165. The honest claim is modest and it is not a promotion: **the live book's right tail is slightly better than every number previously recorded for it**, and 43 independent windows cannot say how much.

Band width was swept 0.00 to 0.80 to check the dial is real. P(>20%) rises monotonically to 0.40 then breaks down; holdout median falls monotonically while FIT median peaks at the widest band. The whole spread is 4 points against a 5.7-point standard error, so no value is distinguishable from another and **the pre-registered 0.25 stays**.

**What this closes.** Concentration, the derisk ramp, the weight path and the deployment rule all move along ONE frontier: median against far tail, fit preferring the aggressive end, holdout punishing it. **The dials do not create return, they reallocate it.** Only two changes have ever improved both windows and both are live already: the ranking rule and full deployment. Further sizing work has no expected value. The levers that ADD return are outside the strategy - fee confirmation at about 3% of NAV on this turnover, and fill quality - and both need the organisers, not a backtest.

---

## 4h. Live-state audit, 2026-09-20 18:53Z - nothing on the dashboard is readable yet

Triggered by the operator asking which of the leading books is right. The answer is none of them, and the reason is not a strategy question.

**Every book in the fleet has exactly one day of journals, `cycles-2026-09-20.jsonl`, and nothing older.** Process start times from the cycle records:

| book | first cycle | age at audit | state |
|---|---|---|---|
| `momentum_top3_4h` | 12:08Z | 6h 45m | 2 names, equity 104,104, 1 closed trade |
| `momentum_top5_4h` | 12:08Z | 6h 45m | 4 names, equity 103,342 |
| `donchian_4h` | 12:08Z | 6h 45m | 4 names, equity 100,825 |
| `momentum_top3_full` | **18:21Z** | **32 minutes** | **flat, 100% cash, equity exactly 100,000.00** |

So the dashboard's "+4.393%" on `momentum_top3_4h` is a **six-hour mark-to-market move on two positions with one closed trade**. It is not a track record and it does not rank anything. Section 1 already forbids revising on live P&L; `RESEARCH_PORTFOLIO_RETURN.md` section 1 adds the outside version of the same point, that a leaderboard at this sample size is consistent with chance.

**`momentum_top3_full` is flat for a correct reason, not a broken one, and this was checked rather than assumed.** Its first cycle at 18:21Z evaluated AVAXUSDT, NEARUSDT and TRXUSDT as fresh entries, and `bot/run.py` line 215 suppressed all three opening BUYs under the cold-start guard at `DECISIONS.md#cold-start-chases-the-bar`. The order journal carries exactly one record, `cold_start_entry_suppressed`, and nothing since. `self.cold_start` is cleared on that same fresh cycle, the channel state persists as held, and the target still names all three, so **the book takes its position at the next 4h bar close, 20:00Z**. Equity being exactly 100,000.00 for 30 consecutive cycles is the signature to check: it means no position was ever opened, not that the book is losing.

**What this means for reading the A/B.** `#full-deployment-outcome` needs 28 days and the clock on `momentum_top3_full` started 2026-09-20 18:21Z, six hours after its own control. The two arms are not yet comparable on any horizon, and `./run_bots.sh compare` will keep saying so.

**The competition-day version of this matters.** On 2026-10-04 every book cold-starts. Whatever is mid-breakout on that first cycle is suppressed and entered one bar later, up to four hours after the signal. That is the guard working as designed, but it means the first four hours of a fourteen-day window are spent flat, and nobody has measured what that costs.

## 4i. Return-maximisation operating logic - experiment, learn, validate, re-learn, 2026-09-21

This section is the operator directive. **Maximise final portfolio return over the fourteen competition days.** Past results are priors and guardrails, not scripture. A family marked "closed" means do not rerun the same dial on the same data and call it discovery; it does **not** ban a new mechanism, a corrected simulator, new sealed data or a state-conditional policy. Every new idea must say why it should add right-tail return, run beside the control, and be easy to reverse.

### What the current leaders actually say

The 2026-09-20 19:03Z snapshot behind the current ranking is:

| portfolio | return | age | readable conclusion |
|---|---:|---:|---|
| paper `ranked5_4h` | +4.372% | <1 day | liquid momentum plus a 4h clock is the common hypothesis |
| paper `ranked5_hourlyexit` | +4.368% | <1 day | the exit difference has contributed essentially nothing yet |
| live `momentum_top3_4h` | +4.327% | 6.9h | concentration amplified the shared move |
| live `momentum_top5_cushion` | +3.679% | 10.4h | the cushion difference is only +0.041pp |
| live `momentum_top5_4h` | +3.638% | 10.8h | same winner-momentum cluster |

Process check during this update: all seven configured strategy workers in this checkout report `STOPPED`. The table is the latest saved portfolio state, not a claim that those returns are still live. Restarting capital-bearing processes is an operator action and was not inferred from a documentation request.

The commonality is more informative than their order: the leading books all own liquid recent winners on roughly the same 4h rhythm. This corroborates the mechanism found in the long sample and in Begušić and Kostanjčar; it does not select top3 versus top5 or one exit after six to eleven hours. These portfolios are correlated observations of one market move, not five independent confirmations. **Act on the common mechanism; do not chase the displayed winner.**

### Profit recycling: define it correctly

At every cycle `bot/run.mark` computes current equity `E_t = cash + marked positions`; `portfolio.deltas` then computes each order as `(target_weight - current_weight) * E_t`. Therefore realised and unrealised profits already increase the dollar size of the next target, and losses reduce it. **Compounding/recycling is already 100%.** With gross capped at 1.0 and no leverage, there is no multiplier above this.

The correct default is therefore:

```
deployable_NAV_t = marked_equity_t
target_notional_i,t = target_weight_i,t * deployable_NAV_t
sum(abs(target_weight_i,t)) <= 1.0
```

Do not create a special "house money" bucket: a rupee of profit and a rupee of starting capital have the same forward payoff. A profit lock is justified only by **contest state** - for example, once a visible qualifying target/rank has been reached - not because the rupee came from a winning trade.

### Position sizing: next mechanism to test

Keep `momentum_top3_full` as the return champion/control: top-three liquid momentum among names that passed the channel, full gross across the names that actually signalled, current 25% drift band. Add shadow arms one at a time; do not change selection and sizing together.

**Arm A - bounded conviction/uncertainty tilt.** Equal weight ignores both the distance between ranks and estimation uncertainty. On each fresh 4h bar, compute the existing 40-bar momentum score `m_i`, a slow causal volatility estimate `sigma_i`, and cross-sectional robust z-score `z_i`. For the same selected top three only:

```
raw_i = exp(eta * clip(z_i, -2, 2)) / max(sigma_i, sigma_floor)
w_i = project raw_i onto the bounded simplex:
      sum(w_i) = current target gross and 0.20 <= w_i <= 0.45
```

Use a proper bounded-simplex projection; naive clip-then-renormalise can break the caps. Pre-register a single conservative `eta`; do not grid-search it. The 20%-45% bounds stop this becoming the rejected top1 lottery, while allowing the strongest cleaner trend to receive more recycled NAV. Use slow volatility because Chen and Cai find fast time-varying moment estimates do not transfer well in crypto portfolio construction.

**Arm B - dispersion-conditioned winner drift.** Keep target selection and gross unchanged. Use the already-published dispersion state only to change the no-trade band: allow a wider band in the high-dispersion tercile so a winning position can grow toward the 45% cap; tighten toward equal weight in low dispersion. This is not the rejected constant band sweep: its mechanism is that high dispersion produces both this strategy's right tail and its winner separation. Shadow it first because the same regime also contains the worst windows.

**Arm C - rank/target overlay, only if the leaderboard is observable.** Below the projected top-20 cut, stay at full gross in the idiosyncratic top-three book and avoid the BTC floor, maximising dispersion from a BTC-heavy field. Above the cut, progressively correlate with the field through a BTC sleeve or lock enough NAV to preserve qualification. This is state-triggered, never a blind end-of-calendar derisk. Without reliable rank/cut data, Arm C is disabled.

Do **not** introduce full Kelly, leverage, top1 concentration, permanent BTC fill, or an unrestricted covariance optimiser. Recent work supplies hypotheses, not permission: the 2026 Conformal Kelly study preserved forecast calibration on its sealed window but its sizing rule fell below passive growth; the repo's own top1 and always-on tests show the same overfit shape.

### The learning loop

1. Write the causal formula, costs, one primary score and kill conditions before seeing the result.
2. Reconcile the simulator to the control within 0.1pp, then run anchored fit, sealed holdout, year blocks and rolling fourteen-day windows.
3. Primary objective is holdout `P(return > 10%)`; also report `P(>5%)`, `P(>20%)`, median, worst fortnight, max drawdown and turnover. Promote only if `P(>10%)` and median both improve, the improvement is not carried by one year/coin, and worst fortnight is no more than 5pp below control.
4. Run any survivor as an identical-timestamp shadow beside the control. Read paired return deltas, exposure and attribution at every closed 4h bar; do not compare unaligned launch NAVs.
5. The fourteen competition days are enough to **operate and update probabilities**, not enough to establish a timeless edge. During the contest, adapt only on pre-declared state variables (rank/target, dispersion, signal uncertainty), never on which arm happens to lead the screenshot.
6. At each checkpoint: keep, shrink, or revert. Record what falsified the mechanism. A failed arm becomes information for the next hypothesis, not a principle that all future sizing research is forbidden.

### Immediate outcome

Run the validated liquid-winner momentum mechanism; use `momentum_top3_full` as the current return-maximising control; keep all profits continuously in marked NAV; and spend new research capacity on the three bounded/state-dependent arms above. The highest-value implementation order is **Arm A, then Arm B, then Arm C if and only if leaderboard visibility exists**. This supersedes the sentence in section 4g that "further sizing work has no expected value": repeated static dials are closed, but portfolio-aware and state-conditional sizing are open.

### Implementation status, 2026-09-21

Arm A is now implemented as a paper-only paired experiment in `paper_lab_v9`.
`top3_equal_full`, `top3_invvol_full` and `top3_conviction_full` share the same
top-30 ADV/Roostoo universe, channel gate, 4h clock, top-three momentum selection,
20%-45% name bounds, 100% gross ceiling, 10 bps fee assumption and passive-cross
fill model. Only the sizing map differs. The conviction arm uses the declared
single value `eta=0.35`; it was not grid-searched.

`liquid_winner_14d` was added separately as the slower paper-mechanism arm: top
nine recent winners from the same liquid pool, equal weighted and rebalanced every
14 days. Do not compare its raw path to the 4h arms without accounting for the
different signal and turnover; it is a strategy-family test, not a sizing A/B.

Every v9 candidate writes append-only `decisions`, `orders` and `fills` JSONL
streams at `live/paper_lab_v9/<candidate>/`. The paper dashboard exposes each
bot's decision/event counts and log path. Its state remains descriptive: there is
no automatic winner promotion and no capital-bearing process is changed by v9.

Operational verification at 2026-09-21 01:05 IST: both LaunchAgents are running;
the lab has not exited, the localhost dashboard is live at `http://127.0.0.1:8788`,
all 17 books have trace records, and the full suite reports 159 passing tests.
The first three cycles are startup/fill observations only and must not be read as
performance evidence.

Dashboard clarification added later on 2026-09-21: the terminal no longer shows
aggregate lab P&L or fees. Its header and result cards are scoped to one selected
bot, the comparison table is one explicit independent wallet per row, and the log
tabs retrieve that bot's append-only decisions, orders and fills from
`/api/bot?name=<bot>`. Switching the bot updates results, logic, positions,
working orders and logs together.

---

## 4i. "We are not booking enough profits" - measured on our own live positions, 2026-09-22

`DECISIONS.md#live-excursion-outcome`, gate `gates/live_excursion.py`, declaration `config/live_excursion.yaml`, artifact `results/live_excursion.json`. 11 trials added. **Nothing adopted.**

**The observation is correct and bigger than expected.** 96 closed round trips, deduplicated to **57 symbol-episodes across 22 symbols**. Median maximum favourable excursion **+2.77%** against a median realised **+0.85%**, so the median position captures **0.33** of its best moment and hands back the rest. Summed give-back is 171.5 points of position return. The extreme case: ENAUSDT reached +12.8%, closed at +2.7%, peak **5% into a 36-hour hold**.

**Every rule that books it loses on those same paths.** Trailing stops and fixed targets replayed on the observed minute marks, exit charged 5 bps, no re-entry:

| rule | mean | vs actual | wins |
|---|---|---|---|
| **actual exits** | **+1.91%** | - | - |
| trail 1.0% | +0.48% | -1.43 pp | 22/57 |
| trail 1.5% | +0.56% | -1.35 pp | 17/57 |
| trail 3.0% | +1.98% | +0.07 pp | 15/57 |
| target 3% | +1.16% | -0.75 pp | 12/57 |
| target 12% | +2.05% | +0.14 pp | 6/57 |

A tight trail cuts mean return by two thirds. The four rules with a positive mean delta fire on 7 to 29 of 57 episodes and win on 5 to 15, so they barely act and their edge is noise. **Candidates: NONE.**

**Name the trap.** The 2% and 3% targets raise the MEDIAN trade from +0.85% to about +2.0% while cutting the MEAN from +1.91% to +1.17%. A book running them shows more winners, more closed trades and a better-looking blotter while making less money. That is exactly what "not booking enough profits" feels like from the dashboard, and it is the wrong reading of the same data.

**Why it cannot work.** MFE against peak position in the hold is Spearman **+0.434, p=0.001** - the biggest winners peak LAST. Any rule tight enough to catch ENA at 5% of its hold truncates SUIUSDT, which ran +21.2% with its peak at 89% and was captured at 0.85. And nothing observable early separates them: first-30 and first-60-minute returns against peak position give p=0.29 and p=0.22, and against give-back p=0.99. A fast start actually predicts a BETTER final return, median +1.34% against +0.35%.

**The stated mechanism is inverted on both halves, on 24 symbols and 1,252 minutes of live marks.** Cross-sectional correlation is **0.350 at 1 minute, 0.381 at 15, 0.407 at 60, 0.414 at 240** - weakest at the shortest horizon and rising with it, the Epps effect, not the premise. PC1 explains 41.1% of 1-minute variance, so 59% is idiosyncratic and there is no single pattern to time. Mean lag-1 autocorrelation of 1-minute returns is **-0.029**: mildly mean-reverting, not trending, the same sign and size as `#scalp-meanrev-outcome` and arXiv:2608.21888.

**What it is worth.** An independent dataset agreeing with the history. Targets died on 4h bars across 26 configs; they die again on live minute paths. The channel exit is already both the stop and the target. **Sample limit: 44 hours, one regime, 57 episodes - enough to refute a large obvious effect, nowhere near enough to establish one.**

---

## 4j. alpha_flow - the profit-booking bot, built and running, 2026-09-22

`DECISIONS.md#alpha-flow-declaration`. Operator instruction: stop treating the existing rules as fixed, build a bot that books profits and recycles them, drive selection from correlation and coin selection, find the logic in volume, gamma and order flow, use exploitable alternate data, ship it for forward testing. 53 trials added, ledger now **525**.

### What the analysis found before the build

**Order flow is a null at tradeable horizons.** `taker_buy_quote` is cached for the full history, so true aggressor imbalance is computable, and `#flow-scalp-outcome` only ever tested it at 5 to 30 minutes. At 4h to 3 days the cross-sectional IC never reaches |t| 1.3. As a ranker it takes holdout median from 3.12% to 0.85%.

**Coin selection is structurally weak here, and the number is 0.835.** That is the mean correlation of each name to the equal-weight universe at 4h. About 16% of a coin's variance is idiosyncratic, so choosing between names is mostly choosing beta - and selecting ON the residual is the worst arm tested, at a -67% worst window.

**Funding crowding is the strongest fit signal this repo has ever produced and it does not replicate.** A new panel at `data/cache/alt/funding_panel.parquet` (10,731 x 51 names, back to 2020) gives IC -0.068 at 3 days, t -7.1 on fit. On holdout the 24h IC is +0.008, t +0.6. Coverage is the reason: only **46% of fired candidates have a perp**, non-randomly, so any veto strips the majors. The nonsense control - vetoing the LEAST crowded - reproduces the baseline exactly, which is what a coverage artifact does and a real signal does not.

**All three forms of booking profits are now tested.** Recycling into the same target is arithmetically a rebalance that pays fees (3.07 to 3.10 vs control 3.11). Redeploying into new names loses on every pairing (2.44 vs 3.59). **Skimming into cash improved both windows** - holdout median 3.11 to 3.59, drawdown -12.67 to -8.43, gross 0.699 to 0.511 - but the return gain is **not significant (p=0.14)** and the drawdown gain is **reproduced by a random-timing control**, so it is exposure reduction, not timing.

### What was built and why it is shaped this way

| file | what |
|---|---|
| `data/options.py` | dealer gamma from Deribit: strike and expiry parsed from the instrument name, BS gamma off `mark_iv`, net GEX in dollars per 1% move, gamma flip strike |
| `bot/alt_data.py` | throttled collector: GEX plus open interest, long/short ratio and funding per held name |
| `bot/alpha_flow_run.py` | `Bot` subclass with the skim ladder |
| `config/alpha_flow.yaml` | frozen declaration |
| `tests/test_alpha_flow.py` | 8 tests |

**The bot**: `momentum_top3_full` plus a ladder that skims 40% of a position each time it gains 5% from its reference, then resets the reference, so a runner is booked repeatedly on the way up and a position that never gains is never touched. Booked cash **idles**, because recycling was measured to be a no-op or worse. Control is `momentum_top3_full`, identical otherwise. Started via `./run_bots.sh alphaflow`, cold-start suppressed 3 entries on its first cycle as designed, takes its position at the next bar close.

**Why gamma is collected and not traded.** Deribit publishes option OI as a snapshot and never as a history; Binance retains OI and long/short for 30 days. Neither survives the fit-and-holdout split every other claim here is held to. `alt_data.trades_on_it` is **false** and the collector runs every 15 minutes so a dataset exists in 30 days. First reading: BTC net GEX **-425m per 1% move**, 645 instruments, gamma flip **80,000**, spot 86,487 - dealers short gamma, hedging with the move.

**What to watch.** Median 14-day return against the control AND mean gross. If the skim is only reducing exposure, return tracks the control while gross sits near 0.51 and nothing was gained.

---

## 4k. RSI 50/70 band and the "filter the coins that follow it" question, 2026-09-22

`DECISIONS.md#rsi-band-outcome`, gate `gates/rsi_band.py`, artifact `results/rsi_band.json`. 3 trials, ledger **528**. **Nothing adopted.**

15-minute bars for the 55 names ever in the PIT top-30 were downloaded for this and are now at `data/cache/panel_15m.parquet`; only five symbols were cached at 5m. Note the two cache conventions that coexist and cost a debug cycle: `data/flow.py` reads `flow_<iv>.parquet`, `data/universe.build_panel` writes `panel_<iv>.parquet`.

| interval | trades/day | win | mean GROSS | net @10bps | reached RSI 70 |
|---|---|---|---|---|---|
| 15m | 99.6 | 0.381 | **-0.36 bps** | -20.36 | **11%** |
| 1h | 23.7 | 0.382 | **-1.33 bps** | -21.33 | **12%** |
| 4h | 5.7 | 0.383 | +9.36 bps | -10.64 | **14%** |

**At 15m and 1h it is negative before costs** - stronger than the usual cost failure, there is no gross edge to lose. And the rule almost never does what it is named after: 86 to 89% of trades exit on RSI falling back through 50, not at 70. Median net is far worse than mean at every interval, so the mean is carried by a thin tail of trend continuations and the 70 cap truncates exactly the tail that pays - `#take-profit-outcome` from a third direction.

**The coin filter is the real finding.** Fitted on the fit window, applied to holdout, bottom quartile carried as a nonsense control:

| interval | FIT top vs bottom | HOLDOUT top vs bottom | persistence rho |
|---|---|---|---|
| 15m | +4.02 / -22.63 | **-20.19 / -19.71** | -0.109 |
| 1h | +12.55 / -50.37 | **-22.91 / -25.42** | -0.002 |
| 4h | +58.40 / -50.63 | **-36.92 / -14.46** | -0.024 |

In-sample the 4h filter shows a 109 bps per-trade spread. Out of sample the spread is gone and at 4h it **inverts** - the rejected coins beat the selected ones by 22 bps. All three persistence correlations are zero or negative. **"Filter the coins that follow this pattern" is a description of the fit window, not a strategy.** Independent replication of `#coin-selection-does-not-persist` on an unrelated rule.

Kept: `signals/rsi.py`, Wilder seed, validated against the published series (70.46 vs 70.53), 7 tests. A bare `ewm(adjust=False)` is a different, faster indicator - it crosses 50 more often, and the whole signal is a level cross.

---

## 4l. Live on Binance testnet, 2026-09-22

`DECISIONS.md#testnet-live`. `./run_bots.sh testnet` runs `config/testnet_live.yaml` authenticated against `testnet.binance.vision`, placing **real orders on a real matching engine**. Own journal at `live/testnet_live/`, so the nine paper books are untouched.

**The blocker was removed by building the thing it named.** `bot/run.py` raised `live_orders_blocked_until_restart_reconciliation_is_implemented` for ANY non-dry-run, Roostoo included, so this was on the competition's critical path anyway. `bot/intents.py` writes and **fsyncs the order intent BEFORE** the venue call, resolves it after, and settles every unresolved intent against the venue on startup before a new order may be sent. Binance matches exactly via `newClientOrderId`; Roostoo has no such field so its path reports `matched_by: heuristic` and never claims certainty.

**Four live-only defects, none producible in a dry run:**

| # | defect | symptom |
|---|---|---|
| 1 | empty universe meant "adopt everything" | adopted **487 positions, 469 orders in one cycle**, equity read $444,275 |
| 2 | a resting order locks the asset, holdings don't show it | re-sold the same position every cycle, 15x `-2010`, **book halted** |
| 3 | Binance needs `symbol` on cancel, Roostoo doesn't | `-1105` on every sweep, error rate walking to the kill switch |
| 4 | `wallet_positions` counts `free + lock` | masked by 2 for now; will bite when partial fills appear |

Current state: cycling clean, `halt: False`, no errors, stale orders cancelled correctly, **0 unresolved intents**. 195 tests.

**Read fills and rejections, never returns.** Testnet prices are synthetic, and the account holds ~9,600 USDT against the 100,000 every paper book assumes.

**One book, not nine, and this is a hard limit**: `adopt_wallet` treats the venue wallet as authoritative and all nine bots share one API key, so they would each claim the whole wallet and rebalance each other away. Nine live books needs nine keys.

**Roostoo is still blocked** - both credential lines are commented out and marked NOT YET ISSUED. Forcing it would fail every call, cross the 0.25 error-rate switch in ~5 cycles, and a halt flattens the book. That is question 3 of `ORGANISER_QUESTIONS.md`. Also: the public `exchangeInfo` says `InitialWallet: {"USD": 50000}` against the **100,000** every config assumes - worth confirming, it halves every notional.

---

## 5. Settled - do not re-test

- **Gate 4, by counting.** Section 1.
- **Sub-hourly mean reversion and scalping.** Section 4b. Confirmed dead by outside evidence as well as by this repo's own sweeps.
- **Cost-aware turnover filters at this holding period.** `#rotation-hysteresis-outcome`.
- **`exit_bars = 10` is correct.** Walk-forward over 33 blocks. `DECISIONS.md#exit-walkforward-outcome`
- **The PIT top-30-by-ADV universe rule is correct.** Per-coin edge does not persist (Spearman 0.091, p=0.586) and the 8 worst coins beat the 8 best out of sample. `DECISIONS.md#coin-selection-does-not-persist`
- **RSI 50/70 band is a null at 15m, 1h and 4h**, and negative BEFORE costs at 15m and 1h. `#rsi-band-outcome`.
- **Filtering coins by which ones obeyed a rule in-sample has zero out-of-sample content**, now measured twice on two unrelated rules. `#rsi-band-outcome`, `#coin-selection-does-not-persist`.
- **Order flow, volume surge and average trade size are nulls as cross-sectional rankers at 4h to 3d.** `#alpha-flow-declaration`.
- **Funding-rate crowding does not replicate out of sample**, and its fit-window strength is a perp-coverage artifact. `#alpha-flow-declaration`.
- **Recycling booked cash is a rebalance, and redeploying it into new names is worse than idling it.** `#alpha-flow-declaration`.
- **Booking at peaks does not work, now on LIVE data as well as history.** Median capture is 0.33 and the give-back is real, but the biggest winners peak last (rho +0.434, p=0.001) and nothing observable early separates them. `#live-excursion-outcome`.
- **The short-horizon co-movement premise is measurably inverted.** Correlation 0.350 at 1 min rising to 0.414 at 4h; 1-min lag-1 autocorrelation -0.029. `#live-excursion-outcome`.
- **The entry rule survives its two strongest challenges**: cross-sectional reversal and strong-but-retraced both lose to demanding the new high.
- **Deployment cannot be raised.** Removing the channel gate, filling empty slots with next-best momentum, and never trimming a winner all lose on the holdout. `#compounding-outcome`.
- **The static drift band stays at 0.25.** The constant-value sweep had an interior optimum near 0.40 but the entire spread was inside the noise floor at 43 independent windows. Do not select another constant from that sweep. Section 4i leaves a dispersion-conditioned band open because that is a different causal mechanism. `#compounding-outcome`.

Nulls, all in `DECISIONS.md`: `#scalp-meanrev-outcome` (54 configs), `#correlation-cap-outcome` (24), `#exit-clock-outcome` (12), `#flow-scalp-outcome` (72), `#meanrev-xs-outcome` (48), `#ratchet-outcome` (26), `#strong-retraced-outcome` (24).

---

## 6. Fee robustness

Measured sensitivity, full history, net:

| book | 5 bps | 10 bps | 15 bps | 20 bps |
|---|---|---|---|---|
| donchian_4h | 2.071 | 1.957 | 1.842 | **1.727** |
| momentum_top5_4h | 2.107 | 1.907 | 1.707 | 1.506 |
| momentum_top3_4h | 2.084 | 1.882 | 1.679 | 1.477 |

`donchian_4h` loses 0.114 Sharpe per 5 bps; the concentrated books lose about 0.20.
Against the 1.806 hurdle at N=754 (1.726 at N=470), `donchian_4h` clears to roughly 15 bps while **both concentrated books fall below at 10 bps**.

**`donchian_4h` is the robust book. `momentum_top3_4h`, the one currently live, is a bet that fees are cheap and that the rank gate binds.** It is down 0.717%.

---

## 7. Regime context

Dispersion is the dominant conditioner and the scanner publishes it every cycle.
It is **3.65%, the low tercile**, where the book is measurably a coin flip: median Screen 3 +0.49, P(return>0) 0.507, while still paying cost drag.

**Flat performance right now is expected behaviour, not a fault.** In the top tercile the same book scores +3.72.

Breadth carries no information in any book - do not condition on it.

---

## 8. Bug log - defects found in this repo's own code

Trust the harness accordingly. Full list including this session's four is in `CLAUDE.md` under anti-patterns.

- **Two look-ahead bugs** in the exit-clock work, both from Binance bars being labelled by **OPEN** time.
  Caught by a **nonsense control**: a random exit at the same rate returned 27,594x against the real rule's 114x.
  A one-bar delay test had already passed the broken code.
  Use `signals.exit_clock.to_fast` for cross-frequency work and assert fast==slow reproduces the single-clock function exactly.
- `gates/ratchet` reported **skew as +0.00 for every arm** because `gates.concentration.stats` does not return skew, and skew was the declared kill criterion.
- `kept_share` was a mean of per-trade ratios and returned **-37**, which is not a share of anything.
- `bot/compare.py` had the paper-lab version **hardcoded** and silently showed a 3-hour-stale root.
- **A pgrep guard that cannot match its own process is not a guard.** Section 3.
- **A default argument pointing at a fixed path goes stale exactly like a hardcoded list.** Section 3.
- **A frozen book's telemetry is indistinguishable from a live one's** unless age is shown. Section 2.
- **A default argument is a silent declaration.** `gates.concentration.rank_score` defaulted momentum to a **20-bar** lookback while every deployed book ranks on **40**, so five gates scored a book the bot does not trade. Found by a reconciliation failure, not by a test: a new gate missed section 4e's tables by 0.6 points of median return and the lookback was the only difference. `competition_oos` and `exit_walkforward` were re-run under the correct lookback and **neither conclusion moved**; `correlation_cap`, `exit_clock` and `ratchet` were not re-run and their nulls still rest on 20 bars. `DECISIONS.md#ranking-lookback-mismatch`.

---

## 9. Next session protocol, in priority order

1. **Send `ORGANISER_QUESTIONS.md`.** Zero trials. Highest value action available, and now the ONLY one that changes anything material. It carries a **seventh question added 2026-09-21 on leaderboard visibility**, which decides whether the BTC floor can be made rank-conditional rather than blind. The duplicated Screen 3 question was merged at the same time.
2. **Let forward evidence accumulate, and separate inference from operation.** `paper_lab_v8` and the frozen cushion A/B add observations, not trials. Their existing promotion claim is not readable before 28 complete days and `./run_bots.sh compare` correctly enforces that. During the fourteen-day competition, however, operate and update state using the pre-declared logic in section 4i; do not pretend the resulting fortnight establishes a timeless edge. The lab is supervised now, so check it is alive rather than assuming it.
3. **Decide `momentum_top3_4h` versus `donchian_4h` deliberately**, on section 6, not on the live P&L of either. The live sample is hours long and means nothing.
4. **Decide the derisk ramp.** Both sides are measured, section 4f. On the competition objective it is negative; as a risk preference it is the operator's call. A state-triggered version is the shape the literature endorses and is untested.
5. **Re-run `correlation_cap`, `exit_clock` and `ratchet` under `MOM_BARS = 40`** if any of their nulls is ever cited to close a question. Zero trials: re-measuring an already-counted configuration is not a new search.
6. **Implement section 4i's sizing arms in order: bounded tilt, conditional drift, then rank overlay only if rank is observable.** One declared value per mechanism, identical-timestamp shadow, and the existing control reconciliation first.
7. **Do not run a sweep to rescue Gate 4.** It cannot be rescued. Run one only if a family has a stated mechanism and a pre-registered per-trade floor, as `config/flow_scalp.yaml` did.

---

## 9b. The analysis tab

`http://127.0.0.1:8787/analysis`, served by `bot/analysis.py` and `bot/analysis.html`, data at `/api/analysis`.
The desk page is unchanged and links to it.

Six panels, in the order they should be read:

1. **Readiness.** Every gate between the current state and a readable claim: the 28-day forward A/B, Gate 10's three distinct days, and 30 markout fills per horizon, each with a progress bar. This is first on the page on purpose.
2. **Normalised equity, all six strategies on one axis**, base 100.
3. **Gated arm minus its control**, with the days-remaining verdict printed on the chart.
4. **Per-strategy detail**: equity, underwater and gross-exposure sparklines, plus equity, return, drawdown, gross, names and markout.
5. **Regime**: dispersion and pct-long history, labelled with which one carries information and which does not.
6. **Decision log**: bar closes only, across all books, with targets, orders and equity.

**The page refuses to imply readability.** `ab_spread` computes `readable` from elapsed days and the chart prints "TOO EARLY - N more days" until the gate is met, because `bot/compare.py` already refuses to read a lead before `min_comparison_days` and a chart that quietly ignored that would undo it.

One bug worth remembering: `live/scanner/scans-*.jsonl` is **flat**, while `live/scanner/state.json` nests the same fields under `universe`. Reading the wrong shape returns a full-length series of nulls that renders as an empty panel rather than raising, so `tests/test_analysis.py` asserts the values rather than the row count.

## 9c. Selection funnel, and the coin-picking question

The analysis tab's funnel panel answers "are the signals being picked up" continuously, per book: listed on venue -> top-30 by ADV -> tradable -> above the channel -> held after the rank cut, with every dropped name and its reason.

**It also settles a recurring misreading.** These books look broad because the POOL is 30 names. They are not broad. On 2026-09-20 `donchian_4h` held **3 of 23 tradable names at 15% gross and 85% cash**, because only 3 of 23 cleared the channel. The panel prints an explicit banner when cash exceeds 70%, because that state is **under-deployment, not over-diversification**, and the two want opposite fixes.

The funnel distinguishes `SIGNAL_NOT_TAKEN` (above channel, outside the rank cut) from `FLAT` (no channel break). Collapsing those two would hide whether the signal fired at all, which is the thing being diagnosed.

**On filtering to "the best coins with edge and alpha": this repo has falsified that twice and must not do it.**
- `CLAUDE.md`: coin-level performance has **zero persistence**, Spearman -0.018, p=0.91, and picking historical winners was **worse** than picking historical losers.
- `DECISIONS.md#coin-selection-does-not-persist`: Spearman 0.091, p=0.586, and **the 8 worst coins beat the 8 best out of sample**.

The selection that IS supported is already in the stack and is not per-coin alpha: an **absolute** liquidity bar (top-30 by 30-day median dollar volume across the whole Binance market, not a rank inside Roostoo's 66 - see finding 1 in `CLAUDE.md`), a spread gate, the channel itself, and a **cross-sectional momentum rank recomputed every bar** in the top5/top3 books. Concentration is available and already running as `momentum_top3_4h`; it is chosen on a stated objective, not on a backtest ranking.

## 9d. Session P&L attribution, 2026-09-20 14:15Z

The books went from green to red. The cause is one name, not the strategy.

| book | AVAX | TRX | ENA | book |
|---|---|---|---|---|
| donchian_4h | +2.02% | +1.14% | **-3.82%** | -0.02pp |
| momentum_top5_4h | +2.02% | +1.14% | **-3.77%** | -0.08pp |
| momentum_top3_4h | +2.40% | n/a | **-5.82%** | **-1.02pp** |

**Two of three names are up.** ENAUSDT carries the entire loss in every book, and the spread across books is exactly position sizing: 4.8% weight costs 0.18pp, 31.8% weight costs 1.85pp.

`momentum_top3_4h` is additionally down 0.69pp from `#cold-start-chases-the-bar`, which is launch timing rather than strategy.

Exit floors are far below: ENA's 10-bar low sits 15.6% under the mark, TRX's 2.5%. That gap is the channel rule working as designed, and `DECISIONS.md` records **four** separate failures of tightening it (`#asymmetry-outcome` ATR stops, `#take-profit-outcome`, `#exit-clock-outcome` faster clock, `#ratchet-outcome`). Do not propose a fifth without a declared mechanism and a control.

Two new analysis panels make this readable without a query: **Open positions** (entry, mark, contribution, distance to exit, with a banner when a red book is carried by one red name) and the **Selection funnel**.

**Nothing here is a result.** The sample is about two hours.

## 9e. Robustness pass, 2026-09-20 17:30Z

Three defects found from nine hours of live logs. None changes a signal; all three change what the stack costs or reports.

1. **`#live-rebalance-chases-drift`** - the real one. Backtest turnover is `|w_t - w_{t-1}|` on TARGET weights and never models a holding drifting with its mark; the live book rebalances against the drifted actual weight, so an unchanged target emitted an order every cycle. Five of `donchian_1h`'s eleven closed trades were 3-to-19-dollar drift chases paying full fees **the backtest never charged**. Fixed with the already-pre-registered, explicitly unfitted `portfolio.no_trade_band: 0.25`, which the live path used nowhere. Opens and closes are never suppressed; only drift is.
2. **`#dust-trades-distort-count-statistics`** - those same trades produced a reported payoff ratio of **2,156** off an `avg_loss` of half a cent. The blotter now splits material from dust at a stated 50-dollar floor and reports BOTH win rates.
3. **`#restart-telemetry`** - the dashboard reported 1-3 "restarts" and said a worker had died. **Zero crashes occurred.** It was counting operator stop/starts and a `--once` probe. `bot/health.py` now separates crashes, resumes and probes.

`#no-trade-band-live-outcome` is a **null in backtest** and that is the point: the momentum books are bit-identical because equal 1/n weights mean every move is a full open or close, and the backtest has no drift to suppress because it never modelled drift. The backtest could not have found defect 1.

Stack restarted on the fixed code at 17:30Z. Ledger 770 -> 776.

## 9f. scalper_live, running on operator override

`config/scalper_live.yaml`, `bot/scalper_run.py`, supervised via `./run_bots.sh scalper`, seventh card on the desk page.

**It failed its own backtest and runs anyway, by explicit operator instruction.** `config/scalper_v1.yaml` said "promotion: none. A pass earns a paper bot"; 0 of 64 arms passed. Paper only, never promoted.

**Read the MEAN net bps per trade and nothing else.** Backtest: win rate 0.665, median **+26.72 bps**, mean **-5.93 bps** over 559 trades. **64 of 64 arms had a positive median and a negative mean**, so a good-looking win rate here is confirmation of the failure mode, not evidence against it. The dashboard card is built around the mean for that reason and `./run_bots.sh scalpreport` prints it.

**Falsification, pre-stated:** if the mean is still negative after 200 live round trips, the family is settled forward as well as in backtest and the bot should be stopped. If the mean clears 10 bps, the backtest was wrong and that is worth knowing.

**Universe widened 2026-09-20T18:20Z: 5 names -> 23.** The backtest was limited to the five names with 5m parquet history; the live bot reads the live Binance feed and has no such limit, so it now runs the standard PIT top-30-by-ADV intersected with Roostoo listings, the same rule as every other book. Signal rate goes from ~0.89/day to ~4.1/day, which turns the 200-trade falsification threshold from ~7.5 months into ~1.6 months - the only lever that raises sample WITHOUT degrading the edge. Lowering `ofi_thresh` 2.0 -> 1.5 would also triple the count and the backtest says it makes the mean WORSE (-5.93 to -9.90 bps), so it was not touched.

**Read this as an extrapolation.** The per-trade edge was never measured outside those five names. It is defensible because the universe rule is the most validated thing in the repo and the 5 bps spread gate excludes the thin names where a 4 bps gross edge dies first, but it is still untested ground.

Design: long-only spot (fading a rally needs a short at 10 bps both legs with no maker discount), 30m bars, `ret<=-0.8%` with `ofi_z<=-2.0`, 0.5 ATR target, 1.0 ATR stop, 8-bar time stop, cost gate at 2x the round trip, 2-bar cooldown, 6 trades/symbol/day, 10% per trade, max 3 concurrent. Universe is the live PIT top-30 intersected with Roostoo, 23 names as of 18:20Z.

**A defect was caught before it went live:** the first build read `data/cache/5m`, whose last bar was **2026-09-19 05:30**, over 32 hours stale. It now pulls 30m bars from the live Binance feed and refuses any symbol whose newest bar is older than 90 minutes, journalling `scalper_bars_stale`. A scalper on stale bars produces meaningless forward evidence that looks exactly like real evidence.

It subclasses `Bot`, so it inherits the cold-start guard, drift no-trade band, kill switches, mirror check, markout instrumentation and atomic state unchanged.

## 9g. Positioning, implied vol and flow data, 2026-09-23

**Open interest and long/short history exist back to 2021-12.** The "30 days only" claim in four files was a REST limit; `data.binance.vision` archives it. `data/vision.py`, `data/macro.py`, `DECISIONS.md#positioning-history`.

**Eleven rules built on it failed a three-window test** (2022, 2023-24, 2025-26) against the deployed book with its ladder: OI-confirmed breakouts, funding veto, top-trader tilt, negative-funding priority, five market gates, two positioning-triggered booking rules. No live logic changed. `DECISIONS.md#positioning-edges-outcome`.

**The one robust fact is a prohibition:** removing the lowest-funding breakouts costs 1.5 to 3.7pp of median 14-day return in every window. Never add a veto that can remove them.

**Two stamping defects were caught before any number was read**, and one of them (the taker ratio's bucket-start timestamp) had manufactured a t=2.35 signal. Live and backtest features now agree to 5e-7 on OI; evidence at `results/positioning_live_parity.txt`.

`bot/alt_data.py` logs every feature in the gate's own definition, on a background thread. **All bots were found STOPPED on 2026-09-23** and were not restarted by the session that did this work.

Ledger 969 -> 980.

## 9h. Live test, fleet reset and lower-timeframe paper bots, 2026-09-23

`python3 -m gates.live_validation` now works again and checks every book against the backtest on the live bar. Four live defects fixed, each in `DECISIONS.md#live-validation-2026-09-23` or `#lowtf-paper-bots`: channel state that never caught up after a missed close; wide-tick names (PEPE and friends) refused by execution while the rank kept picking them, which cut the ranked book's real edge from 3.1% to 1.2% (operator chose to trade them; honest expectation now about 2.7%); the alt-data collector running once per 4h; and a full-deployment buy that could not afford its fee and was faked in the journal.

**Fleet reset to 100,000 at 2026-09-22T20:48Z**, 15 books, archive at `live/_archive/`. Five lower-timeframe paper bots added on instruction; all fail their backtest and are forward evidence only.

**Open, needs Roostoo keys:** fill rate of a passive order on a one-tick book, and rotation underweighting when sell cash arrives only on fill.

## 10. Quick commands

```
./run_bots.sh status         # what is live in this repo
./run_bots.sh compare        # gated arms vs controls, with age and NOT TRADING marks
./run_bots.sh scanner        # start the universe scanner (refuses if one is up)
./run_bots.sh scanstop
./run_bots.sh paperlab       # start the supervised paper lab, LAB=... to pick a root
./run_bots.sh labstop
./run_bots.sh scalper      # start the supervised paper scalper
./run_bots.sh scalperstop
./run_bots.sh scalpreport  # forward per-trade record; the MEAN is the criterion
./run_bots.sh start|stop     # CONFIGS=... to scope to one bot
python3 -m pytest tests -q   # expect 90 passed
python3 -m ruff check bot/ signals/ gates/ data/ core/ tests/   # expect clean
python3 -m gates.gate04_deflated_sharpe   # reports BOTH 754 and 470; both fail
```

Dashboard: http://127.0.0.1:8787 · Analysis: http://127.0.0.1:8787/analysis
