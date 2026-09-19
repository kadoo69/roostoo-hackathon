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
