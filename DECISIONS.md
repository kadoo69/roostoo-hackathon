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
