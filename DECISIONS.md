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
