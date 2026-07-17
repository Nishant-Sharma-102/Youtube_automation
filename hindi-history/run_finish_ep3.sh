#!/usr/bin/env bash
set -uo pipefail
HH=/home/user/Documents/agentic_ai/hindi-history
ROOT=/home/user/Documents/agentic_ai
LOG=/tmp/ep3_finish.log
export PATH="/home/user/.nvm/versions/node/v22.22.0/bin:$PATH"
cd "$HH"
echo "=== ep3 finish start $(date '+%F %T %Z') ===" > "$LOG"

echo "--- [1/3] voice (Edge TTS) + music bed ---" >> "$LOG"
if ! .venv/bin/python gen_voice_edge.py --episode 3 --scenes-file data/ep3.json >> "$LOG" 2>&1; then
  echo "RESULT: VOICE_FAILED" >> "$LOG"; exit 1
fi

echo "--- waiting for 9 images ---" >> "$LOG"
for i in $(seq 1 60); do
  [ "$(ls images/ep3_scene*.jpg 2>/dev/null | wc -l)" -ge 9 ] && break
  sleep 5
done

echo "--- [2/3] assemble ---" >> "$LOG"
if ! .venv/bin/python assemble_video.py --episode 3 --scenes-file data/ep3.json >> "$LOG" 2>&1; then
  echo "RESULT: ASSEMBLE_FAILED" >> "$LOG"; exit 1
fi
.venv/bin/python -c "import json;p='data/ep3.json';d=json.load(open(p));d['youtube_video_id']='';d['status']='ready';json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"

echo "--- [3/3] upload PUBLIC ---" >> "$LOG"
cd "$ROOT"
if ! node hindi-history/orchestrator_history.js --privacy public --file data/ep3.json >> "$LOG" 2>&1; then
  echo "RESULT: UPLOAD_FAILED" >> "$LOG"; exit 1
fi
echo "RESULT: SUCCESS" >> "$LOG"
echo "=== ep3 done $(date '+%F %T %Z') ===" >> "$LOG"
