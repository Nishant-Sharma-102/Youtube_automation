#!/usr/bin/env bash
#
# Daily content-generation backfill for the Giggle Grove catalog.
# Invoked by cron. Generates up to N draft episodes per run (2 Gemini requests each),
# staying under the free-tier daily cap. Already-generated episodes are skipped, and
# the run stops cleanly if the quota is hit.
#
# Timed (in crontab) for just after the Gemini free-tier quota resets
# (midnight Pacific ≈ 12:30 PM IST) so each run starts with fresh quota.

set -euo pipefail

# nvm-installed Node is not on cron's default PATH — add it explicitly.
export PATH="/home/user/.nvm/versions/node/v22.22.0/bin:$PATH"

PROJECT_DIR="/home/user/Documents/agentic_ai"
LIMIT="${1:-8}"   # episodes per run; 8 × 2 requests = 16, safely under the 20/day cap

cd "$PROJECT_DIR"
echo "===== cron-generate run: $(date '+%Y-%m-%d %H:%M:%S %Z') (limit=$LIMIT) ====="
npm run generate -- --all --limit "$LIMIT"
