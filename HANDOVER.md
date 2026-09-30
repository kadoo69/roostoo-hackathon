# Handover

Current state only. The full history of sessions to 2026-09-23 is archived at `docs/archive/HANDOVER_2026-09-23.md`; older section references in code and configs point there.

## Session 2026-09-30: LIVE on Roostoo (read first)

- Official FAQ: round started 2026-09-30, first trade due 2026-10-01 12:00 UTC; 30 calls/min; EC2 Sydney via Session Manager; public repo; no manual stop/override/trade. Data Sources Pack = Binance Vision, CryptoDataDownload, CoinAPI (nothing new for research; added `data-api.binance.vision` failover).
- Keys issued and in `.env`. Test account 50,000 USD. **Competition key answers "not yet a member of this competition"** as of 14:25Z; the `competition` book logs `wallet_unavailable` every poll and will start trading on the first successful wallet read. Ask the organisers if it is still inactive near the deadline.
- `gates/roostoo_smoke.py` measured fees (0.10% taker, 0.05% maker) and found four live-API mismatches, all fixed with regression tests (`#roostoo-keys-2026-09-30`).
- Operator chose `momentum_top3_30m`, lock OFF (`#competition-book-2026-09-30`). `competition` + `competition_rehearsal` started on the Mac at 14:22Z with `./run_bots.sh live`.
- Public repo LIVE: https://github.com/kadoo69/roostoo-hackathon (default `main`, tag `round1-live-2026-09-30`); commit live changes to `main` and push. AWS login NOT working yet (portal says the college email is not verified: invite not received). Next: accept AWS invite, run `deploy/ec2_bootstrap.sh` in Session Manager, then `./run_bots.sh livestop` on the Mac (never both hosts); watch the first real fills on the rehearsal book.

## Session summary 2026-09-25..27 (read first)

**Fleet (19 books + testnet):** core 4h `donchian_4h`, `momentum_top3_full`, `momentum_top3_lock`; short-term `momentum_top3_30m/15m/5m`, `momentum_top3_30m_allcash`, `momentum_top3_1h_allcash`, `momentum_top3_1h_long` (other session), `accel_15m`; burst `burst_5m`, `burst_15m`; A/B arms `burst_strong_15m`, `momentum_top3_15m_eq`, `momentum_top3_15m_hold3h`, `momentum_top3_5m_hold2h`, `momentum_top3_15m_slowexit`; shorts `short_accel_15m`, `short_pullback_15m`. All short-term longs: shorts off, target lock off, ladder on. A/B stop rules fall due 2026-10-10/11.
**Retired:** `accel_5m`, `momentum_top3_1h`, `momentum_top3_15m_allcash`, `momentum_top3_5m_allcash`, `momentum_top3_30m_wide`, `momentum_top3_15m_hold12h` (data under `live/_archive/`).
**Live P&L 2026-09-27 06:10Z:** fleet +74.1k net = +46.3k realised + 27.9k open; best `momentum_top3_30m` +15.0%; ~20.6k of the open gain is one coin (NEAR, held by 12 books).
**Robustness added:** catch-up entry guard + live min hold (`bot/entry_guard.py`), stale-cycle guard (sleep detection), parallel bar download (7-18 s -> 1-2 s), bar-close aligned loop (act 5-13 s after a close), cycle watchdog (frozen worker exits, supervisor respawns), Binance 418/429 guard (`bot.feed.binance_get`; an IP ban happened 2026-09-27 05:05Z when heavy analysis ran beside the fleet: run scans one at a time, never at a bar close), executor lets a held short close when shorts are off. `gates.live_validation` all PASS; `gates.live_audit` 0 parity mismatches.
**Key findings (DECISIONS anchors):** uptime is the #1 leak (overnight offline 9.0 of 9.1 h; sleep caused 57% of vanished open gains) `#unrealised-giveback-2026-09-27`; fast books detect rallies but keep ~0%, slow books keep 25-64% of the rallies they catch `#rally-capture-score-2026-09-27`; no take-profit beats current exits, fast-book edge appears after 2-3 h holds `#live-hold-time-2026-09-26`; signal hit rate is below 50%, profit is payoff asymmetry, momentum IC among candidates is negative `#signal-quality-2026-09-26`; whole Roostoo pool trades worse `#full-roostoo-pool-live-replay-2026-09-26`; long-only passes only at 1h, clock ensemble fails `#lowtf-long-only-clocks-outcome`, `#lowtf-clock-ensemble-outcome`.
**Tools:** desk dashboard at `/` (old at `/full`), `python3 -m gates.path_forensics`, `gates.signal_quality`, `gates.rally_capture`, `gates.live_audit`, `gates.live_validation`, `gates.fleet_review`; strategy docs `docs/strategies/` (zip on Desktop).
**Next:** keep the Mac awake (plug in; `sudo pmset -a disablesleep 1`) or move to EC2 (`deploy/README.md`); after 3-5 days of clean uptime, fold A/B winners into the core books as one declared change; decide the competition book (`momentum_top3_30m` candidate; lock yes/no) by 2026-10-03; get Roostoo keys and measure real fills; build cockpit, watchdog alerts and pre-flight gate (ideas in this session). Nothing from this session is committed.

## Fleet 2026-09-26 16:27Z (read first)

- 13 books in `run_bots.sh` plus `momentum_top3_1h_long` (other session) and `testnet_live`. All short-term books are long-only with no target lock (`#short-term-shorts-off-2026-09-26`, `#short-term-lock-off-2026-09-26`); the ladder is on everywhere.
- New live A/B paper books: `burst_5m`, `burst_15m` (`#burst-books-declaration`), `burst_strong_15m` vs `burst_15m` (entry needs >2% prior hour) and `momentum_top3_15m_eq` vs `momentum_top3_15m` (equal weights) (`#burst-strong-and-equal-weight-declaration`). Stop rules fall due 2026-10-10.
- `short_accel_15m` (short-only, 4h breakdown + volume + >2% falling hour + accelerating non-blow-off downside) started 2026-09-26 ~16:55Z (`#short-accel-declaration`); on 2025-26 history it fires about once a day and holds a short 13% of the time.
- Hold-time twins started 2026-09-26 ~17:4xZ (`#live-hold-time-2026-09-26`): `momentum_top3_15m_hold12h`, `momentum_top3_15m_hold3h` (control `momentum_top3_15m`), `momentum_top3_5m_hold2h` (control `momentum_top3_5m`).
- `momentum_top3_30m_wide` started 2026-09-26 (`#wide-pool-book-declaration`): the 30m rule on the whole Roostoo pool (64 coins, `universe_mode: venue_all`), control `momentum_top3_30m`.
- `short_pullback_15m` started 2026-09-27 (`#short-pullback-declaration`): `short_accel_15m` without the 4h-breakdown and falling-hour filters.
- Retired 2026-09-27: `momentum_top3_30m_wide`, `momentum_top3_15m_hold12h` (`#retired-2026-09-27`). Robustness added 2026-09-26/27: parallel fetch, bar-close alignment, cycle watchdog; `gates.live_validation` all PASS and `gates.live_audit` 0 parity mismatches on 492 decisions at 05:0xZ.
- `momentum_top3_15m_slowexit` started 2026-09-27 (`#rally-capture-score-2026-09-27`): 15m entry, 40-bar exit; rally-capture score shows fast books detect but do not capture, slow books capture but miss.
- Retired 2026-09-26: `momentum_top3_1h` (duplicate of 1h_long), `momentum_top3_15m_allcash`, `momentum_top3_5m_allcash`; data in `live/_archive/retired-2026-09-26/`.
- Dashboard leaderboard shows realised and open P&L.

## Fleet review 2026-09-26 ~09:40Z (read first)

- UPTIME IS THE BINDING PROBLEM: the Mac slept 19.5 h (09-25 13:53Z to 09-26 09:21Z); online 6.5 h of the last 26.5 h. Battery was at 8% at 09:31Z. Replaying the rule over the missed bars: sleep cost the 30m and 15m books ~3 points each (`#fleet-review-2026-09-26`).
- The 5m clock loses even when online (-3.7% to -6.1% in the replay, 5m_allcash -2.8% live); its day-14 falsification against 15m is due 2026-10-07.
- Best books: 15m +9.2%, 30m +9.0%, accel_15m +8.7%, 30m_allcash +6.4%. Shorts still negative (-6.1k).

## Path forensics 2026-09-25 ~05:40Z (read with the 09-24 state below)

- Fleet was already running at 05:25Z after the Mac woke; not restarted. The Mac is ON BATTERY (87%, ~2h left): plug in or the fleet dies again.
- `python3 -m gates.path_forensics` added; findings at `DECISIONS.md#path-forensics-2026-09-25`.
- Defect: the min hold and sticky slots use the simulated path, so a wake-up entry can be sold a bar later (PUMP/TAO 05:25Z on both 5m books). Catch-up entries (decided >1 bar late) net -6.1k on 65 positions vs +8.2k on 216 on time.
- `accel_5m` STOPPED 2026-09-25 ~09:05Z on operator instruction (`#accel-5m-retired-2026-09-25`); fleet is now 12 books in `run_bots.sh` plus `momentum_top3_1h_long` and `testnet_live`.
- Stale-cycle guard LIVE since 2026-09-25 07:06Z on every book (`bot.run.stale_cycle`, `#stale-cycle-guard`): a cycle that slept >5 s after fetching data (wall minus monotonic clock) or ran >300 s sends nothing and re-decides the bar next poll; watch `stale_cycle_aborted` in `live/<book>/orders-*.jsonl`. `gates/live_audit.py` parity fixed (it ignored entry confirmation): 162 decisions, 0 mismatches (`#live-audit-parity-fix-2026-09-25`).
- Fixes A (no stale new entries on catch-up) and B (min hold from the real entry bar) are LIVE since 2026-09-25 06:16Z on the 8 contenders books and both accel books (`bot/entry_guard.py`, `#catch-up-and-live-min-hold`); the 13-book stack was restarted together. Watch `stale_entry_blocked` / `live_min_hold` in `live/<book>/signals-*.jsonl`. Positions open before the restart carry no entry stamp, so B protects only new ones. `momentum_top3_1h_long` (other session) runs `bot.contenders_run` too and picks up A on its next restart.

## State at 2026-09-24 ~19:35Z (read this first)

- **Fleet, 15 books, all dry-run paper except `testnet_live`** (`./run_bots.sh status`; dashboard `http://127.0.0.1:8787/`, heatmap `/heatmap`):
  - Competition candidates, 4h long-only: `donchian_4h`, `momentum_top3_full`, `momentum_top3_lock`.
  - Short-term contenders books (`bot/contenders_run.py`, rule `signals/contenders.py`): `momentum_top3_1h/30m/15m/5m` and their `_allcash` twins (new entries absorb idle cash, `#idle-cash-new-entry-declaration`). Rule stack: 20/10 channel + 40-bar momentum, top 3 across both sides sized by |momentum| (cap 0.5), breadth switch for shorts, frozen stretch filter (`#lowtf-exhaustion-outcome`), sticky slots (`#let-winners-run-outcome`), volume confirmation 1.5x, 4h alignment ON only for 1h/30m (OFF for 15m/5m by operator, `#no-htf-15m-5m`, `#allcash-5m-no-htf`), 3-bar minimum hold on 5m books (`#min-hold-5m`), 3%/15% ladder both sides, target lock on all eight (window 2026-09-24 to 10-08, `#lowtf-lock-declaration`).
  - `accel_15m`, `accel_5m` (`bot/accel_run.py`, `#accel-guard-outcome`): paper only, failed backtest, kept by operator.
  - `momentum_top3_1h_long` belongs to ANOTHER session working in this repo; do not touch it. That session also added the "source hub" to `run_bots.sh`.
- **Validated today (adopted):** sticky slots; 4h alignment + volume confirmation (1h short-term book positive fit and holdout); target lock on short-term books (passes all clocks, P(>15%) falls to 0.02-0.04).
- **Failed today (do not re-test):** ML Ridge (`#ml-mvp-outcome`), top-down L/S, breadth shorts, acceleration (reverses at 15m-1h, `#accel-outcome`), accel guard, failed-breakout exit, shorter HTF (1h/2h) confirmation, idle-cash top-up of held names, stop-and-reverse (reversal leg -73..-98%). Short side has no edge at any clock tested.
- **Fixed today:** partial-universe false signals (`bot.feed.bar_frame` retry + `data_gaps`, bar close deferred up to 3 polls), per-symbol bar-cut race, halted TON/OMNI excluded, stablecoin list, dashboard ERR counting, heatmap threading, ledger residue.
- **Live so far (~26h, books online only ~30% because the Mac sleeps):** 15m +10.1%, 5m +10.5%, 30m ~+7%, 1h -2.7% (pre-filter shorts), 4h books ~-1%. Profit came almost entirely from ONDO/LTC in the 12-17Z trend; chop bleeds small. Trades under 15 minutes have no gross edge (+4.8 bps vs 12.2 bps fees).
- **Tools:** `python3 -m gates.fleet_review` (per-book review), `python3 -m gates.live_audit` (signal parity, fill realism), `python3 -m gates.universe_coverage`, `python3 -m gates.live_validation`.

## Next steps, in order
1. Uptime: EC2 (`deploy/README.md`) or mains power with `sudo pmset -a disablesleep 1`. Every live number is distorted until this is fixed.
2. Let the new rules run 7-14 days online before changing anything; compare each `_allcash` book with its twin and the 5m/15m books (4h check off) with 1h/30m (on).
3. Decide the competition book by 2026-10-03: `momentum_top3_full` with or without the lock; get Roostoo keys and measure one real fill and commission first.

## State at 2026-09-23

- **17:00Z: 11 books.** The three 4h books plus eight short-term paper books (1h/30m/15m/5m, Donchian and momentum; `#lowtf-5m-paper-bots`). The 4h books' first entries were forced once through the pending-entry retry at 17:01Z on operator instruction.

- **Books reset to 100,000 at 2026-09-23T16:08Z**; first entries at the 20:00Z close. Coverage: 88 Roostoo pairs = 26 in the pool, 38 outside the Binance top 30 by volume, 21 tokenized stocks, OMNI and TON halted on Binance, PAXG pegged (`python3 -m gates.universe_coverage`). Open: CRCLB and SNDKB (tokenized stocks) occupy two of the Binance top-30 slots.

- **Fleet cut to the three winners 2026-09-23** (`donchian_4h`, `momentum_top3_full`, `momentum_top3_lock`, plus `testnet_live`); everything else retired, see `#book-diagnosis-2026-09-23`. `topdown_ls` was built and tested (failed, `#topdown-ls-outcome`) and is stopped; the `/heatmap` dashboard page stays. Retired live data moved to `live/_archive/retired-2026-09-23/`. Earlier the same day the operator had stopped the whole fleet (`./run_bots.sh stop` plus `testnetstop`, scanner, lab, scalper, alpha_flow) so the bots can be modified. Dashboards and `awake` still run. Restart the whole stack together with `./run_bots.sh start` and `./run_bots.sh testnet` once the changes land.
- **ML research MVP built and NULL** (`ml_research/mvp.py`, `config/ml_mvp.yaml`, `#ml-mvp-outcome`): positive rank IC, no gain over 7-day momentum after costs, long/short worse than long-only. `python3 -m ml_research.mvp run` reproduces it; `python3 -m ml_research.mvp signal` prints the current book from the frozen rule. Do not promote it.

- **Fleet**: 16 books, reset to 100,000 together at 2026-09-22T20:48Z (earlier state in `live/_archive/`). Fifteen are Roostoo paper books in dry run, one places real orders on Binance testnet. `BOTS.md` lists them.
- **Keep the Mac awake and on mains power** (`./run_bots.sh awake`). Before the reset the fleet was offline 55% of the time because the laptop slept. EC2 (`deploy/README.md`) is the durable fix.
- **Live validation passes** on every book: `python3 -m gates.live_validation`.
- **Research is saturated.** 1,011 configurations tried; the latest sweeps (`#competition-wf-outcome`, `#literature-edges-outcome`, `#intraday-structure-outcome`, `#execution-timing-outcome`) found one pass, the target lock, and no new signal.
- **Rehearsal running**: `momentum_top3_lock` from 2026-09-23T08:00Z, compared with `momentum_top3_full` from the same moment.

## Before 2026-10-04, in order

1. Send `ORGANISER_QUESTIONS.md`: commission, 50k vs 100k, the Screen 2 cut and field size, leaderboard visibility.
2. Get Roostoo keys, then measure: one real fill (commission), fill rate of passive orders on one-tick names (PEPE and friends), rotation underweighting when sell cash arrives on fill.
3. Decide the competition book on 2026-10-03 from the backtests plus the forward week: `momentum_top3_full` with or without the target lock, or `donchian_4h`.
4. Set the competition window in the chosen config's `target_lock` block if the lock is adopted, and point the book at Roostoo with `ROOSTOO_DRY_RUN=0`.
5. Restart the whole stack together, never one book mid-bar.

## Fixed 2026-09-23, fleet restarted together at 05:40Z

`#execution-gaps-2026-09-23`: two-tick quotes accepted (ARB), missed entries retried every cycle until the next close, lot-step dust no longer blocks re-entry, the resting-order guard matches Roostoo pairs, target gross rounds down.
Watch gaps with `python3 -m gates.execution_gaps` (or `--watch 60`); `gates.live_validation` now fails a book whose target the venue rule refuses.

## Open defects and risks

- **Fixed 2026-09-24: partial-universe decisions.** `bot.feed.bar_frame` silently dropped symbols whose fetch failed, so books ranked a partial universe (`#live-audit-2026-09-24`). Now retried, and a bar close waits up to 3 polls for complete data. Re-run `python3 -m gates.live_audit` to check parity; look for `data_incomplete` in `live/<book>/errors-*.jsonl`.

- **Network.** 2026-09-23 16:31-16:41Z the Mac lost connectivity (not on Wi-Fi, likely a hotspot) and every book failed its cycles until it returned; the books recover on their own and missed entries retry until the next close, but a drop across a bar close delays that bar's trades. Same fix as uptime: EC2.

- **Uptime.** The Mac slept on battery 2026-09-22T21:04Z to 2026-09-23T04:04Z and the fleet acted a median 8 minutes late on every close; `caffeinate` does not hold a machine on battery. Each minute of lateness costs the ranked book 1.7+ bps a leg. EC2 or mains power with the lid open before 10-04. `#execution-timing-outcome`.

- On a real venue a sell rests until it fills, so a rotation buys less of the new name, and booking never tops it up. Partly closed: the retry now re-buys the new name once the sell's cash arrives, inside the same bar. Fill rates are unmeasurable until keys arrive. `#lowtf-paper-bots`.
- The retry pays the price at retry time, not the bar close the backtest fills at. Measure the difference from `live/<book>/orders-*.jsonl` after a week.
