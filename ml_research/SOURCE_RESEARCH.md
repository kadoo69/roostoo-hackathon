# Source feature research

As of 2026-09-24. This directory is an observational research layer. Its
features and labels do not enter a trading bot.

## What is usable today

The existing Binance price momentum rank with the full-market liquidity
selection is the best tested decision stack. Four predeclared source tilts
were simulated against that exact book with fees and the existing booking
rules. None improved validation, holdout and recent periods together.
See [`results/source_edges.md`](../results/source_edges.md) and the complete
diagnostics in [`results/source_edges.json`](../results/source_edges.json).

| Candidate combination | Intended edge | Historical result | Next use |
|---|---|---|---|
| Momentum + Hyperliquid funding | Favor breakouts where shorts pay longs | Holdout +0.32 percentage points median 14-day return; recent -0.64 | Context only |
| Momentum + Hyperliquid minus Binance funding | Detect cross-venue positioning divergence | Validation -0.35; holdout +0.36; recent +0.52 | Forward shadow ranking; no sizing |
| Momentum + negative funding on both venues | Short pressure behind a breakout | Holdout -0.45 | Archive for diagnosis |
| Cross-venue funding + stablecoin expansion | Require liquidity support for the divergence | Validation -0.91; recent -1.27 | Do not gate trades |
| Rising OI + negative funding | Potential short build-up | OI history only just started | Evaluate after 30/60 days |
| Aggressor flow + book imbalance | Distinguish persistent buying from a one-off sweep | No order-book history | Evaluate forward, particularly for execution timing |
| Deribit gamma + price breakout | Possible amplifying market regime | GEX history only just started; dealer sign assumed | BTC/ETH market context only |

The historical study uses exact source timestamps at the 4-hour decision
close and neutral values for unavailable feeds. Coverage of active candidates
with both funding histories is only 32–43% by period, so even a small positive
segment result would need coverage and replication checks. The stablecoin
historical series may have been revised after publication.

## Forward validation contract

`source_features.py` stores fetch-time-stamped snapshots. `forward_validation.py`
keeps the first snapshot per source, symbol and UTC day, enters at the first
Binance spot hourly close strictly after availability, and labels the exact
24-hour and 72-hour closes only after those bars exist. The 72-hour evaluation
uses every third day to reduce outcome overlap. `MARKET` stablecoin observations
use BTCUSDT as a declared market proxy. Binance spot returns are research
labels, not Roostoo execution returns.

For short-frame research it also keeps the first snapshot in each UTC hour,
then labels +1 hour and, on every fourth UTC hour, +4 hours. The artifacts are
`results/source_short_outcomes.parquet` and
`results/source_short_validation.json`. Hourly samples from one day remain
correlated; the report requires 30 distinct days before showing an exploratory
correlation and reports collection gaps explicitly.

The JSON report withholds correlations until 30 distinct matured days and
marks them exploratory until 60 days. A feature also needs the same sign in
both time blocks, a cost-stressed paper arm that beats its unchanged control,
adequate feed coverage, and a sensible inverse control before an execution
change is proposed. These checks are independent of the 15-minute polling
count; repeated readings from one day do not count as new days.

The strongest future use of these sources is conditional: source features can
explain or time an already justified momentum position if they add net value.
The current study does not support a universal source score, a funding veto,
or an order-size increase.

## Reproduce

```sh
/opt/anaconda3/bin/python3 -m ml_research.source_features --forward
/opt/anaconda3/bin/python3 -m ml_research.source_edges --run
/opt/anaconda3/bin/python3 -m ml_research.forward_validation
```

Data sources: [Hyperliquid public funding history](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals),
[Deribit public API](https://docs.deribit.com/), and
[DefiLlama historical stablecoin supply](https://github.com/DefiLlama/api-docs/blob/main/llms-pro.txt).
