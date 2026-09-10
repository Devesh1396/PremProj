#!/usr/bin/env bash
# LOCAL n8n FOR WORKFLOW DEVELOPMENT AND PARITY TESTING — throwaway.
#
# docker-compose.yml is NOT touched by this script and must not be. It is
# the VPS deployment, documented in docs/OPERATIONS.md: it joins n8n's
# existing external network and publishes no port. This is a separate,
# disposable n8n installed from npm, used to import a workflow, execute it
# headlessly and compare the result against the Python reference.
#
# npm rather than Docker on purpose. It is the only route that works in
# every environment this repo has been built in so far: the container
# registries (docker.n8n.io, Docker Hub's blob CDN) are blocked behind
# some egress proxies, and the npm registry is not.
#
# NO n8n CREDENTIALS ARE REQUIRED, and none should be created here. The
# workflow reads its Postgres credential from the local n8n's own
# credential store, seeded from .env.local by --seed-credentials, and its
# LLM key from the environment. Nothing in this script touches the VPS.
#
# Usage:
#   bash scripts/local_n8n.sh install            # npm install n8n (~2.5 GB)
#   bash scripts/local_n8n.sh seed-credentials   # Postgres credential from .env.local
#   bash scripts/local_n8n.sh import <file.json> # import/replace a workflow
#   bash scripts/local_n8n.sh execute <id>       # run it headlessly, JSON to stdout
#   bash scripts/local_n8n.sh version
#
# N8N_HOME defaults to a directory OUTSIDE the repository, so 2.5 GB of
# node_modules never lands in the working tree or a commit.

set -euo pipefail

# PINNED. `npm install n8n` unpinned picked up 2.35.7 on 2026-09-10 and would
# pick up something else tomorrow. Workflow JSON is version-sensitive -- node
# `typeVersion` values and the CLI surface both move across majors, and 2.x
# already dropped `execute --file` -- so a parity result proven against an
# unpinned install proves nothing reproducible.
#
# Raise this deliberately, re-run the parity suite, and record the result.
# Do NOT let it float.
N8N_VERSION="${N8N_VERSION:-2.35.7}"

# The VPS runs its own n8n and this pin does not change it. If the two differ
# across a major, a workflow proven here may not import there. See
# docs/OPERATIONS.md "n8n version" for how to check.
N8N_HOME="${N8N_HOME:-${TMPDIR:-/tmp}/premproj-n8n}"
N8N_BIN="$N8N_HOME/node_modules/.bin/n8n"

# This n8n is a test harness on a machine behind a proxy that returns 405
# for telemetry. Left on, every command ends in a wall of Rudderstack
# stack traces that bury the workflow output.
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_VERSION_NOTIFICATIONS_ENABLED=false
export N8N_TEMPLATES_ENABLED=false
export N8N_RUNNERS_ENABLED=false
export N8N_USER_FOLDER="${N8N_USER_FOLDER:-$N8N_HOME/.n8n}"
# ajv ships inside n8n. The control contract is validated against the SAME
# stored schema document the Python reference uses, by a second
# implementation of the same standard -- which is the point: one schema,
# two validators, one parity suite.
export NODE_FUNCTION_ALLOW_EXTERNAL="${NODE_FUNCTION_ALLOW_EXTERNAL:-ajv,ajv-formats}"

cmd="${1:-help}"

case "$cmd" in
install)
    mkdir -p "$N8N_HOME"
    cd "$N8N_HOME"
    [ -f package.json ] || npm init -y >/dev/null
    echo "installing n8n@$N8N_VERSION into $N8N_HOME (several minutes)"
    npm install "n8n@$N8N_VERSION" --no-audit --no-fund
    installed="$("$N8N_BIN" --version)"
    echo "n8n $installed"
    if [ "$installed" != "$N8N_VERSION" ]; then
        echo "expected n8n $N8N_VERSION, got $installed -- the pin did not hold" >&2
        exit 1
    fi
    ;;

version)
    [ -x "$N8N_BIN" ] || { echo "n8n not installed. Run: bash scripts/local_n8n.sh install" >&2; exit 1; }
    installed="$("$N8N_BIN" --version)"
    echo "$installed"
    # Loud, because a drifted local install silently invalidates every
    # parity result the suite reports.
    [ "$installed" = "$N8N_VERSION" ] || {
        echo "WARNING: pinned to $N8N_VERSION but $installed is installed." >&2
        echo "Reinstall, or change N8N_VERSION deliberately and re-run parity." >&2
        exit 1
    }
    ;;

seed-credentials)
    # Written from .env.local, never from .env and never from anything on
    # the VPS. The local database holds synthetic data only.
    [ -f .env.local ] || { echo ".env.local not found; see docker-compose.local.yml" >&2; exit 1; }
    set -a; . ./.env.local; set +a
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    cat > "$tmp/creds.json" <<JSON
[{
  "id": "premprojphiruntime01",
  "name": "phi_runtime (local)",
  "type": "postgres",
  "data": {
    "host": "${POSTGRES_HOST:-127.0.0.1}",
    "port": ${POSTGRES_PORT:-55432},
    "database": "${POSTGRES_DB:-phi}",
    "user": "${POSTGRES_RUNTIME_USER:-phi_runtime}",
    "password": "${POSTGRES_RUNTIME_PASSWORD}",
    "ssl": "disable"
  }
}]
JSON
    "$N8N_BIN" import:credentials --input="$tmp/creds.json" --decrypted 2>&1 | grep -v '^\[' || true
    echo "seeded credential: phi_runtime (local)"
    ;;

import)
    file="${2:?usage: local_n8n.sh import <file.json>}"
    # n8n 2.x dropped `execute --file`; a workflow must be imported and
    # then executed by id. The file therefore carries a stable id.
    "$N8N_BIN" import:workflow --input="$file" 2>&1 | grep -vE '^\[|Rudder|Axios|^\s+at ' || true
    ;;

execute)
    id="${2:?usage: local_n8n.sh execute <workflow-id>}"
    # --rawOutput promises "only JSON data, with no other text" and does not
    # deliver it: n8n prints node-loading warnings and task-broker notices
    # to stdout before the payload. A parity harness that json.loads() the
    # output needs it to actually be JSON, so trim to the first brace.
    "$N8N_BIN" execute --id="$id" --rawOutput 2>/dev/null | sed -n '/^{/,$p'
    ;;

*)
    sed -n '2,30p' "$0"
    ;;
esac
