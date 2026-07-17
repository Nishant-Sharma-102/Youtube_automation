#!/usr/bin/env bash
#
# Scheduled publish job (brief §4.5). Publishes any 'ready' episode whose
# scheduled_date is on/before today, then marks it 'published'.
#
# Schedule: 11:00 UTC on Mon/Wed/Fri/Sun (see src/publish-config.ts) = 16:30 IST.
# Because system cron runs in the host's local timezone (IST here), the crontab
# entry uses 30 16 ... — the IST equivalent of 11:00 UTC.
#
# Idle-safe: if nothing is 'ready', it logs a warning and exits cleanly.

set -euo pipefail

# nvm-installed Node is not on cron's default PATH — add it explicitly.
export PATH="/home/user/.nvm/versions/node/v22.22.0/bin:$PATH"

PROJECT_DIR="/home/user/Documents/agentic_ai"
cd "$PROJECT_DIR"
echo "===== cron-publish run: $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
npm run publish
