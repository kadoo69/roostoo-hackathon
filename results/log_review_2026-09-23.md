# Live log review, 2026-09-23

Two periods.
**Pre-reset**: 2026-09-20 08:12 to 2026-09-22 20:38 UTC, about 60 hours, archived at `live/_archive/reset-20260922T2038Z/`.
**Post-reset**: 2026-09-22 20:48 to 2026-09-23 04:09 UTC, 7.3 hours, the fleet restarted clean on the fixed code.
Produced by `python3 -m gates.log_review <root>`; artifacts `results/log_review_reset-20260922T2038Z.json` and `results/log_review_live_2026-09-23T0409Z.json`.

**Nothing here is a performance result.** 60 hours is under a fifth of one competition fortnight, in a single market regime (a broad altcoin rally), and the pre-reset books ran on four defects fixed on 2026-09-23. It is an operations and logic review.

## Pre-reset: returns against what the market offered

| book | return | max DD | mean gross | BTC | equal-weight universe | EW scaled to the book's gross | book minus that |
|---|---|---|---|---|---|---|---|
| donchian_4h | +4.82% | -3.21% | 0.53 | +7.32% | +11.84% | +5.86% | -1.04pp |
| donchian_4h_cushion | +4.46% | -3.09% | 0.48 | +7.32% | +11.75% | +5.43% | -0.97pp |
| donchian_1h | +3.35% | -5.71% | 0.51 | +7.32% | +11.56% | +4.82% | -1.47pp |
| momentum_top5_4h | +2.44% | -5.01% | 0.66 | +7.32% | +12.58% | +8.53% | -6.08pp |
| momentum_top5_cushion | +2.60% | -4.98% | 0.63 | +7.32% | +12.78% | +8.75% | -6.15pp |
| momentum_top3_4h (56.5h) | +2.81% | -5.37% | 0.67 | +7.08% | +10.69% | +7.83% | -5.01pp |
| momentum_top3_full (50.3h) | -4.45% | -7.03% | 0.73 | +6.22% | +6.07% | +5.40% | -9.86pp |
| scalper_live (50.4h) | +0.88% | -0.34% | 0.05 | +6.22% | +6.59% | -0.02% | +0.90pp |

Zero crashes, zero halts, 1 to 7 transient network `cycle_error`s per book, all recovered on the next cycle.

## What went right

- **The machinery is sound.** No crash, no halt, no kill switch tripped in 60 hours; every error was a transient HTTP failure that the next cycle recovered. After the 2026-09-23 fixes, live signals match the backtest on every book with zero mismatches (`gates/live_validation.py`).
- **Breadth held up.** `donchian_4h` spread across 22 names and had 17 net winners, with the largest single loss 187 dollars (ARB). It was the best Roostoo book, with the smallest drawdown among the channel books.
- **Fees are small for the 4h books.** 35 to 226 dollars over 60 hours.
- **Profit booking did no harm.** Seven skims in total, and at the end of the period every skimmed name was below its skim price (+115 dollars). Far too few events to call it a benefit.

## What went wrong

1. **The books were offline 55% of the time.** Each 60-hour book logged 33 to 34 hours of gaps longer than 10 minutes and missed 8 or 9 of about 15 4h bar closes (34 of about 60 for the 1h book). `pmset -g log` shows the Mac sleeping and waking all through the nights of 2026-09-20 to 22, and `pmset` has `sleep 1`. Sleep is currently held off only by `caffeinate` asserting for 300 seconds at a time, which stops when the session doing it stops. **This is the largest single problem and it is not in the code.** It needs EC2 (`deploy/README.md`) or a `caffeinate -i` tied to the bot supervisors, on mains power.
2. **Every book lagged the market, and the ranked ones lagged badly.** The universe rose about 12% while the books ran at 0.5 to 0.7 gross. Scaled to their own exposure, the channel books were about 1pp behind and the momentum books 5 to 10pp behind.
3. **The momentum losses were concentrated in one or two names.** Both momentum books lost about 3,000 dollars on ARB, which the 40-bar rank selected after a spike and which finished as the universe's worst coin (+4.4%). `momentum_top3_full` lost another 2,600 on ENA. The leaders were NEAR +25.7%, TAO +24.1% and SUI +23.1%; `momentum_top5_4h` caught SUI (+6,677) and NEAR (+2,339), the top-3 books mostly did not. This is the concentration frontier in `FINDINGS.md`: a top-3 book lives or dies on three picks, and in 60 hours that is noise, not evidence against the rank.
4. **PEPE rose 22.3% and no book could buy it.** 3 to 34 refused orders per book (`spread_exceeds_limit`). Fixed on 2026-09-23 by accepting one-tick quotes.
5. **Four logic defects contaminated every pre-reset number.** Channel state that never caught up after a missed close (compounded by item 1: every sleep was a missed close), PEPE refused, a full-deployment book whose last buy was faked in the journal (`momentum_top3_full` sat at 0.68 gross on two names, which is part of its -9.86pp), and the alt-data collector running once per 4h. All in `DECISIONS.md#live-validation-2026-09-23` and `#lowtf-paper-bots`. The pre-reset numbers are therefore a record of the defects as much as of the strategies.

## Post-reset, 7.3 hours

All 15 books up, zero crashes, zero halts. The 4h books entered at the 00:00 UTC close, so they have had four hours of exposure. The lower-timeframe paper books are up 0.9% to 7.3% in a rally in which the universe rose 3% to 8% over the same hours; `momentum_top3_15m` already paid 225 dollars of fees in 7.3 hours, a pace of about 10% of NAV per fortnight, in line with its backtest's cost drag. **Do not read their early gains**: the backtest says these books bleed through turnover, and 7 hours of a rising market is exactly when a high-turnover long book looks best.

Found in the post-reset logs and fixed: `RLUSDUSDT`, Ripple's dollar stablecoin, was inside `testnet_live`'s universe, because the stablecoin list predated it and existed as two separate copies (`data/universe.py` and `bot/universe.py`). There is now one list, extended with RLUSD, USDS, BFUSD and EURI, and a test that the two cannot diverge. Roostoo does not list RLUSD, so no Roostoo book was affected.

## Gaps still open

| gap | why it matters | what closes it |
|---|---|---|
| Laptop sleep | 55% downtime, every sleep a missed bar close | EC2 or a supervised `caffeinate -i` on mains power |
| Passive fill rate on one-tick names | PEPE and friends carry most of the ranked books' edge; a passive order at the bid may not fill in 15 minutes and is not retried until the next close | Roostoo keys |
| Rotation underweighting on a real venue | sell cash arrives only on fill, and a held name is never topped up while booking is on | Roostoo keys, then a declared fix |
| Commission, minimum size, 50k vs 100k starting wallet | every net number is provisional | `ORGANISER_QUESTIONS.md` |
| Booking ladder evidence | seven skims in 60 hours cannot show anything | forward time; 28 days per the pre-registration |
| Scalper criterion | 10 trades at 90% wins is the failure mode its backtest predicts (positive median, negative mean); the criterion is the mean after 200 | forward time |
