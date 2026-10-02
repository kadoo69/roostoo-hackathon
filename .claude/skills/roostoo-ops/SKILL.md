---
name: roostoo-ops
description: Operate the Roostoo bot fleet - start/stop/restart, the live competition pair, paper books, adding or retiring a book, dashboards, keep-awake and deploy, routine checks of fills and missed signals. Use when running, checking, restarting, adding, retiring or diagnosing the bots.
---

# Operating the fleet

Run from the repo root. Read `HANDOVER.md` "CURRENT STATE" first and `docs/ANTIPATTERNS.md` before editing `bot/run.py` or `run_bots.sh`.

## Books

- The fleet, hosts and runners are in `BOTS.md`. LIVE (real orders, EC2 systemd): `competition`, `competition_rehearsal`. Paper on EC2: `roostoo-paper@<book>`. Paper on the Mac: `./run_bots.sh start | stop | restart` (`CONFIGS`).
- `./run_bots.sh status` proves Mac processes exist; `deploy/ec2_status.sh` for EC2; liveness is a `cycles` row under ~90 s old.

## Routine checks

    python3 -m gates.preflight                         # read-only checks before anything live
    python3 -m gates.progress                          # per-book table (see roostoo-live-report)
    python3 -m gates.fill_quality --book competition_rehearsal   # maker share, time to fill, vs mid (one read-only call)
    python3 -m gates.missed_replay --start <utc>       # what the rules would have done had the books been online
    python3 -m gates.market_structure                  # factor share, effective bets, blocks, residual leaders
    python3 -m gates.signal_scan                       # breakouts per clock and what blocks them

## Adding a book

Follow `BOTS.md` "Registering a book" (config, host list, dashboard and validation registries), then restart both dashboards (`pkill -f bot.dashboard`, `nohup python3 -m bot.dashboard &`, same with `--port 8789`); they read the book list only at start.

## Retiring a book

`CONFIGS="config/<book>.yaml" ./run_bots.sh stop`, remove it from default `CONFIGS`, move `live/<book>*` to `live/_archive/retired-<date>/`, keep its config if another book reads it (wf_live reads the 5m/15m configs), record `DECISIONS.md#retired-<date>`.

## Uptime and deploy

- Sleep is the largest measured loss (`#offline-replay-2026-10-01`). On the Mac: mains power and `sudo pmset -a disablesleep 1`.
- AWS: `deploy/ec2_bootstrap.sh` (paste command in README.md), verify with `gates.preflight`, then `./run_bots.sh livestop` on the Mac.

## Rules

- Every live change committed and pushed; commit messages describe only what they contain, no co-author trailer.
- Never delete journals; archive. Save `curl` JSON with `-o` before parsing (the terminal filter mangles pipes).
