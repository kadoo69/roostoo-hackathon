#!/usr/bin/env bash
# Switch the competition account from one live unit to another, on the instance, as root.
# Usage: deploy/switch_live.sh FROM_BOOK TO_BOOK   (DECISIONS.md#competition-r4-2026-10-05)
set -euo pipefail
FROM=${1:?from book}
TO=${2:?to book}
DEST=/opt/roostoo-hackathon
cd "$DEST"
PY="$DEST/.venv/bin/python"

echo "== checks"
sudo -u roostoo "$PY" -c "
from bot.settings import load
import os, sys
os.environ['ROOSTOO_DRY_RUN'] = '0'
s = load('config/$TO.yaml')
ok = (not s.dry_run) and s.keyset == 'comp'
print('$TO', 'sha', s.config_sha256, 'keyset', s.keyset, 'dry_run', s.dry_run, 'shorts', s.shorts_enabled)
sys.exit(0 if ok else 1)"
sudo -u roostoo "$PY" -m pytest tests -q -p no:warnings -x | tail -1
echo "head $(git rev-parse --short HEAD)"

echo "== stop $FROM"
systemctl stop "roostoo-live@$FROM"
systemctl disable "roostoo-live@$FROM" >/dev/null 2>&1 || true
[ "$(systemctl is-active "roostoo-live@$FROM" || true)" != "active" ] || { echo "$FROM still active"; exit 1; }
for u in $(systemctl list-units --type=service --state=active --no-legend 'roostoo-live@*' | awk '{print $1}'); do
  [ "$u" = "roostoo-live@competition_rehearsal.service" ] && continue
  echo "another live unit is active: $u"; exit 1
done

echo "== resting orders on the comp keys"
sudo -u roostoo "$PY" deploy/cancel_pending.py comp --cancel

echo "== start $TO"
systemctl enable "roostoo-live@$TO" >/dev/null 2>&1
systemctl start "roostoo-live@$TO"
sleep 90
echo "$TO: $(systemctl is-active "roostoo-live@$TO") since $(systemctl show -p ActiveEnterTimestamp --value "roostoo-live@$TO")"
D="$DEST/live/$TO"
tail -n 1 "$D"/lifecycle-*.jsonl 2>/dev/null | tail -n 1 | cut -c1-400
tail -n 1 "$D"/reconcile-*.jsonl 2>/dev/null | tail -n 1 | cut -c1-600
tail -n 3 "$D"/orders-*.jsonl 2>/dev/null | cut -c1-300
tail -n 1 "$D"/cycles-*.jsonl 2>/dev/null | tail -n 1 | cut -c1-500
tail -n 5 "$D"/errors-*.jsonl 2>/dev/null | cut -c1-300 || true
