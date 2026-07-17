#!/usr/bin/env bash
# Container entrypoint. Modes:
#   cron  (default) — run supercronic; fires the daily job at 08:00 IST
#   once            — generate + upload one episode right now, then exit
#   shell           — interactive bash (debugging)
set -euo pipefail

# Fail fast if the required secret file wasn't mounted.
if [ ! -f /app/.env ]; then
  echo "FATAL: /app/.env not mounted. Run with: -v \$(pwd)/.env:/app/.env:ro" >&2
  exit 1
fi

case "${1:-cron}" in
  cron)
    echo "[entrypoint] starting supercronic — daily kids-rhyme at 08:00 ${TZ:-UTC}"
    exec supercronic /app/docker/crontab
    ;;
  once)
    echo "[entrypoint] one-shot run"
    exec /app/scripts/cron-kids-rhyme.sh
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
