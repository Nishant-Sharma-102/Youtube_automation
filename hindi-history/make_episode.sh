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
HH=/home/user/Documents/agentic_ai/hindi-history
ROOT=/home/user/Documents/agentic_ai
export PATH="/home/user/.nvm/versions/node/v22.22.0/bin:$PATH"
cd "$HH"

echo "### [1/5] story (Claude)"
.venv/bin/python gen_episode_claude.py --episode "$N" --topic "$TOPIC"
.venv/bin/python -c "import json;p='data/ep$N.json';d=json.load(open(p));d['title']=d['title_hindi'];d['youtube_video_id']='';json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"

echo "### [2/5] images (Pollinations 1080p)"      # to completion BEFORE voice
.venv/bin/python regen_images.py --episode "$N"

echo "### [3/5] voice + music bed (Edge TTS)"     # writes durations after images
.venv/bin/python gen_voice_edge.py --episode "$N" --scenes-file "data/ep$N.json"

echo "### [4/5] assemble"
.venv/bin/python assemble_video.py --episode "$N" --scenes-file "data/ep$N.json"
.venv/bin/python -c "import json;p='data/ep$N.json';d=json.load(open(p));d['youtube_video_id']='';d['status']='ready';json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"

echo "### [5/5] upload ($PRIVACY)"
cd "$ROOT"
node hindi-history/orchestrator_history.js --privacy "$PRIVACY" --file "data/ep$N.json"
echo "### DONE ep$N"
