#!/usr/bin/env bash
# Run the full suite with NO optional extension available (D15 floor).
#
# The CI job `bare` does this by deleting the contrib control files inside
# the Postgres service container. This is the same thing for a local
# server, and it exists because the alternative -- trusting that the
# degradation branches still work -- is what let steps 12 and 13 ship an
# ungated similarity() call that killed the K1 seeder outright.
#
# pg_trgm and btree_gin are CONTRIB and ship with every PostgreSQL, so
# their absence cannot be tested by choosing a different image or a
# different server. It can only be tested by taking them away.
#
# DESTRUCTIVE: drops and rebuilds the public schema of $DATABASE_URL. Point
# it at the local throwaway database, never at anything real.
#
#   set -a; . ./.env.local; set +a
#   bash testing/run_bare.sh
#
# The extension files are always put back, including on failure and on
# Ctrl-C -- a developer machine left permanently unable to CREATE EXTENSION
# would be a bizarre thing to debug a week later.

set -uo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?set DATABASE_URL first: set -a; . ./.env.local; set +a}"

EXTDIR="${PG_EXTENSION_DIR:-$(pg_config --sharedir 2>/dev/null)/extension}"
[ -d "$EXTDIR" ] || EXTDIR=/usr/share/postgresql/16/extension
[ -d "$EXTDIR" ] || { echo "cannot find the extension directory; set PG_EXTENSION_DIR" >&2; exit 1; }

STASH="$(mktemp -d)"

restore() {
    # mv back only what we actually moved; an empty stash is not an error.
    if [ -n "$(ls -A "$STASH" 2>/dev/null)" ]; then
        mv "$STASH"/* "$EXTDIR"/ 2>/dev/null
    fi
    rmdir "$STASH" 2>/dev/null
    echo "extensions restored to $EXTDIR"
}
trap restore EXIT INT TERM

echo "hiding optional extensions from $EXTDIR"
for ext in vector pg_trgm btree_gin; do
    mv "$EXTDIR"/$ext* "$STASH"/ 2>/dev/null && echo "  hid $ext"
done

echo "rebuilding the public schema"
psql "$DATABASE_URL" -q \
  -c "drop schema if exists public cascade" \
  -c "create schema public" \
  -c "grant usage on schema public to phi_runtime, phi_practitioner" >/dev/null 2>&1

python3 scripts/migrate.py >/dev/null || { echo "migrations failed" >&2; exit 1; }

echo "recorded capabilities:"
psql "$DATABASE_URL" -tA -F'  ' \
  -c "select capability, enabled from system_capabilities order by 1" 2>/dev/null

still_on=$(psql "$DATABASE_URL" -tAc \
  "select count(*) from system_capabilities where enabled" 2>/dev/null)
if [ "${still_on:-1}" != "0" ]; then
    echo "an optional extension is still available -- this run is not testing" >&2
    echo "the D15 floor it claims to test" >&2
    exit 1
fi

bash testing/run_all.sh
