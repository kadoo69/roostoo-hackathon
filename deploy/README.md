# Deploying and operating the books

## Where things run

The live books and the checkpoint paper twins run on the EC2 instance `i-015fad70d34b0b83d` (ap-southeast-2) under systemd.
The other paper books run on the Mac under `./run_bots.sh`.
A book never runs on two hosts: two processes on one account would both trade it, and `run/LIVE_HOST_EC2` on the Mac makes `./run_bots.sh live` refuse (`DECISIONS.md#ec2-cutover-2026-10-02`).

## EC2

Two systemd templates, both starting `bot.runner`, which picks the bot class from the config (`DECISIONS.md#sleeves-rehearsal-2026-10-02`):

- `roostoo-live@<book>.service`: real Roostoo orders, `ROOSTOO_DRY_RUN=0`, keys from `.env` chosen by the config's `meta.keyset`.
- `roostoo-paper@<book>.service`: paper, `ROOSTOO_DRY_RUN=1`, `CPUQuota=25%`; the bootstrap refuses a paper unit whose config is not keyless paper.

Access from the Mac:

    python3 deploy/aws_login.py            # browser sign-in for the `hackathon` profile
    deploy/ec2_status.sh                   # units, gates.progress, last rehearsal cycle, competition wait
    python3 deploy/ssm_shell.py <script>   # run a shell script on the instance (SendCommand is denied)

Deploy or redeploy: run `deploy/ec2_bootstrap.sh` on the instance (through `ssm_shell.py`).
It pulls `main`, installs requirements, runs the read-only pre-flight and the test suite, then restarts every unit in `BOOKS` and `PAPER_BOOKS`.
To start one new paper book without touching the others, pull, check the config is keyless paper, and `systemctl enable --now roostoo-paper@<book>`.
Never restart the competition book except for a committed change.

## Mac

    ./run_bots.sh start | stop | restart | status   # the paper books in CONFIGS
    ./run_bots.sh progress | progressstop           # 30-minute review -> results/progress/latest.json
    ./run_bots.sh awake | awakestop                 # caffeinate while on mains power
    ./run_bots.sh report | trades | compare | dashboard

Each book runs under a respawning supervisor whose process pattern is scoped to this repo's absolute path.
A sleeping Mac stops every Mac book; uptime is the largest measured loss (`DECISIONS.md#offline-replay-2026-10-01`).
`deploy/com.roostoo.dashboard.plist` keeps the dashboard up across logins.

## Dashboard

    ./run_bots.sh dashboard          # http://127.0.0.1:8787 (desk), /analysis, /heatmap, /full

The desk pulls the EC2 books every 3 minutes (`bot/ec2_feed.py`) and reads the Mac books from their own journals.
It reads the book list only at start: restart it after adding a book.

## Trade tracking

    ./run_bots.sh trades

Reconstructs round-trip trades from the order journal by FIFO lot matching and reports realised P&L, fees, win rate, payoff ratio, profit factor, expectancy and holding period, with the lots still open.
`--csv` also writes `live/<bot>/trades_closed.csv` and `trades_open.csv`, the structured trade logs of the Screen 1 audit trail.
Quantity bought equals quantity closed plus quantity still open, and quantity sold equals quantity closed; a breach means the blotter and the venue disagree.
Fees come from the venue's `CommissionPercent` on real fills and from the configured schedule on paper fills.
Before submitting, `python3 deploy/export_logs.py` copies the journals into `logs/`.

## State and restart safety

Holdings, cash, universe and last processed bar persist to `live/<bot>/state.json` after every cycle, written atomically.
On restart a book restores that state, and outside dry run it reads the venue wallet and adopts it where the two disagree.
A config change between runs is journalled as `config_changed_mid_run`, which the desk counts as a note, not an error.
