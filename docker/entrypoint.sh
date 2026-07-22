#!/usr/bin/env bash
# Container entrypoint. Modes:
#   cron  (default) — run supercronic; fires the daily documentary job at 08:00 IST
#   once            — produce + publish one documentary episode right now, then exit
#   shell           — interactive bash (debugging)
set -euo pipefail

# Fail fast if the required secret file wasn't mounted.
if [ -d /app/.env ]; then
  echo "FATAL: /app/.env is a DIRECTORY, not a file." >&2
  echo "  This happens when ./.env did not exist on the host, so Docker created an" >&2
  echo "  empty directory for the bind mount. On the host: 'docker compose down &&" >&2
  echo "  rm -rf .env', then create the real .env file and 'docker compose up -d'." >&2
  exit 1
fi
if [ ! -f /app/.env ]; then
  echo "FATAL: /app/.env not mounted / not found." >&2
  echo "  Create ./.env next to docker-compose.yml (see deploy.local.env / DOCKER.md)," >&2
  echo "  then: docker compose up -d" >&2
  exit 1
fi
# Sanity: the channel's own token must be present (in the single .env or documentary/.env).
if ! grep -q '^YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN=..' /app/.env 2>/dev/null \
   && [ ! -f /app/documentary/.env ]; then
  echo "WARN: YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN not found in /app/.env and no" >&2
  echo "      /app/documentary/.env mounted — publishing will fail until it's set." >&2
fi

case "${1:-cron}" in
  cron)
    echo "[entrypoint] starting supercronic — daily documentary at 08:00 ${TZ:-UTC}"
    exec supercronic /app/docker/crontab
    ;;
  once)
    echo "[entrypoint] one-shot run"
    exec /app/scripts/cron-documentary.sh
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
