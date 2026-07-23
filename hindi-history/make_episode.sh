#!/usr/bin/env bash
# Canonical one-command pipeline for a new episode — runs the phases STRICTLY
# SEQUENTIALLY so nothing writes data/epN.json concurrently (the race that
# corrupted image links + scene durations when images and voice ran in parallel).
#
#   ./make_episode.sh <N> "<topic>" [privacy]
#
# Phases: Claude story -> Pollinations 1080p images -> Edge TTS voice + music bed
# -> assemble -> upload (privacy default: public). Voice is free/uncapped (Edge TTS).
set -euo pipefail
N="${1:?usage: make_episode.sh <N> \"<topic>\" [privacy]}"
TOPIC="${2:?topic required}"
PRIVACY="${3:-public}"
# Derive paths from this script's location so it works on the host AND in the /app
# container (override with DOC_ROOT). Node: nvm on host, already on PATH in-container.
HH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${DOC_ROOT:-$(cd "$HH/.." && pwd)}"
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
# Prefer the hindi-history venv; fall back to a container-wide /app/.venv.
PY="$HH/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: no python venv ($HH/.venv or $ROOT/.venv)"; exit 1; }
cd "$HH"

echo "### [1/5] story (Claude)"
"$PY" gen_episode_claude.py --episode "$N" --topic "$TOPIC"
"$PY" -c "import json;p='data/ep$N.json';d=json.load(open(p));d['title']=d['title_hindi'];d['youtube_video_id']='';json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"

echo "### [2/5] images (Pollinations 1080p)"      # to completion BEFORE voice
"$PY" regen_images.py --episode "$N"

echo "### [3/5] voice + music bed (Edge TTS)"     # writes durations after images
"$PY" gen_voice_edge.py --episode "$N" --scenes-file "data/ep$N.json"

echo "### [4/5] assemble"
"$PY" assemble_video.py --episode "$N" --scenes-file "data/ep$N.json"
"$PY" -c "import json;p='data/ep$N.json';d=json.load(open(p));d['youtube_video_id']='';d['status']='ready';json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"

echo "### [5/5] upload ($PRIVACY)"
cd "$ROOT"
node hindi-history/orchestrator_history.js --privacy "$PRIVACY" --file "data/ep$N.json"
echo "### DONE ep$N"
