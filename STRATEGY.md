# Strategy: 4h Donchian Channel Breakout

This is the strategy the competition bot runs.
It is `bot_a_4h`, defined by the frozen config at `config/bot_a_4h.yaml` and implemented in `bot/`.

The whole system is two comparisons per coin per four hours.
Everything else in this document is universe selection, position sizing, risk limits, and the evidence for why those two comparisons are the ones being made.

---

## 1. The rule

For each coin in the universe, on every completed 4-hour candle:

**Upper channel** is the highest close of the previous 20 completed 4h bars, about 3.3 days.
**Exit floor** is the lowest close of the previous 10 completed 4h bars, about 1.7 days.
Both windows exclude the bar currently being judged, so nothing in the signal uses information that was not available when the bar closed.

The position is either long or flat.
There is no short leg and no leverage.

| State | Condition | Action |
|---|---|---|
| Flat | close **above** the upper channel | Enter long on the next bar |
| Long | close **below** the exit floor | Exit to cash on the next bar |
| Either | neither condition met | Do nothing |

There is no separate stop-loss.
The exit floor is the stop, and because it is a trailing 10-bar low it rises automatically as price rises, so gains are protected without a second rule.

### Worked example

BTC on 4h bars.
The highest close of the last 20 bars is $82,400 and the lowest close of the last 10 bars is $79,100.

1. A bar closes at $82,900, which is above $82,400, so the bot buys $5,000 of BTC, being one twentieth of a $100,000 account.
2. Price rises to $90,000 over the next two days, and the trailing 10-bar low has risen with it to about $86,500. The position is held.
3. A bar closes at $86,200, which is below $86,500, so the bot sells. The trade is booked at roughly +4%.

---

## 2. Why this works

The channel is a regime detector, not a forecast.
A close above a 3.3-day high means the recent balance between buyers and sellers has just broken, and the bot does not need to know why, nor does it need to be right more often than not.
Measured directional accuracy for this family of signals sits slightly below a coin flip, and that is not a defect.

The edge comes from the asymmetry between the two windows.
Entry requires clearing a 20-bar high, exit only requires losing a 10-bar low, so the bot gives back less on the way out than it waited for on the way in.
This produces many small losses and occasional large gains, which shows up as a return skew of **+1.73** against roughly zero for holding the same coins.

That skew is the point.
The competition scores Sortino at the heaviest weight, and Sortino penalises only downside deviation while leaving upside unpenalised, so a payoff shaped like this scores well by construction rather than by luck.

---

## 3. Universe

The signal is worthless without the right set of coins, and this turned out to matter more than any parameter in the rule.

Every day the bot ranks the **entire Binance USDT market** by 30-day median dollar volume, takes the **top 30**, and trades whichever of those Roostoo lists.
In practice this yields about 22 tradable names, of which roughly 6 are long at any time.

The ranking pool must be the whole market, not Roostoo's own list.
Ranking inside Roostoo's 66 listed coins and taking its top 20 scores an out-of-sample Sharpe of **-0.15**, because a rank cut inside an already-filtered list admits that venue's thinnest names.
Ranking the full market and trading the listed intersection scores **1.56** with the identical signal.
The liquidity bar has to be absolute, not relative.

Stablecoins, tokenized gold, leveraged tokens and tokenized equities are excluded.

### Coin selection does not work

Picking coins that performed well historically was tested and rejected.

Across 43 coins with a full record in both halves of the out-of-sample period, the rank correlation of performance between the two halves is **-0.018 for Sharpe (p = 0.91)**, effectively zero.
The ten best coins of the first half returned a mean Sharpe of 0.099 in the second, while the ten worst returned 0.262 and the full set returned 0.196.
Selecting winners was worse than selecting losers.

No coin property predicted future performance either: volatility, dollar volume, time in market, autocorrelation and length of history give p-values of 0.56, 0.77, 0.23, 0.09 and 0.08, none of which survives correction for having tested five.

The universe rule is therefore mechanical and forward-looking, and the bot holds no hand-picked list of names.

---

## 4. Position sizing and risk

Each long position is **one twentieth of equity**.
If only 6 coins signal, the book is 30% invested and 70% cash, and that is intended rather than a shortfall.
Sitting in cash when few signals fire is how the strategy avoids drawdown.

**Gross exposure is hard-capped at 1.0.**
If more than 20 coins signal simultaneously, every weight is scaled down proportionally.
This cap is not cosmetic: on live data on 2026-09-19 the uncapped construction would have run **1.45x gross** and breached the competition's no-leverage rule, because the historical average exposure of 0.30 said nothing about the maximum.

Kill switches halt the bot on any of:

- drawdown from peak beyond 25%
- venue error rate at or above 25% of order attempts
- ticker data older than 120 seconds
- Roostoo and Binance prices diverging by more than 50 bps

A time-based de-risking ramp shrinks exposure linearly from 2026-10-15 to the close of the window on 2026-10-17.
It is coded into the frozen config rather than applied by hand, because the repository is submitted before 14 October and any post-submission change has to be pre-declared behaviour.

---

## 5. Execution

Orders are **LIMIT** by default, placed 1 bp inside the touch, to earn the 5 bps maker fee instead of the 10 bps taker fee.
An order unfilled after 15 minutes is cancelled and re-evaluated on the next cycle rather than chased.

Each pair's `PricePrecision`, `AmountPrecision` and `MiniOrder` are read from `exchangeInfo` at startup and respected on every order, and an order below the venue minimum is logged as skipped rather than sent malformed.

Signals are computed from **Binance** klines, and orders are placed on **Roostoo**.
Roostoo publishes no historical endpoint, so a bot sourcing its own bars would need 20 bars of warm-up, which is a meaningful fraction of a 14-day window.
Roostoo mirrors Binance almost exactly, and this is measured every cycle rather than assumed.
The first live reading on 2026-09-19 was **0.9 bps** of deviation, and the bot halts if it ever exceeds 50 bps.

---

## 6. Measured performance

All figures are net of a 5 bps maker fee, computed from daily-compounded returns.

| | Out-of-sample 2023+ | Recent 2025+ | BTC buy-and-hold 2023+ |
|---|---|---|---|
| CAGR | **80.8%** | 55.5% | 53.1% |
| Sharpe | **2.21** | 1.54 | 1.15 |
| Sortino | **4.28** | 2.94 | 1.79 |
| Calmar | **4.58** | 3.14 | 1.00 |
| Max drawdown | **-17.7%** | -17.7% | -53.0% |
| Screen 3 composite | **3.745** | 2.582 | 1.361 |

Behaviour over 1,345 rolling 14-day windows, which is the shape the competition actually scores:

| | This strategy | BTC buy-and-hold |
|---|---|---|
| Fortnight finishes positive | **57.6%** | 55.7% |
| Return above 5% | 23.4% | **30.3%** |
| Median 14-day Screen 3 | **+3.83** | +3.73 |
| Worst 14-day outcome | **-10.0%** | -29.8% |

Activity, which matters for the Screen 1 audit requirement:

- trades on **11.9 of every 14 days**
- about **31 trades** per fortnight
- mean holding period **2.69 days**
- about **6 coins** long at a time

---

## 7. Robustness

**Fee sensitivity.** The fee schedule is still unconfirmed, so the strategy was tested across the plausible range.

| Round-trip fee | Screen 3 | Annual cost drag |
|---|---|---|
| 5 bps (maker) | 3.745 | 4.1% |
| 10 bps (taker) | 3.393 | 8.2% |
| 15 bps | 3.065 | 12.3% |
| 20 bps | 2.756 | 16.4% |

The strategy remains strong across the whole range.
This is the reason a 1h intraday variant was built and rejected: it scores comparably at 5 bps but falls to 1.473 at 10 bps and turns negative at 20 bps, because it trades four times as often.

**Look-ahead control.** Inserting extra bars of delay between signal and execution degrades performance smoothly rather than collapsing it, at Sharpe 2.00, 1.95 and 1.91 for zero, one and two bars of added lag.
A look-ahead artifact dies at the first bar of delay; a real effect decays in proportion to the edge surrendered.

**Live implementation parity.** The live signal is an incremental state machine and the backtest is a vectorised array operation, written separately.
Replayed bar by bar over 199 bars and 22 symbols, they agree on all **3,938 cells with zero mismatches**.
Without this check no backtest number would transfer to the live bot.

---

## 8. What this strategy has not established

The strategy **fails the repository's own pre-registered validation gate**, and the submission should say so rather than imply otherwise.

The Deflated Sharpe Ratio corrects an observed Sharpe for the number of configurations searched before finding it.
Across the 351 trials logged in `config/trials.yaml`, the expected maximum Sharpe obtainable by chance alone is 1.675 annualised.
This strategy's 2.206 exceeds that, but its Deflated Sharpe Ratio is **0.8687 against a pre-registered threshold of 0.95**, so it does not clear the bar.

The failure differs in kind from every earlier candidate in this repository.
All previous strategies sat *below* the null's expected maximum, giving them an infinite minimum track record length, meaning no quantity of additional data could ever establish them.
This one sits above it, so its minimum track record length is finite at **2,927 daily observations, about 8.0 years**, against the 3.7 years it currently has.

The claim is unproven, not refuted.

It passes at a trial count of 21, which is the number of universe constructions evaluated to reach it, but repository policy counts every configuration ever run because each one consumed the same error budget.
That policy gives 351 and the honest verdict is failure.

Entering the competition with this strategy is a considered bet on the best candidate produced across 351 trials.
It is not a strategy demonstrated to have edge, and the two statements are both true.

---

## 9. Where things live

| Path | Purpose |
|---|---|
| `config/bot_a_4h.yaml` | Frozen parameters, SHA-stamped into every log record |
| `bot/strategy.py` | The channel rule as a live state machine |
| `signals/donchian.py` | The same rule vectorised, used for backtesting and parity checks |
| `bot/universe.py` | Daily liquidity ranking and venue intersection |
| `bot/portfolio.py` | Target weights, the 1/20 divisor and the gross cap |
| `bot/execution.py` | Limit-first order placement, precision handling, stale-order sweep |
| `bot/risk.py` | Kill switches and the de-risking ramp |
| `bot/verify.py` | Signal parity, position reconciliation, fill quality |
| `bot/run.py` | The cycle loop |
| `DECISIONS.md` | Every non-obvious choice, with its reasoning and its evidence |
| `results/` | Gate artifacts and backtest outputs |

Run it with `python3 -m bot.run config/bot_a_4h.yaml`.
It is dry-run by default; set `ROOSTOO_DRY_RUN=0` with credentials in `.env` to place real orders.
