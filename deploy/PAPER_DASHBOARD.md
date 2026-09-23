# Paper lab dashboard

Open http://127.0.0.1:8788 while logged into this Mac.
The read-only server refreshes the atomic paper-lab snapshot every ten seconds.
It does not place orders, alter bot state, or request market data.
The terminal reads the independent portfolios from `live/paper_lab_v9` with equity curves, native Roostoo pairs, exposure, cash, fees, FIFO realized P&L, marked positions, exit floors, pending limits, per-bot trace counts, and a searchable execution ledger.
The top selector is authoritative: every headline result, position, working order,
decision, order, fill and CSV export belongs only to that selected bot. The
comparison table keeps one row per independent wallet and intentionally has no
aggregate P&L or aggregate fee figure.
CSV export contains the currently filtered, displayed ledger rows, up to 300.
Closed rows represent FIFO lot matches rather than necessarily one complete position round trip.
Entry cost includes allocated purchase fees; individual unrealized position P&L uses the marks saved atomically with the new experiment's NAV.
The historical sizing and exit panels use `results/allocation_review.json` and `results/exit_review.json` and can switch between 10 and 20 bps costs.
These historical metrics are separate from live statistics, which require at least 28 complete sampled days before display.
The first experiment remains in `live/paper_lab_v1` as an archived record.
For the current experiment's CLI report use `/opt/anaconda3/bin/python3 -m bot.paper_lab --config config/paper_lab_v9.yaml --report`.
Data older than three minutes is flagged as stale; recent errors remain visible in operational health.

Run manually from the repository root with `/opt/anaconda3/bin/python3 -m bot.paper_dashboard`.
The running macOS service is `com.roostoo.paper-dashboard`, loaded from `deploy/com.roostoo.paper-dashboard.plist`.
Inspect it with `launchctl print gui/501/com.roostoo.paper-dashboard`.
Stop it with `launchctl bootout gui/501/com.roostoo.paper-dashboard`.
Load it again after logout or reboot with `launchctl bootstrap gui/501 /Users/aaravmahajan/roostoo-hackathon/deploy/com.roostoo.paper-dashboard.plist`.
The server binds only to localhost, port 8788; the existing journal dashboard at port 8787 is separate.
Logs are `live/paper-dashboard.out` and `live/paper-dashboard.err`.
