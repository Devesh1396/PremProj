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
# ajv is taken away too. It is an optional dependency in exactly the same
# sense, and the branch where node is present but ajv is NOT was reachable
# here and nowhere in CI -- so it crashed rather than skipping, and no job
# noticed for as long as it existed.
#
# The extension files and the ajv modules are always put back, including on
# failure and on Ctrl-C -- a developer machine left permanently unable to
# CREATE EXTENSION would be a bizarre thing to debug a week later.

set -uo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?set DATABASE_URL first: set -a; . ./.env.local; set +a}"

EXTDIR="${PG_EXTENSION_DIR:-$(pg_config --sharedir 2>/dev/null)/extension}"
[ -d "$EXTDIR" ] || EXTDIR=/usr/share/postgresql/16/extension
[ -d "$EXTDIR" ] || { echo "cannot find the extension directory; set PG_EXTENSION_DIR" >&2; exit 1; }

STASH="$(mktemp -d)"
AJV_STASH="$(mktemp -d)"

restore() {
    # mv back only what we actually moved; an empty stash is not an error.
    if [ -n "$(ls -A "$STASH" 2>/dev/null)" ]; then
        mv "$STASH"/* "$EXTDIR"/ 2>/dev/null
    fi
    rmdir "$STASH" 2>/dev/null
    echo "extensions restored to $EXTDIR"
    if [ -n "$(ls -A "$AJV_STASH" 2>/dev/null)" ]; then
        mkdir -p node_modules && mv "$AJV_STASH"/* node_modules/ 2>/dev/null
        echo "ajv restored to node_modules/"
    fi
    rmdir "$AJV_STASH" 2>/dev/null
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
rc=$?

# ---------------------------------------------------------------------
# The second floor: node present, ajv absent.
#
# The parity suites must SKIP loudly, not crash and not pass quietly. A
# suite that passes here without saying it skipped is not detecting the
# absence, which is the same failure in a different disguise.
# ---------------------------------------------------------------------
if command -v node >/dev/null 2>&1; then
    echo
    echo "hiding ajv from node_modules/"
    for mod in ajv ajv-formats; do
        [ -e "node_modules/$mod" ] && mv "node_modules/$mod" "$AJV_STASH"/ \
            && echo "  hid $mod"
    done
    if [ -d node_modules/ajv ]; then
        echo "ajv is still present; this phase is not testing what it claims" >&2
        exit 1
    fi
    for suite in test_contract_registry test_n8n_parity; do
        echo
        echo "=== $suite (node present, ajv absent) ==="
        if ! out=$(python3 "testing/$suite.py" 2>&1); then
            echo "$out"
            echo "  ^^ must SKIP the ajv half, not fail" >&2
            rc=1
            continue
        fi
        echo "$out" | grep -E "SKIP|All checks passed" | tail -5
        echo "$out" | grep -q "SKIP" || {
            echo "  ^^ passed without reporting a SKIP -- it is not detecting" >&2
            echo "     that ajv is missing" >&2
            rc=1
        }
    done
else
    echo
    echo "node is not installed; the ajv floor was NOT tested"
fi

exit $rc
