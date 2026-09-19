# Logic review and prospective comparison

Reviewed the main checkout after reading CLAUDE.md, STRATEGY.md and relevant chronological decisions.
The existing 4h candidate has suggestive historical performance but no established edge under the repository's registered tests.
The new experiment does not select a replacement on the data used to invent it.

## Material findings

| Priority | Finding | Consequence | Disposition |
|---|---|---|---|
| High | `Bot.apply_dry_fill` immediately fills every proposed limit; `Executor.send` journals before cash/inventory acceptance. | Unobserved fills and rejected wallet changes can appear as trades; old paper P&L is unsuitable for comparing execution-sensitive horizons. | Isolated lab requires a later quote to cross the resting limit; fills, fees, inventory and events commit in one state snapshot. |
| High | `universe.select` takes today's top 180 by 24h volume before ranking 30-day medians and accepts 15 daily observations. | The actual selection differs from the stated full-market 30-day rule, precisely where historical performance was most sensitive. | Lab ranks all active spot USDT symbols surviving the existing exclusions, requires 30 contiguous completed daily bars, and aborts on failed requests. |
| High | `feed.bar_frame` silently discards request failures; `evaluate` drops missing closes; `Bot.cycle` builds a target from surviving columns. | A feed fault can compress time, suppress a signal, and liquidate an otherwise valid holding. | Lab requires complete contiguous, current closed bars and valid quotes for all required symbols before committing a cycle. |
| High | `Bot.mark` values an unquoted holding at zero. | False drawdown can trigger liquidation and corrupt reported NAV. | Lab rejects missing marks and pauses without changing wallets. |
| High | A cold start evaluates only the latest bar; a restart evaluates only one bar after an outage. | The running state can miss a prior breakout or an intermediate exit; the separate parity test does not cover this lifecycle. | Lab replays 240 completed bars on cold start and every missed bar on restart; rejects outages longer than its replay buffer. Warm-up is explicitly finite and is not full-history parity. |
| High | Saved config mismatches only log warnings in the old runner; pending intent is not restart-safe for authenticated trading. | Changing configuration can blend incomparable runs; authentic orders cannot safely resume. | Existing authenticated-order block remains. Lab refuses a changed config or implementation fingerprint and uses a process lock and atomic state. |
| Medium | The old peak history is truncated to 5,000 polling observations on restart; mirror hysteresis is not persisted. | Restart changes risk memory. | Lab persists an all-time peak and a drawdown halt latch; mirror failures pause all candidates. |
| Medium | STRATEGY.md says the low-channel floor only rises. | The rolling low can decrease before exit; this is not a ratcheting stop. | Documentation corrected; baseline channel mechanics remain fixed. |
| Medium | Existing descriptions mix 351, 386 and 413 trials and reuse DSR values from earlier counts. | An old probability can be misrepresented as current evidence. | Six prospective configurations registered; no old DSR relabelled as a current calculation. Gate 4 remains unpassed. |
| Medium | The Sortino asymmetry argument in STRATEGY.md conflicts with later fortnight analysis. | A payoff-shape argument is presented as demonstrated competition advantage. | Documentation corrected. |
| Medium | Frozen preregistration contains legacy 12% breaker and 0.8 net cap while selected config uses 25% and 1.0. | Gate compliance and chosen operational policy are not interchangeable claims. | Explicit unresolved governance discrepancy; thresholds were not amended. |

## Prospective experiment

`config/paper_lab.yaml` declares four fixed 20/10 channel horizons: 1h, 4h, 8h and 1d.
Holding the bar counts fixed deliberately changes the economic lookback as well as the decision frequency.
The 4h control is the existing chosen rule.
The sole new signal candidate retains the 4h channel but permits entry only when the breakout candle closes above its open, quote volume exceeds the preceding 20-bar median, and taker-buy quote volume exceeds half of total quote volume.
It uses the ordinary channel exit regardless of flow, so the filter does not force constant rebalancing as the earlier volume family did.
This is a causal mechanism hypothesis, not a claim that the earlier negative-net volume results have been overturned.
BTC buy-and-hold is a separate executed benchmark with the same initial cash, fee and limit-fill model.
Its entry retries after expiration; the channel books wait until the next decision bar after an expired order.
All six have independent $100,000 wallets and simultaneous public quote observations.
Fees are fixed at 10 bps per side as a declared conservative scenario, not asserted to be the actual venue fee.
The shared liquidity universe uses the existing asset exclusion set; new stablecoins or synthetic assets absent from that set remain a taxonomy maintenance risk.

The runner is `python3 -m bot.paper_lab`.
It has no path that calls `Executor.send` or signed order endpoints and does not load account credentials.
State, pending orders, accounting events and NAV observations are persisted together in `live/paper_lab_v1/state.json`.
`python3 -m bot.paper_lab --report` reads the comparison without connecting to a venue.
The human-readable JSON is also refreshed at `live/paper_lab_v1/comparison.json`.
Existing bot state and journals are not reused.

## What the experiment can establish

A later observed ask at or below a buy limit, or bid at or above a sell limit, permits a simulated fill at that limit.
An order expires before fill evaluation at 15 minutes, including after an outage.
There are no fills on the placement observation and no borrowing against unfilled sell proceeds.
Buy notional plus fee is reserved from available cash; sell inventory is bounded by holdings.
This model misses crossings between polls and does not model queue position, depth, partial fills or impact.
It is neither a lower nor upper bound on real performance because fill selection and adverse selection can move results either way.
Actual venue fill quality and Gate 10 remain unverified.

No winner is announced from a short sample.
Reports include costs, turnover, fills, pending orders, exposure, drawdown halt state and net returns from a common start.
Daily metrics are suppressed until 28 complete sampled UTC days exist, excluding the first and current partial days and rejecting missing-day sequences.
Even after 28 days, rankings are descriptive and `edge_established` remains false.
Twenty-eight days cannot prove edge and will not be available before the October competition begins.
Promotion would require a separately reviewed paired comparison against the 4h control and BTC, honest multiple-testing adjustment and the outstanding registered gates.
The process performs no automatic strategy switch or live parameter fitting.

Official Binance field definitions for completed candle times and taker-buy quote volume are documented in [Spot market data](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market).

## Verification

Regression tests exercise the actual signal, execution price planner and paper ledger code.
Cases include no same-observation fill, cash reservations, duplicate orders, expiration after downtime, stale and missing bars, missing marks, missed intermediate exits, entry filtering and short-sample reporting.
Public-data validation and process status are recorded separately from statistical evidence.
