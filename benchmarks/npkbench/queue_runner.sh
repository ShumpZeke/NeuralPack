#!/bin/sh
# Sequential experiment queue. Each non-comment line of the queue file is
#     WORKDIR|ENV|ARGS
# and runs  (cd WORKDIR && env ENV python -m benchmarks.npkbench.run ARGS)  with the repository's
# virtualenv. A line whose --out directory already holds summary.json, or whose failure marker
# exists under $NPK_BENCH_HOME/failed/, is skipped. The queue file is re-read after every run, so
# lines may be appended or reordered while it runs, and the runner exits when nothing is left.
# Runs stage their output in "<out>.partial" (see run.py), so nothing unfinished looks like a result;
# an interrupted run (a VM restart kills the runner) is redone from scratch when the runner is
# started again:
#     (nohup sh benchmarks/npkbench/queue_runner.sh >> $NPK_BENCH_HOME/queue.log 2>&1 &)
# Check that it is alive with  ps -eo pid,args | grep -E '^ *[0-9]+ /bin/sh .*queue_runner'
# (never pgrep -f: it matches its own command line).
#
# Environment: NPK_BENCH_HOME (default ~/npk-data) holds the datasets, clones, packs and queue.txt;
# QUEUE overrides the queue file; NPK_VENV overrides the virtualenv (default <repo>/.venv).
REPO=$(cd "$(dirname "$0")/../.." && pwd)
export NPK_BENCH_HOME="${NPK_BENCH_HOME:-$HOME/npk-data}"
QUEUE="${QUEUE:-$NPK_BENCH_HOME/queue.txt}"
VENV="${NPK_VENV:-$REPO/.venv}"
FAILED="$NPK_BENCH_HOME/failed"
mkdir -p "$FAILED"
while true; do
  while ps -eo args | grep -q "^python -m benchmarks.npkbench.run"; do sleep 15; done
  next=""
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue;; esac
    out=$(printf '%s' "$line" | sed -n 's/.*--out \([^ ]*\).*/\1/p')
    wd=$(printf '%s' "$line" | cut -d'|' -f1)
    case "$out" in /*) full="$out";; *) full="$wd/$out";; esac
    marker="$FAILED/$(basename "$full")"
    if [ ! -f "$full/summary.json" ] && [ ! -f "$marker" ]; then next="$line"; break; fi
  done < "$QUEUE"
  [ -z "$next" ] && { echo "queue empty $(date)"; exit 0; }
  wd=$(printf '%s' "$next" | cut -d'|' -f1); envs=$(printf '%s' "$next" | cut -d'|' -f2); args=$(printf '%s' "$next" | cut -d'|' -f3-)
  echo "=== $(date) START $args"
  ( cd "$wd" && . "$VENV/bin/activate" && env $envs python -m benchmarks.npkbench.run $args ) || {
      out=$(printf '%s' "$args" | sed -n 's/.*--out \([^ ]*\).*/\1/p')
      date > "$FAILED/$(basename "$out")"; echo "=== FAILED $args"; }
  echo "=== $(date) END"
done
