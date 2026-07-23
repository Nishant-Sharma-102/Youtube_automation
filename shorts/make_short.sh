#!/usr/bin/env bash
# Canonical one-command pipeline for a new YouTube Short.
#
#   ./make_short.sh "<topic>" [privacy] [id]
#
# Generates a fresh short-form script (Claude) -> vertical 1080x1920 images
# (Pollinations) -> voice (ElevenLabs/Google/Edge) -> assemble a vertical Ken-Burns
# video with burned captions + optional music -> upload as a Short (privacy default:
# private, so you can review it before flipping to public).
#
# It REUSES the documentary channel's modules + venv + token; the only difference is
# the VERTICAL dimensions forced below.
set -euo pipefail
TOPIC="${1:?usage: make_short.sh \"<topic>\" [privacy] [id]}"
PRIVACY="${2:-private}"
ID_ARG="${3:-}"

# Derive paths from this script's location so it works on the host AND in the /app
# container (override with DOC_ROOT). Node: nvm on host, already on PATH in-container.
SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${DOC_ROOT:-$(cd "$SH/.." && pwd)}"
for d in /home/user/.nvm/versions/node/*/bin; do [ -d "$d" ] && export PATH="$d:$PATH"; done
# Reuse the documentary venv (its deps: httpx, edge-tts, mutagen, Pillow, mcp sdk).
PY="$ROOT/documentary/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: no python venv (documentary/.venv or $ROOT/.venv)"; exit 1; }

# ── VERTICAL 9:16 — this is what makes it a Short. Overrides the documentary 16:9. ──
export DOC_VIDEO_W=1080 DOC_VIDEO_H=1920
export DOC_POLLINATIONS_WIDTH=1080 DOC_POLLINATIONS_HEIGHT=1920
# Punchier narration for a Short than the deep, slow documentary voice (overridable).
export DOC_EDGE_RATE="${DOC_EDGE_RATE:-+2%}" DOC_EDGE_PITCH="${DOC_EDGE_PITCH:-+0Hz}"
export SHORTS_PUBLISH_PRIVACY="$PRIVACY"

cd "$SH"
ID_FLAG=(); [ -n "$ID_ARG" ] && ID_FLAG=(--id "$ID_ARG")

echo "### [1/2] generate short (script -> images -> voice -> assemble)"
"$PY" gen_short.py "$TOPIC" "${ID_FLAG[@]}"

echo "### [2/2] upload ($PRIVACY)"
cd "$ROOT"
node shorts/orchestrator_shorts.js --privacy "$PRIVACY"
echo "### DONE short"
