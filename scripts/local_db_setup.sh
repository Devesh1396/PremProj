#!/usr/bin/env bash
# Bring up the LOCAL development database, migrate it, and set the runtime
# role passwords. Idempotent: safe to re-run.
#
# This is the local mirror of docs/OPERATIONS.md steps 3-6. It never touches
# docker-compose.yml, the `phi` project, or the n8n network.
#
#   bash scripts/local_db_setup.sh          # up + migrate + roles + verify
#   bash scripts/local_db_setup.sh --reset  # destroy the volume first
#
# Windows: use scripts/local_db_setup.ps1, or run this under Git Bash / WSL.

set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE=docker-compose.local.yml
ENV_FILE=.env.local

if [ ! -f "$ENV_FILE" ]; then
  echo "no $ENV_FILE — copying from .env.local.example"
  cp .env.local.example "$ENV_FILE"
fi

# shellcheck disable=SC1090
set -a; . "./$ENV_FILE"; set +a

: "${POSTGRES_DB:?}" "${POSTGRES_ADMIN_USER:?}" "${POSTGRES_ADMIN_PASSWORD:?}"
: "${POSTGRES_RUNTIME_USER:?}" "${POSTGRES_RUNTIME_PASSWORD:?}"
: "${POSTGRES_PRACTITIONER_USER:?}" "${POSTGRES_PRACTITIONER_PASSWORD:?}"
: "${DATABASE_URL:?}"

dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }
psql_admin() { dc exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" "$@"; }

if [ "${1:-}" = "--reset" ]; then
  echo "== destroying the local volume (development data only) =="
  dc down -v
fi

echo "== 1. up =="
dc up -d

echo "== 2. waiting for healthy =="
for _ in $(seq 1 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' phi-postgres-local 2>/dev/null || echo starting)
  [ "$state" = healthy ] && break
  sleep 2
done
[ "${state:-}" = healthy ] || { echo "postgres did not become healthy"; dc logs --tail=40 postgres; exit 1; }
echo "healthy"

echo "== 3. migrate (admin role, from the host) =="
python3 scripts/migrate.py

# Roles are CREATED by migration 005 with no password (see its section 1),
# so this has to happen after migrate, exactly as on the VPS.
echo "== 4. role passwords =="
psql_admin -c "ALTER ROLE ${POSTGRES_RUNTIME_USER} WITH PASSWORD '${POSTGRES_RUNTIME_PASSWORD}';" >/dev/null
psql_admin -c "ALTER ROLE ${POSTGRES_PRACTITIONER_USER} WITH PASSWORD '${POSTGRES_PRACTITIONER_PASSWORD}';" >/dev/null
echo "set for ${POSTGRES_RUNTIME_USER} and ${POSTGRES_PRACTITIONER_USER}"

echo "== 5. verify roles =="
psql_admin -c "
  SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
    FROM pg_roles
   WHERE rolname IN ('phi_admin','phi_runtime','phi_practitioner')
   ORDER BY rolname;"

# The one property that makes RLS real rather than cosmetic.
psql_admin -t -c "
  SELECT CASE WHEN rolsuper OR rolbypassrls
              THEN 'FAIL: phi_runtime can bypass RLS'
              ELSE 'ok: phi_runtime is NOSUPERUSER NOBYPASSRLS' END
    FROM pg_roles WHERE rolname='phi_runtime';" | grep -q '^ *ok' \
  || { echo "phi_runtime is not correctly constrained"; exit 1; }

echo "== 6. capabilities =="
psql_admin -c "SELECT capability, enabled FROM system_capabilities ORDER BY capability;"

cat <<MSG

Local database ready.

  DATABASE_URL=${DATABASE_URL}

Run the suites with:
  set -a; . ./.env.local; set +a; bash testing/run_all.sh
MSG
