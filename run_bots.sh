#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
PY=${PY:-python3}
CONFIGS=${CONFIGS:-"config/bot_a_4h.yaml config/bot_b_1h.yaml config/bot_c_5names.yaml"}
mkdir -p live run

pidfile() { echo "run/$1.pid"; }
running() { local p; p=$(cat "$(pidfile "$1")" 2>/dev/null) || return 1; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

start_one() {
  local cfg=$1 name; name=$(basename "$cfg" .yaml)
  if running "$name"; then echo "  $name already running (pid $(cat "$(pidfile "$name")"))"; return; fi
  nohup bash -c '
    cfg="$1"; name="$2"; py="$3"
    while true; do
      "$py" -m bot.run "$cfg" >> "live/$name.out" 2>&1
      code=$?
      printf "[%s] exited code=%s, respawning in 10s\n" "$(date -u +%FT%TZ)" "$code" >> "live/$name.out"
      sleep 10
    done
  ' _ "$cfg" "$name" "$PY" >> "live/$name.supervisor.out" 2>&1 &
  echo $! > "$(pidfile "$name")"
  disown 2>/dev/null || true
  echo "  $name started (supervisor pid $!)"
}

stop_one() {
  local name=$1 p
  p=$(cat "$(pidfile "$name")" 2>/dev/null) || { echo "  $name not running"; return; }
  pkill -P "$p" 2>/dev/null
  kill "$p" 2>/dev/null
  pkill -f "bot.run config/$name.yaml" 2>/dev/null
  rm -f "$(pidfile "$name")"
  echo "  $name stopped"
}

case "${1:-start}" in
  start)
    echo "starting:"; for c in $CONFIGS; do start_one "$c"; done
    sleep 3; echo "processes:"; pgrep -f "bot.run config" | sed 's/^/  pid /' || echo "  NONE - check live/*.out"
    ;;
  stop)
    echo "stopping:"; for c in $CONFIGS; do stop_one "$(basename "$c" .yaml)"; done
    ;;
  restart) "$0" stop; sleep 2; "$0" start ;;
  status)
    for c in $CONFIGS; do
      n=$(basename "$c" .yaml)
      if running "$n"; then echo "  $n RUNNING (supervisor $(cat "$(pidfile "$n")"))"; else echo "  $n STOPPED"; fi
    done
    echo "  worker processes: $(pgrep -f 'bot.run config' | wc -l | tr -d ' ')"
    ;;
  report) shift; exec "$PY" -m bot.status "$@" ;;
  trades) shift; exec "$PY" -m bot.blotter --csv "$@" ;;
  dashboard) shift; exec "$PY" -m bot.dashboard "$@" ;;
  *) echo "usage: $0 {start|stop|restart|status|report|trades|dashboard}"; exit 2 ;;
esac
