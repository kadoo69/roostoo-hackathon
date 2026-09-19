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
