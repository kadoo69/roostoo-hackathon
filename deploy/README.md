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
