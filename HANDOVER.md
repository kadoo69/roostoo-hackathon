# Handover

Current state only. The full history of sessions to 2026-09-23 is archived at `docs/archive/HANDOVER_2026-09-23.md`; older section references in code and configs point there.

## State at 2026-09-23

- **Fleet**: 16 books, reset to 100,000 together at 2026-09-22T20:48Z (earlier state in `live/_archive/`). Fifteen are Roostoo paper books in dry run, one places real orders on Binance testnet. `BOTS.md` lists them.
- **Keep the Mac awake and on mains power** (`./run_bots.sh awake`). Before the reset the fleet was offline 55% of the time because the laptop slept. EC2 (`deploy/README.md`) is the durable fix.
- **Live validation passes** on every book: `python3 -m gates.live_validation`.
- **Research is saturated.** 1,007 configurations tried; the latest two sweeps (`#competition-wf-outcome`, `#literature-edges-outcome`) found one pass, the target lock, and no new signal.
- **Rehearsal running**: `momentum_top3_lock` from 2026-09-23T08:00Z, compared with `momentum_top3_full` from the same moment.

## Before 2026-10-04, in order

1. Send `ORGANISER_QUESTIONS.md`: commission, 50k vs 100k, the Screen 2 cut and field size, leaderboard visibility.
2. Get Roostoo keys, then measure: one real fill (commission), fill rate of passive orders on one-tick names (PEPE and friends), rotation underweighting when sell cash arrives on fill.
3. Decide the competition book on 2026-10-03 from the backtests plus the forward week: `momentum_top3_full` with or without the target lock, or `donchian_4h`.
4. Set the competition window in the chosen config's `target_lock` block if the lock is adopted, and point the book at Roostoo with `ROOSTOO_DRY_RUN=0`.
5. Restart the whole stack together, never one book mid-bar.

## Open defects and risks

- On a real venue a sell rests until it fills, so a rotation buys less of the new name, and booking never tops it up. Unmeasurable until keys arrive. `#lowtf-paper-bots`.
- An unfilled passive entry is cancelled after 15 minutes and not retried until the next bar close. `#live-validation-2026-09-23`.
