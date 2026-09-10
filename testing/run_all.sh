#!/usr/bin/env bash
# Full verification. Requires DATABASE_URL.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
echo "=== migrations ==="
python3 scripts/migrate.py || fail=1
echo
echo "=== prompt registry ==="
# D23: the prompts are rows now, and test_run_engine deliberately replaces
# them with stubs. Reload the canonical seven before every run so a suite
# that died mid-way cannot leave stub specifications active.
python3 scripts/load_prompts.py | tail -9 || fail=1
echo
echo "=== contract registry ==="
# Same reason as the prompts (D23, migration 012): RUN_ENGINE validates
# against a ROW now, and a migrated database with an empty registry raises
# ContractMissing on the first control block.
python3 scripts/load_contracts.py | tail -3 || fail=1
echo
echo "=== handoff registry ==="
# D24: which substantive handoff each engine owes, per mode. Verified
# against the registered prompts, so a renamed tag fails here rather than
# registering a block no engine will ever emit.
python3 scripts/load_handoffs.py | tail -12 || fail=1
echo
echo "=== price registry ==="
# D30: the fourth registry. n8n cannot read config/model_prices.json, so
# the rate card is rows too -- otherwise the production path records
# UNPRICED for a call the reference implementation prices.
python3 scripts/load_prices.py | tail -6 || fail=1
for t in concept_layer knowledge_layer client_layer run_engine case_events knowledge_inbox prompt_contracts contract_registry n8n_parity n8n_sql measurement intake client_new handoff_flow normalization ontology_seed knowledge_factory embeddings discovery retrieval evaluation controversy_gaps safety followup foundation practice youtube optional_deps; do
  echo
  echo "=== $t ==="
  out=$(python3 "testing/test_$t.py" 2>&1); rc=$?
  # Surface every named skip. V3: an optional dependency degrades to a
  # NAMED skip -- and naming it inside a suite whose output this loop then
  # throws away is not naming it to anyone. A reader must be able to see,
  # from this summary alone, which floor a green run was green on.
  echo "$out" | grep -E "^  SKIP" || true
  echo "$out" | tail -3
  [ $rc -eq 0 ] || { fail=1; echo "  ^^ SUITE FAILED (exit $rc)"; }
done
echo
echo "=== idempotency ==="
python3 scripts/migrate.py
echo
if [ $fail -eq 0 ]; then echo "ALL SUITES PASSED"; else echo "FAILURES PRESENT"; fi
exit $fail
