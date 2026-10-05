#!/usr/bin/env bash
# One-shot EC2 setup for the live Roostoo books. Paste into an AWS Session Manager shell:
#
#   export REPO_URL=https://github.com/kadoo69/roostoo-hackathon.git
#   export ROOSTOO_COMP_API_KEY=... ROOSTOO_COMP_SECRET_KEY=...
#   export ROOSTOO_TEST_API_KEY=... ROOSTOO_TEST_SECRET_KEY=...
#   curl -fsSL https://raw.githubusercontent.com/kadoo69/roostoo-hackathon/main/deploy/ec2_bootstrap.sh | sudo -E bash
#
# Idempotent: re-running pulls the latest commit and restarts the books.
# BOOKS defaults to the competition book and its test-account rehearsal; PAPER_BOOKS (default ride_5m)
# run keyless paper books under roostoo-paper@ (DECISIONS.md#ec2-paper-ride-2026-10-02).
# DECISIONS.md#competition-book-2026-09-30
set -euo pipefail

: "${REPO_URL:?set REPO_URL to the public GitHub repo}"
BRANCH=${BRANCH:-main}
DEST=/opt/roostoo-hackathon
BOOKS=${BOOKS:-"competition_z25 competition_rehearsal"}
PAPER_BOOKS=${PAPER_BOOKS:-"wf_live ride_5m ride_z3_5m sleeves_z3_5m split_tilt_5m regime_ls_30m ride_z25_5m ride_z25_swap_5m ride_z25_zrank_5m ride_z25_churn_5m ride_z25_gate_5m ride_z25_n4_5m"}

log() { printf '\n== %s\n' "$*"; }

log "packages"
if command -v dnf >/dev/null; then
  dnf install -y -q git python3.11 python3.11-pip chrony >/dev/null || dnf install -y -q git python3.12 python3.12-pip chrony >/dev/null
  systemctl enable --now chronyd >/dev/null 2>&1 || true
elif command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3-venv python3-pip chrony >/dev/null
  if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    apt-get install -y -qq software-properties-common >/dev/null
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv >/dev/null
  fi
fi
PY=$(command -v python3.12 || command -v python3.11 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || { echo "need python >= 3.11"; exit 1; }
timedatectl set-timezone UTC 2>/dev/null || true

log "service user and code"
id roostoo >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin roostoo
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch -q origin "$BRANCH"
  git -C "$DEST" checkout -q "$BRANCH"
  git -C "$DEST" reset -q --hard "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$DEST"
fi
git config --global --add safe.directory "$DEST"
mkdir -p "$DEST/live" "$DEST/run"

log "python environment"
[ -x "$DEST/.venv/bin/python" ] || "$PY" -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q --upgrade pip
"$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"

log "credentials (.env, mode 600, never committed)"
ENV="$DEST/.env"
touch "$ENV"
for k in ROOSTOO_COMP_API_KEY ROOSTOO_COMP_SECRET_KEY ROOSTOO_TEST_API_KEY ROOSTOO_TEST_SECRET_KEY; do
  v="${!k:-}"
  [ -z "$v" ] && continue
  grep -v "^$k=" "$ENV" > "$ENV.tmp" || true
  echo "$k=$v" >> "$ENV.tmp"
  mv "$ENV.tmp" "$ENV"
done
grep -q '^ROOSTOO_COMP_API_KEY=' "$ENV" || { echo "ROOSTOO_COMP_API_KEY missing"; exit 1; }
chown -R roostoo:roostoo "$DEST"
chmod 600 "$ENV"

log "pre-flight (read-only, places no order)"
sudo -u roostoo bash -c "cd $DEST && .venv/bin/python -m gates.preflight"

log "tests"
sudo -u roostoo bash -c "cd $DEST && .venv/bin/pip install -q -r requirements-dev.txt >/dev/null && .venv/bin/python -m pytest tests -q -p no:warnings -x" | tail -2

if [ "${SKIP_SYSTEMD:-0}" = 1 ]; then log "SKIP_SYSTEMD=1: stopping before services (container test)"; exit 0; fi
log "systemd"
cp "$DEST/deploy/roostoo-live@.service" /etc/systemd/system/
systemctl daemon-reload
for b in $BOOKS; do
  systemctl enable "roostoo-live@$b" >/dev/null 2>&1
  systemctl restart "roostoo-live@$b"
done
cp "$DEST/deploy/roostoo-monitor.service" "$DEST/deploy/roostoo-monitor.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now roostoo-monitor.timer >/dev/null 2>&1
cp "$DEST/deploy/roostoo-paper@.service" /etc/systemd/system/
systemctl daemon-reload
for b in $PAPER_BOOKS; do
  sudo -u roostoo bash -c "cd $DEST && .venv/bin/python -c \"from bot.settings import load; import sys; s=load('config/$b.yaml'); sys.exit(0 if s.dry_run and not s.keyset else 1)\"" \
    || { echo "refusing paper unit for $b: not a keyless paper config"; exit 1; }
  systemctl enable "roostoo-paper@$b" >/dev/null 2>&1
  systemctl restart "roostoo-paper@$b"
done
sleep 20
for b in $PAPER_BOOKS; do printf '%-24s %s (paper)\n' "$b" "$(systemctl is-active "roostoo-paper@$b")"; done
for b in $BOOKS; do
  printf '%-24s %s\n' "$b" "$(systemctl is-active "roostoo-live@$b")"
  tail -n 1 "$DEST/live/$b/cycles-$(date -u +%F).jsonl" 2>/dev/null | cut -c1-220 || true
done
log "done: commit $(git -C "$DEST" rev-parse --short HEAD); watch with: sudo journalctl -u roostoo-live@competition -f ; tail -f $DEST/live/competition/cycles-*.jsonl"
