#!/usr/bin/env bash
# Nightly encrypted backup. A VPS has no backups by default.
# Exits non-zero on any failure so cron mail surfaces it.
#
# Cron:  30 2 * * * /opt/phi/scripts/backup.sh >> /var/log/phi-backup.log 2>&1

set -euo pipefail

cd "$(dirname "$0")/.."

# PHI_ENV_FILE lets the restore drill run this script against a development
# database without a .env. Production is unchanged: default is .env.
ENV_FILE="${PHI_ENV_FILE:-.env}"
[ -f "$ENV_FILE" ] || { echo "FATAL: $ENV_FILE not found"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# docker  — the VPS: postgres runs in a container with no published port.
# direct  — a host-reachable server, which is how the drill exercises this.
MODE="${BACKUP_PG_MODE:-docker}"

STAMP=$(date +%Y-%m-%d-%H%M)
DIR="${BACKUP_DIR:-./backups}"
RETAIN="${BACKUP_RETENTION_DAYS:-30}"
DUMP="$DIR/phi-$STAMP.dump"
ROLES="$DIR/phi-$STAMP.roles.sql"

mkdir -p "$DIR"
echo "[$(date -Is)] starting backup (mode: $MODE)"

pg() {  # pg <pg_dump|pg_dumpall> <args...>
    local tool="$1"; shift
    case "$MODE" in
      docker) docker compose exec -T postgres "$tool" -U "$POSTGRES_ADMIN_USER" "$@" ;;
      direct) PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" "$tool" \
                  -h "${POSTGRES_HOST:-127.0.0.1}" -p "${POSTGRES_PORT:-5432}" \
                  -U "$POSTGRES_ADMIN_USER" "$@" ;;
      *) echo "FATAL: BACKUP_PG_MODE must be docker or direct, got '$MODE'"; exit 1 ;;
    esac
}

# ---------------------------------------------------------------------
# 1. Roles. THE DATABASE DUMP DOES NOT CONTAIN THEM.
# ---------------------------------------------------------------------
# pg_dump dumps one database; roles are cluster-wide, so they are not in it.
# Restoring onto a fresh machine without them fails every GRANT and every
# CREATE POLICY -- measured on the 2026-09-10 drill: 298 errors, all 52 RLS
# policies among them. The data lands and the access controls do not, and
# pg_restore's exit code is easy to miss because the tables look populated.
#
# --no-role-passwords deliberately: the backup then carries no credentials
# at all. Passwords come from .env at restore time, exactly as they do at
# first install (docs/OPERATIONS.md step 5), so a leaked dump is client data
# to protect rather than client data plus the keys to it.
pg pg_dumpall --roles-only --no-role-passwords > "$ROLES"
if ! grep -q "CREATE ROLE phi_runtime" "$ROLES"; then
    echo "FATAL: roles dump does not contain phi_runtime; refusing to treat as valid"
    rm -f "$ROLES"; exit 2
fi
echo "  roles dumped ($(stat -c%s "$ROLES") bytes)"

# ---------------------------------------------------------------------
# 2. The database. Custom format: compressed and selectively restorable.
# ---------------------------------------------------------------------
pg pg_dump -d "$POSTGRES_DB" -Fc > "$DUMP"

SIZE=$(stat -c%s "$DUMP")
# A dump under 100 KB means something went wrong; a valid schema is larger.
if [ "$SIZE" -lt 100000 ]; then
    echo "FATAL: dump is only ${SIZE} bytes, refusing to treat as valid"
    rm -f "$DUMP" "$ROLES"; exit 2
fi
echo "  dumped ${SIZE} bytes"

# ---------------------------------------------------------------------
# 3. Encrypt, copy off-site, prune. Both files travel together: a database
#    dump without its roles is not a restorable backup.
# ---------------------------------------------------------------------
FINAL=("$DUMP" "$ROLES")
if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
    for f in "$DUMP" "$ROLES"; do
        gpg --yes --batch --encrypt --recipient "$BACKUP_GPG_RECIPIENT" "$f"
        rm -f "$f"
    done
    FINAL=("$DUMP.gpg" "$ROLES.gpg")
    echo "  encrypted to ${FINAL[*]}"
else
    echo "  WARNING: BACKUP_GPG_RECIPIENT unset, backup is UNENCRYPTED"
fi

# A backup that stays on the same VPS is not a backup.
if [ -n "${BACKUP_REMOTE_TARGET:-}" ]; then
    rsync -a --partial "${FINAL[@]}" "$BACKUP_REMOTE_TARGET/" \
      || { echo "FATAL: off-site copy failed"; exit 3; }
    echo "  copied off-site"
else
    echo "  WARNING: BACKUP_REMOTE_TARGET unset. If this VPS is lost, so is this dump."
fi

find "$DIR" -name 'phi-*.dump*' -mtime +"$RETAIN" -delete
find "$DIR" -name 'phi-*.roles.sql*' -mtime +"$RETAIN" -delete
echo "[$(date -Is)] backup complete: ${FINAL[*]}"
