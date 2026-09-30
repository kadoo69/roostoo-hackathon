# momentum_top3_30m_allcash - 30m contenders that redeploy idle cash into new entries

Identical to `momentum_top3_30m` except that a NEW entry absorbs the cash left idle (profit the ladder banked, closed positions), up to 50% per name. Rank 5 on the dashboard; a paired arm against `momentum_top3_30m`.

## Live snapshot (dashboard, 2026-09-26 ~15:28 IST)

| Return | Net P&L | Equity | Drawdown | Gross | Positions | Evidence |
|---|---|---|---|---|---|---|
| 6.465% | 6,464.97 | 106,465 | -0.26% | 30% | 3 | 2 daily returns |

The dashboard's Sharpe, Sortino and Calmar for this book are computed from 2 daily returns and mean nothing yet; ignore them until there are at least 30 daily returns.
The book started at 100,000 USD paper on 2026-09-23 16:08Z (the `_allcash` twins on 2026-09-24 18:09Z) and was online only about 17-40% of the time because the host Mac slept.

## Status

Paper book (dry run), operator instruction 2026-09-24. The idle-cash-for-new-entries test was close to neutral in backtest (`DECISIONS.md#idle-cash-new-entry-declaration`: about -0.3 points per fortnight on 1h, +0.02 on 30m).

**Update 2026-09-26: shorts are OFF on this book** (operator; `DECISIONS.md#short-term-shorts-off-2026-09-26`). It now trades long only; the profit ladder, target lock and every other rule below are unchanged. Where this file describes short candidates, the breadth switch or short fees, those parts are inactive.

## Data and universe

- **Signal prices:** Binance spot klines (`GET /api/v3/klines`), closed bars only, labelled by bar OPEN time. A bar is used only after its close time has passed (`bot.feed.closed_bars`).
- **Execution prices:** the Roostoo ticker (`MaxBid`, `MinAsk`, `LastPrice`); Roostoo mirrors Binance.
- **Universe (`bot.universe.select`, refreshed every 24 h):** the top 30 USDT pairs on Binance by 30-day median daily dollar volume, stablecoins excluded, pairs that stopped printing bars (halted, e.g. TON, OMNI) excluded, intersected with the pairs Roostoo lists. About 25 names trade in practice.
- **Window:** every decision replays the last 181 closed bars of the book's own clock for every universe name (`max(entry+5+20, REPLAY_BARS=150, 180+2)`).
- **Completeness:** if any universe name failed to download, or its last bar is older than the newest bar of the others, the decision is deferred up to 3 polls (`bot.feed.data_gaps`, `incomplete_hold`), so the book never ranks a partial universe.

## Signal (`signals.contenders.targets`, one function for backtest and live)

All lookbacks are in bars of the book's own clock (30m).

1. **Momentum:** `mom = close / close.shift(40) - 1` (40 bars).
2. **Long channel (Donchian 20/10, `signals.donchian.position`, exit mode `lowchannel`):** enter when the close is above the highest close of the prior 20 bars; stay in until the close falls below the lowest close of the prior 10 bars. Exit is checked before entry.
3. **Short channel (`signals.donchian.breakdown_position`):** set when the close is below the lowest close of the prior 20 bars; cleared when the close is above the highest close of the prior 10 bars. A coin with a live long channel cannot be a short candidate.
4. **Candidates:** long if the long channel is live AND `mom > 0`, strength `mom`. Short if the short channel is live AND `mom < 0` AND the breadth switch is on, strength `-mom`.
5. **Breadth switch for shorts (`donchian.breadth_short_regime`):** on when fewer than 40% of the universe have positive 40-bar momentum.
6. **Stretch filter (entries only, frozen from the fit period, `DECISIONS.md#lowtf-exhaustion-outcome`):** `z = (close - mean20) / std20` over 20 bars. A coin NOT already held may not enter a long when `z` is in `[]` (no long skip), nor a short when `z` is in `[(-inf,-3),[-3,-2.5),[-2.5,-2),[-2,-1.5),[-1.5,-1),[-1,1),[1,1.5)]` (every short with z < 1.5) (intervals are [low, high), `null` = unbounded). A held coin is never forced out by it. In practice the short skip list blocks almost every short (shorts are about 2% of position-bars in backtest).
7. **Entry confirmation (`signals.contenders.entry_confirmation`, new entries only):**
   - **Volume:** the entry bar's quote volume must be at least 1.5x the median of the prior 20 bars (`DECISIONS.md#breakout-quality-outcome`).
- **4h alignment (ON):** a NEW entry needs the coin's own 4h 20/10 Donchian state to agree with its side: long needs the 4h long channel live, short needs the 4h breakdown live. 4h bars are joined on CLOSE times (`signals.exit_clock.to_fast`), so a 4h bar is visible only after it has finished.
8. **Selection, top 3 with sticky slots (`DECISIONS.md#let-winners-run-outcome`):** a held coin keeps its slot while it is still a candidate on the same side; free slots go to the strongest new candidates by strength. Up to 3 names across both sides.
- **Minimum hold:** none.
9. **Sizing:** weight proportional to strength (|40-bar momentum|) across the chosen names, normalised to gross 1, each capped at 0.50 with the excess handed to the uncapped names (`cap_weights`, 5 rounds); what cannot be placed stays in cash. Sign = side. A lone candidate therefore takes the full 0.50 cap.
- **Idle-cash absorption (ON, the only difference from `momentum_top3_30m`):** when a NEW position opens, the cash left idle after held positions (which are never topped up) and the new entries' own targets is added to the new entries in proportion to their targets, each capped at 50% of equity, gross at most 1 (`bot.contenders_run.absorb_idle`, `DECISIONS.md#idle-cash-new-entry-declaration`). Held names are still never topped up, so nothing the ladder sold is bought back.

## Live execution pipeline (`bot/run.py` `Bot.cycle`, every 30 s)

Order of operations inside one cycle:

1. Refresh the universe if 24 h old; download 181 closed bars per universe coin; check data completeness (defer up to 3 polls if incomplete).
2. Read Roostoo quotes; mark equity = cash + holdings at `LastPrice` + short values.
3. **Mirror check:** compare Roostoo `LastPrice` with Binance for every universe coin; a deviation of 50 bps or more on two consecutive cycles is a kill-switch breach.
4. **Kill switches (`bot.risk.gate`):** drawdown from the equity peak of 25% or more, order error rate of 25% or more, Roostoo ticker older than 120 s, or the mirror breach. Any breach sets the target to empty (flatten).
5. **De-risk ramp (`bot.risk.derisk_multiplier`):** every target is multiplied by a factor that is 1.0 until 2026-10-15 00:00Z, falls linearly to 0.0 at 2026-10-17 20:00Z (end of the competition window).
6. **New bar?** A decision is made only when the latest closed bar is newer than the last one processed (`bar_close_due`). Between closes the book carries its holdings forward and only the ladder and pending-entry retries trade.
7. **Target** from the signal (above), floored to 1e-8 and multiplied by the de-risk factor.
- **Guard A, catch-up entry guard (since 2026-09-25 06:16Z, `bot/entry_guard.py`, `DECISIONS.md#catch-up-and-live-min-hold`):** a decision is a catch-up when the book skipped at least one bar since its last processed bar or runs more than one bar after the close. On a catch-up, a coin the book does not hold (at least 1% weight on the same side) is NOT opened if the rule's simulated path already held it on the previous row. Coins new on the latest row still open; exits act normally; the freed weight stays in cash.
- **Guard B, live minimum hold:** the book stamps every real position with the decision bar its order went out on (persisted in state as `opened`). While a position is younger than `min_hold_bars` by that stamp (not configured here, so B never acts), it is kept at its current weight and side even if the target drops or flips it; the rest of the target is scaled to keep gross at most 1.
8. **Held shorts are never topped up** (`portfolio.hold_shorts`).
9. **Profit ladder (`bot/booking.py`, step 3%, slice 15%):** every position has a reference price set at entry. Each time the mark reaches the reference x 1.03 (long) or x 0.97 (short), 15% of the position is sold (or covered) and the reference resets to the mark. A held position is never topped back up. Skims under 10 USD are skipped. Backtest status: not a validated return gain; its drawdown gain is reproduced by a random-timing control, so it is exposure reduction.
- **Target lock (ON, `bot/lock.py`, `DECISIONS.md#lowtf-lock-declaration`):** window 2026-09-24 00:00Z to 2026-10-08 00:00Z. The book's equity at its first cycle in the window is the anchor. Once equity is 5% above it, the target is scaled so gross is at most 0.30 for the rest of the window (the lock persists across restarts). This trades the chance of winning for the chance of qualifying; P(fortnight > 15%) falls to about 0.02-0.04 in backtest.
10. **Regime gate:** `always_on` (does nothing).
11. **Orders (`portfolio.deltas`):** the difference between target and current weights, with a 25% no-trade band: a rebalance smaller than 25% of the larger of the two weights is skipped, so price drift does not cause orders. Opens, closes, skims and lock cuts are never inside the band. Orders under 1 USD are skipped. Sells go before buys.
12. **Cold start:** the first cycle of a process with no saved bar memory opens nothing (`DECISIONS.md#cold-start-chases-the-bar`).
13. **Stale-cycle guard (since 2026-09-25 07:06Z, `bot.run.stale_cycle`, `DECISIONS.md#stale-cycle-guard`):** before each order, if the machine slept more than 5 s since the cycle fetched its data (wall clock minus monotonic clock) or the cycle has run more than 300 s, no further order is sent, the bar is rolled back and re-decided on fresh data at the next poll.
14. **Order pricing (`bot/execution.py`):** longs use LIMIT orders at `min(bid x (1 + 1 bp), ask - 1 tick)` for buys and `max(ask x (1 - 1 bp), bid + 1 tick)` for sells, rounded to the tick; resting orders are cancelled after 300 s. Shorts use MARKET orders (open at MaxBid, close at MinAsk).
15. **Fees:** 0.05% per LIMIT side, 0.10% per MARKET side and per short side.
16. **Paper fills (dry run; Roostoo keys not issued yet):** a buy fills at the limit price if cash covers price x qty x (1 + fee); a sell fills at the limit price. If the spread is wider than 5 bps (a one-tick coin such as PEPE), the fill is charged at the far side instead.
17. **Missed entries** are retried every cycle until the next bar close while at least 1% of equity is in cash (`pending_entries`).
18. State (holdings, cash, ladder references, lock state, `opened` stamps, last bar) is saved atomically every cycle; journals go to `live/<book>/{cycles,signals,orders,errors,lifecycle,universe}-YYYY-MM-DD.jsonl`.

## Parameters (from `config/momentum_top3_30m_allcash.yaml`)

| parameter | value |
|---|---|
| universe | top 30 USDT pairs by 30-day median dollar volume, intersected with Roostoo, refreshed 24 h |
| channel | Donchian 20 entry / 10 exit (closes) |
| momentum | 40 bars |
| names | up to 3, both sides |
| max weight | 0.50 per name, gross at most 1.0 |
| breadth switch for shorts | fewer than 40% of the pool with positive 40-bar momentum |
| profit ladder | sell 15% each +3% (cover 15% each -3% for shorts), reference resets |
| no-trade band | 25% |
| orders | LIMIT, 1 bp inside, 300 s timeout; shorts MARKET |
| fees | 0.05% limit, 0.10% market and shorts |
| poll | 30 s |
| kill switches | drawdown 25%, error rate 25%, ticker age 120 s, mirror 50 bps |
| de-risk ramp | 1.0 until 2026-10-15 00:00Z, 0.0 at 2026-10-17 20:00Z |
| clock | 30m |
| 4h alignment | ON |
| volume confirmation | 1.5x prior 20-bar median |
| stretch skip long | none |
| stretch skip short | z < 1.5 |
| sticky | yes |
| min hold | none |
| idle-cash absorption | YES, new entries only, cap 0.50 each |
| target lock | +5% then gross 0.30, 2026-09-24 to 10-08 |


## Backtest evidence

- Idle cash to new entries (I2, `DECISIONS.md#idle-cash-new-entry-declaration`): 30m median -0.71% -> -0.82% fit, +1.09% -> +1.11% holdout; adds 8-10% turnover; P(>5%) and P(>10%) unchanged; its control was indistinguishable, so there is no timing effect. Larger new entries earn about what they cost.
- Topping HELD names back up (I1) failed outright and is not used.
- Sleep-window replay (without absorption modelled): +3.65% if online.

## Live trade forensics (to 2026-09-26 09:30Z, `python3 -m gates.path_forensics`)

6 positions (21 closed rows), 67% profitable, net +6,413. By coin: ONDO +4,758, NEAR +1,523, LINK +1,014; worst ENA -589, LTC -529. Median holding time 19.5 h. Holds over 4 h made +7,531; 1-4 h lost -1,118. No shorts. From its start (2026-09-24 18:09Z) it beat its plain twin +5.69% against +0.64% over the same hours.

## Known weaknesses and what to watch

- Live it beats its twin (+5.69% vs +0.64% from the same start) but that is 6 positions; ONDO is 74% of net.
- **The target lock FIRED at 2026-09-25 08:56Z** (equity 105,695 against its anchor 100,634). Until 2026-10-08 the book holds at most 0.30 gross, which is why the dashboard shows 30% gross. Its remaining return is about a third of the rule's, so from here it is no longer a fair comparison with its unlocked twin.
- Concentration: absorption pushes single names to the 0.50 cap, so one failed breakout costs more.

## Files

- `config/momentum_top3_30m_allcash.yaml` (all parameters)
- `signals/contenders.py` (`targets`, `_pick_with_entry_filter`, `stretch`, `cap_weights`, `entry_confirmation`, `absorb_idle` lives in `bot/contenders_run.py`)
- `signals/donchian.py` (`position`, `breakdown_position`, `breadth_short_regime`)
- `bot/contenders_run.py` (the live book), `bot/entry_guard.py` (guards A and B), `bot/run.py` (cycle, stale-cycle guard, fills)
- `bot/booking.py` (ladder), `bot/lock.py` (target lock), `bot/portfolio.py` (deltas, band), `bot/execution.py` (order pricing), `bot/risk.py`, `bot/universe.py`, `bot/feed.py`
- Backtest harness: `gates/let_winners_run.py` (`simulate`), `gates/breakout_quality.py`, `gates/lowtf_long_only_clocks.py`
- Run: `./run_bots.sh start` (whole stack), status `./run_bots.sh status`, review `python3 -m gates.fleet_review`, parity `python3 -m gates.live_audit`

