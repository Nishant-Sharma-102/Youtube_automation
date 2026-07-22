#!/usr/bin/env bash
#
# One-command deploy for the documentary channel on EC2 (or any Docker host).
#
#   ./scripts/deploy.sh            # pull latest, (re)build, start the 08:00 daily job
#   ./scripts/deploy.sh once       # ...then immediately produce+publish ONE episode
#
# Prereq (once): a real ./.env file next to docker-compose.yml with your secrets +
# DOC_* settings (copy your deploy.local.env here, or see DOCKER.md).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "== deploy from: $(pwd) =="

# 1. Preflight — the #1 cause of a failed deploy is a missing/malformed .env.
if [ -d .env ]; then
  echo "ERROR: ./.env is a DIRECTORY (Docker created it because the file was missing)."
  echo "  Fix: docker compose down && rm -rf .env, then create the real .env file."
  exit 1
fi
if [ ! -f .env ]; then
  echo "ERROR: ./.env not found. Create it first (copy your deploy.local.env here):"
  echo "  scp deploy.local.env <host>:$(pwd)/.env      # from your local machine"
  exit 1
fi
if ! grep -q '^YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN=..' .env; then
  echo "WARN: YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN looks empty in ./.env —"
  echo "      publishing will fail until it's set."
fi

# 2. Pull latest code (skip if not a git checkout).
if [ -d .git ]; then
  echo "== git pull =="
  git pull --ff-only || echo "(git pull skipped/failed — continuing with local code)"
fi

# 3. Build + start the daily scheduler.
echo "== docker compose up -d --build =="
docker compose up -d --build
docker compose ps

# 4. Optional immediate run.
if [ "${1:-}" = "once" ]; then
  echo "== one-shot: produce + publish one episode now =="
  docker compose run --rm documentary once
fi

echo
echo "✅ Deployed. Daily documentary publishes at 08:00 (container TZ)."
echo "   Watch:  docker compose logs -f"
