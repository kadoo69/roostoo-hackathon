# Paper lab dashboard

Open http://127.0.0.1:8788 while logged into this Mac.
The read-only server refreshes the atomic paper-lab snapshot every ten seconds.
It does not place orders, alter bot state, or request market data.
The six independent paper portfolios are shown with equity curves, exposure, cash, fees, FIFO realized P&L, positions, pending limits, and a searchable execution ledger.
CSV export contains the currently filtered, displayed ledger rows, up to 300.
Closed rows represent FIFO lot matches rather than necessarily one complete position round trip.
Entry cost includes allocated purchase fees; individual unrealized position P&L is omitted because per-symbol market marks are not saved in the source snapshot.
Data older than three minutes is flagged as stale; recent errors remain visible in operational health.

Run manually from the repository root with `/opt/anaconda3/bin/python3 -m bot.paper_dashboard`.
The running macOS service is `com.roostoo.paper-dashboard`, loaded from `deploy/com.roostoo.paper-dashboard.plist`.
Inspect it with `launchctl print gui/501/com.roostoo.paper-dashboard`.
Stop it with `launchctl bootout gui/501/com.roostoo.paper-dashboard`.
Load it again after logout or reboot with `launchctl bootstrap gui/501 /Users/aaravmahajan/roostoo-hackathon/deploy/com.roostoo.paper-dashboard.plist`.
The server binds only to localhost, port 8788; the existing journal dashboard at port 8787 is separate.
Logs are `live/paper-dashboard.out` and `live/paper-dashboard.err`.
