# Questions for the Roostoo organisers

Written 2026-09-20. Question 7 added and the duplicated Screen 3 question merged 2026-09-21.
These are the items that no amount of backtesting resolves.
`config/preregistration.yaml` carries `costs.confirmed: false` with a deadline of 2026-10-01, and every net-of-cost number in this repo is provisional until they are answered.

Why this matters in one line: the ranked book turns over roughly 400x over the fourteen-day window, so a factor-of-eight error in commission is worth about 3% of NAV, which is larger than the spread between the top Screen 3 finishers.

---

## Send this

> Hi, a few questions before the 2026-10-04 window opens.
>
> **1. Commission.** The API README's example `place_order` responses show `CommissionPercent` of 0.00012 and 0.00008, but at the 2026-09-18 info session the stated figures were 0.1% for market orders and 0.05% for limit orders. That is about a factor of eight apart. Which is correct for the competition account, and is `CommissionPercent` on the fill response authoritative?
>
> **2. Maker versus taker.** Is the 0.05% limit-order rate charged on any order submitted as LIMIT, or only on orders that actually rest and fill passively? Our execution is limit-first and never crosses, so the two readings give materially different costs.
>
> **3. API keys.** Our key is still marked not yet issued. When are competition keys released, and is there a test key available before 2026-10-04? We need one real fill to confirm the commission above, and we also need it to verify order lifecycle behaviour: partial fills, rejections, and minimum order size.
>
> **4. Minimum order size and quantity precision.** What are the minimum notional and the quantity step per pair? We round quantity to the step and have already been bitten by a float-precision rounding that produced a quantity a venue rejected outright.
>
> **5. Screen 3 scoring convention.** Are Sortino, Sharpe and Calmar computed on daily returns across the full fourteen days, and which risk-free rate and annualisation convention apply? Calmar over fourteen days is dominated by a single session, so the convention changes the ranking.
>
> **6. Screen 2 advancement.** How many entrants advance from Screen 2 per region, and roughly how large is the field? Our strategy choice turns on this. If qualification is the binding constraint we run a concentrated book; if the cut is loose enough that most reasonable entries survive, we run a lower-drawdown one. The two are materially different and we would rather pick on your number than on a guess.
>
> **7. Leaderboard visibility during the window.** Is a live ranking visible to entrants while the competition runs, and if so at what frequency and in how much detail - full field, own rank only, or a top-N board? We are not asking in order to react to other entrants' positions. We are asking because the strategy that maximises expected return and the strategy that maximises probability of finishing in the top 20 are different strategies, and the second one is only implementable if we can observe whether we are above or below the cut. If no ranking is visible we will size as if it is not, which is a materially more conservative choice and we would rather make it deliberately.
>
> Thanks.

---

## What each answer changes here

| answer | what it changes |
|---|---|
| commission | `preregistration.yaml` `costs.spot_market_fee` / `spot_limit_fee`, then `costs.confirmed: true`. Unblocks a non-provisional read of every net number. |
| maker vs taker | Decides whether `paper_lab_v8` belongs at 10 bps or 5. See `DECISIONS.md#paper-lab-v8-fee-revert`. |
| keys | Unblocks Gate 10, which needs three distinct days of live operation, and the one fill that settles commission. |
| min size / step | `PairSpec.round_qty`. A backtest never formats an order, so this cannot be caught here. |
| **Screen 2 advancement** | **Decides which book we enter.** `momentum_top3_4h` clears Screen 2 in 42.8% of historical fortnights against `donchian_4h`'s 23.4%, but pays -43.2% maximum drawdown against -17.7%. If the cut is loose, the second book is better. See `DECISIONS.md#competition-book-selection`. |
| scoring convention | The fortnight scorers in `gates/`. `results/logic_review_2026_09_19.md` already records a Sortino annualisation defect in five of them. |
| **leaderboard visibility** | **Decides whether the BTC floor can be made rank-conditional.** `RESEARCH_PORTFOLIO_RETURN.md` section 1 records the result: in a contest, the rank-optimal policy mimics the field when ahead and diverges from it when behind, and BTC is what the field holds. A constant floor is a blind bet; a state-dependent one needs an observable rank. If no ranking is visible, the floor stays off. |

Note on what an answer does NOT change: `DECISIONS.md#trial-counting-rule` establishes that Gate 4 needs an annual Sharpe of 2.498 against the 2.206 the book has, and confirming fees moves Sharpe by about 0.11 per 5 bps at most.
Confirming costs makes the numbers real. It does not make the gate pass.
