# The bot fleet

Fifteen books. Fourteen are paper on Roostoo in dry run; one places real orders on Binance testnet.

**The whole fleet was reset to 100,000 and restarted together at 2026-09-22T20:48Z**, on the replayed channel state, the one-tick spread rule and cash-capped buys. Everything before that is archived under `live/_archive/`. No reading may span the reset.

**Read this first: a gated arm's number means nothing without its control, and as of 2026-09-22 every control is gone.** The operator enabled booking on every book including the four that were controls, so each pair now measures its own treatment ON TOP OF booking rather than against a no-booking baseline. No reading carries across that boundary. `DECISIONS.md#booking-on-every-bot`.

---

## The fleet

| bot | interval | channel | rank | positions | pool | deployment | venue | booking |
|---|---|---|---|---|---|---|---|---|
| `donchian_4h` | 4h | 20/10 | none | 1/20 each | 30 | fixed | roostoo | ON |
| `donchian_4h_cushion` | 4h | 20/10 | none | 1/20 each | 30 | fixed + cushion | roostoo | ON |
| `donchian_1h` | 1h | 20/10 | none | 1/20 each | 30 | fixed | roostoo | ON |
| `momentum_top5_4h` | 4h | 20/10 | momentum 40 | top 5 | 30 | fixed | roostoo | ON |
| `momentum_top5_cushion` | 4h | 20/10 | momentum 40 | top 5 | 30 | fixed + cushion | roostoo | ON |
| `momentum_top3_4h` | 4h | 20/10 | momentum 40 | top 3 | 30 | fixed | roostoo | ON |
| `momentum_top3_full` | 4h | 20/10 | momentum 40 | top 3 | 30 | **full** | roostoo | ON |
| `alpha_flow` | 4h | 20/10 | momentum 40 | top 3 | 30 | full | roostoo | ON |
| `scalper_live` | 30m | own rule | none | 10% per trade | 30 | own | roostoo | ON |
| `testnet_live` | 1h | 20/10 | none | 1/20 each | **12** | fixed | **binance testnet** | ON |
| `donchian_30m` | 30m | 20/10 | none | 1/20 each | 30 | fixed | roostoo | ON |
| `donchian_15m` | 15m | 20/10 | none | 1/20 each | 30 | fixed | roostoo | ON |
| `momentum_top3_1h` | 1h | 20/10 | momentum 40 | top 3 | 30 | full | roostoo | ON |
| `momentum_top3_30m` | 30m | 20/10 | momentum 40 | top 3 | 30 | full | roostoo | ON |
| `momentum_top3_15m` | 15m | 20/10 | momentum 40 | top 3 | 30 | full | roostoo | ON |

All fourteen Roostoo books run in **dry run**. Only `testnet_live` places real orders.

## What each one is for

- **`donchian_4h`** is the selected configuration and the reference book. `#bot-selection`.
- **`donchian_1h`** is the same rule at 1h, a comparison and never a candidate. It trades most often, which makes it the fastest source of order-lifecycle evidence.
- **`momentum_top5_4h` / `momentum_top3_4h`** rank the fired names by 40-bar momentum and hold the top N. The ranking, not the exposure, is what produces the right tail. `#competition-book-selection`.
- **`*_cushion`** arms add a cash cushion to their control.
- **`momentum_top3_full`** spreads across whatever signalled instead of leaving cash in unfilled slots. The only change that improved the right tail on BOTH windows. `#full-deployment-outcome`.
- **`alpha_flow`** was the booking arm; booking is now everywhere, so its remaining job is the **alternate-data collector**: dealer GEX, plus every positioning feature and market input in the exact definition `gates/positioning_edges.py` scored (OI change, funding, premium, top-trader vs retail, taker ratio, aggregate OI and funding, DVOL, Coinbase premium), every 15 minutes, for up to 12 held names. It never trades on them: all failed their test. `#alpha-flow-declaration`, `#positioning-edges-outcome`.
- **`scalper_live`** runs on explicit operator instruction after failing its own backtest, paper only, to accumulate forward evidence. `#scalper-v1-outcome`.
- **`donchian_30m`, `donchian_15m`, `momentum_top3_1h`, `momentum_top3_30m`, `momentum_top3_15m`** are the deployed rules on faster clocks, added on operator instruction as paper forward evidence. **All five fail their backtest**, the ranked ones by cost: `momentum_top3_15m` holdout median is -21.3% per fortnight at 384x turnover. Never candidates. `#lowtf-paper-bots`.
- **`testnet_live`** exists to test what a backtest cannot: wire format, rounding, minimum notional, partial fills, cancel semantics, real fill rates. `#testnet-live`.

## Profit booking: the skim ladder

`bot/booking.py`, identical on every book: **3% step, 15% slice, no recycle.**

Each position carries a reference price. When the mark reaches reference x 1.03, 15% of the current position is sold and the reference resets to the mark, so a runner is booked repeatedly on the way up and a position that never gains is never touched.

**Booked cash idles.** Recycling into the same target is arithmetically a rebalance that only pays fees; redeploying into lower-ranked names is worse than holding cash. Both measured. `#alpha-flow-declaration`.

**Honest status: not a validated improvement.** The holdout return gain is p=0.14 and the drawdown gain is reproduced by a random-timing nonsense control, so it is exposure reduction rather than timing. Deployed on operator instruction as forward evidence.

**Why 3% and 15% and not something tighter.** Tightening the step ALONE is the only statistically significant effect in the whole ladder grid and it is harmful: holdout P(>20%) falls from 0.168 to 0.070 at a 1% step, p=0.004. Cutting the slice at the same time removes that cost. **Step and slice move together or not at all.**

## Running them

    ./run_bots.sh start | stop | restart | status | report | trades | dashboard
    ./run_bots.sh alphaflow | alphaflowstop
    ./run_bots.sh scalper | scalperstop | scalpreport
    ./run_bots.sh testnet | testnetstop        # LIVE ORDERS on Binance testnet
    ./run_bots.sh compare                      # gated arm vs its control

Dashboard at `http://127.0.0.1:8787/`, analysis tab at `/analysis`.

**Registering a new bot takes two places, and forgetting the second makes it trade invisibly.** `run_bots.sh` starts it; `bot/dashboard.py` `BOTS` is the only registry the dashboard and `bot/compare.py` read. This stale-list defect has now bitten three times.

## Architecture in one paragraph

`bot/run.py` is the cycle: refresh universe if stale, fetch bars, evaluate channels, compute target, apply the booking ladder, diff against holdings, place orders. A bot with a different signal subclasses `Bot` and overrides `compute_target`, inheriting cold-start suppression, the drift band, kill switches, mirror checks, markout instrumentation and atomic state. `bot/scalper_run.py` and `bot/alpha_flow_run.py` are the two subclasses.

**Two hooks decide how a subclass behaves and both have drawn blood:**
- `trades_every_cycle()` - true lets orders fire between bar closes. Turning it on for booking made `deltas` run where `channels` is empty, which reads as "sell everything". It flattened three books. `#booking-flattened-the-book`.
- `target_from_channels()` - false for the scalper, because carrying holdings forward between bar closes would silence every intrabar stop and target it has.

## What the live test on 2026-09-23 changed

`python3 -m gates.live_validation` runs every book through the live code on the live bar and checks it against the backtest. Run it before any restart that matters. `DECISIONS.md#live-validation-2026-09-23`.

- **Channel state is replayed from 150 bars at every close**, with the backtest's own `signals.donchian.position`, instead of a saved flag stepped one bar. A missed close no longer loses a trend. Any disagreement with the saved state is journalled as `channel_state_resynced`.
- **A one-tick quote is always tradeable**, however wide in bps; anything wider than both 5 bps and one tick is still refused. This is what lets the ranked books hold PEPE, BONK, SHIB and FLOKI, which is where most of their backtested edge lives. Paper fills on those names are charged the far side of the quote.
- **Honest expectation for the ranked books:** with their spread paid, `momentum_top3_full` holdout median is about 2.7%, not the 3.1% the older gates report at fee-only cost.

## Kill switches

Halt on drawdown beyond 25%, error rate at or above 25%, ticker older than 120 seconds, or mirror deviation beyond 50 bps on two consecutive cycles.

**A halt empties the target set, which flattens the book.** That is why the hysteresis on the mirror check matters, and why pointing a bot at a venue it cannot authenticate against is destructive rather than merely useless.

## Live-order safety

Not dry run means every order intent is written and **fsynced before** the venue call and resolved after. On startup every unresolved intent is settled against the venue before a new order may be sent; if any cannot be settled, submission stays blocked. `bot/intents.py`, `#testnet-live`.

Binance matches an intent exactly through `newClientOrderId`. Roostoo has no such field, so its path matches on pair, side, quantity and a timestamp window and reports `matched_by: heuristic`.

## State

`live/<bot>/state.json` holds holdings, cash, channel state, universe, equity curve, `skim_refs` and `skims`, written atomically every cycle. Journals are per day: `cycles-`, `orders-`, `signals-`, `lifecycle-`, `universe-`, `intents.jsonl`.

**Two state traps seen in production.** A channel state that says held while holdings are empty leaves a book unable to re-enter until that channel exits and breaks out again. And equity sitting at exactly the starting value for many consecutive cycles means no position was ever opened, not that the book is flat by choice.
