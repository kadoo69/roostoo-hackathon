---
name: roostoo-live-report
description: Produce the 30-minute Roostoo live report - per-book table since each book's latest start, dynamic-bot pick and scorecard, market structure, competition account status and breakage (bots not cycling, halts, freezes, faults, fills, Mac on battery). Use whenever asked for the live report, a status check, or "how are the bots doing".
---

# 30-minute live report

Run from the repo root. Report ONLY results since each book's latest start; never pre-reset numbers.

## Collect (one Bash call, timeout 250 s)

    date -u; pmset -g batt | tail -1
    ./run_bots.sh status | grep -c RUNNING
    tail -1 live/competition/waiting-$(date -u +%F).jsonl      # inactive account = wallet_unavailable
    ls live/competition/ | grep -c cycles                      # >0 means the competition book has traded
    timeout 150 python3 -m gates.progress | grep -E "^(momentum|competition|wf_live|ride|blend|regime)"
    timeout 60 python3 -m gates.wf_report | grep -E '"periods"|pick_beat|mean_variant'

Then read with Python: `live/wf_live/adaptive.json` (clock, at, top scores), `results/market_structure.json` (`pc_share[0]`, `effective_bets`, `coins` sorted by `resid_24h_pct`), and for every running book the last row of `live/<book>/cycles-<date>.jsonl` (`ts_utc`, `halt`, `freeze`, `breaches`, `positions`) and the last row of `errors-<date>.jsonl` WITH its `ts_utc`.
For `regime_ls_30m` also report the last `"regime"` in its signals journal.

## Output

One table: book, return, orders, fill, closed, win, booked, holdings, up 24h, faults (Sharpe/Sortino/R-DD once `gates.progress` prints them).
Then 3-5 lines: what changed since the last report, dynamic-bot pick and scorecard, market structure, competition account status with time left to any deadline, breakage.
Lead with breakage if there is any (battery, halted or frozen book, stale cycles).

## Traps (each happened)

- An error row is only a fault if its `ts_utc` is recent; overnight sleep leaves old `cycle_error` and `data_incomplete` rows that are not news.
- `gates.progress` prints an empty table while the Mac sleeps; then report last-cycle times per book instead, never stale numbers as current.
- `pmset -g batt` can say "charging" with `ExternalConnected = No` moments later; check `ioreg -rn AppleSmartBattery | grep ExternalConnected` when in doubt.
- `halt` liquidates (drawdown only); `freeze` holds (venue, ticker or mirror faults, `DECISIONS.md#live-faults-2026-10-01`). A halted live book stays halted until restarted.
- The rehearsal's flat result after 2026-10-01 07:06Z came from a bug liquidation (`#cancel-both-args-2026-10-01`); its twin `momentum_top3_30m` is the honest rule P&L.
- Retired books (`momentum_top3_5m`, `_15m`) live in `live/_archive/retired-2026-10-01/`; do not report them.
- Fix anything clearly broken and say so; changes to real-money execution need the operator (see `roostoo-incident`).
