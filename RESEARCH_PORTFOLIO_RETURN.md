# Literature review: maximising portfolio return under a RANK objective, read against this repo

Written 2026-09-21.
Companion to `RESEARCH_SHORT_HORIZON.md`, which screened signal papers on whether an edge clears a 10 bps round trip.
This one screens a different literature on a different question, because the binding constraint is no longer the signal.

Screen 2 advances the top 20 per region on `(Final - Initial) / Initial`.
That is not a return-maximisation problem and it is not a Sharpe-maximisation problem.
It is a **contest**, and contests have their own literature with results that do not follow from portfolio theory.
Every paper below was read for one thing: does it change a decision this repo has already recorded?

Three do. One kills an idea the repo was about to adopt. One supplies the mechanism the repo has been missing. One independently validates the universe rule.

---

## 1. The finding that matters most: rank-optimal is not return-optimal, and it is ADVERSARIAL

### Staněk (2024, revised 2025), arXiv:2412.04490 - M6 Investment Challenge: The Role of Luck and Strategic Considerations

The closest published analogue to Roostoo that exists.
M6 was a real investment competition with a public leaderboard, a fixed deadline and a field of teams, scored on realised performance.
Two results, and both transfer.

**One.** The extreme Sharpe ratios at the top of the M6 leaderboard are not beyond what chance produces given the number of teams.
This is the multiple-testing argument this repo already applies to itself at `#trial-counting` and `#gate4-rerun-outcome`, pointed outward at the competition instead of inward at the research.
It has a direct operational consequence: **a leaderboard position, ours or anyone's, is not evidence of edge**, and mid-competition leaderboard reading must not be used to revise strategy. Section 1 of `HANDOVER.md` already forbids this for our own P&L; the same reasoning forbids inferring anything from a rival's.

**Two, and this is the one that changes a decision.**
Staněk derives the portfolio strategy that maximises P(top rank) in a stylised model of the contest and shows it is *not* the return-maximising portfolio.
The optimal policy is **adversarial with respect to the field's positioning, and conditional on current rank**:
- when BEHIND, maximise dispersion from what the field holds, even at the cost of expected return;
- when AHEAD, mimic the field, because correlation with the field preserves a rank you already hold.

The empirical section finds M6 participants' submitted weights actually did this.

**What this does to the BTC floor.**
`HANDOVER.md` section 4e leaves the BTC floor undecided, pending question 6 on where the cut falls.
This paper says the framing was incomplete.
In a crypto contest, BTC is not a neutral cash substitute - it is *the single most likely thing every other entrant is holding*.
Filling idle slots with BTC is therefore the **mimic-the-field** move, and the literature says that move is correct only when already above the cut and wrong when below it.
The raw distributional comparison in section 4e (median 3.12 vs 2.63, P(>10%) 0.321 vs 0.347) measures the floor's effect against the MARKET.
It does not measure the only thing that decides a rank, which is the book's dispersion from the FIELD.

So the decision is not "floor or no floor".
It is: **hold BTC only while above the projected cut, and hold the idiosyncratic book or nothing while below it.**
That policy needs a live leaderboard to be implementable, which makes question 6 of `ORGANISER_QUESTIONS.md` more valuable than it already was, and adds a question: **is the leaderboard visible during the competition, and at what frequency?**
If it is not visible, the state-dependent policy is unimplementable and the floor is a blind bet, which argues for leaving it off exactly as section 4e decided, but for a better reason than the one recorded there.

### Brown, Harlow and Starks (1996), Journal of Finance 51(1) - Of Tournaments and Temptations

The empirical ancestor. 334 growth funds, 1976-1991: mid-year losers raise portfolio volatility in the second half by more than mid-year winners do, and the effect strengthens as the field becomes more rank-aware.
This is the same rank-conditional risk-shifting Staněk derives, observed in the wild thirty years earlier.
Its value here is confirmatory rather than directive: the policy is not an artefact of one stylised model.

### Browne (1999), Advances in Applied Probability 31(2) - Reaching goals by a deadline

The continuous-time solution for maximising P(wealth reaches a target by a fixed date).
The optimal policy is equivalent to holding a European digital option struck at the target, written on the **growth-optimal (log-optimal) portfolio**.
Two consequences for us, and they pull in opposite directions, which is the useful part.

The strategy is *not* a fixed allocation. It scales aggression with distance to target and time remaining, becoming more aggressive when behind and near the deadline and, critically, **switching to the risk-free asset once the target is reached** - the deadline analogue of the derisk ramp, but triggered by state rather than by the calendar.
And the risky leg is the growth-optimal portfolio, not the highest-variance one.
Aggression belongs in the SIZING, not in the selection.
That is a formal statement of the repo's own L1 finding: `top1` raised P(>20%) while producing a negative holdout median, because concentrating the *selection* is not the same lever as scaling the *exposure*.

### Long (2026), arXiv:2604.17577 - Exact Finite-Horizon Quantile Kelly

Maximising a fixed upper quantile of terminal wealth over a finite horizon decomposes exactly into ordinary Kelly problems under a **shadow law** `k/n`, the count distribution of the outcomes you are conditioning on, and converges to ordinary Kelly as the horizon lengthens.
Plain reading: to finish in the right tail over a short horizon, size as if the favourable outcome were more frequent than it truly is, and the shorter the horizon the further from Kelly you should sit.
This is the formal justification for `full_deployment` over the 14-day window, and it also bounds it: the shadow law is still a probability vector, so the licence to overbet is finite.
`top1 full` at -2.56% holdout median and -81.8% drawdown is what overshooting that bound looks like.

---

## 2. What the crypto cross-section says about the book itself

### Liu, Tsyvinski and Wu (2022), Journal of Finance 77(2) - Common Risk Factors in Cryptocurrency

Three factors - market, size and momentum - price the crypto cross-section, and ten characteristic-sorted long-short strategies are all absorbed by them.
The sign on size is the one to read carefully: the long-short size return is significantly **negative**, meaning large caps outperformed small ones over the sample.
That is independent support for this repo's most load-bearing and least intuitive decision, the absolute top-30-by-ADV liquidity bar at `#roostoo-universe-pool-size`, which was adopted on a Sharpe difference of -0.15 against 1.56 and never had outside corroboration until now.
Momentum's long-short return is significantly positive, which supports the ranking rule; nothing here supports the *lookback*, and `#ranking-lookback-mismatch` is a reminder that 40 bars was never itself validated.

### Borri, Liu, Tsyvinski and Wu (2026), arXiv:2510.14435 - Cryptocurrency as an Investable Asset Class

Seven stylised facts. The one that bears on sizing: **jumps are frequent and large**, more so than in equities.
A book being built for a 14-day right tail wants exposure to those jumps, which is an argument for staying deployed and against any rule that flattens exposure on a schedule.
It cuts the other way too: the same jump intensity is why the left tail reaches -28% in a fortnight, and why `top3` rather than `top1` is the floor of concentration.

### The MAX / lottery literature - and why it does NOT license buying the wildest coins

There is an obvious wrong turn available when the objective is "maximise return": tilt toward the most explosive names.
The literature does not support it, and it does not even agree with itself.
Grobys and Junttila (2021, *Speculation and lottery-like demand in cryptocurrency markets*, JIFMIM) and the *Financial Innovation* MAX study (2021) report a **negative** MAX-return relation, with a 3.03% weekly raw spread between the highest and lowest MAX deciles.
Other work in the same literature reports a **positive** and significant MAX-return relation robust to size, momentum and skewness controls.
When a literature this size cannot agree on the sign, the effect is not a foundation to build on.

This repo's own `#coin-selection-does-not-persist` says the same thing from its own data: per-coin edge does not persist (Spearman 0.091, p=0.586) and the eight worst coins beat the eight best out of sample.
**Conclusion: buy the right tail through position concentration on a validated signal, not through selecting lottery-like coins.** The two are easy to confuse and only one of them has evidence behind it.

---

## 3. What this review does NOT provide

It provides no new signal, and it was not read for one.
`RESEARCH_SHORT_HORIZON.md` already established that the short-horizon signal literature confirms this repo's nulls, and nothing here revisits that.

It provides no answer to where the qualification cut falls.
Staněk's policy is conditional on rank, and rank is unobservable without the organiser's answer or a live leaderboard.
The literature has raised the value of `ORGANISER_QUESTIONS.md`, not replaced it.

It adds **zero trials**.
No configuration was evaluated and nothing was selected. The family-wise error budget is untouched.

---

## 4. Ranked implications, highest expected value first

1. **Add a leaderboard-visibility question to `ORGANISER_QUESTIONS.md`.** Staněk's result is only implementable if rank is observable during the run. This is now as valuable as question 6 and costs the same nothing.
2. **Re-frame the BTC floor as a rank-conditional rule, not a constant one.** Mimic the field when ahead, diverge when behind. Do not adopt a constant floor: the section 4e comparison measured it against the market, and the market is not what a rank is scored against.
3. **The derisk ramp is a calendar trigger where the literature uses a state trigger.** Browne's optimal policy goes risk-free when the TARGET is reached, not when the CLOCK runs out. `#derisk-ramp-protection-outcome` measures the calendar version as negative on both screens. A state-triggered version is the shape the literature endorses, and it is untested here.
4. **Do not tilt toward high-MAX coins.** The one idea a "maximise return" brief most invites is the one with contradictory evidence outside and a clean null inside.
5. **Never revise strategy on a mid-competition leaderboard reading.** Staněk's first result says the top of a leaderboard is consistent with chance at this field size.

---

## 5. Position sizing and recycling profits: additional paper check, 2026-09-21

This pass was prompted by the operator's narrower question: if the signal is held fixed, can dynamic sizing or a different treatment of profits raise terminal NAV over fourteen days? The answer is useful but not magical. Profits do not have a different economic identity from starting capital, and this bot already marks the whole wallet to market before computing order notionals. The research therefore bears on the **weight map**, estimation stability and contest state, not on a separate profit account.

### What transfers

**Begušić and Kostanjčar (2019), _Momentum and liquidity in cryptocurrencies_.** The paper studies 711 coins from 2015-2019, sorts on fourteen-day momentum and Amihud liquidity, equal-weights and rebalances every fourteen days. The momentum spread is significant in the liquid bucket, and the liquid-winner long-only portfolio remains attractive after the paper's explicit cost deductions. This independently supports the repo's liquid-universe plus winner-ranking architecture. It does **not** validate the repo's 4h clock: the study is daily, biweekly and in-sample, and its figure assumes zero market impact.

**Chen and Cai (2025), _Optimal vs. Naive Diversification in the Cryptocurrencies Market_.** Turnover penalties improve mean-variance portfolios, but the benefit shrinks as rebalancing becomes less frequent. Sophisticated time-varying mean/covariance forecasts generally underperform their simpler sample counterparts; volatility-timing portfolios only modestly improve on 1/N because crypto correlations are high. Translation: test a bounded, slow sizing tilt, not an unconstrained optimizer with fast estimates. The current 25% no-trade band is directionally consistent with this evidence.

**Krabichler and Wunsch (2021), _Hedging Goals_.** A finite deadline and a wealth target define a different control problem from mean-variance optimization. The optimal policy is state-dependent, and the paper supplies a transaction-cost-aware reinforcement-learning formulation. This supports testing a target/rank overlay, not blindly raising risk at a calendar date. Its continuous-market assumptions and monetary goal are not a direct Roostoo implementation.

### What is only a hypothesis

**Bui and Nguyen (2026), _Systematic Trend-Following with Adaptive Portfolio Construction_.** A six-hour crypto trend framework combines volatility-regime trailing stops, rolling selection and asymmetric allocation, reporting strong 2022-2024 results across 150+ pairs. It is a recent preprint with a short evaluation window and a multi-component design, so it cannot identify which component earned the return. It motivates a clean volatility/dispersion-conditioned sizing arm; it does not justify importing the full strategy.

**Ryan (2026), _Conformal Kelly_.** This is the warning attached to any clever sizing idea. A fractional-Kelly rule looked excellent after roughly 200 development configurations, but on the sealed 2022-2024 window its two variants earned only 8.5% and 7.0% annual growth, below passive benchmarks, and ranked last on Sharpe and Calmar. Calibration transferred; economic value did not. Dynamic Kelly or forecast-confidence sizing belongs in shadow until it wins on sealed data.

### Research-to-experiment conclusion

The highest-value new family is not more concentration, permanent full exposure, or faster rebalancing; those are already measured. It is a **bounded portfolio-aware tilt inside the existing top-three liquid momentum book**, plus a **state-triggered contest overlay** if rank is observable. Both keep the validated signal and change only allocation. The full operating logic and promotion rule are in `HANDOVER.md#4i-return-maximisation-operating-logic---experiment-learn-validate-re-learn-2026-09-21`.

---

## Sources

- Staněk, F. (2024). *M6 Investment Challenge: The Role of Luck and Strategic Considerations.* arXiv:2412.04490.
- Brown, K., Harlow, W. and Starks, L. (1996). *Of Tournaments and Temptations: An Analysis of Managerial Incentives in the Mutual Fund Industry.* Journal of Finance 51(1), 85-110.
- Browne, S. (1999). *Reaching goals by a deadline: digital options and continuous-time active portfolio management.* Advances in Applied Probability 31(2), 551-577.
- Long, C. D. (2026). *Exact Finite-Horizon Quantile Kelly for Repeated Multi-Outcome Events.* arXiv:2604.17577.
- Liu, Y., Tsyvinski, A. and Wu, X. (2022). *Common Risk Factors in Cryptocurrency.* Journal of Finance 77(2), 1133-1177.
- Borri, N., Liu, Y., Tsyvinski, A. and Wu, X. (2026). *Cryptocurrency as an Investable Asset Class: Coming of Age.* arXiv:2510.14435.
- Grobys, K. and Junttila, J. (2021). *Speculation and lottery-like demand in cryptocurrency markets.* Journal of International Financial Markets, Institutions and Money.
- *Lottery-like preferences and the MAX effect in the cryptocurrency market.* Financial Innovation (2021), 7:82.
- Begušić, S. and Kostanjčar, Z. (2019). *Momentum and liquidity in cryptocurrencies.* arXiv:1904.00890.
- Chen, H. and Cai, X. (2025). *Optimal vs. Naive Diversification in the Cryptocurrencies Market: The Role of Time-Varying Moments and Transaction Costs.* arXiv:2501.12841.
- Krabichler, T. and Wunsch, M. (2021). *Hedging Goals.* arXiv:2105.07915.
- Bui, D. and Nguyen, T. (2026). *Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in Cryptocurrency Markets.* arXiv:2602.11708.
- Ryan, R. J. (2026). *Conformal Kelly: Conformal Prediction Intervals as the Scale in Fractional Kelly Position Sizing.* arXiv:2608.01494.

## 6. Implemented forward experiment: paper lab v9

The literature pass was translated into `config/paper_lab_v9.yaml`; it does not
alter any capital-bearing bot. The live paper terminal ranks raw return before
Sharpe, Sortino and Calmar, and every candidate has its own append-only decision,
order and fill streams under `live/paper_lab_v9/<candidate>/`.

| Bot | What changes | Why it exists | Falsification signal |
|---|---|---|---|
| `liquid_winner_14d` | Top nine 14-day winners in the top-30 ADV/Roostoo intersection; equal weight; rebalance every 14 days | Direct forward translation of the paper's liquid-winner, biweekly mechanism | Loses after the same 10 bps fee model, or profit is concentrated in untradeable/wide-spread names |
| `top3_equal_full` | Existing 4h channel-qualified top-three signal; bounded equal weight | Paired sizing control | N/A; it is the comparison anchor |
| `top3_invvol_full` | Same names and bounds; slow 90-bar inverse volatility | Tests the modest volatility-timing result without a covariance optimizer | Return delta is non-positive or comes only from lower gross exposure |
| `top3_conviction_full` | Same names and bounds; `exp(0.35 * clipped robust-z(momentum)) / slow_vol` | Tests whether rank distance plus uncertainty improves profit recycling | Return delta is non-positive, cap-bound all the time, or dominated by one coin/regime |

The three top-three arms use a bounded-simplex projection with 20%-45% per-name
bounds and at most 100% gross. When fewer than three names qualify, the
single-name cap intentionally leaves cash rather than disguising concentration
as compounding. Every rebalance sizes dollars from current marked equity, so
profits and losses are automatically recycled into the next target notionals.

The main decision checkpoint remains 28 complete days for stable ratios, but the
14-day competition horizon is still displayed continuously. Before any promotion,
compare same-timestamp paired return, fees, turnover, exposure and coin-level
attribution. A screenshot leader is not evidence if it launched at a different
time or carried different gross exposure.

Additional papers inspected in this pass:

- Kashyap (2024), *To Trade Or Not To Trade: Cascading Waterfall Round Robin Rebalancing Mechanism for Cryptocurrencies*, arXiv:2407.12150. Its cost-aware no-trade-boundary idea supports measuring turnover and retaining the existing drift band, but the paper supplies numerical illustrations rather than a clean out-of-sample crypto comparison.
- Etienne et al. (2025), *Revisiting the Structure of Trend Premia: When Diversification Hides Redundancy*, arXiv:2510.23150. The barbell-horizon result is from managed-futures markets with rolling eight-year training windows, not crypto; no multi-horizon bot was added from it.
- Bui and Nguyen (2026), arXiv:2602.11708. The reported 6h framework combines selection, trailing stops, volatility regimes and long-short allocation, so it cannot isolate a Roostoo-compatible edge. It remains a hypothesis source, not a replicated bot.
