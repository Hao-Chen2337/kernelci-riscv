#!/usr/bin/env bash
# Stop this deployment: the host services it started, then the docker compose stack.
#
#     deploy/stop.sh
#
# This is `./run.sh stop` moved into `deploy/`.  It stops what the deployment
# *recorded* (`var/state/stack-<project>.pids`: role|pid|start-time|pattern, so a
# recycled pid survives), and falls back to pattern matching - loudly, naming what
# it is about to hit - when there is no record.  Compose data stays in volumes.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

die() { echo "X $*" >&2; exit 1; }
ok()  { echo "OK $*"; }

stop_recorded_services() {
   # pid-file
  local file="$1" role pid start pattern now killed=0
  while IFS='|' read -r role pid start pattern; do
    [ -n "${pid:-}" ] || continue
    if [ ! -d "/proc/$pid" ]; then
      echo "  $role: pid $pid is gone already"
      continue
    fi
    now="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
    if [ "$now" != "$start" ]; then
      echo "  !! $role: pid $pid now belongs to an unrelated process (start time changed); NOT killing it"
      continue
    fi
    if kill "$pid" 2>/dev/null; then
      echo "  $role stopped (pid $pid)"
      killed=$((killed + 1))
    else
      echo "  !! $role (pid $pid) could not be killed - check it by hand: ps -p $pid -o args="
    fi
  done < "$file"
  echo "  $killed host service(s) stopped from $file"
}

  # Same overridable identity as the stack: one machine can host several isolated
  # deployments, and stopping one must not stop another.
  project="${KCI_COMPOSE_PROJECT:-kcirv}"
  serve_port="${KCI_SERVE_PORT:-8999}"
  cb_port="${KCI_CB_PORT:-8003}"
  sched_conf="/tmp/kcisched-$project"
  pid_file="$ROOT/var/state/stack-$project.pids"
  rc=0
  # These used to be machine-global pkill patterns that killed another deployment's
  # scheduler, callback and artifact server (the compose teardown below was already
  # project-scoped, #18).
  if [ -f "$pid_file" ]; then
    stop_recorded_services "$pid_file"
  else
    # No record (started before pids were recorded, or by another checkout): say
    # so, show what pattern matching is about to hit, then do it - a stop that
    # quietly stops nothing would be worse.
    echo "  !! no service ownership record at $pid_file: this deployment cannot prove"
    echo "     which processes are its own, so it falls back to pattern matching,"
    echo "     which can also match ANOTHER deployment's services:"
    pgrep -af "scheduler\.py.*--yaml-config $sched_conf/" 2>/dev/null | sed 's/^/       /'
    pgrep -af "uvicorn lava_callback.*--port $cb_port" 2>/dev/null | sed 's/^/       /'
    pgrep -af "http\.server $serve_port" 2>/dev/null | sed 's/^/       /'
    pkill -f "scheduler.py.*--yaml-config $sched_conf/" 2>/dev/null && echo "  scheduler stopped"
    pkill -f "uvicorn lava_callback.*--port $cb_port" 2>/dev/null && echo "  callback stopped"
    pkill -f "http.server $serve_port" 2>/dev/null && echo "  artifact server stopped"
  fi
  # API stack (api/db/redis/storage/ssh) runs under docker compose; data stays
  # in volumes, a later stack brings it back as-is.
  if [ ! -d "$ROOT/kernelci-api" ]; then
    echo "  (no kernelci-api checkout: no compose project to stop)"
  else
    out=""
    if out="$(cd "$ROOT/kernelci-api" && docker compose -p "$project" -f docker-compose.yaml down 2>&1)"; then
      echo "API stack stopped (project $project)"
    else
      # The branch had no else: a failed compose down printed nothing and the
      # reader believed the stack was down while its containers kept running (#14).
      echo "X 'docker compose -p $project down' FAILED - containers of project $project may still be up:"
      printf '%s\n' "$out" | sed 's/^/    /'
      echo "    inspect with: docker compose -p $project -f $ROOT/kernelci-api/docker-compose.yaml ps"
      rc=1
    fi
  fi
  # `exit`, not `return`: this was `./run.sh stop`'s function and it is a script
  # now.  The status is the point - a compose teardown that failed must not read as
  # "the stack is down" (that was #14, and the message above names the project).
  exit "$rc"
