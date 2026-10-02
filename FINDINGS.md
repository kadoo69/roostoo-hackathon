# Findings index

`DECISIONS.md` is the authoritative record and it is 2,600 lines across 150 anchors. This is the way in.

Every claim below links to the anchor that carries its evidence. Nothing here is a summary you should trust on its own; it is a map.

---

## The five things that are actually true

**Correction 2026-09-23 (`#universe-completeness`):** until this date the research universe omitted every live Binance name Roostoo does not list. On the complete universe the ranked book's 2023-24 median falls from 4.43% to 2.30% and 2025-26 from 2.91% to 2.43%; the target lock's P(>2%) of 0.674 is unchanged. Relative verdicts below stand; absolute levels quoted before this date are too high.

1. **The edge is in the universe rule, not the signal.** Ranking by liquidity inside Roostoo's own 66 listings scores OOS Sharpe -0.15. Ranking the full 264-name Binance universe and trading the intersection scores **1.56 with the identical signal**. `#roostoo-universe-pool-size`
2. **The two screens are collinear at 14 days, not merely in tension.** Within a fortnight the Screen 3 composite is governed by the sign of the window's return, which is governed by BTC beta. Anything that cuts beta cuts P(positive), P(qualifying) and the composite together. `#beta-is-the-only-screen3-lever`, `#screen3-is-a-sign-indicator`
3. **Nothing here passes Gate 4 at an honest trial count, and that is settled.** DSR 0.8445 against a pre-registered 0.95, after a counting rule written **before** the number was computed cut the ledger from 754 to 470. Passing needs 9.8 years of data or Sharpe 2.498 against 2.206. `#trial-counting-rule`, `#gate4-standing-verdict`
4. **Coin-level edge does not persist.** Spearman 0.091 at p=0.586 between periods, and the eight worst coins beat the eight best out of sample. Replicated independently on an unrelated rule. `#coin-selection-does-not-persist`, `#rsi-band-outcome`
5. **Only two changes have ever improved both windows at once**, and both are live: the momentum ranking rule, and full deployment. `#competition-book-selection`, `#full-deployment-outcome`

## The one frontier everything moves along

Concentration, the derisk ramp, the weight path, the deployment rule and the booking ladder all trade **median return against the far tail**, in the same direction, with the fit window preferring the aggressive end and the holdout punishing it.

**The dials do not create return. They reallocate it.** `#compounding-outcome`, `#max-return-levers-outcome`, `#derisk-ramp-protection-outcome`

## Dead families: do not re-test

| family | configs | verdict | anchor |
|---|---|---|---|
| sub-hourly mean reversion | 54 | dead, confirmed by outside literature | `#scalp-meanrev-outcome` |
| order-flow scalping 5m/15m/30m | 72 | dead | `#flow-scalp-outcome` |
| cross-sectional mean reversion | 48 | dead | `#meanrev-xs-outcome` |
| global Ridge on price/flow ranks, 12h relative target | 2 | dead: IC +0.05 to +0.08 but no gain over 7d momentum after costs | `#ml-mvp-outcome` |
| ratchet stops | 26 | dead | `#ratchet-outcome` |
| correlation caps | 24 | dead | `#correlation-cap-outcome` |
| strong-but-retraced entries | 24 | dead | `#strong-retraced-outcome` |
| exit clock | 12 | dead | `#exit-clock-outcome` |
| take-profit targets | 26 | dead, then re-killed on live data | `#take-profit-outcome`, `#live-excursion-outcome` |
| ride exits: trail or half-book after +5%, or no cap | 4 | null; every arm flips sign between Aug-Sep and the live window | `#ride-exits-outcome` |
| RSI 50/70 band, 15m/1h/4h | 6 | dead, negative BEFORE costs at 15m and 1h | `#rsi-band-outcome` |
| order flow / volume / trade size as rankers | 9 | dead at 4h to 3d | `#alpha-flow-declaration` |
| funding-rate crowding | 15 | strongest fit signal in the repo, does not replicate; re-tested on corrected data, still null | `#alpha-flow-declaration`, `#positioning-edges-outcome` |
| positioning: OI, top-trader vs retail, funding veto and priority | 4 | null on 2022, fit and holdout. **Never veto negative-funding names**: removing them costs 1.5-3.7pp in every window | `#positioning-edges-outcome` |
| market gates: crowding, implied vol, Coinbase premium, stablecoin supply, washout BTC sleeve | 5 | null; crowding gate is the nearest miss (better 2022 and holdout, worse fit) | `#positioning-edges-outcome` |
| booking triggered by positioning | 2 | harmful (per-coin) or inert (market) | `#positioning-edges-outcome` |
| literature: BTC overnight, Monday Asia open, ETF-flow momentum, multi-horizon trend rank, liquidation-flush reversal | 5 | all fail on the competition engine; the two published anomalies decayed after publication | `#literature-edges-outcome` |
| intraday structure: first-hour momentum, 1h cointegrated pairs, quiet-market gate; alt hour-of-day and live 1m lead-lag diagnostics | 3 | all fail; pairs net -8 to -34 bps per trade and 48% exit on the stop; no hour moves the pool 10 bps; BTC-to-alt 1m lag is +3.3 bps | `#intraday-structure-outcome` |
| execution timing: delay the order k minutes after the 4h close | 1 | null with the opposite sign; every delay costs 1 to 8 bps because breakouts continue; the backtest's at-close fill is optimistic by about 0.4pp a fortnight on the ranked book | `#execution-timing-outcome` |
| drawdown brake: half gross after -8% in the window, alone and with the lock | 2 | null; lowers P(>2%) and median everywhere, helps only the worst window; a random-hour cut does better, because in-window drawdowns recover | `#drawdown-brake-outcome` |
| decorrelated universe traded long/short or long-only; beta-hedged C0 | 3 | fail; low-correlation selection = a random third; the hedge halves the worst window but cuts median and P(>2%) in the up periods | `#decorrelated-directional-outcome` |
| podcast edges: daily 20-day-high 5-day window, volume-growth rank, small-cap pump short, equal-weight stack | 4 | all fail on the complete universe; the small-cap short sleeve has a -39% worst fortnight and random shorts match it; the stack trades median for a shallower worst window | `#podcast-edges-outcome` |
| short sleeve, intrabar entry, channel ensemble, half/half blend | 4 | fail; only the target lock passes | `#competition-wf-outcome` |
| short sleeves on the complete universe: D1 breakdowns on donchian_4h, W1 bull-regime laggards in the ranked book's free slots | 2 | fail; D1 doubles the worst window and matches its random control; W1 loses 2023-24, the bull run; at 1h no signal drifts past a round trip | `#short-paper-books-outcome`, `#weak-short-bull-outcome`, `#book-diagnosis-2026-09-23` |
| top-down long/short: breadth+BTC regime gates the side, breakout longs, breakdown shorts, inverse-vol, both-side ladder | 4 | fail; the regime layer removes the longs when C0 earns most, inverse-vol is worse than equal weight; only buys a shallower worst window | `#topdown-ls-outcome` |
| breadth-switched shorts with own slots on 1h/30m/15m books | 6 | fail in every fit period and 5 of 6 holdouts; shorts double turnover, the shuffled switch does as well | `#lowtf-breadth-shorts-outcome` |
| top-3 contenders across both sides, sized by strength, 1h/30m/15m | 3 | fail vs long-only everywhere; strength sizing beats random sizes by 6-16 points, the short side and the fast clock lose | `#lowtf-contenders-outcome` |
| acceleration (return minus prior return, vol-scaled), long and short, 1h/30m/15m | 6 | fail; acceleration REVERSES at these clocks (15m rank IC -0.02, t -11 to -14) and betting on the reversal loses to cost too | `#accel-outcome` |
| clock-agreement ensemble: mean of 15m, 30m and 1h long-only contenders targets | 1 | fail: beats its components' average (+0.76, shifted control -1.36) and cuts the worst fortnight to about -13%, but loses to 1h long-only and 30m on median in every period; the 15m leg is a -8% a fortnight drag | `#lowtf-clock-ensemble-outcome` |
| long-only on the live 15m/30m contenders rules | 2 | fail: shorts are only ~2% of position-bars there, so nothing changes; long-only passes at 1h (already paper as momentum_top3_1h_long); the 15m live rule is about -8% a fortnight historically | `#lowtf-long-only-clocks-outcome` |
| acceleration guard on the contenders rule (refuse blow-off entries, exit on sharp deceleration) | 3 | fail; about equal to the control, early exits cost 2-3 points a fortnight | `#accel-guard-outcome` |
| rotation hysteresis | - | null, effects below the noise threshold | `#rotation-hysteresis-outcome` |

**Ledger stands at 1,020 rows** (679 in the Sharpe family before the positioning run). Every configuration counts, including nulls and abandoned searches.

## Settled parameters: do not re-fit

- Short-term contenders books hold a leader while its channel holds (sticky slots) and keep the 3%/15% ladder. `#let-winners-run-outcome`

- `exit_bars = 10`, walk-forward over 33 blocks. `#exit-walkforward-outcome`
- Pool 30. 20 is worse on every measure, 40 is indistinguishable. `#roostoo-universe-pool-size`
- Gross cap 1.0, which is the no-leverage rule anyway. `#sizing-sweep-outcome`
- `top3` is the floor of concentration. top2 holdout median falls to 0.44, top1 goes **negative** at -2.56 with an 81.8% drawdown. `#max-return-levers-outcome`
- Drift band 0.25. Real dial, interior optimum near 0.40, whole spread inside the noise floor. `#compounding-outcome`
- Booking ladder 3% step and 15% slice. Step and slice must move together. `#booking-on-every-bot`

## What the literature says, read against this repo

- **Short-horizon predictability is real and does not pay.** arXiv:2608.21888 measures 15-minute reversal across 183 pairs at **1.3 bps against a 5 bps round trip**, and thresholding makes it worse. A near-verbatim independent reproduction of this repo's own scalp null. `RESEARCH_SHORT_HORIZON.md`
- **Rank-optimal is not return-optimal, and it is adversarial.** The M6 Investment Challenge (arXiv:2412.04490) derives the policy that maximises P(top rank): diverge from what the field holds when behind, mimic it when ahead. In a crypto contest BTC is what the field holds. `RESEARCH_PORTFOLIO_RETURN.md`
- **A leaderboard at this field size is consistent with chance.** Never revise strategy on a mid-competition reading, ours or a rival's. Same source.
- **Large caps beat small in crypto**, which is outside support for the absolute liquidity bar. Liu, Tsyvinski and Wu, JF 2022.

## The live test, 2026-09-23

- **The ranked books' edge was mostly in names live execution refused.** PEPE and the other wide-tick memes carry most of `momentum_top3_full`'s holdout median. Live, before the fix: about 1.2%. Every gate: 3.1%. Filtered out: 1.4%. Traded with their spread paid: about 2.7%, now deployed. `#live-validation-2026-09-23`
- **Live channel state drifted from the rule** after every missed close. Fixed by replay. Over a fortnight the drift is noise (0.00pp median), but it made every forward A/B pair a comparison of start times.

## Defects found in this repo's own code

The full list is `docs/archive/HANDOVER_2026-09-23.md` section 8 and `docs/ANTIPATTERNS.md`. The ones that generalise:

- **Bars labelled by OPEN time** produced two look-ahead bugs, caught by a nonsense control and not by a delay test. `#lowtf-lookahead-control`
- **A default argument is a silent declaration.** `rank_score` defaulted momentum to 20 bars while every deployed book ranks on 40, so five gates scored a book the bot does not trade. `#ranking-lookback-mismatch`
- **A flag that changes WHEN a function runs is as dangerous as one that changes what it returns.** Enabling booking made `deltas` run where `channels` is empty, which reads as "sell everything". Three books flattened. `#booking-flattened-the-book`
- **A suppression rule silently eats a deliberate trade that resembles what it suppresses.** A 15% skim sits inside the 25% no-trade band, so every skim would have been suppressed while still being journalled. `#booking-flattened-the-book`
- **`x = maybe or default` hides a missing value.** Booking references were recomputed as the current price every cycle, so no pre-existing position could ever book. 18 holdings, 0 references. `#booking-on-every-bot`
- **A backtest cannot catch wire-format defects.** Four live-only defects surfaced within minutes of real orders. `#testnet-live`, `#qty-precision-defect`
- **A citation that no longer resolves reads as evidence and is not.** Eight frozen configs cite declaration anchors that were never written, and `HANDOVER.md` carried a dead one. `tests/test_doc_anchors.py` now fails the build on a new one. `#declaration-anchors`
- **Mean exposure says nothing about maximum exposure.** Cap on gross, never on a volatility scalar. `#leverage-cap-semantics`

## Open, and what would close it

1. **Send `ORGANISER_QUESTIONS.md`.** Zero trials, highest value available. Commission, keys, the Screen 2 cut, and leaderboard visibility.
2. **The $50,000 versus $100,000 question.** Roostoo's public `exchangeInfo` reports an initial wallet of 50,000 while every config assumes 100,000.
3. **Roostoo credentials.** Everything is paper until they arrive.
4. **Gate 10** needs three distinct days of unattended operation, which a sleeping laptop cannot provide. EC2.
5. **The forward books** need 28 days before anything is readable, and every control was given up on 2026-09-22.

## Reading order for a fresh session

`CLAUDE.md`, then `BOTS.md` for what is running, then `DATA_SOURCES.md` before touching any data, then this file, then `HANDOVER.md` for the current state (history in `docs/archive/`), then `DECISIONS.md` for the evidence behind any single claim.
