#!/usr/bin/env bash
# 8 PM Mon/Wed/Fri/Sun trigger — publishes any 'ready' episode due today.
# Cron runs with a minimal environment, so set PATH explicitly and cd to the project.
set -euo pipefail

# --- adjust these two lines for your EC2 box ---
export PATH="$HOME/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin"
PROJECT_DIR="$HOME/giggle-grove/v2"
# ------------------------------------------------

cd "$PROJECT_DIR"
echo "===== cron-publish $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
# PUBLISH_PRIVACY defaults to 'private' (your test-safe rule). Set it to 'public' in the
# environment (or the crontab line) once you've confirmed episode quality.
npm run publish -- --privacy "${PUBLISH_PRIVACY:-private}"
echo "===== done $(date '+%H:%M:%S') ====="
