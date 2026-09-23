# Sizing, venue eligibility and profit protection

The request was to balance too many small positions against too few large positions, improve risk-adjusted results, verify Roostoo tickers and clarify the monitor.
The subsequent request added profit protection after a short live profit reversal.
Neither a high daily P&L peak nor its subsequent give-back is an adequate fitting sample.

## Venue and execution

Every executable symbol must map to a currently tradable Roostoo `PairSpec` and a valid quote.
Exchange information is refreshed every five minutes in the paper experiment; an invalid or untradeable required symbol pauses the cycle rather than falling back to a Binance execution market.
The terminal displays saved native pairs such as BTC/USD, not invented USD names derived from a Binance string.
Binance remains the historical signal and full-market liquidity-ranking source.
The validated start ranked 470 markets and selected 24 Roostoo pairs.
Balanced books exclude signalling names above the unchanged 5 bps spread threshold before ranking replacements.
Names such as PEPE can therefore be excluded without reserving an unfillable target slot; the terminal shows excluded pairs and observed spreads.
Historical bar data does not establish historical Roostoo spreads, so this execution eligibility filter is a forward operational control, not part of the historical performance claim.

## Sizing study

`config/allocation_review.yaml` declares 5, 8 and 12 slots, equal and inverse-volatility allocation, plus two controls, at 10 and 20 bps per side.
The six balanced candidates cap gross target exposure at 80%, single-name targets at 20%, discard target allocations below 2%, and reduce exposure to a 25% annualized forecast volatility target using 90 completed 4h return observations.
The forecast uses portfolio returns, so correlated names do not count as independent risk reductions.
Actual exposure and volatility can diverge from targets through price changes and incomplete fills.
Unfilled sells do not free cash or position slots for prospective buys.
Fewer qualifying signals leave cash rather than forcing diversification with unqualified names.

Orders in the historical simulator act at the next bar open, charge drift-rebalancing turnover and both-way costs, and cannot borrow.
Fit and later assessment windows have no overlapping dates.
Both windows have been repeatedly studied before; neither is newly untouched evidence.
Current Roostoo membership conditions the historical universe, and queue position, depth and drawdown-halt execution are not simulated.

At 10 bps per side in the 2025-onward assessment:

| Allocation | Sharpe | Sortino | Calmar | Max drawdown |
|---|---:|---:|---:|---:|
| Original 4h | 1.44 | 2.71 | 3.16 | -15.54% |
| Momentum top 5 | 1.54 | 3.04 | 4.27 | -35.11% |
| Balanced 5 equal | 1.81 | 3.46 | 3.35 | -18.36% |
| Balanced 12 equal | 1.42 | 2.63 | 2.53 | -14.00% |

Balanced 12 is the fit-only pick among balanced candidates under the declared rule at both costs, but it does not dominate the original control.
Balanced 5 is included as an explicitly assessment-informed diagnostic because its recent tradeoff is attractive; it is not a validated winner.
Inverse volatility was not an automatic improvement.
At higher costs the incumbent remains stronger on several metrics, so no original strategy is replaced on a claim of superiority.

## Exit study

`config/exit_review.yaml` declares five exit rules at two costs on the same momentum-ranked 4h top-five selection.
Decisions use completed hourly closes and executions use the following hourly open, including gaps.
Full overlay exits remain blocked until the 4h selection turns off and back on.
This differs from the earlier take-profit study, whose full-exit implementation could re-enter immediately on the next bar while its selected mask stayed true.
The prior result therefore tested a particular re-entry policy, not every possible profit-protection rule.

At 10 bps per side in the later assessment:

| Exit | Sharpe | Sortino | Calmar | Max drawdown |
|---|---:|---:|---:|---:|
| Original channel | 1.54 | 2.97 | 4.29 | -35.03% |
| 1h 10-close floor | 1.87 | 4.66 | 5.48 | -20.88% |
| Full exit at +8% | 0.95 | 1.45 | 0.97 | -38.37% |
| Half exit at +8% | 1.41 | 2.44 | 2.50 | -36.18% |
| Arm at +5%, trail peak by 3% | 1.52 | 2.71 | 3.34 | -26.26% |

The hourly floor improves the recent window but deteriorates on the earlier fit window: Sharpe 1.63 versus 2.85 at 10 bps, and 0.55 versus 2.29 at 20 bps.
This is a regime-dependent candidate for forward testing, not evidence of a universal best exit.
The live candidate preserves 4h entry/ranking and applies the completed 1h floor only to exits, with re-entry blocked until the ranked selection resets.
No fixed take-profit or trailing percentage overlay is enabled.
Faster exits can truncate winners and lower qualification return, even though they are not fixed price targets.
The ordinary rolling floor can move down; it is not a ratcheting stop.

## Forward experiment and terminal

`config/paper_lab_v2.yaml` starts ten independent paper portfolios with a common fresh start.
The six original comparisons are joined by a ranked-five control, balanced-five and balanced-twelve candidates, and the ranked-five/hourly-exit candidate.
The first experiment's state and journals remain in `live/paper_lab_v1`; the new portfolios live in `live/paper_lab_v2`.
The loaded paper-lab service now uses the v2 config.
The original authenticated execution block remains in place and no real orders are submitted.

The terminal at http://127.0.0.1:8788 shows native Roostoo pairs, actual and target weights, position values, per-position open P&L, current exit floors and cushions, pending limits, cash, concentration, exclusions and live freshness.
It separates historical sizing/exit assessments from live ratios, which remain unavailable until enough forward daily observations accumulate.
The 28-day display floor is not proof of statistical sufficiency.
The parameter trials remain in the append-only ledger and Gate 4 has not been passed or relabelled.
