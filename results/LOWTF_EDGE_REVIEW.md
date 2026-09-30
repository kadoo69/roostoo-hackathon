# Short-frame edge review — 2026-09-24

## Decision

Keep the primary 4-hour portfolio unchanged. Run the confirmed 1-hour
**long-only** variation as an isolated paper bot against the existing confirmed
1-hour book. Its historical improvement is substantial at the modeled cost,
but it was developed on these years, fails a doubled-cost check, and exceeded
the live bot's 25% drawdown halt level in both historical periods. It is a
forward-validation candidate, not validated alpha.

## What was tested

| Arm | 2023–24 median 14d | 2025–26 median 14d | Later Sharpe / Sortino / Calmar | Result |
|---|---:|---:|---|---|
| Unchanged 4h momentum book | +2.30% | +2.24% | 1.57 / 2.87 / 3.59 | Primary control |
| 1h 20-bar breakout on idle cash | +1.81% | +1.96% | 1.55 / 2.85 / 3.60 | Fails return and ratios |
| 1h 20-day breakout on idle cash | +1.97% | +2.48% | 1.70 / 3.12 / 4.22 | Fails earlier median and slower-clock control |
| 80% 4h + 20% confirmed 1h book | +1.87% | +1.99% | 1.66 / 3.22 / 4.08 | Fails return and doubled fast costs |

The 1-hour 20-day sleeve's recent lift was almost reproduced by observing the
same channel every four hours. Faster observation did not establish a unique
edge. The 15-minute and 30-minute ranked books remain dominated by turnover
and fees in `results/lowtf_paper_bots.json`.

## Best short-frame hypothesis: remove shorts from the confirmed 1h book

Both arms use sticky top-three contender slots, 4-hour channel alignment,
1.5× previous 20-bar median quote volume at entry, identical stretch skips,
3%/15% profit skims, a 25% no-trade band, and the same point-in-time universe.
Only the short-entry switch differs. Both books were run through the same
costed simulator.

| Period and book | Median 14d | Sharpe | Sortino | Calmar | Worst 14d | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| 2023–24, current both sides | +1.10% | 0.99 | 1.70 | 0.92 | -42.9% | -57.7% |
| 2023–24, long only | +1.23% | 1.72 | 3.12 | 3.97 | -32.1% | -32.4% |
| 2025–26, current both sides | +2.25% | 1.56 | 3.10 | 3.92 | -28.0% | -35.6% |
| 2025–26, long only | +2.83% | 2.05 | 4.34 | 7.17 | -22.8% | -30.8% |

The post-result stress test doubled the long-only fee and tick assumptions.
Its median fell to **-0.13%** in 2023–24 and **+1.22%** in 2025–26; later
Sharpe fell to **1.44**. These are below the ordinary-cost both-sides control.
No cost-robust alpha claim follows from this experiment. The simulator also
does not stop permanently at the bot's 25% drawdown limit, so its multiyear
return and ratio figures cannot be treated as executable live outcomes.

## Forward comparison now running

`momentum_top3_1h_long` is a separate, forced-dry-run LaunchAgent with its
own state and journals. It uses the same signal implementation as the backtest
and passes a disabled short switch. The unchanged `momentum_top3_1h` remains
its control. The dashboard and `./run_bots.sh compare` identify that pairing.
The first complete hourly decision placed two **dry-run** buys with no shorts.

Read the comparison only after the existing 28-complete-day gate and check
uninterrupted cycles, matching bar decisions, order costs, net return and daily
Sharpe, Sortino and Calmar together. Even then, dry-run limit fills require
separate execution validation. At the current date the 28-day gate falls after
the competition's October 17 end, so this trial cannot establish a fully
prospective result before that deadline.

The source-feature validator now records 1-hour and non-overlapping 4-hour
outcomes as well as 24/72-hour outcomes. Its current short-horizon report has
114 matured 1-hour observations across only two days; the source collector's
longest gap is 10 hours. No source feature qualifies for an alpha estimate yet.

Evidence: `results/lowtf_confirmed_long_only.json`,
`results/lowtf_portfolio_mix.json`, `results/lowtf_idle_sleeve.json`,
`results/lowtf_calendar_sleeve.json`, and
`results/source_short_validation.json`.
