# CLAUDE.md — Roostoo Competition Bot

Read this first, then `STRATEGY.md`, then `DECISIONS.md`.
`DECISIONS.md` is the authoritative record: every non-obvious choice is anchored there with its reasoning and its evidence, and the code carries no comments by design.

---

## What this project is

A trading bot for the Roostoo crypto competition.
Live window is 2026-10-04 to 2026-10-17, fourteen days, 100,000 USD of paper capital, 1x only, directional strategies only.

Scoring runs two gates in sequence.
**Screen 2** ranks on raw return and advances the top 20 per region, so it is a hard qualification cut.
**Screen 3** then ranks survivors on `0.4*Sortino + 0.3*Sharpe + 0.3*Calmar`.
**Screen 1** is a compliance check on rule adherence, trade-log integrity and commit-history consistency, and failing it makes the other two irrelevant.

The repository is a research pipeline and a live bot in one.
Research is gated by a pre-registration at `config/preregistration.yaml` whose thresholds are frozen; the live bot is under `bot/`.

---

## The strategy in one paragraph

A Donchian channel breakout on 4h bars, long only, on the most liquid venue names.
Enter when the close exceeds the highest close of the prior 20 bars.
Exit when the close falls below the lowest close of the prior 10 bars.
Each position is one twentieth of equity, the remainder is cash, and gross exposure is hard-capped at 1.0.
The universe is the top 30 names by 30-day median dollar volume across the whole Binance USDT market, intersected with what Roostoo lists, refreshed daily.

Selected configuration is `bot_a_4h`. `bot_b_1h` is the same rule at 1h and exists as a comparison, not a candidate.

---

## The three findings that shaped everything

**1. The edge is in the universe rule, not the signal.**
Ranking by liquidity inside Roostoo's own 66 listings scores an out-of-sample Sharpe of -0.15.
Ranking the full 264-name survivorship-free Binance universe and trading the listed intersection scores 1.56 with the identical signal.
A rank cut inside an already-filtered list admits the venue's thinnest names. The bar must be absolute.
Separately, coin-level performance has **zero persistence** (Spearman -0.018, p=0.91 between periods), and picking historical winners was worse than picking historical losers.
See `DECISIONS.md#roostoo-universe-pool-size` and `#roostoo-coin-selection-does-not-persist`.

**2. The two screens are collinear at 14 days, not merely in tension.**
Within a fortnight the Screen 3 composite is governed by the sign of the window's return, which is governed by BTC beta.
Anything that cuts beta cuts P(positive), P(qualifying) and the composite together.
Measured across a core/sleeve range and again across position sizing, the composite rises monotonically as qualification probability falls, with no interior point where both improve.
This refutes the original plan's claim that asymmetry serves both screens.
See `DECISIONS.md#beta-is-the-only-screen3-lever`.

**3. Nothing here passes Gate 4 at an honest trial count.**
The ledger stands at 413 trials. The Deflated Sharpe hurdle is a function of how many configurations were searched.
The selected strategy scores DSR 0.8687 against a pre-registered 0.95 threshold.
It is the first candidate whose Sharpe exceeds the null's expected maximum, so its minimum track record length is finite (2,927 observations, about 8 years) rather than infinite as every predecessor's was.
The claim is unproven, not refuted, and the submission must say so.
See `DECISIONS.md#gate4-rerun-outcome`.

---

## Repo layout

| Path | What it holds |
|---|---|
| `config/preregistration.yaml` | Frozen thresholds for every gate. Amending it invalidates all prior gate artifacts. |
| `config/trials.yaml` | Append-only trial ledger. Every configuration ever evaluated, including nulls and abandoned searches. |
| `config/bot_a_4h.yaml` | The selected live configuration. `meta.frozen: true` or it will not load. |
| `config/bot_b_1h.yaml` | 1h comparison bot. |
| `DECISIONS.md` | Authoritative reasoning log, anchor-linked from configs and commits. |
| `STRATEGY.md` | The strategy written up for a reader, including the gate scorecard and what it has not established. |
| `signals/donchian.py` | The channel rule, vectorised, used for backtesting. |
| `bot/strategy.py` | The same rule as a live incremental state machine. |
| `bot/` | Live bot: settings, feed, universe, strategy, portfolio, execution, risk, state, journal, verify, blotter, insights, dashboard, status, run. |
| `gates/` | Validation gates and research runs. |
| `results/` | Gate artifacts and backtest outputs, committed. |
| `deploy/` | systemd unit for EC2, launchd plist for macOS, and operating instructions. |
| `live/` | Journals, state, snapshots. Gitignored. |
| `data/cache/` | 1.7 GB of Binance klines. Gitignored. Rebuild with `python3 -m data.bootstrap 1h`. |

---

## How the live bot works

**Market data comes from Binance, execution goes to Roostoo.**
Roostoo publishes no historical endpoint, so a self-sourcing bot would need 20 bars of warm-up out of a fourteen-day window.
Roostoo mirrors Binance almost exactly, so signals are computed from Binance klines and orders are placed on Roostoo.
The mirror is measured every cycle, not assumed. Median deviation runs about 4 to 5 bps.

**Each cycle** refreshes the universe if stale, fetches bars, evaluates the channel state, computes target weights, diffs against current holdings, and places orders only when a new bar has closed or a halt fires.
State persists atomically to `live/<bot>/state.json` after every cycle. On restart it is restored, and outside dry run the venue wallet is read and adopted as authoritative where the two disagree.

**Execution** is limit-first at or inside the touch, never crossing. `Executor.limit_price` clamps a buy to `ask - tick` and a sell to `bid + tick`.
Unfilled orders are cancelled after 15 minutes rather than chased.
Empirically, a limit posted 1 bp inside the touch fills within 15 minutes 93.8% of the time at the median symbol, giving a blended 5.31 bps per side.

**Kill switches** halt on drawdown beyond 25%, error rate at or above 25%, ticker older than 120 seconds, or a material mirror deviation beyond 50 bps on two consecutive cycles.
A halt empties the target set, which flattens the book, so the hysteresis matters.

---

## Trade tracking and the dashboard

`bot/blotter.py` reconstructs round-trip trades from the order journal by FIFO lot matching, apportions both legs' fees to the matched quantity, and reports realised P&L separately from open lots.
Two identities are checkable and must always hold: **bought equals closed plus open**, and **sold equals closed**.
A breach is a reconciliation failure, not a reporting bug.

`bot/dashboard.py` serves a page and `/api/state` from the same journals the bots write, standard library only.
`bot/insights.py` derives interpretation rather than displaying bare numbers: live exposure against the 18% historical mean, realised fee drag against the backtest's expectation per bot, distance to each kill switch rather than raw levels, shadow days against the three Gate 10 needs, supervisor restarts, and an explicit warning that win rate is meaningless below about 30 closed trades.
Market breadth scans all 66 venue names on a background thread every four minutes, because the scan takes roughly 65 seconds and must never block a page load.

---

## Running it

    ./run_bots.sh start | stop | restart | status | report | trades | dashboard

Dry run is the default. `ROOSTOO_DRY_RUN=0` with credentials in `.env` places real orders.
`BOT_VENUE=binance_testnet` switches venue for order-lifecycle testing.

For unattended running, `deploy/README.md` covers systemd on EC2 and launchd on macOS.
Agent-spawned background processes do not survive between tool calls, so a shadow run has to be started from a real terminal or a service manager.

---

## Conventions

- **No comments in code.** Structure and naming carry meaning; reasoning lives in `DECISIONS.md`.
- **Declare before you test.** A new family gets a config file with a stated mechanism and failure mode before any backtest runs.
- **Every configuration counts as a trial**, including nulls and abandoned searches, because each one consumes the family-wise error budget and raises the Gate 4 hurdle for every other candidate.
- **Pre-registered thresholds are never moved** to make something pass. Scope a control or add hysteresis instead of loosening it.
- **Long markdown files put one sentence per line.**
- **Never use the em dash.** Use a plain dash.
- Commit messages describe what changed and why, and must not describe work the commit does not contain.

---

## Anti-patterns learned here, at cost

**Do not optimise on a short sample.** 413 trials say it reverses. Two live trades is not a sample and a 100% win rate on them is noise.

**Do not let a test harness reimplement the logic it tests.** A hand-rolled limit price inside `gates/order_lifecycle.py` produced a marketable order and led to a false claim that the bot was crossing the spread. It was not. The harness now calls `Executor.limit_price`.

**Check a new metric against a series whose answer you already know.** `bot/report.py` shipped a Sortino that omitted the annualisation of downside deviation, inflating it by sqrt(365). It was caught because BTC buy-and-hold returned 34.22 where its known value is 1.7913.

**A backtest cannot catch wire-format defects.** `PairSpec.round_qty` computed `(qty // step) * step` in binary float and produced `0.0024600000000000004`, which Binance rejects outright. Backtests multiply weight vectors and never format an order. This is why the interim venue exists.

**Mean exposure says nothing about maximum exposure.** The book averages 18% gross but the construction is bounded at 1.5x, and it hit 1.45x on live data, which would have breached the no-leverage rule. Cap on gross, not on the volatility scalar.

**Telemetry can lie without trading being wrong.** The journal logged `gross_exposure 0` while holding half the book, because intermediate cycles recorded an empty target instead of held weights. Trading was unaffected; the Screen 1 audit trail was not.

**Measure in the venue's units.** The mirror check counted single-tick rounding as divergence. PEPE's tick is 26.2 bps, so one tick alone approached the halt threshold.

**Faster is not better here, and not only because of cost.** Gross Sharpe, before any fee, falls monotonically as the bar shortens and goes negative at 5m. A 5m breakout is noise that mean-reverts.

---

## Open items

- **2026-09-19 review update:** `results/logic_review_2026_09_19.md` records execution, universe and data-integrity gaps, and a surviving Sortino annualisation defect in five fortnight scorers.
  Their historical Screen 3 artifacts and the sign-indicator thesis need re-evaluation with corrected scoring.
- **Prospective paper lab:** `config/paper_lab.yaml` declares 1h, 4h, 8h and daily channels, a flow-confirmed 4h candidate and BTC control.
  `python3 -m bot.paper_lab --report` shows the isolated live-market paper comparison; simulated fills do not establish real fill quality or edge.

- **Roostoo credentials are not issued.** Every signed endpoint, the real `CommissionPercent`, fill quality, partial fills and rejections are untested on the competition venue. The README and the organizer disagree about commission by a factor of eight and only a live fill settles it.
- **Gate 10 needs three distinct days** of live operation and must run from a real terminal or EC2.
- **Gates 3, 5 and 7** have never been run. Gate 8 fails on drawdown, Gate 4 fails on trial count.
- **The full-history drawdown is 38.1%**, not the 17.7% the 2023-onward window shows. Quote the longer number.
