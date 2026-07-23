#!/usr/bin/env bash
#
# Daily Shorts auto-pilot. Generates + uploads N vertical YouTube Shorts, fully
# unattended. Default: 2 shorts per run, one per pillar (rotated), 10:00 IST.
#
#   SHORTS_PER_RUN=2                # how many shorts to make this run
#   SHORTS_PUBLISH_PRIVACY=public   # public|unlisted|private  (see note below)
#
# Each short: AI-suggested topic -> Claude short script -> vertical 1080x1920 visuals
# -> voice -> assemble (burned captions + optional music) -> upload as a Short with
# public like/view stats HIDDEN. Publishes to the SAME channel as the documentary
# pipeline (its token).
#
# Idle/failure-safe: a failure on one short is logged and does NOT abort the others.
set -uo pipefail

# Node: nvm dirs on the host, already on PATH inside the container.
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
ROOT="${DOC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="$ROOT/documentary/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: no python venv (documentary/.venv or $ROOT/.venv)"; exit 1; }

COUNT="${SHORTS_PER_RUN:-2}"
PRIVACY="${SHORTS_PUBLISH_PRIVACY:-public}"
# Rotate through the documentary pillars so the day's shorts aren't all the same theme.
PILLARS=("History" "Mysteries" "Science & Space" "Alternate History")

echo "=========== cron-shorts run: $(date '+%Y-%m-%d %H:%M:%S %Z')  count=$COUNT privacy=$PRIVACY ==========="

for i in $(seq 1 "$COUNT"); do
  pillar="${PILLARS[$(( (i - 1) % ${#PILLARS[@]} ))]}"
  echo; echo "#### short $i/$COUNT — pillar: $pillar ####"

  topic="$(cd "$ROOT/documentary" && "$PY" suggest_topic.py --pillar "$pillar" 2>/dev/null || true)"
  if [ -z "$topic" ]; then
    echo "WARN: no topic suggested for '$pillar' — skipping this one."
    continue
  fi
  echo "topic: $topic"

  if bash "$ROOT/shorts/make_short.sh" "$topic" "$PRIVACY"; then
    echo "short $i done."
  else
    echo "WARN: short $i failed (topic: $topic) — continuing with the rest."
  fi
done

echo "=========== cron-shorts done: $(date '+%Y-%m-%d %H:%M:%S %Z') ==========="
