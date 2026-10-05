# Handover

Current state only. The full history of sessions to 2026-09-23 is archived at `docs/archive/HANDOVER_2026-09-23.md`; older section references in code and configs point there.

## CURRENT STATE 2026-10-05 21:35 IST / 16:05Z (read this first; everything below is history)

### The competition account
- Unit `roostoo-live@competition_r4` on EC2 at `64f7cfb`: the regime contenders rule long-only, 30m, n = 3. Equity about 96,250-96,550 (-3.5% since the 100k start). Leaderboard 20:12 IST (`run/leaderboard.json`): #1 +6.0%, #10 +0.3%, top-20 line -0.1%, us second last.
- Holdings: ADA ~0.50 (cost 0.2725), ENA ~0.24 (cost 0.2571), AAVE ~0.09 (bought 20:30 IST with idle cash), FIL ~0.08 (cost 1.0921), cash 7,289. Market regime DOWN since the 15:00Z bar: the rule's target is {AAVE 0.5} and it makes no new longs until the regime leaves DOWN.
- Operator guards (all in `config/competition_r4.yaml`, all in DECISIONS): 6 h hold + no trims after entry (ENA/FIL until the 18:00Z bar), no sale below cost unless down >5% (`live_no_loss_exit_max`), ENA held at any loss (`live_hold_below_cost`). Cost of the guards so far: at 21:00 IST the paper copy `regime_ls_30m` cut to AAVE only and rose (+2.40% to +2.75%) while the live book fell about a point.
- Bugs fixed today (each with a test): same-cycle rotation underfill (`#same-cycle-rotation-underfill-2026-10-05`); guards crowding held positions down to fit the gross cap (`#guard-crowding-fix-2026-10-05`, sold FIL at 21:00; an ENA sell was cancelled with `deploy/cancel_pending.py`); blotter reading an externally cancelled order as a fill (cancel tool now journals `cancelled_external`).

### Next actions
1. Freeze the live book; no more live changes until the day-3 check (17:30 IST 10-07), where regime vs `ride_5m` is decided once on data. Recommend removing `live_hold_below_cost` (and probably the other guards) there: the rule's own exits beat the guards today.
2. Paper tick-scalper grid (`bot/tick_scalper.py`, Mac, 48 cells, declared in `config/tick_scalp_pepe.yaml`): read about 08:30 IST 10-06 by its decision rule. At 68 min only PEPE touch (+250 over 28 trips) stood out; nothing survived the trade-through rule; EDEN lost -384 on one stuck lot. It runs on the Mac, so the Mac must stay on mains.
3. AWS SSO lasts 8-12 h: `! python3 deploy/aws_login.py`, approve at once (codes expire in 10 min).

### Lessons from 10-05
- Every hand-timed live move lost (13:09 switch, 14:00 seed, holding a laggard); the paper copy that never changed made money. Guards that block the rule's exits also block its risk control.
- Any new guard must be tested against the others (the crowding bug came from two guards each rescaling the target).
- Before any live change, snapshot the current signals and every book first (operator feedback).

## CURRENT STATE 2026-10-05 13:25 IST / 07:55Z (superseded)

### The competition account
- Unit `roostoo-live@competition_r4` on EC2 since 13:09 IST (07:39Z), config sha `3e530af1c364a8d3`, EC2 at `1af9b99`. Rule: the regime contenders rule long-only on 30m bars (top 3 breakouts by 40-bar momentum, at most 0.5 each, no new longs while the market regime is DOWN, no shorts), 3%/15% ladder, exit escalation, 1% underfill chase cap (`#competition-r4-2026-10-05`, `#competition-r4-live-2026-10-05`).
- `competition_z25` (the ride) is stopped and disabled, staged as the revert. One live unit per account: `deploy/switch_live.sh FROM TO` (run on the instance as root after pulling) stops the old unit, cancels resting COMP orders (`deploy/cancel_pending.py`) and starts the new one.
- At the switch all four ride positions were sold; the account is in cash (100,075, +0.08% since the open) until the rule opens a fresh name. Paper record of the same rule: `regime_ls_30m` (shorts on; its target now ADA, SUI, NEAR, all old entries the live book will not chase).
- Why: since the open `regime_ls_30m` +5.66% against the live ride +0.35%, the lead all long side. Caveat on record: on 14-day replays the ride is stronger (+17.7% vs +6.5% median); the forward window decides.

### Next actions
1. Watch the first entries: tail `live/competition_r4/cycles-*.jsonl` and `orders-*.jsonl` on EC2 through `deploy/ssm_shell.py`, or the desk at 8787.
2. 17:30 IST 10-07 day-3 check, plus daily: revert to `competition_z25` if `competition_r4` trails the ride twin `ride_z25_zrank_5m` by more than 2 points from 13:09 IST 10-05; trailing `regime_ls_30m` by more than 2 points is an execution fault, investigate first.
3. Daily: `python3 deploy/export_logs.py`, commit `logs/`.

### Settled today (do not re-test without new evidence)
- n = 4 on the regime rule loses to n = 3 at every one of 12 offsets (14 d and 3 d).
- A +1.5% exit on 30m breakouts: 92% top below +1.5% before a 1.5-std pullback, but the 24 h drift (+0.76% mean) beats the capped exit (+0.52%). Volatility has fallen: median 30m std 0.49% vs 0.78% the 4 days before.
- Everything in the 12:25 section below still holds for the ride research.

## CURRENT STATE 2026-10-05 12:25 IST / 06:55Z (superseded)

### The competition account
- Unit `roostoo-live@competition_z25` on EC2, running since 09:56 IST with config sha `0bb985ffae5259f9` (EC2 checkout `6c47778`). Rule: per-coin 2.5-sigma burst ride, 2 slots of 1/2, target 2 x daily vol, 24 h hold, 3%/15% ladder, simultaneous triggers ranked by z (`rank_by: z`), 1% cap on completing a cash-capped entry (`underfill_max_chase`), exit escalation that reads fills from `CoinChange`. No churn, no gate, probe spent.
- Holdings: UNI 1/3 (exit by 20:05 IST), LTC 1/6 (20:10), PUMP 1/6 (21:15), ONDO 1/3 (08:25 IST 10-06), unless targets hit first. Equity about 99,900 (-0.1%); leaderboard about 40th at 10:35 IST (field compressed).
- The live book is FROZEN on the operator's instruction ("just monitor"); change it only with a declared test over 12 start offsets plus paper time, and the operator's yes.

### What changed live on 10-05 (all committed, DECISIONS anchors)
`#underfill-chase-cap-2026-10-05` (01:47), `#competition-zrank-2026-10-05` (08:12), `#competition-trim-churn-2026-10-05` (08:25, WITHDRAWN 09:56 by `#competition-churn-off-2026-10-05`: churn loses 8 of 12 fourteen-day offsets), `#escalation-fill-field-2026-10-05` (08:36, a real bug: Roostoo reports FilledQuantity = Quantity on unfilled orders), `#churn-keep-strong-2026-10-05` (09:13, moot after the churn came off), `#live-gate-rollback-2026-10-05` (an interrupted deploy had restarted live with the gate; rolled back in 3 minutes, no decision made under it).

### Paper books on EC2 (compare at the day-3 check)
- `ride_z25_zrank_5m` = live twin; `ride_z25_n4_5m` = live rule with 4 slots, seeded 12:17 IST from the live positions at 1/4 each (`#ride-n4-paper-2026-10-05`); `ride_z25_gate_5m` = live + breadth gate (`#ride-regime-gate-outcome`, 9 of 12 offsets); `ride_z25_churn_5m` = churn record; `ride_z25_5m` (old ranking) and `ride_z25_swap_5m` (full swaps, about -2.9%, the worst book); plus regime_ls_30m (best forward book, +8.6%), ride_z3_5m, ride_5m, wf_live, sleeves, split_tilt.
- Desk 8787 on the Mac: competition-first view with live venue quotes every 3 s and a trigger radar (`#desk-revamp-2026-10-05`, `#desk-live-quotes-2026-10-05`).

### Next actions
1. 20:05-21:15 IST: UNI, LTC, PUMP exit (or hit targets); watch the first fresh 1/2 entry and compare with `ride_z25_n4_5m`.
2. 17:30 IST 10-07: `python3 -m archive.gates.day3_fleet_forward` on EC2 (and on the Mac with `--live-return=... --live-dd=... "--live-subs=a,b,c"`); decide by `#day3-fleet-forward-declaration`. Candidates to weigh there: 4 slots, breadth gate, regime_ls long-only (R4).
3. Daily: `python3 deploy/export_logs.py`, commit `logs/`. The exported CSVs now skip stale-cancelled orders (`#code-review-fixes-2026-10-05`).

### Research state 10-05 (do not re-test without new evidence; all over 12 start offsets unless noted)
- NULL: partial trims, churn (PT50C; its +35% single window was luck), nearer targets, ride1_wide (64 coins, +1% trigger), concentration (1 slot), z >= 5 skip, correlation-liquidity regime (all arms; high-risk triggers ride about 0% but filtering them fails), lone-burst filter, 6 slots, full swaps (paper A/B).
- Passed or near: ranking by z (live), breadth gate (paper), 4 slots (same return, lower drawdown, higher Sharpe; half the offsets).
- Missed-trigger audit: of 90 triggers since the open, 10 hit target, mean -0.08%; top-5 books hold 6-45 positions.

### Lessons (also in CLAUDE.md)
- Judge every change over many start offsets; one window flips sign. Do not stack live changes under rank pressure. A rejected tool call may already have run on EC2: check unit start time and lifecycle config_sha after any interrupted deploy. Keep the Mac on mains; renew AWS with `python3 deploy/aws_login.py`.

## CURRENT STATE 2026-10-05 01:20 IST / 2026-10-04 19:50Z (read this first; everything below is history)

### The competition account
- Unit `roostoo-live@competition_z25` on EC2 `i-015fad70d34b0b83d`, code `6697030`, config `config/competition_z25.yaml`.
- Rule: per-coin 15-minute burst ride. Buy when a coin's 3-bar 5m return reaches 2.5 x its own 24 h std (z >= 2.5); take profit at 2 x the coin's one-day volatility fixed at entry, else exit after 24 h; 3%/15% booking ladder; 2 slots of 1/2 since 23:00 IST (`#competition-two-slots-2026-10-04`).
- Holding LTC, PUMP, UNI at 1/3 each (opened under n=3, kept by the weight-aware transition); 2 x 1/2 entries begin once two of them exit. Latest exits: LTC and UNI by about 20:00 IST 10-05, PUMP by about 21:10 IST (its target is +16.7%).
- Equity 100,699 (+0.70%) at 01:18 IST; peak 102,527 at 22:22 IST; drawdown almost all PUMP (-4.3% since the peak, the pool flat). Realized: SUI +5.1% (+1.7k), skims +203. Leaderboard about 3rd at the last look (gap about 1-2.5 pp, day 1 of 14).
- No faults. No manual order has ever been sent on the COMP keys (FAQ Q28). Every live change today is a commit with a DECISIONS anchor and a README change-table row.

### Running right now
- EC2: `competition_z25` (live), `competition_rehearsal` (TEST keys), paper `wf_live`, `ride_5m`, `ride_z3_5m`, `sleeves_z3_5m`, `split_tilt_5m`, `regime_ls_30m`, and the new A/B pair `ride_z25_5m` / `ride_z25_swap_5m` (both started flat 01:15 IST, `#ride-swap-paper-2026-10-05`).
- EC2 monitor: `roostoo-monitor.timer` every 5 min writes `live/monitor/status-<day>.jsonl` and `latest.json` (read-only, alerts for stale cycle, halt/freeze, drawdown > 5%, no unit) (`#ec2-monitor-2026-10-05`). `deploy/ec2_status.sh` prints it.
- Mac: desk on 8787 (pulls EC2 via a child process since `e35623e`; 8789 never shows EC2 by design), half-hourly monitor, 7 paper books. The Mac `aws` CLI is broken (Homebrew Python 3.14); use `bot.ec2_session.run_script` and renew SSO with `python3 deploy/aws_login.py`.

### Next actions (in order)
1. 10:00 IST 10-05: progress read of the A/B (`ride_z25_5m` vs `ride_z25_swap_5m`: equity, whether the swap fired and on what) and a forward checkpoint of the live 2-slot rule on trades since 23:00 IST only. No decision from it.
2. On or after 01:10 IST 10-08: `python3 -m archive.gates.repeat_trigger_forward`; decide by `#repeat-trigger-forward-declaration` together with the A/B equity. Only a pass makes the swap a candidate for the competition book, and only on the operator's decision.
3. LIVE since 01:47 IST 10-05 (20:17Z, commit `6697030`): `#underfill-chase-cap-2026-10-05`, a cut-short entry completes only within 1% of its order price. Restart resumed LTC/PUMP/UNI, first bar-close decision (20:15Z bar) clean, 0 orders, no alerts. E2E check: `python3 deploy/checks/underfill_chase_e2e.py`.
4. Leaderboard 01:31 IST 10-05: 9th at +0.4%; 1st +3.1%, 2nd +1.4%, places 3-10 within 0.6 pp. No rank rule yet.
5. Daily: `python3 deploy/export_logs.py`, commit `logs/` (covers every unit that traded the COMP account). At the end: `git tag submission-final`.

### Research state (do not re-test without new evidence)
- 10-04 nulls on the ride: sizing by z, the 64-coin universe, nearer targets, shorter holds, gain locks, rotation, leader hold, pullback entry, trend-gated rotation. Passed: 2.5 sigma trigger (by rule), V2 volatility targets (operator call after seeing three arms), 2 slots (`#ride-hold-slots-outcome`).
- Trigger strength over 30 days: z 2.5-4 rides about +1.3% with 56% wins; z >= 5 (exhaustion) about 0% with 38%. Fresh triggers and 6.5 h-old flat holdings are worth about the same (+0.99% vs +0.88%), less than a swap's cost, which is why swaps lose on average.
- The rule earns in trends (+22% / +46% in the trend windows) and gives back a little in chop (-0.5% over the last 3 days). Today's money went to FET (+9.7% since the open, three triggers we missed while switching or full) and ADA.

### Lessons from day one (also in CLAUDE.md)
- Execution bugs cost more than strategy: the cash-capped entry that could never complete (`#underfilled-entry-2026-10-04`) cost about the gap to first place.
- Every unit switch costs the first bar's trigger; switching in the first two hours missed FET at 18:20 and SOL at 19:00.
- The one-shot probe entry was borderline under Q28; never repeat it.

## Day-one detail 2026-10-04 17:30-23:00 IST (history)

### Pending reads
- 2026-10-05 10:00 IST: forward checkpoint of the live 2-slot ride (trades since 23:00 IST only).
- On or after 2026-10-07 19:40Z (01:10 IST 10-08): `python3 -m archive.gates.repeat_trigger_forward`, decide by `#repeat-trigger-forward-declaration` (paper book only if it passes).
- EC2 monitor: `live/monitor/status-<day>.jsonl` on the instance (`#ec2-monitor-2026-10-05`); exit-variant research on the ride is exhausted (10 nulls on 10-04).

### 23:00 IST: competition_z25 now runs 2 slots of 1/2 (`#competition-two-slots-2026-10-04`, commit `51f5446`)
- Evidence `#ride-hold-slots-outcome`: N2 beat N3 in every window (+20.3 / +47.7 / +4.1% against +18.4 / +24.3 / +3.7%), drawdown no worse; leader-hold failed.
- Transition: LTC, PUMP, UNI (opened under n=3) keep 1/3 and their exits; slots are counted by weight, so new 1/2 entries open as they exit. No forced sale.
- Also tonight: underfilled-entry fix (`#underfilled-entry-2026-10-04`); SUI closed at its target (+5.1%); day-one lessons in CLAUDE.md. Equity 101,788 (+1.79%) at 23:00 IST.

### FIRST COMPETITION FILL 19:30 IST (14:00Z): BUY SUI, about 27,992 at 1.1907 (33.3k, maker LIMIT, order 3421782)
- Placed by the one-shot probe (`#competition-probe-2026-10-04`, commit `f1d0f85`, z >= 2.0, SUI the highest z on the 13:55Z bar); the probe is now spent (`probe_done` in `live/competition_z25/ride_state.json`). It proves COMP trading is enabled after the open. SUI is held under the ride exits: +5% over the 1.1934 entry close (high >= about 1.253) or 24 h (14:00Z 10-05), plus the 3%/15% ladder.
- All 17 live decisions from 12:35Z to 13:45Z matched an independent recomputation from Binance bars (no mismatches).

### Switch at 19:06 IST: the competition account now runs `competition_z25` (`#competition-z25-2026-10-04`)
- Operator 19:03 IST: loosen for an agile bot. `competition_z3` with `sigma_k` 2.5, picked by the declared `#ride-agile-outcome` (2.5 sigma beat nearer take-profits; it trails z3 by 11 pp in W2 and leads by 2.4 pp in the last 3 days). Commit `069f003`; `roostoo-live@competition_z25` active, all other competition units inactive and disabled; swapped while flat.
- Its first decision (13:30Z bar) wanted SOL at 121.75; the cold-start guard suppressed it by design (`#cold-start-chases-the-bar`). The ride state drops entries the book does not hold on the next decision, so no ghost slot; SOL is in its 1 h cooldown. Every unit switch costs the first bar's trigger this way.
- Tested and failed today, do not re-propose without new evidence: sizing by z (`#ride-scaled-entry-outcome`), the 64-coin universe (`#ride-z3-wide-outcome`), take-profits nearer than +5% (`#ride-agile-outcome`).

### Earlier switch at 18:30 IST: `competition_z3` (`#competition-z3-2026-10-04`)
- Operator 18:27 IST: run ride z3 (per-coin 3-sigma trigger) while the market is choppy, switch back to `competition_ride` when it swings. Commit `b037499`; `roostoo-live@competition_z3` active, every other competition unit inactive and disabled. Swapped while flat (100,000 cash, 0 orders). First cycle 13:00Z clean, target empty, all 3 slots free.
- Switch back = the procedure below with `competition_ride` (config, tests and registries already exist; set `BOOKS` and the `tests/test_runner.py` assertion to it). Swap only while flat or accept that the new unit ignores the old unit's positions.

### Earlier switch at 18:11 IST: `competition_ride` (`#competition-ride-2026-10-04`)
- Operator 18:10 IST: "go ahead with ride 5m logic and get in the trade, we will switch dynamically". `config/competition_ride.yaml` = `ride_5m` on the COMP keys with competition_wf's execution/risk blocks. Commit `702f635`, EC2 checked out at it; `roostoo-live@competition_ride` active, `competition_wf` and `competition_split` inactive and disabled (one unit per account). competition_wf was flat (100,000 cash, 0 orders) when stopped.
- First cycle 12:41Z: no faults, 100,000 cash, ride target empty: no coin has a live +2%/15m trigger, and its replay holds nothing, so all 3 slots are free (no ghost slots). It buys on the next fresh trigger. NEAR/PUMP (held by paper `ride_5m`) triggered before the start and are not bought (stale-entry guard unchanged).
- Dynamic switching = same procedure in reverse: `systemctl disable --now roostoo-live@competition_ride`, `systemctl enable --now roostoo-live@<book>`, update `BOOKS` in `deploy/ec2_bootstrap.sh` and the test in `tests/test_runner.py`, commit and push. Switch while flat where possible: a new unit does not inherit the old one's positions. For the split, archive `live/competition_split/sleeves.json` first.
- Status: `deploy/ec2_status.sh` now reports competition_ride first.

## Previous state 2026-10-04 17:55 IST / 12:25Z (history)

### First hour of the competition (opened 17:30 IST / 12:00Z)
- `competition_wf` is live on the COMP account, cycling every 30 s, wallet 100,000, no errors, no freeze, **no orders yet**.
- Cause, not a fault: its style `15m|htf0|vol1.5` (picked 17:00 IST) holds LTC 46% / SOL 34% / XRP 20% in its replay path, entered before the open, so `stale_entry_blocked` refuses them every bar (`#stale-rebuy-2026-10-01`), and the sticky top-3 slots stay full until one exits its channel (close under its 10-bar low): the cold-start ghost-slot issue (open decision 5 of the 10-01 state below).
- Unstuck by any of: a channel exit in LTC/SOL/XRP; the hourly re-pick (next about 18:00 IST) moving to another style (a new style starts clean; the ride style trades from real positions at once); or the operator switching to the split fallback. Changing the guard or slot logic is real-money code and needs a declared change and operator approval.
- Decision point: if still flat around 19:30 IST, the operator decides on the split fallback (procedure below).
- Paper at 17:52 IST: wf_live +5.74%, ride_z3_5m +4.48%, regime_ls_30m +4.01%, ride_5m +2.33%, sleeves_z3_5m +1.51%, split_tilt_5m -0.62%, rehearsal -0.67% (since 10-03 19:52 IST).
- The operator wants every time in IST.

### Competition
- **Trading opens 2026-10-04 12:00Z (20:00 HKT / 17:30 IST), runs 14 days (end about 10-18 12:00Z, confirm with the organisers).** Repo link before 10-14 (`python3 deploy/export_logs.py`, commit `logs/`, tag `submission-final` at the end).
- **The competition account runs `competition_wf` = `wf_live` on the COMP keys** (operator 10-04 11:15Z, `#competition-wf-2026-10-04`): hourly replay of ~30 styles over 3 days, trades the leader, 3.0 pp switch margin, cash allowed, booking ladder on, exit escalation on, 25% drawdown halt, de-risk off (operator will check during the run). Its first pick at 11:30Z was `15m|htf0|vol1.5` (fresh start, no incumbency), while paper `wf_live` holds `resid|1h`.
- The account joined 10-03 22:46Z (wallet 100,000); orders were rejected ("no permission to trade") until the open, nothing filled. `competition_split` ran it 06:06-11:25Z, never traded, now inactive and disabled.
- **Known risks recorded before the switch:** `wf_live`'s selection has not beaten the mean style or the fixed rule forward (picks -5.3% vs -4.6% / -2.4%); its +5.8% paper came from ride trades and downtime luck; it never placed real orders; its config has `short.enabled: true` (short styles can be picked; shorts were a drag in every test and whether the COMP account accepts shorts is untested). No manual stop or override on the competition account (rules); any change is a committed config plus a unit restart.
- **Fallback, staged:** `competition_split` at rule 40 / ride 60 (`#competition-ride-share-2026-10-04`, `#split-tilt-outcome`; 40/60 led 50/50 by 0.04-0.08 pt over 17 live hours). Switch: `systemctl disable --now roostoo-live@competition_wf`, archive `live/competition_split/sleeves.json` if it exists (SleevesBot reads `rule_share` only when it is absent, `#competition-code-review-2026-10-04`), `systemctl enable --now roostoo-live@competition_split`, and change `BOOKS` in `deploy/ec2_bootstrap.sh` back. Never two units on one account.

### Where things run
- **EC2** `i-015fad70d34b0b83d`, checkout `9867b88`. Live: `competition_wf` (COMP), `competition_rehearsal` (TEST keys, 50/50 split, real orders). Paper: `wf_live`, `ride_5m`, `ride_z3_5m`, `sleeves_z3_5m`, `split_tilt_5m` (40/60), `regime_ls_30m`. Status: `deploy/ec2_status.sh`; scripts: `python3 deploy/ssm_shell.py <script FILE>` (piping a heredoc through `/dev/stdin` returns nothing).
- **Mac** paper: `momentum_top3_30m`, `blend_30m_ride`, `resid_30m`, `htf0_30m`, `ride1_5m`, `wide_30m`, `ride1_wide_5m`; desk on 8787 (manual) and 8789 (launchd). **The Mac sleeps on battery and that blinds monitoring** (EC2 bots are unaffected): keep it on mains, `sudo pmset -a disablesleep 1`. AWS SSO expires after some hours: `python3 deploy/aws_login.py` and approve the link within minutes.

### Book snapshot 2026-10-04 11:36Z (since each book's start)
competition_wf 0.00% (100,000 cash, waiting for the open); rehearsal -0.66% since 10-03 14:22Z; split_tilt_5m -0.59%; wf_live +5.81%; ride_z3_5m +4.59% (Sharpe 21); regime_ls_30m +3.59%; ride_5m +2.45%; sleeves_z3_5m +1.55%; Mac: ride1_wide_5m about +7%, htf0_30m about +3%, momentum_top3_30m (the old rule's twin) about +0.3%.

### Done 2026-10-03/04 (all committed, DECISIONS anchors)
Research, all nulls except the tilt: price action (`#price-action-outcome`), regime_ls as comp bot (`#regime-competition-outcome`), stop-and-retune loop (`#adaptive-loop-outcome`), tick capture closed as market making (`#tick-capture-closed`), session timing (`#session-timing-outcome`), R4 split (`#split-r4-outcome`), 40/60 tilt PASS (`#split-tilt-outcome`). Fleet: wf_live moved to EC2, three paper books retired (`#wf-live-to-ec2-2026-10-03`), fleet review (`#fleet-forward-2026-10-03`). Code: clock resync before a stale-ticker freeze (`#clock-resync-2026-10-03`), `bot/sleeves.cap_entries` (tested, unused). Switches: `#competition-switch-2026-10-04`, `#competition-wf-2026-10-04`.

### Open items
1. First hours of the competition: watch `competition_wf` orders, fills, faults and its style picks; if it faults, trades shorts that error, or bleeds, the operator decides on the split fallback.
2. Checkpoint 10-05: `ride_z3_5m` / `sleeves_z3_5m` and `regime_ls_30m` against their declared rules; `split_tilt_5m` 3-day stop rule.
3. Mac paper books still run pre-fix code until their next restart (`./run_bots.sh restart`, operator).
4. End-of-run de-risk: operator decision during the competition (`derisk_start_utc` is 12-31, i.e. off).

### Lessons (do not repeat)
- Only the 8787 desk pulls EC2 (`bot/dashboard.py` starts `ec2_feed` on that port alone); 8789 never shows EC2 books. On 10-04 the 8787 feed thread stalled for 7 h after the AWS token expired (age 26004 s, no error shown) and the process still ran 11:47 IST code: after `deploy/aws_login.py`, restart it (`python3 -m bot.dashboard`) and check `/api/desk` `ec2.fetched_age_s` < 400. Since 20:55 IST each pull runs in a child process (`ec2_feed.fetch_isolated`), because the in-process session stayed "expired" after a renewed login. The `aws` CLI on this Mac is broken (Homebrew Python 3.14 pyexpat mismatch); test AWS with `python3 -c 'from bot.ec2_session import run_script; print(run_script("echo hi",60))'`, not `aws sts`.
- Guard every commit on the pytest result (`case` on the summary line); a `| tail -1 &&` chain committed failing tests on 10-04.
- A sleeves ledger records entries even when the venue rejects the order (pre-open); reset it before the first real trading bar.
- Keep the Mac on mains with sleep disabled through any decision window; scheduled reminders live only in an awake session.

## Previous state 2026-10-03 06:30Z (history)

### Deadlines and blockers
- **Competition starts 2026-10-03 12:00Z (20:00 HKT / 17:30 IST)**, runs to 10-17; repo link before 10-14 (`python3 deploy/export_logs.py`, commit `logs/`, tag `submission-final` at the end).
- `competition` (COMP keys) is the **plain 30m rule** and waits for the account; it starts trading by itself on the first good wallet read.
- **The split bot is staged, not running:** `config/competition_split.yaml` = the rehearsed 50/50 rule + ride sleeves on the COMP keys (`#competition-split-staged-2026-10-03`). Switch (operator only, the session permission check blocks the agent): on EC2 `systemctl disable --now roostoo-live@competition` then `systemctl enable --now roostoo-live@competition_split`, then put it in `BOOKS` of `deploy/ec2_bootstrap.sh` and the desk/validation registries. Never both units at once. Its rule half reads `config/competition.yaml`, which must stay the plain rule.
- Evidence for the switch: stage-3 gate clean at 05:53Z (no failed orders, no faults, rehearsal -1.90% vs paper `sleeves_5m` -2.02% since 10-02 16:00Z); stress test Aug-Oct (`#stress-split-vs-rule-2026-10-03`): split +85.5% / max DD -14.8% / Calmar 5.76 vs plain rule +58.6% / -24.1% / 2.43, better under doubled fees and in the worst 3- and 14-day windows.

### Where things run
- **EC2** `i-015fad70d34b0b83d`, all units start `bot.runner` (class from config). Live: `roostoo-live@competition` (plain rule, waiting), `roostoo-live@competition_rehearsal` (50/50 split, TEST keys). Paper: `ride_5m`, `sleeves_5m`, `sleeves_ivol_5m`, `ride_z3_5m`, `sleeves_z3_5m`, `uni_donchian_15m`, `regime_ls_30m`. Fleet table and registration steps: `BOTS.md`.
- **Mac** paper (sleeps unless `sudo pmset -a disablesleep 1` and mains power; it slept most of the night of 10-02): `momentum_top3_30m`, `wf_live`, `blend_30m_ride`, `resid_30m`, `htf0_30m`, `ride1_5m`, `wide_30m`, `ride1_wide_5m`.
- **AWS access**: `python3 deploy/aws_login.py` (browser device approval; the token expired overnight and blocked EC2 monitoring until the operator re-ran it at ~05:50Z). Status: `deploy/ec2_status.sh`; scripts on EC2: `python3 deploy/ssm_shell.py <script>`.

### Book snapshot 2026-10-03 05:53Z (EC2, since each book's start)
uni_donchian_15m +2.77% (UNI), regime_ls_30m +3.79% (shorts closed, TRX), ride_z3_5m -0.14%, sleeves_ivol_5m -0.25%, sleeves_z3_5m -0.28%, ride_5m -0.55% since its EC2 restart, sleeves_5m -2.00%, competition_rehearsal -2.61% since 10-02 14:22Z (52,729 -> 51,729 since its split switch). Overnight the pool fell 1.4% with 3 of 25 coins up (UNI, WLD, TRUMP); the only ride trigger was a PUMP bounce that then fell 5.5%.

### Done 2026-10-02/03 (all committed, DECISIONS anchors)
Stage 2 split on the rehearsal (`#sleeves-rehearsal-2026-10-02`); research nulls: ride exits, bStocks, coin EDA, inverse-vol sizing, ride trigger recheck, dynamic triggers (per-coin 3-sigma best risk-adjusted, paper as `ride_z3_5m`), single coin (UNI, failed validation, paper as `uni_donchian_15m`), regime blocks (trend to chop at 09-23); `regime_ls_30m` moved to EC2; Swolecharts/free-data review (no integration; unlock data now paid); dead-code cleanup (`#dead-code-cleanup-2026-10-02`: retired runtime deleted, 113 research modules in `archive/`, run as `python3 -m archive.gates.<name>`); desk fixes (scrolling, notes vs errors); stress test; split bot staged.

### Open items
1. Operator: switch `competition` to `competition_split` (above), ideally before 12:00Z.
2. EC2-code fixes left for after the start: `bot.runner` does not know the `hedge_explorer` blend config; `bot/regime.py` reads the dead scanner state for an unused regime gate.
3. Checkpoint 10-05: `sleeves_ivol_5m`, `ride_z3_5m`/`sleeves_z3_5m`, `uni_donchian_15m`, `regime_ls_30m` against their declared falsification rules.
4. DONE 2026-10-03 ~07:00Z: price action and technical factors (`#price-action-outcome`): no tradeable edge; ten rank ICs pass statistically (short-horizon reversal, stretched-volatile coins lag) but are 1-3 bps/h against 10 bps fees; no event, session, BTC-lead or continuation feature holds in both windows. The +5% continuation rate is falling (52.7% W1, 39.6% W2, 28.6% last 3 days, break-even 37.5%), which supports the ride keeping its +5% cap. Rerun: `python3 -m archive.gates.price_action` (`--refresh` to refetch bars).

### Lessons (do not repeat)
- The session's permission check blocks changes to the competition config; plan operator-run steps for anything touching the COMP account.
- Keep the Mac on mains with sleep disabled, and re-run `aws_login.py` before it expires, or both the paper fleet and EC2 monitoring go dark.
- Never blend sleeves inside one book's weights; use `bot/sleeves.py`. In chop nothing beats holding.

## Previous state 2026-10-02 16:10Z (history)


### Deadlines and blockers
- **Competition starts 2026-10-03 12:00Z** (20:00 HKT / 17:30 IST), per the operator 2026-10-02; this settles the FAQ (09-30) vs slides (10-04) conflict. Account still NOT ACTIVE until then ("not yet a member", polled every 30 s); the bot starts trading by itself on the first good wallet read. If it is still inactive at 12:30Z on 10-03, the operator messages the organisers (team Hackathon-Team118).
- **Repo link due before 2026-10-14**; before submitting run `python3 deploy/export_logs.py` and commit `logs/`; at the end tag `submission-final`. Finalist deck by 10-27.
- Competition account = 100k per slides (TEST account 50k); sizing is fractional so it does not matter (`#submission-deliverables-2026-10-02`).

### Where things run
- **EC2** `i-015fad70d34b0b83d` (ap-southeast-2, t3.medium, unlimited credits, ~3% CPU), repo at /opt/roostoo-hackathon, commit 1b8018c+:
  - `roostoo-live@competition` (COMP keys, real orders, waiting, the plain 30m rule via ContendersBot) and `roostoo-live@competition_rehearsal` (TEST keys, real orders; **since 16:00Z the 50/50 sleeves**, sold LTC/TRUMP on its first decision, equity 52,730). Both have **exit escalation** on (`#exit-escalation-2026-10-02`). All EC2 units start `bot.runner`, which picks the class from the config (`#sleeves-rehearsal-2026-10-02`).
  - `roostoo-paper@regime_ls_30m` (paper, moved from the Mac 2026-10-02 18:59Z with its state: open NEAR/PUMP shorts from the 18:00Z DOWN flip, equity ~105.2k; `#regime-ls-to-ec2-2026-10-02`). Mac copy archived in `live/_archive/moved-to-ec2-20261002T1905Z/`.
  - `roostoo-paper@uni_donchian_15m` (paper since 2026-10-02 17:50Z, UNI only, Donchian 20/10 on 15m; FAILED its validation rule, strategy pick post-hoc, `#single-coin-outcome`; stop after 3 days if it trails buy-and-hold UNI or loses).
  - `roostoo-paper@ride_z3_5m` and `roostoo-paper@sleeves_z3_5m` (paper since 2026-10-02 17:40Z, the ride on the per-coin 3-sigma trigger, alone and inside the 50/50 split, `#ride-z3-declaration`): **compare at the 10-03 checkpoint** against ride_5m / sleeves_5m / rehearsal, forward hours first, before the 11:00Z stage-3 call.
  - `roostoo-paper@sleeves_ivol_5m` (paper since 2026-10-02 17:15Z, sleeves with inverse-vol entry sizing; replay says it de-levers and fails its return condition, `#sleeves-ivol-declaration`; judge 10-05).
  - `roostoo-paper@ride_5m` (paper, momentum ride, +4.9%) and `roostoo-paper@sleeves_5m` (paper, **50/50 rule + ride with separate ledgers**, started 14:45Z, first trade TRUMP). Paper unit runs `bot.paper_main`.
- **Mac** (paper, sleeps on battery): wf_live, momentum_top3_30m (control), ride1_5m, blend_30m_ride, regime_ls_30m, resid_30m, htf0_30m, wide_30m, ride1_wide_5m. `run/LIVE_HOST_EC2` makes `./run_bots.sh live` refuse on the Mac (never two hosts on one account).
- **AWS access**: `python3 deploy/aws_login.py` (browser device sign-in, botocore refreshes keys until the Identity Center session ends). Commands on EC2 go through `python3 deploy/ssm_shell.py <script>` (SendCommand is denied). Status: `deploy/ec2_status.sh`. Redeploy: run `deploy/ec2_bootstrap.sh` on the instance (pulls main, restarts live + paper units; never restart the competition book except for a committed change).
- **Desk** http://127.0.0.1:8787/: "Live on Roostoo · EC2" band (pulls EC2 every 3 min), paper fleet below, live Binance price card.

### Done 2026-10-02 (all committed, DECISIONS anchors)
Ride ghost-slot fix (`#ride-ghost-slots-2026-10-01`); wide-pool paper books (`#wide-pool-live-2026-10-01`, nothing gained so far); EC2 cutover (`#ec2-cutover-2026-10-02`); COMP key used only by the bot (`#comp-key-bot-only-2026-10-02`); submission deliverables: MIT LICENSE, Dockerfile (835 MB), `logs/`, README sections (`#submission-deliverables-2026-10-02`); exit escalation; ride_5m on EC2 (`#ec2-paper-ride-2026-10-02`); blend test (`#blend-checkpoint-outcome`: one-book blend fails, ride beats rule on the live window); sleeves (`#sleeves-declaration`: ledger replay +23.7% vs rule +16.3%, max DD -10.9% vs -15.2%).

### Operator decision taken, staged rollout in progress
50/50 sleeves (rule + ride, separate ledgers) for the competition book. Stage 1 done (paper `sleeves_5m` on EC2). **Stage 2 done 2026-10-02 16:00Z** (commit 72f4534, `#sleeves-rehearsal-2026-10-02`): rehearsal = `sleeves_5m` on the TEST account. Stage 3 gate: by 10-03 11:00Z no failed rehearsal order, no faulted cycle, rehearsal within 1 point of `sleeves_5m` since the switch. Stage 3 itself = copy the sleeves blocks into `config/competition.yaml` (keyset comp), commit, redeploy; `tests/test_runner.py` asserts competition is ContendersBot, update it with the switch. **Stage 3:** same for `competition`, deployed before **2026-10-03 ~11:00Z** (an hour before start, so the first wallet read already runs the sleeves runner), only with operator OK and stages 1-2 clean; otherwise the competition book starts on the rule as today. Stop rule: sleeves_5m trailing the rehearsal by >2 pts after 3 days.

### Checkpoint 2026-10-03 (must finish before 11:00Z, ahead of the 12:00Z start)
Compare on EC2 at equal uptime, forward only: competition_rehearsal (rule) vs ride_5m (ride) vs sleeves_5m (split). Retire wide_30m / ride1_wide_5m on 10-08 if still below controls. Target lock (Screen 3) is an operator decision around 10-12.

### Research 2026-10-02 evening (all null, nothing live changed)
Ride exits (`#ride-exits-outcome`), bStocks in the pool (`#bstocks-pool-outcome`), coin EDA (`#coin-eda-outcome`: no return edge; vol forecastable and unrewarded pool-wide), inverse-vol sizing replay (`#sleeves-ivol-declaration`), ride trigger recheck and dynamic triggers (`#ride-threshold-recheck-outcome`, `#ride-dynamic-trigger-outcome`: per-coin 3-sigma best risk-adjusted), regime blocks (`#regime-blocks-2026-10-02`: trend to chop at 09-23). Operator: judge on the present market, not history.

### Competition split bot staged 2026-10-03 06:20Z (`#competition-split-staged-2026-10-03`)
`config/competition_split.yaml` = the rehearsed 50/50 split on the COMP keys, NOT running (one account, one unit). The stage-3 in-place switch was blocked by the session permission check; `competition` starts at 12:00Z on the plain rule unless the operator runs the switch in that anchor. Stage-3 gate was clean at 05:53Z; stress test favours the split (`#stress-split-vs-rule-2026-10-03`).

### Cleanup 2026-10-02 ~19:30Z (`#dead-code-cleanup-2026-10-02`)
Retired runtime deleted, 113 finished research modules moved to `archive/` (`python3 -m archive.gates.<name>`), registries pruned to the 17 running books, `BOTS.md` and `deploy/README.md` rewritten. EC2 code untouched. Two EC2-code findings to fix with the operator after the start: `bot.runner` would run `blend_30m_ride` with the wrong class if it ever moved to EC2; `bot/regime.py` reads the dead scanner state for an unused regime gate.

### Lessons (do not repeat)
- Never blend sleeves inside one book's weights (they interfere); use `bot/sleeves.py`.
- In chop nothing beats holding; shorts, faster clocks, textbook technicals, wide pool all failed.
- Check `&&` chains: a passing `tail` hid failing tests once; use the `case` guard on pytest output before committing.

## Previous state 2026-10-01 14:00Z (history)

### Deadlines and blockers
- **Sleeves 2026-10-02 14:45Z (`#sleeves-declaration`, commit 1b8018c):** operator chose a 50/50 split of the competition rule and the momentum ride with separate ledgers. Stage 1 done: `sleeves_5m` runs on EC2 as paper (`roostoo-paper@sleeves_5m`, via `bot.paper_main`). Stage 2 (next): a sleeves config for `competition_rehearsal` (TEST keys, real orders) - the live unit must run `bot.sleeves_run`, and its first decision sells the rehearsal's current rule holdings that the sleeves do not own. Stage 3: the same for `competition` before 2026-10-04, only if stages 1-2 run clean. Stop rule: `sleeves_5m` trailing `competition_rehearsal` by more than 2 points after 3 days.
- **EC2 deploy 2026-10-02 13:46Z (commit bbbcb1b):** exit escalation live on `competition` and `competition_rehearsal`; `ride_5m` moved to EC2 as `roostoo-paper@ride_5m` (paper, keyless, `#ec2-paper-ride-2026-10-02`) and removed from the Mac's `CONFIGS`. Instance credit mode is `unlimited`; load about 3% CPU, 3 GB memory free. AWS access is browser sign-in now: `python3 deploy/aws_login.py`, approve, and botocore refreshes the keys until the Identity Center session ends.
- **LIVE BOOKS RUN ON EC2 since 2026-10-02 12:36Z** (`#ec2-cutover-2026-10-02`): instance `i-015fad70d34b0b83d`, ap-southeast-2, systemd units `roostoo-live@competition` and `roostoo-live@competition_rehearsal` under /opt/roostoo-hackathon. Check them with `python3 deploy/ssm_shell.py <script>` (boto3 + `hackathon` AWS profile; SSO session credentials expire, re-paste from the portal). The Mac refuses `./run_bots.sh live` while `run/LIVE_HOST_EC2` exists. Paper books still run on the Mac. To update the instance: re-run the bootstrap (it pulls `main` and restarts the units).
- **The first-trade deadline (2026-10-01 12:00 UTC) has passed with the competition account STILL NOT ACTIVE** (`/v3/balance`: "not yet a member of this competition", last seen 13:53Z; waiting since 2026-09-30 14:22Z). The `competition` book polls every 30 s and starts on the first good wallet read. The operator must message the organisers.
- **Uptime.** The Mac slept on battery 2026-09-30 ~20:40Z to 10-01 ~05:15Z and dropped to battery several times after; overnight sleep cost the 30m rule about 1 point and the fast books 2-3 (`DECISIONS.md#offline-replay-2026-10-01`). Keep it on mains with `sudo pmset -a disablesleep 1`, or deploy to AWS with `deploy/ec2_bootstrap.sh` when access works, then `./run_bots.sh livestop` on the Mac. NEVER run `competition` on two hosts.
- No manual stop, override or trade on the competition account; every live change committed and pushed (public repo, `main`).

### What is running (`./run_bots.sh status`; desk http://127.0.0.1:8787/)
| book | what | since |
|---|---|---|
| `competition` | REAL orders, COMP keys, the 30m `momentum_top3_30m` rule unchanged; waiting for the account | restarted 07:42Z on the fault fixes |
| `competition_rehearsal` | same rule, REAL orders on the TEST account | 07:42Z (flat after the 07:06Z cancel-bug liquidation) |
| `momentum_top3_30m` | paper twin and control of the competition rule | 17:34Z 09-30 |
| `wf_live` | dynamic bot (paper): 29 styles + cash, hourly 3-day leader, decision point OFF, switch margin 3.0 pp | 08:33Z |
| `ride_5m` | paper: momentum ride alone (+2%/15m jump, hold for +5% up to 24 h) | 08:28Z |
| `blend_30m_ride` | paper: fixed 50/50 competition rule + ride | 08:28Z |
| `regime_ls_30m` | paper: regime switch, shorts and no new longs only in a confirmed DOWN regime (`signals/regime_ls.py`); history says DOWN states rebound (`#technicals-survey-2026-10-01`) | 08:28Z |
| `resid_30m` | paper: competition rule on market-neutral prices, 4h filter off | 12:15Z |
| `htf0_30m` | paper: competition rule with the 4h filter off | 12:15Z |
| `ride1_5m` | paper: momentum ride with a 1% trigger (control `ride_5m`) | 12:17Z |
| `wide_30m` | paper: competition rule on the whole Roostoo pool (~64 coins), control `momentum_top3_30m` (`#wide-pool-live-2026-10-01`) | 19:24Z |
| `ride1_wide_5m` | paper: 1% ride on the whole pool, control `ride1_5m` | 19:24Z |
Retired today: `momentum_top3_15m`, `momentum_top3_5m` (`#retired-2026-10-01`; configs stay, wf_live uses them).

### Fixed today (all committed, all books restarted on them)
- Stale path entries are dropped on every decision, not only after a start or catch-up (`#stale-rebuy-2026-10-01`): the one-bar-late rebuy cost -5.4k on paper and would have been the competition account's first trade.
- Roostoo cancel sends order_id or pair, never both (`#cancel-both-args-2026-10-01`): the venue rejected every stale-order cancel, which tripped the error-rate halt and liquidated the rehearsal at 07:06Z.
- Ride books ran on ghost slots (`#ride-ghost-slots-2026-10-01`, commit c6804a9): the replayed ride path filled its 3 slots with entries the book never took, so `ride_5m`, `ride1_5m`, `blend_30m_ride` and `wf_live` averaged 2-17% gross. They now decide from their real positions (`burst_rider.live_step`, state in `live/<book>/ride_state.json`). Live since the restart of those four books at 19:23Z; the blend's ride sleeve was not seeded, so it sold its open PUMP on restart.
- Fault handling (`#live-faults-2026-10-01`): error rate over the last 40 venue calls; venue/ticker/mirror faults FREEZE the book instead of liquidating (only the 25% drawdown kill liquidates); mirror checks only held coins; last-known marks for unquoted coins; held coins survive a universe refresh; no resubmit after a failed pending query; an ambiguous submission reconciles every cycle and the process restarts after 10 failures.

### Research today (all in DECISIONS.md, all nulls recorded)
- Red-team harness `gates/stress.py` and three agent reports in `results/stress/` (`#stress-harness-declaration`): the 30m edge is thin and depends on maker fills and a few big trends; the 15m rule has no edge after costs.
- Failed declared tests: crash-regime shorts (`#crash-shorts-outcome`), 1h clock for the competition book (better on history, -12.8% vs +9.9% on the unseen last 12 days, `#competition-1h-outcome`), strength/volatility sizing tilts (`#strength-tilt-outcome`), follow-the-leader style switching in the current market (`#adaptive-recent-2026-10-01`).
- Afternoon, all recorded: residual long/short spread FAIL (`#residual-spread-outcome`); replay decomposition, all 13-19% styles earned in the trending 09-19..25 week (`#replay-decomposition-2026-10-01`); minute-level scan, moves revert 2-8 bps below the 10 bps fee (`#micro-scan-2026-10-01`); technicals survey, no textbook rule beats holding the pool, all negative on 2025-26 history (`#technicals-survey-2026-10-01`); sizing, 0.33 cap and vol targeting better on history but trail in the rally, none passes (`#sizing-competition-outcome`); ride trigger 1% vs 2% (`#ride-trigger-2026-10-01`).
- Descriptive: overnight minute patterns (`#overnight-patterns-2026-10-01`), best-signal profile (`#best-signals-2026-10-01`), fill quality (all maker, buys under 10 s, one slow exit in six, `#fill-quality-2026-10-01`). HRT AI Labs post assessed: ignore (execution RL, no disclosed edge).

### Open operator decisions
1. Exit escalation: DONE 2026-10-02 (commit e41b5b2, `#exit-escalation-2026-10-02`); live on EC2 only after the next bootstrap run (needs fresh AWS session credentials).
2. Drawdown halt stays permanent within a process (red-team item 7).
3. Sizing: keep the 0.5 cap (raw return, Screen 2) or move to the 0.33 cap (better on history and Screen 3, about -0.85 pt in the rally window); recommended after qualifying.
4. Wiring the regime switch into the competition book: only if `regime_ls_30m` beats `momentum_top3_30m` with profitable shorts over its 7-day paper run.
5. Contenders ghost slots: after a cold start the 30m rule's sticky slots keep path entries the book refused until their channel exit (rehearsal: 9 of 23 decisions today; `resid_30m` 30 of 30). The competition account will cold-start on activation. Fixing it touches real-money code.

### Next steps
1. Account activation; first trades: check with `python3 -m gates.fill_quality --book competition` and the stale-entry journal events.
2. Checkpoint 2026-10-03: compare competition, rehearsal, momentum_top3_30m, regime_ls_30m, ride_5m, ride1_5m, blend_30m_ride, resid_30m, htf0_30m, wf_live on forward results only; switch the competition book only with the operator.
3. 2026-10-08: apply the 7-day stop rules in each paper config.
Tools added today: `gates.stress`, `gates.stress_competition`, `gates.stress_m15`, `gates.stress_wf`, `gates.missed_replay`, `gates.overnight_patterns`, `gates.crash_shorts`, `gates.competition_1h`, `gates.best_signals`, `gates.strength_tilt`, `gates.fill_quality`, `gates.adaptive_recent`, `gates.residual_spread`, `gates.micro_scan`, `gates.technicals_survey`, `gates.sizing_competition`. Skills: `roostoo-live-report`, `roostoo-incident`, `roostoo-ops`, `roostoo-research` (start sessions in the repo so they load).

## State at 2026-10-01 01:10 IST / 2026-09-30 19:40Z (history)

### Deadlines and blockers
- **Competition main round started 2026-09-30; first trade due 2026-10-01 12:00 UTC** (official FAQ). No manual stop, override or trade on the competition account; every live change must be committed and pushed (public repo https://github.com/kadoo69/roostoo-hackathon, work on `main`).
- **Competition account NOT ACTIVE**: `/v3/balance` with the COMP key answers "not yet a member of this competition" (last seen 19:34Z). The `competition` book polls every 30 s and starts by itself on the first good wallet read. If still inactive near the deadline, the operator messages the organisers.
- **AWS access expected 2026-10-01** (portal https://d-906625dad1.awsapps.com/start said the operator's college email was not verified). Deploy with `deploy/ec2_bootstrap.sh` (tested end to end in an Amazon Linux 2023 container; paste command is in README.md), then `./run_bots.sh livestop` on the Mac. NEVER run the competition book on two hosts.
- Until then the Mac hosts everything. It was ON BATTERY at 01:00 IST: keep it on mains; `sudo pmset -a disablesleep 1` keeps it awake with the lid closed. Claude Code cloud sessions are not a bot host (time limits, processes not persisted).

### What is running (`./run_bots.sh status`; desk http://127.0.0.1:8787/)
| book | what | since |
|---|---|---|
| `competition` | REAL orders, COMP keys, `config/competition.yaml` = the `momentum_top3_30m` rule (30m breakout, 4h + 1.5x volume confirmations, top 3 by momentum, 0.5 cap, 3%/15% ladder), target lock OFF, derisk ramp moved past the window; waiting for account | 2026-09-30 14:22Z |
| `competition_rehearsal` | same rule, REAL orders on the Roostoo TEST account (50k USD) | 14:22Z |
| `wf_live` | THE dynamic bot (paper): every hour scores 29 styles + cash on the last 3 days (long breakouts 5m-4h with filters, shorts 15m/1h, momentum ride +2%->+5%, order-flow, open-interest, residual, one-coin-per-block) and trades the leader; reads the decision point | restarted 19:39Z |
| `momentum_top3_5m/15m/30m` | fixed-clock paper baselines; 5m exit changed to the 36-bar (3 h) low | reset 17:34Z |
Start/stop: `./run_bots.sh start|stop` (paper set), `live|livestop` (competition + rehearsal, ROOSTOO_DRY_RUN=0), `progress|progressstop` (30-minute review loop), `fleet` (old 18-book paper fleet, stopped). Dashboards are `python3 -m bot.dashboard` (8787) and `--port 8789`.

### Tools
`python3 -m gates.preflight` (read-only checks), `gates.progress` (per-book trades, fills, booked skims, Sharpe/Sortino/R-DD, uptime; also every 30 min to `results/progress/`), `gates.wf_report` (dynamic bot's forward scorecard), `gates.signal_scan` (breakouts and what blocks them, per clock), `gates.levels` (chart levels), `gates.market_structure` (PCA: factor share, effective bets, blocks, residual leaders), `gates.decision_point` (merge research-agent JSONs into `results/decision/latest.json`), `gates.roostoo_smoke` (order lifecycle on the TEST account; places small orders).

### Decisions and findings of 2026-09-30 (all in DECISIONS.md)
- Live API differs from the README; five fixes (`#roostoo-keys-2026-09-30`). Fees measured: 0.10% taker, 0.05% maker; fills instant.
- Competition book choice (`#competition-book-2026-09-30`); declared tests all NOT adopted: slower exit (`#competition-exit-outcome`), adaptive clock (`#adaptive-clock-outcome`, near-miss), burst drivers and exits (`#burst-drivers-outcome`). Best-trades study: top 5% of entries = 71% of gains (`#best-trades-study-2026-09-30`).
- Market: chop inside a 14-day rally; PC1 ~60% of variance, ~2.7 effective bets of 25 (`#market-structure-2026-10-01`).
- Decision point from four Sonnet research agents (`#decision-point-outcome-2026-10-01`): chop; allowed `1h|htf0|vol0`, `30m|htf0|vol0`, `blocks|1h`, `resid|30m`, cash; gross 0.9; shorts, order-flow and open-interest styles off. EXPIRES 2026-10-01 07:29Z; after that `wf_live` uses its full menu until the agents are re-run and `python3 -m gates.decision_point` merged again.
- Bug fixed at 19:40Z: a restart after a rule change bought stale path entries (`#restart-stale-entry-2026-10-01`).

### Open operator decisions
1. Target lock on the competition book: risk agent recommends ON; operator chose OFF ("all in").
2. Re-run the research agents every ~12 h to refresh the decision point?
3. Feed the decision point into the competition book (only after its paper effect is seen)?
4. The 30-minute chat reports and one-shot checks were session-only cron jobs; they die with the session. The repo's own 30-minute review loop keeps writing `results/progress/`.

### Next steps
1. When AWS works: bootstrap, verify with `gates.preflight`, `./run_bots.sh livestop` on the Mac.
2. Watch the competition account; the first trade happens on the first qualifying breakout after activation (the first bar after a start is suppressed by design).
3. Checkpoint 2026-10-03: compare `competition` (once live), `wf_live` and the baselines on forward-only results (return and drawdown) before any change to the competition book; every change committed.

## Session summary 2026-09-25..27 (history)

**Fleet (19 books + testnet):** core 4h `donchian_4h`, `momentum_top3_full`, `momentum_top3_lock`; short-term `momentum_top3_30m/15m/5m`, `momentum_top3_30m_allcash`, `momentum_top3_1h_allcash`, `momentum_top3_1h_long` (other session), `accel_15m`; burst `burst_5m`, `burst_15m`; A/B arms `burst_strong_15m`, `momentum_top3_15m_eq`, `momentum_top3_15m_hold3h`, `momentum_top3_5m_hold2h`, `momentum_top3_15m_slowexit`; shorts `short_accel_15m`, `short_pullback_15m`. All short-term longs: shorts off, target lock off, ladder on. A/B stop rules fall due 2026-10-10/11.
**Retired:** `accel_5m`, `momentum_top3_1h`, `momentum_top3_15m_allcash`, `momentum_top3_5m_allcash`, `momentum_top3_30m_wide`, `momentum_top3_15m_hold12h` (data under `live/_archive/`).
**Live P&L 2026-09-27 06:10Z:** fleet +74.1k net = +46.3k realised + 27.9k open; best `momentum_top3_30m` +15.0%; ~20.6k of the open gain is one coin (NEAR, held by 12 books).
**Robustness added:** catch-up entry guard + live min hold (`bot/entry_guard.py`), stale-cycle guard (sleep detection), parallel bar download (7-18 s -> 1-2 s), bar-close aligned loop (act 5-13 s after a close), cycle watchdog (frozen worker exits, supervisor respawns), Binance 418/429 guard (`bot.feed.binance_get`; an IP ban happened 2026-09-27 05:05Z when heavy analysis ran beside the fleet: run scans one at a time, never at a bar close), executor lets a held short close when shorts are off. `gates.live_validation` all PASS; `gates.live_audit` 0 parity mismatches.
**Key findings (DECISIONS anchors):** uptime is the #1 leak (overnight offline 9.0 of 9.1 h; sleep caused 57% of vanished open gains) `#unrealised-giveback-2026-09-27`; fast books detect rallies but keep ~0%, slow books keep 25-64% of the rallies they catch `#rally-capture-score-2026-09-27`; no take-profit beats current exits, fast-book edge appears after 2-3 h holds `#live-hold-time-2026-09-26`; signal hit rate is below 50%, profit is payoff asymmetry, momentum IC among candidates is negative `#signal-quality-2026-09-26`; whole Roostoo pool trades worse `#full-roostoo-pool-live-replay-2026-09-26`; long-only passes only at 1h, clock ensemble fails `#lowtf-long-only-clocks-outcome`, `#lowtf-clock-ensemble-outcome`.
**Tools:** desk dashboard at `/` (old at `/full`), `python3 -m gates.path_forensics`, `gates.signal_quality`, `gates.rally_capture`, `gates.live_audit`, `gates.live_validation`, `gates.fleet_review`; strategy docs `docs/strategies/` (zip on Desktop).
**Next:** keep the Mac awake (plug in; `sudo pmset -a disablesleep 1`) or move to EC2 (`deploy/README.md`); after 3-5 days of clean uptime, fold A/B winners into the core books as one declared change; decide the competition book (`momentum_top3_30m` candidate; lock yes/no) by 2026-10-03; get Roostoo keys and measure real fills; build cockpit, watchdog alerts and pre-flight gate (ideas in this session). Nothing from this session is committed.

## Fleet 2026-09-26 16:27Z (history)

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

## Fleet review 2026-09-26 ~09:40Z (history)

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
