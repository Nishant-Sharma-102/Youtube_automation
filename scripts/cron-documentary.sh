#!/usr/bin/env bash
#
# Daily documentary auto-pilot (08:00 IST). One fresh episode, fully unattended:
#   refill topics if low -> approve the next draft -> Phases 2-8 -> auto-pick v1 ->
#   finalize -> publish (public) with Hindi+English captions, suspense music,
#   multi-image visuals and the deep Hindi voice.
#
# Idle-safe: any phase that finds nothing to do exits 0. A hard failure in a phase
# aborts the day's run (no half-published video) and is visible in the log.
set -uo pipefail

# Node: nvm dirs on the host, already on PATH inside the container.
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
# ROOT is derived from this script's location so it works on the host AND in the
# /app container. Override with DOC_ROOT if you relocate the repo.
ROOT="${DOC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOC="$ROOT/documentary"
# Prefer the documentary venv; fall back to a container-wide /app/.venv.
PY="$DOC/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: no python venv found ($DOC/.venv or $ROOT/.venv)"; exit 1; }
cd "$DOC"

echo "=========== cron-documentary run: $(date '+%Y-%m-%d %H:%M:%S %Z') ==========="

# 0. Refill the topic queue if we're low on drafts (Phase 1). Non-fatal.
DRAFTS=$($PY -c "import json;print(sum(1 for r in json.load(open('data/topics_mirror.json')) if r.get('status')=='draft'))" 2>/dev/null || echo 0)
echo "drafts available: $DRAFTS"
if [ "$DRAFTS" -lt 2 ]; then
  echo "-- topic queue low; generating more (Phase 1) --"
  $PY generate_topics.py || echo "WARN: topic generation failed; continuing with existing queue."
fi

# 1. Approve exactly one next draft for today (only if nothing is already mid-flight,
#    so a slow/failed previous run isn't stampeded).
$PY - <<'PYEOF'
import json, sys
p = "data/topics_mirror.json"
rows = json.load(open(p))
active = {"approved","script_ready","storyboard_ready","audio_ready","visuals_ready",
          "music_ready","assembly_ready","metadata_ready","ready"}
if any(r.get("status") in active for r in rows):
    print("An episode is already in-flight; not approving a new one. Resuming it.")
    sys.exit(0)
for r in rows:
    if r.get("status") == "draft":
        r["status"] = "approved"; r["approved"] = "yes"
        r["title_choice"] = ""; r["thumbnail_choice"] = ""
        print("Approved today's topic:", r["topic"])
        json.dump(rows, open(p, "w"), ensure_ascii=False, indent=2)
        sys.exit(0)
print("No draft topics left to approve.")
sys.exit(0)
PYEOF

# 2. Run the phases + publish via the shared, flock-locked runner. If a UI-triggered
#    run is already holding the lock, this exits 42 (busy) and today's cron is skipped.
DOC_PUBLISH_PRIVACY="${DOC_PUBLISH_PRIVACY:-public}" "$ROOT/scripts/run-pipeline.sh"
rc=$?
if [ "$rc" -eq 42 ]; then
  echo "A pipeline run is already in progress (UI or a prior cron) — skipping this cron tick."
fi

echo "=========== cron-documentary done: $(date '+%Y-%m-%d %H:%M:%S %Z') (rc=$rc) ==========="
