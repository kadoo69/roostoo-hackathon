# accel_15m - Contenders plus acceleration guard on 15-minute bars

The 15m contenders rule with the stretch filter, plus an acceleration guard: refuse blow-off or decelerating entries and exit early on sharp deceleration. No volume or 4h confirmation, no sticky slots, no target lock. Rank 3 on the dashboard.

## Live snapshot (dashboard, 2026-09-26 ~15:28 IST)

| Return | Net P&L | Equity | Drawdown | Gross | Positions | Evidence |
|---|---|---|---|---|---|---|
| 8.868% | 8,867.70 | 108,868 | 0.00% | 50% | 1 | 2 daily returns |

The dashboard's Sharpe, Sortino and Calmar for this book are computed from 2 daily returns and mean nothing yet; ignore them until there are at least 30 daily returns.
The book started at 100,000 USD paper on 2026-09-23 16:08Z (the `_allcash` twins on 2026-09-24 18:09Z) and was online only about 17-40% of the time because the host Mac slept.

## Status

Paper book (dry run), kept by operator instruction after its backtest failed (`DECISIONS.md#accel-guard-outcome`). Its 5m sibling `accel_5m` was retired on 2026-09-25 at -3.3% (`DECISIONS.md#accel-5m-retired-2026-09-25`).

**Update 2026-09-26: shorts are OFF on this book** (operator; `DECISIONS.md#short-term-shorts-off-2026-09-26`). It now trades long only; the profit ladder, target lock and every other rule below are unchanged. Where this file describes short candidates, the breadth switch or short fees, those parts are inactive.

## Data and universe

- **Signal prices:** Binance spot klines (`GET /api/v3/klines`), closed bars only, labelled by bar OPEN time. A bar is used only after its close time has passed (`bot.feed.closed_bars`).
- **Execution prices:** the Roostoo ticker (`MaxBid`, `MinAsk`, `LastPrice`); Roostoo mirrors Binance.
- **Universe (`bot.universe.select`, refreshed every 24 h):** the top 30 USDT pairs on Binance by 30-day median daily dollar volume, stablecoins excluded, pairs that stopped printing bars (halted, e.g. TON, OMNI) excluded, intersected with the pairs Roostoo lists. About 25 names trade in practice.
- **Window:** every decision replays the last 181 closed bars of the book's own clock for every universe name (`max(entry+5+20, REPLAY_BARS=150, 180+2)`).
- **Completeness:** if any universe name failed to download, or its last bar is older than the newest bar of the others, the decision is deferred up to 3 polls (`bot.feed.data_gaps`, `incomplete_hold`), so the book never ranks a partial universe.

## Signal (`signals.acceleration.guard_targets`, one function for backtest and live)

The contenders rule with the stretch filter plus an acceleration guard (`DECISIONS.md#accel-guard-declaration`). All lookbacks are in 15m bars.

1. **Momentum:** `mom = close / close.shift(40) - 1`.
2. **Long channel:** Donchian 20/10 as in the contenders books (enter above the prior 20-bar high close, exit below the prior 10-bar low close).
3. **Short channel:** 20-bar breakdown, cleared above the prior 10-bar high; never on a coin with a live long channel.
4. **Candidates:** long = long channel AND `mom > 0`; short = short channel AND `mom < 0` AND breadth switch on (fewer than 40% of the universe with positive 40-bar momentum). Strength = |mom|.
5. **Acceleration (`signals.acceleration.features`, short_bars k=12, mid_bars 48):** with `lc = log(close)`: `m_s = lc - lc.shift(12)`, `prior = lc.shift(12) - lc.shift(24)`, `vol = std(diff(lc), 48 bars) * sqrt(12)`, `acc = (m_s - prior) / vol`. `a_side = acc * side` (+1 long, -1 short).
6. **Entry guard:** a NEW position is refused when `a_side > 2.0` (blow-off, too fast) or `a_side <= -1.5` (already decelerating).
7. **Early exit:** a held position is closed when `a_side <= -1.5` (sharp deceleration against it), before its channel breaks.
8. **Stretch filter (entries only, frozen from the 15m fit period):** long entries skipped when `z` (20-bar) is in [-2, -1.5) or >= 3; short entries skipped for every `z < 1`. Held names are never forced out by it.
9. **Selection:** held names that keep their side and pass the deceleration check, plus new candidates that pass the guards, ranked together by strength; the top 3 are held. Unlike the contenders books there are no sticky slots: a stronger new candidate can displace a held name.
10. **Sizing:** weight proportional to strength, normalised, capped at 0.50 each, gross at most 1.
11. **No volume or 4h confirmation, no minimum hold** on this book (min_hold_bars is not set for accel_15m).

Live, it has never opened a short: with shorts only allowed at `z >= 1` during a breakdown, the condition essentially never occurs.

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
- **Target lock:** not configured on this book (no `target_lock` block), so it never caps gross.
10. **Regime gate:** `always_on` (does nothing).
11. **Orders (`portfolio.deltas`):** the difference between target and current weights, with a 25% no-trade band: a rebalance smaller than 25% of the larger of the two weights is skipped, so price drift does not cause orders. Opens, closes, skims and lock cuts are never inside the band. Orders under 1 USD are skipped. Sells go before buys.
12. **Cold start:** the first cycle of a process with no saved bar memory opens nothing (`DECISIONS.md#cold-start-chases-the-bar`).
13. **Stale-cycle guard (since 2026-09-25 07:06Z, `bot.run.stale_cycle`, `DECISIONS.md#stale-cycle-guard`):** before each order, if the machine slept more than 5 s since the cycle fetched its data (wall clock minus monotonic clock) or the cycle has run more than 300 s, no further order is sent, the bar is rolled back and re-decided on fresh data at the next poll.
14. **Order pricing (`bot/execution.py`):** longs use LIMIT orders at `min(bid x (1 + 1 bp), ask - 1 tick)` for buys and `max(ask x (1 - 1 bp), bid + 1 tick)` for sells, rounded to the tick; resting orders are cancelled after 300 s. Shorts use MARKET orders (open at MaxBid, close at MinAsk).
15. **Fees:** 0.05% per LIMIT side, 0.10% per MARKET side and per short side.
16. **Paper fills (dry run; Roostoo keys not issued yet):** a buy fills at the limit price if cash covers price x qty x (1 + fee); a sell fills at the limit price. If the spread is wider than 5 bps (a one-tick coin such as PEPE), the fill is charged at the far side instead.
17. **Missed entries** are retried every cycle until the next bar close while at least 1% of equity is in cash (`pending_entries`).
18. State (holdings, cash, ladder references, lock state, `opened` stamps, last bar) is saved atomically every cycle; journals go to `live/<book>/{cycles,signals,orders,errors,lifecycle,universe}-YYYY-MM-DD.jsonl`.

## Parameters (from `config/accel_15m.yaml`)

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
| clock | 15m |
| acceleration short / mid bars | 12 / 48 |
| refuse entry if side-signed acc | > 2.0 or <= -1.5 |
| early exit if side-signed acc | <= -1.5 |
| stretch skip long | z in [-2,-1.5) or z >= 3 |
| stretch skip short | z < 1 |
| volume / 4h confirmation | none |
| sticky | no |
| min hold | none |
| target lock | not configured |


## Backtest evidence

- Acceleration as a signal reverses at 15m-1h (rank IC -0.02, t -11 to -14; `DECISIONS.md#accel-outcome`).
- The guard on the contenders rule (`DECISIONS.md#accel-guard-outcome`): 15m control -18.91% fit / -18.60% holdout median per fortnight, guard -20.85% / -21.51%; the early exits cost 2-3 points a fortnight and the cost drag is 25.7% per fortnight.
- No backtest exists with the live volume or 4h confirmation because this book does not use them.

## Live trade forensics (to 2026-09-26 09:30Z, `python3 -m gates.path_forensics`)

41 positions (55 closed rows), 46% profitable, net +8,543. By coin: ONDO +4,260, ENA +3,335, LINK +1,006, PUMP +943; worst NEAR -1,976, UNI -316. Median holding time 0.8 h. Holds over 4 h made +7,129; 15 min-1 h holds lost -855. No short was ever opened. ONDO and ENA are 89% of net.

## Known weaknesses and what to watch

- The live +8.9% is ONDO and ENA (89% of net); median hold 0.8 h and 15 min-1 h holds lose.
- Backtest says the guard costs money; the live result is most likely the same trend the other books rode.
- No target lock, so it keeps full exposure after a good start (more upside, more giveback).
- Its 5m sibling lost; watch whether this one gives back once the trend ends.

## Files

- `config/accel_15m.yaml` (all parameters)
- `signals/contenders.py` (`targets`, `_pick_with_entry_filter`, `stretch`, `cap_weights`, `entry_confirmation`, `absorb_idle` lives in `bot/contenders_run.py`)
- `signals/donchian.py` (`position`, `breakdown_position`, `breadth_short_regime`)
- `bot/accel_run.py` (the live book), `signals/acceleration.py` (`features`, `guard_targets`), `bot/entry_guard.py` (guards A and B), `bot/run.py` (cycle, stale-cycle guard, fills)
- `bot/booking.py` (ladder), `bot/lock.py` (target lock), `bot/portfolio.py` (deltas, band), `bot/execution.py` (order pricing), `bot/risk.py`, `bot/universe.py`, `bot/feed.py`
- Backtest harness: `gates/let_winners_run.py` (`simulate`), `gates/breakout_quality.py`, `gates/accel.py`
- Run: `./run_bots.sh start` (whole stack), status `./run_bots.sh status`, review `python3 -m gates.fleet_review`, parity `python3 -m gates.live_audit`

