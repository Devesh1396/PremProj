#!/usr/bin/env bash
# Nightly encrypted backup. A VPS has no backups by default.
# Exits non-zero on any failure so cron mail surfaces it.
#
# Cron:  30 2 * * * /opt/phi/scripts/backup.sh >> /var/log/phi-backup.log 2>&1

set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "FATAL: .env not found"; exit 1; }
set -a; source .env; set +a

STAMP=$(date +%Y-%m-%d-%H%M)
DIR="${BACKUP_DIR:-./backups}"
RETAIN="${BACKUP_RETENTION_DAYS:-30}"
DUMP="$DIR/phi-$STAMP.dump"

mkdir -p "$DIR"
echo "[$(date -Is)] starting backup"

# Custom format: compressed and selectively restorable.
docker compose exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" -Fc > "$DUMP"

SIZE=$(stat -c%s "$DUMP")
# A dump under 100 KB means something went wrong; a valid schema is larger.
if [ "$SIZE" -lt 100000 ]; then
    echo "FATAL: dump is only ${SIZE} bytes, refusing to treat as valid"
    rm -f "$DUMP"; exit 2
fi
echo "  dumped ${SIZE} bytes"

FINAL="$DUMP"
if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
    gpg --yes --batch --encrypt --recipient "$BACKUP_GPG_RECIPIENT" "$DUMP"
    rm -f "$DUMP"
    FINAL="$DUMP.gpg"
    echo "  encrypted to $FINAL"
else
    echo "  WARNING: BACKUP_GPG_RECIPIENT unset, backup is UNENCRYPTED"
fi

# A backup that stays on the same VPS is not a backup.
if [ -n "${BACKUP_REMOTE_TARGET:-}" ]; then
    rsync -a --partial "$FINAL" "$BACKUP_REMOTE_TARGET/" \
      || { echo "FATAL: off-site copy failed"; exit 3; }
    echo "  copied off-site"
else
    echo "  WARNING: BACKUP_REMOTE_TARGET unset. If this VPS is lost, so is this dump."
fi

find "$DIR" -name 'phi-*.dump*' -mtime +"$RETAIN" -delete
echo "[$(date -Is)] backup complete: $FINAL"
