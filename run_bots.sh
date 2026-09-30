#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY=${PY:-python3}
# Gated arms are listed next to the control they must be read against.
# The paper fleet was stopped 2026-09-30 (DECISIONS.md#paper-fleet-stopped-2026-09-30); only the
# competition rule's paper twin, the adaptive scalper and its fixed-clock twins start by default. "$0 fleet" restarts the whole list.
PAPER_FLEET="config/donchian_4h.yaml config/momentum_top3_full.yaml config/momentum_top3_lock.yaml config/momentum_top3_30m.yaml config/momentum_top3_15m.yaml config/momentum_top3_5m.yaml config/momentum_top3_1h_allcash.yaml config/momentum_top3_30m_allcash.yaml config/accel_15m.yaml config/burst_5m.yaml config/burst_15m.yaml config/burst_strong_15m.yaml config/momentum_top3_15m_eq.yaml config/short_accel_15m.yaml config/momentum_top3_15m_hold3h.yaml config/momentum_top3_5m_hold2h.yaml config/short_pullback_15m.yaml config/momentum_top3_15m_slowexit.yaml"
CONFIGS=${CONFIGS:-"config/momentum_top3_30m.yaml config/wf_live.yaml config/momentum_top3_15m.yaml config/momentum_top3_5m.yaml"}
# alpha_flow runs under bot.alpha_flow_run, not bot.run, so it is started separately.
ALPHA_FLOW_CONFIG=${ALPHA_FLOW_CONFIG:-"config/alpha_flow.yaml"}
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
module_for() { case "$1" in topdown_ls) echo bot.topdown_run ;; scalper_adaptive|wf_live) echo bot.scalper_adaptive_run ;; hedge_explorer) echo bot.hedge_explorer_run ;; competition|competition_rehearsal|momentum_top3_1h|momentum_top3_1h_long|momentum_top3_30m|momentum_top3_15m|momentum_top3_5m) echo bot.contenders_run ;; accel_15m|accel_5m) echo bot.accel_run ;; momentum_top3_1h_allcash|momentum_top3_30m_allcash|momentum_top3_15m_allcash|momentum_top3_5m_allcash|burst_5m|burst_15m|burst_strong_15m|momentum_top3_15m_eq|short_accel_15m|momentum_top3_15m_hold12h|momentum_top3_15m_hold3h|momentum_top3_5m_hold2h|momentum_top3_30m_wide|short_pullback_15m|momentum_top3_15m_slowexit) echo bot.contenders_run ;; *) echo bot.run ;; esac; }
workers() { pgrep -f "bot\.(run|topdown_run|contenders_run|accel_run|scalper_adaptive_run|hedge_explorer_run) $ROOT/config/$1\.yaml" 2>/dev/null; }
supervisors() { pgrep -f "cfg=$ROOT/config/$1\.yaml" 2>/dev/null; }
all_workers() { pgrep -f "bot\.(run|topdown_run|contenders_run|accel_run|scalper_adaptive_run|hedge_explorer_run) $ROOT/config/" 2>/dev/null; }
scanner_supervisors() { pgrep -f "scanroot=$ROOT" 2>/dev/null; }
scanner_workers() { pgrep -f "bot\.scanner --root $ROOT" 2>/dev/null; }
scanner_procs() { { scanner_supervisors; scanner_workers; } | sort -u; }
source_supervisors() { pgrep -f "sourceroot=$ROOT" 2>/dev/null; }
source_workers() { pgrep -f "bot\.source_hub --root $ROOT" 2>/dev/null; }
source_procs() { { source_supervisors; source_workers; } | sort -u; }
LAB=${LAB:-config/paper_lab_v9.yaml}
lab_supervisors() { pgrep -f "labroot=$ROOT" 2>/dev/null; }
lab_workers() { pgrep -f "bot\.paper_lab --config $ROOT/config/" 2>/dev/null; }
lab_procs() { { lab_supervisors; lab_workers; } | sort -u; }
scalper_supervisors() { pgrep -f "scalperroot=$ROOT" 2>/dev/null; }
scalper_workers() { pgrep -f "bot\.scalper_run $ROOT/config/" 2>/dev/null; }
scalper_procs() { { scalper_supervisors; scalper_workers; } | sort -u; }
alpha_supervisors() { pgrep -f "alpharoot=$ROOT" 2>/dev/null; }
alpha_workers() { pgrep -f "bot\.alpha_flow_run $ROOT/config/" 2>/dev/null; }
alpha_procs() { { alpha_supervisors; alpha_workers; } | sort -u; }
testnet_supervisors() { pgrep -f "testnetroot=$ROOT" 2>/dev/null; }
testnet_workers() { pgrep -f "bot\.run $ROOT/config/testnet_live" 2>/dev/null; }
testnet_procs() { { testnet_supervisors; testnet_workers; } | sort -u; }

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
  fleet) CONFIGS="$PAPER_FLEET" "$0" start ;;
  progress)
    # Hourly log review of every running book: trades, fills, booked profits, Sharpe, Sortino,
    # return over drawdown. DECISIONS.md#progress-review-2026-09-30
    if pgrep -f "progressroot=$ROOT" >/dev/null; then echo "  progress review already running"; else
      nohup bash -c 'r="$1"; cd "$r"; while true; do "$2" -m gates.progress >> live/progress.out 2>&1; "$2" -m gates.market_structure >> live/progress.out 2>&1; sleep 3600; done' "progressroot=$ROOT" "$ROOT" "$PY" >> live/progress.supervisor.out 2>&1 &
      echo $! > run/progress.pid; disown 2>/dev/null || true; echo "  progress review started (pid $!), hourly -> results/progress/latest.json"
    fi ;;
  progressstop)
    p=$(cat run/progress.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(pgrep -f "progressroot=$ROOT"); [ -n "$sup" ] && kill $sup 2>/dev/null
    rm -f run/progress.pid; echo "  progress review stopped" ;;
  fleetstop) CONFIGS="$PAPER_FLEET" "$0" stop ;;
  live)
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
    if [ -n "$(source_procs)" ]; then echo "  source hub RUNNING"; else echo "  source hub STOPPED"; fi
    ;;
  sources)
    if [ -n "$(source_procs)" ]; then echo "  source hub already running (pids $(source_procs | tr '\n' ' '))"; else
      nohup bash -c 'sourceroot="$1"; cd "$sourceroot"; while true; do "$2" -m bot.source_hub --root "$sourceroot" >> live/source_hub.out 2>&1; sleep 10; done' "sourceroot=$ROOT" "$ROOT" "$PY" >> live/source_hub.supervisor.out 2>&1 &
      echo $! > run/sources.pid; disown 2>/dev/null || true; echo "  source hub started (pid $!)"
    fi ;;
  sourcestop)
    p=$(cat run/sources.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(source_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(source_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/sources.pid
    if [ -n "$(source_procs)" ]; then echo "  source hub STILL RUNNING"; else echo "  source hub stopped"; fi ;;
  scanner)
    # The old guard matched "$ROOT/.*bot\.scanner", but $ROOT reaches the supervisor
    # as a trailing bash -c argument and the worker carried no repo path at all, so
    # neither process ever matched and every invocation started another supervisor.
    # Two of them ran concurrently on 2026-09-20 and both wrote live/scanner/state.json.
    # Both processes now carry $ROOT ahead of the module name: the supervisor via a
    # scanroot= marker, the worker via --root, which bot.scanner verifies and refuses.
    if [ -n "$(scanner_procs)" ]; then echo "  scanner already running (pids $(scanner_procs | tr '\n' ' '))"; else
      nohup bash -c 'scanroot="$1"; cd "$scanroot"; while true; do "$2" -m bot.scanner --root "$scanroot" >> live/scanner.out 2>&1; sleep 10; done' "scanroot=$ROOT" "$ROOT" "$PY" >> live/scanner.supervisor.out 2>&1 &
      echo $! > run/scanner.pid; disown 2>/dev/null || true; echo "  scanner started (pid $!)"
    fi ;;
  scanstop)
    p=$(cat run/scanner.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(scanner_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(scanner_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/scanner.pid
    sleep 0.3
    if [ -n "$(scanner_procs)" ]; then echo "  scanner STILL RUNNING - investigate"; else echo "  scanner stopped"; fi ;;
  paperlab)
    # The lab ran unsupervised until 2026-09-20. Its only product is elapsed forward
    # time against min_comparison_days, so a silent death costs days that cannot be
    # backfilled. It is supervised now, and scoped to $ROOT for the same reason the
    # bot patterns are.
    if [ -n "$(lab_procs)" ]; then echo "  paper lab already running (pids $(lab_procs | tr '\n' ' '))"; else
      nohup bash -c 'labroot="$1"; cd "$labroot"; while true; do "$2" -m bot.paper_lab --config "$labroot/$3" >> live/paper-lab.out 2>> live/paper-lab.err; code=$?; printf "[%s] paper lab exited code=%s, respawning in 30s\n" "$(date -u +%FT%TZ)" "$code" >> live/paper-lab.err; sleep 30; done' "labroot=$ROOT" "$ROOT" "$PY" "$LAB" >> live/paper-lab.supervisor.out 2>&1 &
      echo $! > run/paperlab.pid; disown 2>/dev/null || true; echo "  paper lab started (pid $!) on $LAB"
    fi ;;
  labstop)
    p=$(cat run/paperlab.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(lab_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(lab_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/paperlab.pid
    sleep 0.3
    if [ -n "$(lab_procs)" ]; then echo "  paper lab STILL RUNNING - investigate"; else echo "  paper lab stopped"; fi ;;
  scalper)
    if [ -n "$(scalper_procs)" ]; then echo "  scalper already running (pids $(scalper_procs | tr '\n' ' '))"; else
      nohup bash -c 'r="$1"; cd "$r"; while true; do "$2" -m bot.scalper_run "$r/config/scalper_live.yaml" >> live/scalper_live.out 2>&1; code=$?; printf "[%s] exited code=%s, respawning in 30s\n" "$(date -u +%FT%TZ)" "$code" >> live/scalper_live.out; sleep 30; done' "scalperroot=$ROOT" "$ROOT" "$PY" >> live/scalper_live.supervisor.out 2>&1 &
      echo $! > run/scalper.pid; disown 2>/dev/null || true; echo "  scalper started (pid $!)"
    fi ;;
  scalperstop)
    p=$(cat run/scalper.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(scalper_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(scalper_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/scalper.pid
    sleep 0.3
    if [ -n "$(scalper_procs)" ]; then echo "  scalper STILL RUNNING"; else echo "  scalper stopped"; fi ;;
  scalpreport) shift; exec "$PY" -m bot.scalper_run --report ;;
  alphaflow)
    if [ -n "$(alpha_procs)" ]; then echo "  alpha_flow already running (pids $(alpha_procs | tr '\n' ' '))"; else
      nohup bash -c 'r="$1"; cd "$r"; while true; do "$2" -m bot.alpha_flow_run "$r/config/alpha_flow.yaml" >> live/alpha_flow.out 2>&1; code=$?; printf "[%s] exited code=%s, respawning in 30s\n" "$(date -u +%FT%TZ)" "$code" >> live/alpha_flow.out; sleep 30; done' "alpharoot=$ROOT" "$ROOT" "$PY" >> live/alpha_flow.supervisor.out 2>&1 &
      echo $! > run/alpha_flow.pid; disown 2>/dev/null || true; echo "  alpha_flow started (pid $!)"
    fi ;;
  testnet)
    if [ -n "$(testnet_procs)" ]; then echo "  testnet_live already running (pids $(testnet_procs | tr '\n' ' '))"; else
      nohup bash -c 'r="$1"; cd "$r"; export BOT_VENUE=binance_testnet ROOSTOO_DRY_RUN=0; while true; do "$2" -m bot.run "$r/config/testnet_live.yaml" >> live/testnet_live.out 2>&1; code=$?; printf "[%s] exited code=%s, respawning in 30s\n" "$(date -u +%FT%TZ)" "$code" >> live/testnet_live.out; sleep 30; done' "testnetroot=$ROOT" "$ROOT" "$PY" >> live/testnet_live.supervisor.out 2>&1 &
      echo $! > run/testnet_live.pid; disown 2>/dev/null || true; echo "  testnet_live started LIVE ORDERS (pid $!)"
    fi ;;
  testnetstop)
    p=$(cat run/testnet_live.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(testnet_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(testnet_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/testnet_live.pid
    sleep 0.3
    if [ -n "$(testnet_procs)" ]; then echo "  testnet_live STILL RUNNING"; else echo "  testnet_live stopped"; fi ;;
  alphaflowstop)
    p=$(cat run/alpha_flow.pid 2>/dev/null) && { pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
    sup=$(alpha_supervisors); [ -n "$sup" ] && kill $sup 2>/dev/null
    sleep 0.3
    w=$(alpha_workers); [ -n "$w" ] && kill $w 2>/dev/null
    rm -f run/alpha_flow.pid
    sleep 0.3
    if [ -n "$(alpha_procs)" ]; then echo "  alpha_flow STILL RUNNING"; else echo "  alpha_flow stopped"; fi ;;
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
  *) echo "usage: $0 {start|stop|restart|fleet|fleetstop|progress|progressstop|live|livestop|status|scanner|scanstop|sources|sourcestop|paperlab|labstop|scalper|scalperstop|scalpreport|compare|report|trades|dashboard}"; exit 2 ;;
esac
