# Crypto ML research and trading plan

Written 2026-09-23. This is a research plan, not evidence that an ML strategy is profitable.
The first deliverable is a small, reproducible research loop that can reject weak ideas before they reach a trading bot.

## Objective and venue facts

Predict 12-hour relative returns in a liquid, point-in-time crypto universe, then turn forecasts into positions with a separate cost and risk layer.
Optimize net portfolio performance, measured with Sharpe, Sortino, Calmar, maximum drawdown, turnover and tail loss.
Compare every model with BTC hold, volatility-scaled BTC, equal-weight coins and simple momentum after the same costs.

The [official FAQ](https://roostoo.notion.site/Roostoo-Quant-Trading-Hackathon-Official-FAQ-313ba22fed798042bab7c93c609d004e) confirms that long and short positions are allowed, Roostoo prices stream from Binance, Roostoo supplies ticker snapshots but no OHLCV, and the API permits **30 calls per minute including order queries**.
The competition requires autonomous orders, logs and a traceable commit history, and it shows real-time ranking in its app.
Its FAQ says the main round starts September 30 with a first trade by October 1 at 20:00, whereas the [public event page](https://luma.com/coghwiyt) says live trading is October 4–17.
Treat these dates as unresolved; keep dates in configuration and confirm the assigned round before starting a competition bot.
The event page says $100,000 starting capital, 1x exposure, 0.10% taker and 0.05% maker commission, at least eight active days, top-20 return qualification, then 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar.
The public API example instead reports a $50,000 initial wallet; actual wallet and fill commission must be read from the assigned account.
Roostoo shorts use the existing `/v6/short_open`, `/v6/short_close` and `/v6/short_positions` adapter, with the repo's provisional 0.10% fee per side.
Shorts are an allowed experiment, not a required exposure or a free symmetric version of longs.

## Reuse rule

Implement only the missing research loop in a separate `ml_research/` package.
Reuse `data/binance.py`, `data/flow.py`, `data/daily.py`, `data/vision.py`, `data/universe.py`, `costs/model.py`, `venue/roostoo.py`, `bot/intents.py` and the existing paper/live risk and reconciliation machinery when their behavior is appropriate.
Use the cached Parquet files; do not download another copy of price or futures data unless validation finds a gap.
Do **not** copy `portfolio/backtest.py` into the new research loop: its target-weight turnover and assumed limit fills are insufficient for this execution test.
Implement the smallest new drift-aware simulator, and reconcile it against an existing control before trusting a number.
Do not modify or restart any running bot as part of ML research.

## First MVP

1. Use Binance spot 4-hour bars for decisions and the complete 1-hour archive for conservative execution at the first hourly close after a decision.
   The local 15-minute panel covers only 55 names, so requiring it now would bias the broader universe; upgrade to 15-minute execution only after complete point-in-time coverage exists.
2. Select the daily top 30 eligible USDT coins by preceding 30-day median dollar volume; require 90 prior days of data and exclude stablecoins and leveraged tokens.
   Use a historical listing window, not today's asset list.
3. Build a small feature set: 4-hour, 1-day and 7-day returns; rolling volatility; dollar-volume change; taker-buy imbalance; BTC/ETH returns; and breadth.
   All features use completed bars and carry an availability time.
4. Predict the forward 12-hour coin return minus the contemporaneous universe return, divided by volatility known at the decision time.
   Model scores rank coins; they do not directly specify portfolio weights.
5. Fit a single global Ridge model first, then one LightGBM challenger only if the linear baseline is useful.
   Compare absolute return versus relative return and global versus per-asset models before adding complexity.
6. Initially trade up to five positive-score longs, inverse-volatility weighted, with cash allowed, 15% target annual volatility, 1x maximum gross, 35% BTC/ETH caps, 20% alt cap and 60% total alt cap.
   Run a separately declared short arm with at most two negative-score shorts, 1x combined gross and actual short fees; never turn it on simply because shorts are permitted.
7. Charge actual/provisional venue fees, spread, slippage and position drift at each rebalance.
   Test 1x, 1.5x, 2x and 3x costs; no guaranteed passive fills.

## Data priority

| Tier | Data | Reason and admission test |
| --- | --- | --- |
| 1 | Binance spot OHLCV, taker-buy bar volume, historical universe, executable prices and venue costs | Essential for a trustworthy price-only baseline. |
| 2 | Binance futures price, premium/basis, settled funding, archived OI and aggregate trades; Deribit BTC/ETH DVOL | Test one group at a time against the same dates and portfolio. Existing funding, OI and bar-flow rules were largely null in this repo, so none is presumed useful. |
| 2 for execution; 3 for alpha | Bid/ask and order-book depth | Record spreads now; inspect depth archive quality before storage-heavy modeling. |
| 3 | Hyperliquid, liquidations, full Deribit option chains, stablecoins, exchange flows, Dune, DEX/DeFi, unlocks, Google Trends and social | Add only with historical availability and publication timestamps, then a paired net portfolio gain. |

The [Binance archive](https://github.com/binance/binance-public-data) supplies spot and futures klines and trades.
The existing `data/vision.py` has Binance funding, premium and 5-minute OI/positioning archives from 2021-12 where available; use its symbol mapping and bucket corrections.
The [Deribit API guide](https://docs.deribit.com/articles/options-data-collection-best-practices) separates historical DVOL from current option-chain summaries.
The [Hyperliquid archive](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) may be delayed or incomplete and has requester-paid transfer.

## Validation and experiment order

Use expanding-window folds with a 24-hour purge around fit, validation and score boundaries.
Score 2024 H2 after fitting 2022–2023 and validating 2024 H1; then score 2025 H1, 2025 H2, 2026 H1 and July–September 2026 with each preceding six months as validation.
Those five periods are development evidence because this repository has already studied them.
Freeze the entire pipeline and monthly retraining rule before October 2026, then reserve October 2026–March 2027 as a prospective untouched test.
Never tune on that period, including competition results.

Run these ten hypotheses in order, logging all attempts and failures:

1. Reproduce BTC, equal-weight and existing momentum controls with a delayed, costed simulator; negative controls must fail.
2. Compare 1-hour, 4-hour, 12-hour and daily decision clocks after costs.
3. Compare simple momentum, trend and mean-reversion rules.
4. Compare absolute, BTC-residual and universe-relative targets using global Ridge.
5. Compare global, per-asset and BTC/ETH-versus-alt Ridge models.
6. Compare LightGBM regression and ranking with the selected Ridge model.
7. Add futures basis and known settled funding alone.
8. Add OI change and the four price/OI regimes alone.
9. Add aggregate-trade features on BTC, ETH and SOL, beyond kline taker volume.
10. Compare equal rank weights with inverse-volatility and cost-aware no-trade sizing.

For each experiment record hypothesis, economic mechanism, data availability, features, target, dates, settings, trial count, costs, IC, bucket behavior, net portfolio change and accept/reject decision.
An added feature group needs at least +0.20 net Sharpe versus the same-date control, positive incremental return in three of five development folds, positive strategy return at 2x costs, and no drawdown increase over five percentage points.
Check block-bootstrap paired excess returns, Deflated Sharpe with the full trial history, coefficient/feature stability and stress periods.
No single fold may supply over half the claimed edge.

## Software and risk

Use cached Parquet, Pandas/NumPy and scikit-learn already in the project environment; use local JSON/CSV experiment artifacts instead of adding a service or tracker.
Put implementation in `ml_research/mvp.py`, the fixed research declaration in `config/ml_mvp.yaml`, tests in `tests/test_ml_mvp.py` and reports under `results/ml_mvp/`.
Split modules only when a second caller makes it necessary.

No ML output bypasses hard limits: maximum position, 1x gross, daily loss, drawdown, order size, spread, stale data, API failures, duplicate-order prevention, reconciliation and kill switch.
Reuse the existing venue and intent code for any later paper/live adapter.
Respect the 30-call-per-minute Roostoo limit with a lower configured budget and exponential backoff; never blindly retry an order whose outcome is unknown.
Monitor feature availability, prediction drift, realized IC, exposure, turnover, slippage and position parity.

## Go / no-go

| Transition | Required evidence |
| --- | --- |
| Research to shadow/paper | No timestamp, universe or accounting failure; improvement over simple controls after costs in at least three of five development folds; profitable at 2x costs. |
| Paper to small live | Six-month untouched test with positive paired excess-return confidence bound, net Sharpe at least 1, Deflated Sharpe probability at least 0.95, drawdown no worse than 15%, and eight weeks of reconciled paper trades with realized cost within 1.5x modeled cost. |
| Small live to larger | Six months of small live trading with positive net benchmark excess, cost/impact within assumptions, no unresolved orders or risk violations, and drawdown inside the predeclared limit. |

The 2026 Roostoo window is too short to prove a timeless ML edge.
Use its leaderboard and fills for competition operation and execution diagnostics, not to tune the untouched test.
