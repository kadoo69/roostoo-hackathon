# Literature review: short-horizon crypto predictability, read against this repo

Written 2026-09-20.
Scope: papers on intraday-to-multi-day crypto return predictability, screened on ONE question - does the per-trade edge clear a 10 bps round trip?

That screen is not arbitrary. Every short-horizon family this repo has killed died the same way, and the papers below die the same way too.

---

## 1. The headline: the literature independently confirms this repo's nulls

### Kitron and Wengrowicz (2026), arXiv:2608.21888 - short-horizon mean reversion, 183 Binance pairs

This is the single most useful paper found, because it is a much larger replication of `DECISIONS.md#scalp-meanrev-outcome`.

What it finds:
- 15-minute directional mean reversion is real and pervasive: **90% of 183 Binance pairs** carry significant reversal, against 2.7% of 187 US stocks, in every coin-year since 2021.
- **The signal lives in signs, not magnitudes.** Lag-one autocorrelation is near zero; simply betting against the previous candle captures most of it.
- Reversal concentrates after moves driven by aggressive taker flow and grows with flow intensity. Order-book depth conditions nothing.
- **Gross edge peaks near 1.3 bps per trade against a 5 bps round trip.** Median pair 0.46 bps. Not one of the 183 pairs clears even the 5 bps maker band at any threshold.
- **Thresholding cannot rescue it**, "because trading fewer, better bars shrinks the opportunity count faster than it grows the edge."
- Moving to 5-minute bars makes it **worse** (0.15 bps), not better.

Read against this repo, three of those are near-verbatim reproductions of findings already recorded here:

| this repo | the paper |
|---|---|
| "Selectivity does not rescue it. Raising `entry_z` from 2.0 to 3.0 moves the holdout edge from -0.28 to -0.68 bps and cuts trade count from 29,100 to 5,829 without improving the edge per trade." | "Thresholding cannot rescue it, because trading fewer, better bars shrinks the opportunity count faster than it grows the edge." |
| "Gross Sharpe, before any fee, falls monotonically as the bar shortens and goes negative at 5m." | 5-minute edge 0.15 bps against 15-minute 1.3 bps. |
| `#flow-scalp-outcome`: the divergence arm beats its sign-flipped control, edge is real but 3 to 11 bps and rare. | Reversal concentrates after aggressive taker flow and grows with flow intensity. |

**Conclusion: do not rebuild any 5m-to-15m mean-reversion or scalping family.** The repo's 54-config and 72-config sweeps were not implementation failures. They found the truth, and a 183-pair study with a permutation null and a frozen six-month holdout agrees. The paper's own framing is that the residual is compensation for supplying immediacy, competed down to roughly the cost of competing for it.

### Related confirmation: arXiv:2606.00060 - ML on hourly BTC under costs

27-fold walk-forward, 70,000 hourly observations, XGBoost / LSTM / iTransformer. Naive sign-based strategies produce positive **gross** performance and then collapse at 10 bps: ARC -64.0% long-only, -92.6% long-short.

Its own conclusion is the one that matters: the best cost-aware specifications **do not significantly outperform buy-and-hold** in Sharpe terms after bootstrap adjustment, and performance is concentrated in favourable regimes (profitable in 16 of 27 folds). That is this repo's `#gate4-rerun-outcome` and the BTC-hold benchmark problem, arrived at independently.

---

## 2. What was worth testing, and what happened

### arXiv:2606.00060's cost-aware execution filter - TESTED HERE, null

The paper's one transferable mechanism: change position only when forecast magnitude exceeds `lambda * cost`. It turns a -64% post-cost loss into +65% annualised on hourly BTC, and the paper reports that execution discipline mattered far more than model choice.

It does not transfer literally. At `donchian_4h`'s 2.69-day mean hold the expected absolute move is of order 500 bps against a 10 bps round trip, so a filter on expected move size can never bind. The paper's rule matters at hourly horizons precisely because the forecast is small.

The defensible translation is that the binding cost here is **rank rotation**, not entry, which is what the fee sensitivity already says: `donchian_4h` loses 0.114 Sharpe per 5 bps while the ranked books lose about 0.20, on 4x the turnover. So the filter was applied to the rotation decision - replace an incumbent only when the challenger's momentum score beats it by more than `lambda` round trips.

Declared at `config/rotation_hysteresis.yaml` before any backtest. Result at `DECISIONS.md#rotation-hysteresis-outcome`: **null**. Two of six arms pass the letter of the pre-registered criteria, but every effect is an order of magnitude below this repo's own declared noise threshold, and the filter only removes 1 to 6% of turnover because `lambda * 10bps` is trivially small against 40-bar momentum dispersion. The declared failure mode fired on the top-3 book, where drawdown worsened by up to 2.3 points.

### arXiv:2502.18625 - the market maker's dilemma - TESTED HERE, assumption bounded

The most decision-relevant paper for the existing bots, because it attacks an assumption every book relies on rather than proposing a new signal.

Its mechanism: a resting maker order faces a **negative correlation between fill probability and post-fill return**. "If the next price move is against a maker order in the top-of-book queue, that order automatically fills, with probability 1." A maker who never crosses is systematically filled on the trades that were about to go wrong, and missed on the ones about to go right.

This repo's execution is limit-first and never crosses, and `portfolio/backtest.py:79` sets `crossing = 0.0` for LIMIT. Every backtest therefore charges the fee and **zero** spread and assumes a 100% fill at the close. There is no adverse-selection term at all, and confirming the fee schedule with the organisers would not fix it, because this is not a fee.

Result at `DECISIONS.md#passive-fill-adverse-selection`: **the assumption is optimistic but bounded and small.** See that section for the bracket. Priority is unchanged: fee confirmation is worth about 3x more than adverse selection.

---

## 3. Found, not actionable here

- **arXiv:2607.09426, the Quarter-Hour Effect.** Opening order imbalance measured over the **first ten seconds** of each quarter hour predicts returns over 4 to 12 hours, on six Binance perpetuals. The 4-to-12-hour horizon is genuinely tradeable and matches this repo's bar clock, but the signal needs 10-second trade data the repo does not have and Roostoo does not publish. One detail is worth keeping: the predictive content **rotates** from the lagged-flow component at 4 hours (58%) to the public-signal component at 12 hours (65%), where "public signal" is the part of imbalance spanned by 28 technical indicators on past prices and volumes. If that rotation is real, the 12-hour version is partly reachable from klines alone. It is not reachable from the 4-hour version, which is the one the repo's bar clock would most naturally use.
- **PMC10015199, turn-of-the-candle effect.** +0.58 bps per minute concentrated at minutes 0, 15, 30 and 45. Execution-timing colour, not a strategy; the repo already acts on 4h closes, which are quarter-hour boundaries.
- **arXiv:2605.05089, 2212.06888, 2201.04699 - perpetual basis and funding carry.** Out of scope: the competition is spot, 1x, directional only.
- **arXiv:1811.07860, 2601.07664 - crypto factor models.** Weekly and daily cross-section. Relevant to a longer-horizon book, not to a 14-day window, and the repo's `#meanrev-xs-outcome` already covers the cross-sectional reversal-versus-momentum question on this universe.
- **arXiv:2604.26747, constrained LLM agents for factor discovery.** Methodologically interesting and directly opposed to this repo's hard rule of no LLMs in the research path. Noted, not adopted.

---

## 4. What the literature says this repo should stop doing

1. **Stop looking for alpha below about one hour.** Two independent large-sample studies and two of this repo's own sweeps agree that the edge there is 0.15 to 1.3 bps against a 10 bps round trip, and that selectivity makes it worse rather than better. This is a property of the horizon.
2. **Stop treating cost uncertainty as fee uncertainty alone.** The fee is one term. Adverse selection on passive fills is a second, and the backtest sets it to zero.
3. **Do not expect a cost-aware filter to help at multi-day holds.** It is the right idea at the wrong horizon; the expected move already dwarfs the cost.

## 5. Sources

| id | title | used for |
|---|---|---|
| arXiv:2608.21888 | Short-horizon mean reversion in cryptocurrency markets: a matched cross-market measurement | confirms `#scalp-meanrev-outcome` |
| arXiv:2606.00060 | Machine Learning-Based Bitcoin Trading Under Transaction Costs | source of the cost-aware filter; confirms BTC-hold benchmark problem |
| arXiv:2502.18625 | The Market Maker's Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off | source of the adverse-selection test |
| arXiv:2607.09426 | The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures | not actionable, data gap |
| PMC10015199 | Turn-of-the-candle effect in bitcoin returns | execution-timing colour |
| arXiv:2108.09750 | Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets | sub-second, out of scope |
| arXiv:2602.00776 | Explainable Patterns in Cryptocurrency Microstructure | 1-second LOB, out of scope |
| arXiv:1811.07860 / 2601.07664 | Cryptoasset factor models / Crypto pricing with hidden factors | longer-horizon cross-section |
| arXiv:2212.06888 / 2605.05089 | Fundamentals of perpetual futures / spot-perp basis | out of scope, spot-only competition |

All papers were located and read through Firecrawl Research. Claims above are traced to the specific paper; the two tested mechanisms are traced to `DECISIONS.md` sections with committed artifacts.
