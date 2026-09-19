#!/usr/bin/env bash
cd "$(dirname "$0")"
mkdir -p live/snapshots
ts=$(date -u +%Y-%m-%dT%H%M%SZ)
python3 -m bot.status > "live/snapshots/status-$ts.json" 2>&1
python3 -m gates.gate10_shadow --bot bot_a_4h > "live/snapshots/shadow-a-$ts.json" 2>&1
python3 -m gates.gate10_shadow --bot bot_b_1h > "live/snapshots/shadow-b-$ts.json" 2>&1
echo "snapshot $ts"
