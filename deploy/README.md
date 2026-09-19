# Deploying the bot

## Local (macOS or Linux)

    ./run_bots.sh start     # start both bots under a respawning supervisor
    ./run_bots.sh status    # supervisor and worker process state
    ./run_bots.sh report    # cycles, uptime, restarts, positions, live performance
    ./run_bots.sh stop

Configs default to bot A and bot B.
Override with `CONFIGS="config/bot_a_4h.yaml" ./run_bots.sh start`.

Dry run is the default.
Set `ROOSTOO_DRY_RUN=0` with credentials in `.env` to place real orders.

## EC2 (the competition requirement)

Section 7 of the plan requires unattended operation on the provided instance with
zero manual API calls.
`systemd` is the mechanism, because it restarts on failure and on reboot and it
records start and stop times that match the journal.

    sudo cp deploy/roostoo-bot@.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now roostoo-bot@bot_a_4h
    systemctl status roostoo-bot@bot_a_4h
    journalctl -u roostoo-bot@bot_a_4h -f

The unit name carries the config, so `roostoo-bot@bot_a_4h` runs
`config/bot_a_4h.yaml`.

## Verifying it is actually autonomous

    ./run_bots.sh report

`restarts` counts resume events, `halts` counts kill-switch trips, `errors`
counts logged failures, and `max_cycle_gap_s` shows the longest interruption.
A gap materially larger than the configured `poll_seconds` means the process
died and was respawned.

    python3 -m gates.gate10_shadow --bot bot_a_4h

This evaluates the pre-registered shadow conditions: three distinct days of
operation, live-versus-backtest signal agreement at or above 0.95, median fill
deviation within 5 bps, no unexplained halts and no errors.

## Trade tracking

    ./run_bots.sh trades

Reconstructs round-trip trades from the order journal by FIFO lot matching and
reports realised P&L, fees, win rate, payoff ratio, profit factor, expectancy
and holding period, alongside the lots still open.
`--csv` also writes `live/<bot>/trades_closed.csv` and `trades_open.csv`, which
are the structured trade logs Section 7 requires as the Screen 1 audit trail.

Two accounting identities are checkable at any time and should always hold:
quantity bought equals quantity closed plus quantity still open, and quantity
sold equals quantity closed. A breach means the blotter and the venue disagree.

Fees are taken from the venue's reported `CommissionPercent` where a real fill
supplied one, and fall back to the configured schedule only for dry-run fills.

## State and restart safety

Position state, cash, universe and last processed bar persist to
`live/<bot>/state.json` after every cycle, written atomically.
On restart the bot restores that state, and outside dry run it reads the venue
wallet and adopts it as authoritative where the two disagree.
A config change between runs is journalled as `config_changed_mid_run`.

## macOS overnight persistence

The supervisor detaches to PPID 1 and survives a terminal or agent session
ending, but it does not survive a reboot, and a sleeping Mac stops the network.

For an unattended overnight run:

    caffeinate -i ./run_bots.sh start

`caffeinate -i` prevents idle sleep for as long as it runs. Closing the lid
still sleeps the machine unless the Mac is on power with lid-sleep disabled.

To survive reboot and logout as well:

    cp deploy/com.roostoo.bot.plist ~/Library/LaunchAgents/
    launchctl load -w ~/Library/LaunchAgents/com.roostoo.bot.plist
    launchctl list | grep roostoo

Unload with `launchctl unload -w ~/Library/LaunchAgents/com.roostoo.bot.plist`.

None of this is needed for the competition itself, where the bot runs on the
EC2 instance under systemd. It matters only for accumulating the Gate 10
shadow days beforehand.

## Dashboard

    ./run_bots.sh dashboard          # http://127.0.0.1:8787
    ./run_bots.sh dashboard --port 9000 --host 0.0.0.0

Reads the journals directly, so it reflects whatever the bots have actually
written rather than a separate copy of the state.
It serves one page and one `/api/state` endpoint, refreshes every five seconds,
and uses only the standard library so it runs on the EC2 instance with no extra
dependencies.

It shows, per bot: equity and an equity sparkline, P&L and return, drawdown from
peak, gross exposure, open positions with weights, closed trades with realised
return and holding period, realised net P&L, fees, win rate and profit factor,
plus Sharpe, Sortino, Calmar and the Screen 3 composite once three daily marks
exist.

Read the badges first.
`live` means a cycle landed within five minutes, `stale` means the bot stopped.
`paper` means dry run; it reads `LIVE ORDERS` when `ROOSTOO_DRY_RUN=0`.
`restarts` and `halts` appear only when non-zero, and either one is a reason to
open `live/<bot>.out`.

Binding to `0.0.0.0` exposes the dashboard to the network. On EC2 keep it on
`127.0.0.1` and reach it through an SSH tunnel rather than opening a port.

## Dashboard insights

The dashboard derives interpretation rather than only displaying numbers.
Each insight card states a value, the reference it is being judged against, and
a tone, so a reading is actionable without recalling the backtest.

- **Exposure vs norm** compares live gross exposure against the 18% historical
  mean on 3.7 names. A reading of 50% is 2.8 times normal and means the market
  is in a broad breakout, not that the strategy has changed.
- **Realised fee drag** annualises fees actually paid and compares them to the
  5.1% a year the backtest expects for bot A and 19.3% for bot B. A sustained
  reading above expectation means fills are worse than modelled.
- **Drawdown headroom** and **mirror headroom** show distance to the two kill
  switches rather than the raw level, because distance is what decides whether
  to act.
- **Shadow gate** counts distinct live days against the three Gate 10 requires.
- **Process integrity** surfaces supervisor restarts, which is the number that
  says whether an unattended run was genuinely continuous.
- **Trade sample** states plainly that win rate and payoff mean nothing below
  roughly 30 closed trades, so an early 100% win rate is not read as skill.

Market breadth scans all 66 venue names every four minutes on a background
thread, so page loads never block on it. It reports how many coins are long,
how many sit within 2% of an entry or a stop, the median cushion above the stop
for held names, and names within 3% of being stopped out.
# Prospective paper lab

The independent six-portfolio experiment runs with `/opt/anaconda3/bin/python3 -m bot.paper_lab` from the repository root.
It uses public data only and never submits exchange orders.
On this Mac its service definition is `deploy/com.roostoo.paper-lab.plist`, loaded as `gui/501/com.roostoo.paper-lab`.
Inspect it with `launchctl print gui/501/com.roostoo.paper-lab`.
Stop it with `launchctl bootout gui/501/com.roostoo.paper-lab`.
Load it with `launchctl bootstrap gui/501 /Users/aaravmahajan/roostoo-hackathon/deploy/com.roostoo.paper-lab.plist`.
The service persists after the agent session, restarts after process failure, and inhibits idle sleep while running; it does not survive logout or reboot without being loaded again.
Read current results with `/opt/anaconda3/bin/python3 -m bot.paper_lab --report`.
State and accounting events are in `live/paper_lab_v1/state.json`; the latest comparison is `live/paper_lab_v1/comparison.json`.
Diagnostics are in `live/paper-lab.out`, `live/paper-lab.err`, and dated error streams under `live/paper_lab_v1/`.
Code or configuration changes invalidate the experiment fingerprint; use a new declared experiment root rather than overwriting the old state.
The paper lab uses later observed quote crosses and cannot verify real venue queue position or fill capacity.
