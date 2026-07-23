#!/usr/bin/env bash
#
# Shared pipeline runner — used by BOTH the daily cron (cron-documentary.sh) and the
# manual-trigger dashboard (dashboard.py). It runs whatever approved/in-flight episode
# exists through Phases 2-8, auto-picks v1 title/thumbnail, finalizes, and publishes.
#
#   scripts/run-pipeline.sh [privacy]     # privacy: public|unlisted|private
#                                         # falls back to $DOC_PUBLISH_PRIVACY, then public
#
# A single flock ensures the cron run and a UI-triggered run never execute at once.
# Exit codes: 0 = done, 1 = a phase failed, 42 = busy (another run holds the lock).
set -uo pipefail

# Node: nvm dirs on the host, already on PATH inside the container.
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
ROOT="${DOC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOC="$ROOT/documentary"
PY="$DOC/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: no python venv found ($DOC/.venv or $ROOT/.venv)"; exit 1; }
cd "$DOC"
PRIVACY="${1:-${DOC_PUBLISH_PRIVACY:-public}}"

# Single-run lock on the SHARED data volume so it works across the host and both
# containers (cron + webui) that bind-mount ./documentary/data.
mkdir -p data logs
exec 9>"$DOC/data/.pipeline.lock"
if ! flock -n 9; then
  echo "BUSY: another pipeline run is already in progress. Not starting a second."
  exit 42
fi

echo "=========== run-pipeline: $(date '+%Y-%m-%d %H:%M:%S %Z')  privacy=$PRIVACY ==========="
run() { echo; echo "#### $1 ####"; shift; "$@" || { echo "PHASE FAILED — aborting run."; exit 1; }; }
run "P2 script"            "$PY" gen_script.py
run "P3 storyboard"        "$PY" gen_storyboard.py
run "P4 voice"             "$PY" gen_voice.py
run "P5 visuals"           "$PY" gen_visuals.py
run "P6 music"             "$PY" gen_music.py
run "P7 assemble"          "$PY" assemble.py
run "P8 metadata+captions" "$PY" gen_metadata.py

# Auto-pick v1 title/thumbnail on the metadata_ready row, then finalize -> 'ready'.
"$PY" - <<'PYEOF'
import json
p = "data/topics_mirror.json"; rows = json.load(open(p))
for r in rows:
    if r.get("status") == "metadata_ready":
        r["title_choice"] = "v1"; r["thumbnail_choice"] = "v1"
        print("Auto-picked v1/v1 for:", r["topic"]); break
json.dump(rows, open(p, "w"), ensure_ascii=False, indent=2)
PYEOF
run "finalize" "$PY" finalize.py

echo; echo "#### PUBLISH (privacy=$PRIVACY) ####"
node orchestrator_documentary.js --privacy "$PRIVACY"

echo "=========== run-pipeline done: $(date '+%Y-%m-%d %H:%M:%S %Z') ==========="
