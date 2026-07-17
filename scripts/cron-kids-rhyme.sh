#!/usr/bin/env bash
#
# Daily Giggle Grove kids-rhyme auto-upload (image-based 1080p pipeline).
# Invoked by cron every morning at 08:00 (host local time / IST).
#
# End-to-end for ONE fresh episode:
#   1. pick the next topic from scripts/topics-kids.txt (rotating pointer)
#   2. gen_kids_rhyme.py   -> Claude writes rhyme + SEO metadata (title/desc/hashtags/tags)
#   3. generate_voice.py   -> ElevenLabs narration (chain: ElevenLabs -> Google -> Gemini -> Edge)
#   4. generate_images.py  -> 8x 1920x1080 illustrations (Pollinations, free)
#   5. assemble_video.py   -> renders/epN.mp4 (Ken Burns + captions) + thumbnail
#   6. kids_upload.mjs      -> upload to the channel, made_for_kids=TRUE, privacy=$KIDS_PRIVACY
#
# set -e: if ANY stage fails, the script aborts BEFORE upload — a broken render is
# never published. Logs go to logs/cron-kids-rhyme.log (see crontab redirect).
#
# Env knobs:
#   KIDS_PRIVACY   public (default) | unlisted | private
#   DRY_RUN=1      print the plan (topic, episode #, env presence) and exit — no
#                  generation, no upload, no quota use. Used to validate wiring.

set -euo pipefail

# Resolve the repo root from THIS script's location, so it runs unchanged on the
# host and inside the Docker container (/app). Override with KIDS_ROOT if needed.
ROOT="${KIDS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HH="$ROOT/hindi-history"

# nvm-installed Node isn't on cron's default PATH (host); add it if present.
# In the container Node is already on PATH, so this is a no-op there.
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
PRIVACY="${KIDS_PRIVACY:-public}"
TOPICS_FILE="$ROOT/scripts/topics-kids.txt"
# Kept in the data dir so it persists on the mounted volume (Docker/EC2).
IDX_FILE="$ROOT/hindi-history/data/.kids-topic-index"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$HH/.venv/bin/python"
[ -x "$PY" ] || { echo "no python venv found"; exit 1; }

cd "$HH"

# --- next episode number = max existing epN + 1 ---
LAST="$(ls data/ 2>/dev/null | grep -oE 'ep[0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1 || true)"
EP=$(( ${LAST:-100} + 1 ))

# --- rotating topic selection ---
mapfile -t TOPICS < <(grep -vE '^\s*(#|$)' "$TOPICS_FILE")
N=${#TOPICS[@]}
[ "$N" -gt 0 ] || { echo "topics list is empty"; exit 1; }
IDX="$(cat "$IDX_FILE" 2>/dev/null || echo 0)"
[[ "$IDX" =~ ^[0-9]+$ ]] || IDX=0
TOPIC="${TOPICS[$(( IDX % N ))]}"

# --- ElevenLabs creds from the ROOT .env (kids pipeline's key lives there) ---
set -a
eval "$(grep -E '^ELEVENLABS_(API_KEY|VOICE_ID|MODEL)=' "$ROOT/.env")"
set +a
export HISTORY_ELEVENLABS_VOICE_ID="${ELEVENLABS_VOICE_ID:-}"
export HISTORY_ELEVENLABS_MODEL="${ELEVENLABS_MODEL:-eleven_multilingual_v2}"

echo "===== cron-kids-rhyme $(date '+%F %T %Z')  ep=$EP  privacy=$PRIVACY ====="
echo "topic[$(( IDX % N ))/$N]: $TOPIC"
echo "elevenlabs key: $([ -n "${ELEVENLABS_API_KEY:-}" ] && echo present || echo MISSING); voice id: $([ -n "${ELEVENLABS_VOICE_ID:-}" ] && echo present || echo MISSING)"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1 — plan only, no generation/upload. (topic pointer NOT advanced)"
  exit 0
fi

# advance the topic pointer only for a real run
echo $(( (IDX + 1) % N )) > "$IDX_FILE"

SF="data/ep${EP}.json"
"$PY" gen_kids_rhyme.py  --episode "$EP" --topic "$TOPIC"
"$PY" generate_voice.py  --episode "$EP" --scenes-file "$SF"
"$PY" generate_images.py --episode "$EP" --scenes-file "$SF" --delay 1
"$PY" assemble_video.py  --episode "$EP" --scenes-file "$SF" --thumb-scene 1

cd "$ROOT"
node kids_upload.mjs "$EP" "$PRIVACY"
echo "===== done ep=$EP $(date '+%F %T %Z') ====="
