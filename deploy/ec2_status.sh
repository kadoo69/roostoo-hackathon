#!/usr/bin/env bash
# Live-book status from the EC2 instance: unit state, gates.progress, last rehearsal cycle, competition wait.
# Usage: deploy/ec2_status.sh   (needs the `hackathon` AWS profile; DECISIONS.md#ec2-cutover-2026-10-02)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB="$(mktemp)"
trap 'rm -f "$JOB"' EXIT
cat > "$JOB" <<'REMOTE'
cd /opt/roostoo-hackathon
for b in competition competition_rehearsal; do echo "$b: $(systemctl is-active roostoo-live@$b), up since $(systemctl show -p ActiveEnterTimestamp --value roostoo-live@$b)"; done
sudo -u roostoo .venv/bin/python -m gates.progress 2>&1 | sed -n 1,8p
sudo tail -n 1 live/competition_rehearsal/cycles-$(date -u +%F).jsonl | .venv/bin/python -c "import json,sys;r=json.loads(sys.stdin.read());print('rehearsal last cycle',r['ts_utc'][11:19],'equity',round(r['equity'],2),'positions',r['positions'])"
sudo tail -n 1 live/competition/waiting-$(date -u +%F).jsonl 2>/dev/null | cut -c1-140 || sudo tail -n 1 live/competition/cycles-$(date -u +%F).jsonl | cut -c1-300
echo "commit $(sudo git -C /opt/roostoo-hackathon rev-parse --short HEAD)"
REMOTE
python3 "$ROOT/deploy/ssm_shell.py" "$JOB" 240 | sed -n '/^competition:/,$p'
