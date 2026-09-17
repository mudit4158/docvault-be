#!/usr/bin/env bash
# Runs the existing scripts/purge_trash.py inside the running `api` container.
#
# Deliberately NOT wired into cron by this deploy — see the deployment plan.
# During the trial period, run it manually as needed:
#   ./purge_trash.sh
# Once there's real user data worth purging on a schedule, add it yourself:
#   crontab -e
#   0 3 * * * cd /path/to/docvault-be && ./purge_trash.sh >> /var/log/docvault-purge.log 2>&1
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose exec -T api python scripts/purge_trash.py
