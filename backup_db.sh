#!/usr/bin/env bash
# Dumps the `db` container to a gzipped file under ./backups/, then uploads
# it to the storage bucket's backups/ prefix via the `api` container (which
# already has the ADC identity + google-cloud-storage client — see
# scripts/upload_backup.py). Old local dumps are pruned after upload.
#
# Deliberately NOT wired into cron by this deploy — see the deployment plan.
# During the trial period, run it manually as needed:
#   ./backup_db.sh
# Once there's real user data worth protecting on a schedule, add it
# yourself:
#   crontab -e
#   0 2 * * * cd /path/to/docvault-be && ./backup_db.sh >> /var/log/docvault-backup.log 2>&1
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

mkdir -p backups
timestamp="$(date +%Y%m%d-%H%M%S)"
dump_file="backups/docvault-${timestamp}.sql.gz"

docker compose exec -T db pg_dump -U docvault docvault | gzip > "$dump_file"
docker compose exec -T api python scripts/upload_backup.py "/app/${dump_file}"

# Keep the 7 most recent local dumps; the bucket is the durable copy.
ls -1t backups/*.sql.gz | tail -n +8 | xargs -r rm --

echo "Backed up to gs://.../${dump_file}"
