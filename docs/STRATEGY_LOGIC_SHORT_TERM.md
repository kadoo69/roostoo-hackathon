# Short-term books: strategy logic

Covers `momentum_top3_5m`, `momentum_top3_15m` and `momentum_top3_30m`.
All three run the same rule; only the bar size and one frozen filter setting differ.
State as of 2026-09-23.

## Status in one paragraph

These are paper books (dry run, no real orders) on the Roostoo competition venue, started at 100,000 USD each.
They exist to test a short-term, two-sided trading bot on live data.
They are **not** competition candidates: on historical data every version of this rule lost money after costs (numbers at the end).
The competition candidates are the 4h long-only books (`momentum_top3_full`, `momentum_top3_lock`, `donchian_4h`).

## The rule, top down

Every step runs at each bar close of the book's own clock (5, 15 or 30 minutes), on closed bars only.

### 1. Universe

- Rank every Binance USDT pair by its 30-day median daily dollar volume and keep the top 30.
- Keep only the ones Roostoo lists as tradable crypto (tokenized stocks, stablecoins, gold tokens and wrapped BTC are excluded).
- A pair must have printed a daily bar in the last two days, so a coin halted on Binance (currently TON and OMNI) drops out.
- Refreshed every 24 hours. Today this gives 26 coins.
- Prices come from Binance klines (Roostoo mirrors Binance); orders go to Roostoo.

### 2. Market switch: may we short at all?

- Momentum = close now / close 40 bars ago - 1.
- Breadth = share of the 26 coins with positive momentum.
- **Shorts are allowed only while breadth is below 40%**, meaning most of the pool is falling.
- Longs are always allowed.

### 3. Candidates

- **Long candidate:** the close is above the highest close of the previous 20 bars (a Donchian breakout), the breakout is still live (price has not closed below the lowest close of the previous 10 bars since), and momentum is positive.
- **Short candidate:** the mirror image. The close is below the lowest close of the previous 20 bars, the breakdown is still live (price has not closed above the highest close of the previous 10 bars since), momentum is negative, the coin is not in a live long breakout, and the market switch is on.

### 4. Pick the strongest 3, across both sides together

- Every candidate, long or short, is scored by the size of its momentum.
- The 3 largest are held, whatever mix of longs and shorts that gives.

### 5. Stretch filter: do not chase exhausted moves

- Stretch z = (close - 20-bar average) / 20-bar standard deviation of the close.
- A **new** entry is blocked if its stretch falls in a range that lost money historically; a position already held is never forced out by this filter.
- The blocked ranges were chosen on 2023-24 data only and then frozen:

| book | shorts blocked when z is | longs blocked when z is |
|---|---|---|
| `momentum_top3_5m` | below 1 (uses the 15m setting; no 5m history exists) | -2 to -1.5, or 3 and above |
| `momentum_top3_15m` | below 1 | -2 to -1.5, or 3 and above |
| `momentum_top3_30m` | below 1.5 | none |

- In practice this blocks almost every new short on these three books, because a breakdown almost always has z below 1.
- The reason: history shows a breakdown short has **less than a 50% chance of falling further** at every stretch level, and the more stretched it is the worse the odds (1h example: 38% when z is below -3, 49% when z is between -1 and 1).

### 6. Position sizing

- Each of the 3 picks is weighted in proportion to its momentum size (a coin moving twice as hard gets twice the weight).
- Cap of 50% per coin; excess goes to the other picks, and anything that cannot be placed stays in cash.
- Total exposure (longs plus shorts) is at most 100% of equity; no leverage.
- A position already held is never topped up, so strength weights apply at entry.

### 7. Exits

- **Channel exit:** a long closes when price closes below the lowest close of the previous 10 bars; a short closes when price closes above the highest close of the previous 10 bars.
- **Rotation:** a name that drops out of the top 3 at a bar close is closed.
- **Market switch:** a new short cannot open while breadth is 40% or above.
- **Take profit (skim ladder):** each time a position moves 3% in its favour from its reference price, 15% of it is sold (long) or covered (short) and the reference resets to that price. A position that never gains is never skimmed. Skimmed cash stays in cash.

### 8. Execution and risk

- Checks the market every 30 seconds; decisions fire a median 16 to 23 seconds after each bar close.
- Longs use limit orders 1 bp from the price, cancelled after 5 minutes if unfilled; missed entries are retried each cycle until the next bar close.
- Shorts use Roostoo's short endpoints: market orders, 0.1% fee each side.
- After a restart with no saved bar memory, the first bar's entries are skipped so the book never buys partway through a bar.
- Small weight changes (within 25% of a position) are not traded, to avoid paying fees on noise.
- Kill switches: halt at a 25% drawdown, at a 25% order error rate, if Roostoo prices are older than 120 seconds, or if Roostoo deviates from Binance by more than 50 bps.
- Exposure is scaled down automatically from 2026-10-15 to the end of the competition window on 2026-10-17.

## Costs

- Spot: 0.05% (limit) or 0.10% (market) per side, plus the coin's own tick spread.
- Shorts: 0.10% per side plus spread.
- At these clock speeds turnover is high, which is the main reason the backtests lose.

## Backtest evidence

Median 14-day return, 2023-24 (fit) / 2025-26 (holdout), fees and spread included, on the harness in `gates/lowtf_contenders.py` and `gates/lowtf_exhaustion.py`.

| rule | 30m | 15m |
|---|---|---|
| long-only momentum top 3 (earlier version) | -7.2% / -10.9% | -20.4% / -23.1% |
| top 3 across both sides, sized by strength | -22.5% / -18.2% | -39.0% / -37.6% |
| same, with the stretch filter (current rule) | -7.2% / -8.0% | -18.9% / -18.6% |
| same coins, random sizes (control) | holdout -29.3% | holdout -53.7% |

- Sizing by strength beats random sizing of the same coins by 11 points (30m) and 16 points (15m), so backing the strongest movers is real.
- The losses come from cost at fast clocks and from the short side.
- The 5m book cannot be backtested (the local 5-minute history covers only 5 coins); by the pattern above it is expected to lose more than the 15m book.
- The test that would change this verdict: 14 days of live paper results beating these medians.

## Where it lives

- Rule code: `signals/contenders.py` (used by both the backtest and the live bot).
- Live bot: `bot/contenders_run.py`; configs `config/momentum_top3_{5m,15m,30m}.yaml`.
- Run: `./run_bots.sh start`; dashboard `http://127.0.0.1:8787/`, heatmap `http://127.0.0.1:8787/heatmap`.
- Evidence: `DECISIONS.md` anchors `lowtf-contenders-declaration`, `lowtf-contenders-outcome`, `lowtf-exhaustion-outcome`, `lowtf-breadth-shorts-outcome`.
