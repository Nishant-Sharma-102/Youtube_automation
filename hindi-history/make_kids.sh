#!/usr/bin/env bash
# Illustrated kids-rhyme pipeline -> KIDS channel (made_for_kids=TRUE).
#   ./make_kids.sh <N> "<topic>" [privacy]
set -euo pipefail
N="${1:?}"; TOPIC="${2:?}"; PRIVACY="${3:-public}"
HH=/home/user/Documents/agentic_ai/hindi-history; ROOT=/home/user/Documents/agentic_ai
export PATH="/home/user/.nvm/versions/node/v22.22.0/bin:$PATH"
# --- kids look & voice ---
export HISTORY_IMG_STYLE="cute colorful 3D cartoon, children's animation style, adorable big-eyed baby fox and animal friends, bright cheerful colors, soft rounded shapes, sunny meadow, Pixar-like storybook, no text, no watermark"
export HISTORY_EDGE_VOICE="en-US-JennyNeural"   # warm, friendly, clear
export HISTORY_EDGE_RATE="+5%"
export HISTORY_EDGE_PITCH="+6Hz"                # a touch brighter/cheerful
export HISTORY_MUSIC_BED="0"                    # dark drone unsuitable for kids
cd "$HH"
echo "### story";  .venv/bin/python gen_kids_rhyme.py --episode "$N" --topic "$TOPIC"
echo "### images"; .venv/bin/python regen_images.py --episode "$N"
echo "### voice";  .venv/bin/python gen_voice_edge.py --episode "$N" --scenes-file "data/ep$N.json"
echo "### assemble"; .venv/bin/python assemble_video.py --episode "$N" --scenes-file "data/ep$N.json"
echo "### upload (KIDS channel, made_for_kids=TRUE, $PRIVACY)"
cd "$ROOT"; node kids_upload.mjs "$N" "$PRIVACY"
echo "### DONE kids ep$N"
