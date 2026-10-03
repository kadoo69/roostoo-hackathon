# The bot fleet

Current as of 2026-10-02 (the books that run; retired books are in git history and `live/_archive/`).
`HANDOVER.md` "CURRENT STATE" has the live numbers and next steps.

## Live on Roostoo (EC2, real orders)

| book | clock | runner | what it is |
|---|---|---|---|
| `competition` | 30m | ContendersBot | the competition account (COMP keys): the `momentum_top3_30m` contenders rule, lock off, exit escalation on; waits for the account to activate (`#competition-book-2026-09-30`) |
| `competition_rehearsal` | 5m | SleevesBot | the TEST account: 50/50 rule + ride sleeves with separate ledgers, the stage-2 copy of `sleeves_5m` (`#sleeves-rehearsal-2026-10-02`) |

## Paper on EC2 (full uptime, the checkpoint comparisons)

| book | clock | runner | what it is |
|---|---|---|---|
| `ride_5m` | 5m | AdaptiveScalperBot | the momentum ride: +2% in 15 minutes, hold to +5% or 24 h (`#ride-and-blend-declaration`) |
| `ride_z3_5m` | 5m | AdaptiveScalperBot | the ride with a per-coin 3-sigma trigger (`#ride-z3-declaration`) |
| `sleeves_z3_5m` | 5m | SleevesBot | the 50/50 split with that ride half (`#ride-z3-declaration`) |
| `wf_live` | 5m | AdaptiveScalperBot | the dynamic bot: picks the best style of the last 3 days every hour, 3 pp switch margin (`#walkforward-live-declaration`), on EC2 since 2026-10-03 (`#wf-live-to-ec2-2026-10-03`) |
| `regime_ls_30m` | 30m | RegimeLSBot | the 30m rule that shorts breakdowns in a DOWN regime (`#regime-ls-declaration`, `#regime-ls-to-ec2-2026-10-02`) |

## Paper on the Mac (`./run_bots.sh`)

| book | clock | module | what it is |
|---|---|---|---|
| `momentum_top3_30m` | 30m | contenders_run | the competition rule's paper control |
| `blend_30m_ride` | 5m | hedge_explorer_run | fixed 50/50 blend of the 30m rule and the ride in one book (`#ride-and-blend-declaration`) |
| `resid_30m`, `htf0_30m` | 5m | scalper_adaptive_run | residual-price rule, and the 30m rule without the 4h filter (`#replay-decomposition-2026-10-01`) |
| `ride1_5m` | 5m | scalper_adaptive_run | the ride with a 1% trigger (`#ride-trigger-2026-10-01`) |
| `wide_30m`, `ride1_wide_5m` | 30m, 5m | contenders_run, scalper_adaptive_run | the rule and the ride on the whole Roostoo pool (`#wide-pool-live-2026-10-01`) |

## Registering a book

A book that is not registered trades invisibly. Every one of these, then restart the dashboards:

1. `config/<book>.yaml` with `meta.frozen: true`, `paper_only`, `declared_ref`, `falsification`.
2. Where it runs: Mac `run_bots.sh` `CONFIGS` and `module_for`; EC2 `deploy/ec2_bootstrap.sh` `PAPER_BOOKS` (or `BOOKS`) and `bot/ec2_feed.py` `PAPER`. On EC2 `bot.runner` picks the class from the config (`sleeves`, `regime`, `adaptive`, `contenders`, else the plain `Bot`).
3. `bot/dashboard.py` `BOTS`, `CONTROL_OF`, `EXPECTED_DRAG`; `gates/live_validation.py` `BOOKS`; `bot/desk.py` `SCALPER_BOOKS` for a paper book.

## Architecture in one paragraph

`bot/run.py` is the cycle: refresh universe if stale, fetch bars, evaluate channels, compute target, apply the booking ladder, diff against holdings, place orders.
A book with a different signal subclasses `Bot` and overrides `compute_target`, inheriting cold-start suppression, the drift band, kill switches, mirror checks, markout instrumentation and atomic state.
The subclasses in use are `ContendersBot` (`bot/contenders_run.py`), `AdaptiveScalperBot` (`bot/scalper_adaptive_run.py`), `SleevesBot` (`bot/sleeves_run.py`), `RegimeLSBot` (`bot/regime_ls_run.py`) and the blend in `bot/hedge_explorer_run.py`.

**Two hooks decide how a subclass behaves and both have drawn blood:**
- `trades_every_cycle()` - true lets orders fire between bar closes. Turning it on for booking made `deltas` run where `channels` is empty, which reads as "sell everything". It flattened three books. `#booking-flattened-the-book`.
- `target_from_channels()` - false for a book that computes its target every cycle, because carrying holdings forward between bar closes would silence its intrabar exits.

## Profit booking: the skim ladder

`bot/booking.py`, identical on every book: **3% step, 15% slice, no recycle.**

Each position carries a reference price. When the mark reaches reference x 1.03, 15% of the current position is sold and the reference resets to the mark, so a runner is booked repeatedly on the way up and a position that never gains is never touched.

**Booked cash idles.** Recycling into the same target is arithmetically a rebalance that only pays fees; redeploying into lower-ranked names is worse than holding cash. Both measured. `#alpha-flow-declaration`.

**Honest status: not a validated improvement.** The holdout return gain is p=0.14 and the drawdown gain is reproduced by a random-timing nonsense control, so it is exposure reduction rather than timing. Deployed on operator instruction as forward evidence.

**Why 3% and 15% and not something tighter.** Tightening the step ALONE is the only statistically significant effect in the whole ladder grid and it is harmful: holdout P(>20%) falls from 0.168 to 0.070 at a 1% step, p=0.004. Cutting the slice at the same time removes that cost. **Step and slice move together or not at all.**

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
