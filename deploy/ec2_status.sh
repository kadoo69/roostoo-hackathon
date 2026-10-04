#!/usr/bin/env bash
# Live-book status from the EC2 instance: unit state, gates.progress, last rehearsal cycle, competition wait.
# Usage: deploy/ec2_status.sh   (needs the `hackathon` AWS profile; DECISIONS.md#ec2-cutover-2026-10-02)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB="$(mktemp)"
trap 'rm -f "$JOB"' EXIT
cat > "$JOB" <<'REMOTE'
cd /opt/roostoo-hackathon
for b in competition_z25 competition_z3 competition_ride competition_wf competition_split competition_rehearsal; do echo "$b: $(systemctl is-active roostoo-live@$b), up since $(systemctl show -p ActiveEnterTimestamp --value roostoo-live@$b)"; done
sudo -u roostoo .venv/bin/python -m gates.progress 2>&1 | sed -n 1,8p
sudo tail -n 1 live/competition_rehearsal/cycles-$(date -u +%F).jsonl | .venv/bin/python -c "import json,sys;r=json.loads(sys.stdin.read());print('rehearsal last cycle',r['ts_utc'][11:19],'equity',round(r['equity'],2),'positions',r['positions'])"
for c in competition_z25 competition_z3 competition_ride competition_wf competition_split; do sudo tail -n 1 live/$c/waiting-$(date -u +%F).jsonl 2>/dev/null | sed "s/^/$c /" | cut -c1-160 || true; sudo tail -n 1 live/$c/cycles-$(date -u +%F).jsonl 2>/dev/null | sed "s/^/$c /" | cut -c1-300 || true; done
echo "commit $(sudo git -C /opt/roostoo-hackathon rev-parse --short HEAD)"
REMOTE
"${PYTHON:-python3}" "$ROOT/deploy/ssm_shell.py" "$JOB" 240 | sed -n "/^competition_z25:/,\$p"
