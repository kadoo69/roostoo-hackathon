#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY=${PY:-python3}
CONFIGS=${CONFIGS:-"config/momentum_top3_30m.yaml config/wf_live.yaml config/blend_30m_ride.yaml config/resid_30m.yaml config/htf0_30m.yaml config/ride1_5m.yaml config/wide_30m.yaml config/ride1_wide_5m.yaml"}
# Books that place REAL Roostoo orders; each config's meta.keyset picks its keys.
# competition = round-1 competition account, competition_rehearsal = TEST account.
# DECISIONS.md#competition-book-2026-09-30
LIVE_CONFIGS=${LIVE_CONFIGS:-"config/competition.yaml config/competition_rehearsal.yaml"}
mkdir -p live run

pidfile() { echo "run/$1.pid"; }
running() { local p; p=$(cat "$(pidfile "$1")" 2>/dev/null) || return 1; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

# Process patterns are scoped to THIS repo's absolute path. A sibling checkout
# (roostoo-jev) holds configs with identical relative paths, so a pattern of
# "bot.run config/donchian_4h.yaml" matches the other repo's workers and kills them.
# That is what happened at 2026-09-19T17:41:03Z: starting the jev stack SIGTERMed
# all three bots here and they never came back. Match on $ROOT, never on "config/".
module_for() { case "$1" in wf_live|ride_5m|resid_30m|htf0_30m|ride1_5m|ride1_wide_5m) echo bot.scalper_adaptive_run ;; blend_30m_ride) echo bot.hedge_explorer_run ;; regime_ls_30m) echo bot.regime_ls_run ;; competition|competition_rehearsal|momentum_top3_30m|wide_30m) echo bot.contenders_run ;; *) echo bot.runner ;; esac; }
workers() { pgrep -f "bot\.(run|runner|contenders_run|scalper_adaptive_run|hedge_explorer_run|regime_ls_run) $ROOT/config/$1\.yaml" 2>/dev/null; }
supervisors() { pgrep -f "cfg=$ROOT/config/$1\.yaml" 2>/dev/null; }
all_workers() { pgrep -f "bot\.(run|runner|contenders_run|scalper_adaptive_run|hedge_explorer_run|regime_ls_run) $ROOT/config/" 2>/dev/null; }

start_one() {
  local cfg=$1 dry=${2:-1} name; name=$(basename "$cfg" .yaml)
  if running "$name"; then echo "  $name already running (pid $(cat "$(pidfile "$name")"))"; return; fi
  local orphans; orphans=$(workers "$name")
  if [ -n "$orphans" ]; then
    echo "  $name REFUSED: worker(s) already running without a pidfile: $(echo "$orphans" | tr '\n' ' ')"
    echo "    two books on one state store corrupts both. run '$0 stop' first."
    return
  fi
  ROOSTOO_DRY_RUN=$dry nohup bash -c '
    cfg="$1"; name="$2"; py="$3"; mod="$4"
    while true; do
      "$py" -m "$mod" "$cfg" >> "live/$name.out" 2>&1
      code=$?
      printf "[%s] exited code=%s, respawning in 10s\n" "$(date -u +%FT%TZ)" "$code" >> "live/$name.out"
      sleep 10
    done
  ' _ "$ROOT/config/$name.yaml" "$name" "$PY" "$(module_for "$name")" >> "live/$name.supervisor.out" 2>&1 &
  echo $! > "$(pidfile "$name")"
  disown 2>/dev/null || true
  echo "  $name started (supervisor pid $!)"
}

stop_one() {
  local name=$1 p
  p=$(cat "$(pidfile "$name")" 2>/dev/null) && [ -n "$p" ] && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
  rm -f "$(pidfile "$name")"
  # Supervisors first: killing a worker while its supervisor lives just makes the
  # supervisor respawn it.
  local sup; sup=$(supervisors "$name")
  [ -n "$sup" ] && kill $sup 2>/dev/null
  sleep 0.3
  local w; w=$(workers "$name")
  [ -n "$w" ] && kill $w 2>/dev/null
  sleep 0.3
  w=$(workers "$name")
  [ -n "$w" ] && kill -9 $w 2>/dev/null
  if [ -n "$(workers "$name")" ]; then echo "  $name STILL RUNNING - investigate"; else echo "  $name stopped"; fi
}

case "${1:-start}" in
  start)
    echo "starting:"; for c in $CONFIGS; do start_one "$c"; done
    sleep 3; echo "processes:"; all_workers | sed 's/^/  pid /' || echo "  NONE - check live/*.out"
    ;;
  stop)
    echo "stopping:"; for c in $CONFIGS; do stop_one "$(basename "$c" .yaml)"; done
    ;;
  restart) "$0" stop; sleep 2; "$0" start ;;
  progress)
    # Hourly log review of every running book: trades, fills, booked profits, Sharpe, Sortino,
    # return over drawdown. DECISIONS.md#progress-review-2026-09-30
    if pgrep -f "progressroot=$ROOT" >/dev/null; then echo "  progress review already running"; else
      nohup bash -c 'r="$1"; cd "$r"; while true; do "$2" -m gates.progress >> live/progress.out 2>&1; "$2" -m gates.market_structure >> live/progress.out 2>&1; sleep 1800; done' "progressroot=$ROOT" "$ROOT" "$PY" >> live/progress.supervisor.out 2>&1 &
      echo $! > run/progress.pid; disown 2>/dev/null || true; echo "  progress review started (pid $!), every 30 min -> results/progress/latest.json"
    fi ;;
  progressstop)
    p=$(cat run/progress.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(pgrep -f "progressroot=$ROOT"); [ -n "$sup" ] && kill $sup 2>/dev/null
    rm -f run/progress.pid; echo "  progress review stopped" ;;
  live)
    if [ -f "$ROOT/run/LIVE_HOST_EC2" ] && [ "${FORCE_LOCAL_LIVE:-0}" != 1 ]; then
      echo "refusing: the live books run on EC2 ($(cat "$ROOT/run/LIVE_HOST_EC2")); two hosts would trade one account."
      echo "stop them there first, then rm run/LIVE_HOST_EC2 (DECISIONS.md#ec2-cutover-2026-10-02)"; exit 1
    fi
    echo "starting LIVE ORDER books:"; for c in $LIVE_CONFIGS; do start_one "$c" 0; done
    ;;
  livestop)
    echo "stopping LIVE ORDER books:"; for c in $LIVE_CONFIGS; do stop_one "$(basename "$c" .yaml)"; done
    ;;
  status)
    for c in $CONFIGS $LIVE_CONFIGS; do
      n=$(basename "$c" .yaml)
      w=$(workers "$n" | wc -l | tr -d ' ')
      if running "$n"; then echo "  $n RUNNING (supervisor $(cat "$(pidfile "$n")"), workers $w)"
      elif [ "$w" -gt 0 ]; then echo "  $n ORPHANED - $w worker(s) with no supervisor pidfile"
      else echo "  $n STOPPED"; fi
      [ "$w" -gt 1 ] && echo "    WARNING: $w workers on one state store"
    done
    echo "  worker processes (this repo): $(all_workers | wc -l | tr -d ' ')"
    ;;
  awake)
    # 55% of the pre-reset forward test was lost to the Mac sleeping (pmset sleep 1);
    # every sleep was also a missed bar close. -i blocks idle sleep, -s blocks system
    # sleep on mains power. Closing the lid still sleeps a MacBook without an external
    # display. DECISIONS.md#log-review-2026-09-23
    if pgrep -f "awakeroot=$ROOT" >/dev/null; then echo "  keep-awake already running"; else
      nohup bash -c 'awakeroot="$1"; while true; do caffeinate -is; sleep 5; done' "awakeroot=$ROOT" >> live/awake.out 2>&1 &
      echo $! > run/awake.pid; disown 2>/dev/null || true; echo "  keep-awake started (pid $!)"
    fi ;;
  awakestop)
    p=$(cat run/awake.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(pgrep -f "awakeroot=$ROOT"); [ -n "$sup" ] && { for s in $sup; do pkill -P "$s"; done; kill $sup 2>/dev/null; }
    rm -f run/awake.pid; echo "  keep-awake stopped" ;;
  compare) shift; exec "$PY" -m bot.compare "$@" ;;
  report) shift; exec "$PY" -m bot.status "$@" ;;
  trades) shift; exec "$PY" -m bot.blotter --csv "$@" ;;
  dashboard) shift; exec "$PY" -m bot.dashboard "$@" ;;
  *) echo "usage: $0 {start|stop|restart|progress|progressstop|live|livestop|status|awake|awakestop|compare|report|trades|dashboard}"; exit 2 ;;
esac
