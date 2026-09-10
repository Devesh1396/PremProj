#!/usr/bin/env bash
# Full verification. Requires DATABASE_URL.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
echo "=== migrations ==="
python3 scripts/migrate.py || fail=1
for t in concept_layer knowledge_layer client_layer run_engine case_events knowledge_inbox prompt_contracts measurement intake normalization ontology_seed; do
  echo
  echo "=== $t ==="
  out=$(python3 "testing/test_$t.py" 2>&1); rc=$?
  echo "$out" | tail -3
  [ $rc -eq 0 ] || { fail=1; echo "  ^^ SUITE FAILED (exit $rc)"; }
done
echo
echo "=== idempotency ==="
python3 scripts/migrate.py
echo
if [ $fail -eq 0 ]; then echo "ALL SUITES PASSED"; else echo "FAILURES PRESENT"; fi
exit $fail
