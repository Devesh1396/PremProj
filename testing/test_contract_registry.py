#!/usr/bin/env python3
"""The orchestration contract as a row, and two validators that agree.

BUILD_GUIDE step 11, DECISIONS.md D23, migration 012.

Two claims, and they are different:

  REGISTRY   the contract RUN_ENGINE validates against is a row, not a
             file on the working tree, so n8n can route without a copy of
             this repository. Append-only, one active document per
             schema_version, and ContractMissing rather than validating
             against nothing.

  PARITY     jsonschema (Python) and ajv (the one inside n8n) reach the
             SAME verdict on the same control block, and blame the same
             field. The schema is single-sourced in PostgreSQL; only the
             library differs. Without this the n8n port is two validators
             that happen to agree today.

The parity half needs Node and ajv. It SKIPS loudly when they are absent
rather than passing quietly -- a check that cannot run must say so -- and
CI installs ajv so it is a real gate there.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import load_contracts as LC
import run_engine as RE

FAILS: list[str] = []
AJV_SCRIPT = REPO / "testing" / "ajv_validate.js"


@contextlib.contextmanager
def rollback_after(conn):
    """Run a block and undo it. psycopg3 has no tx.rollback(); Rollback is
    raised INSIDE the transaction block and swallowed by it."""
    try:
        with conn.transaction():
            yield
            raise psycopg.Rollback
    except psycopg.Rollback:
        pass


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def python_verdict(conn, control: dict) -> tuple[bool, list[str]]:
    """(valid, blamed field names) from jsonschema, in ajv's shape."""
    errors = list(RE.validator(conn).iter_errors(control))
    paths = set()
    for err in errors:
        if err.validator == "required":
            # "'CASE_VERSION' is a required property" -- the field name is
            # in the message, not the path, exactly as it is in ajv's params.
            paths.add(err.message.split("'")[1])
        elif err.validator == "additionalProperties":
            # jsonschema names the extra properties in the message.
            paths.update(part for part in err.message.split("'")[1::2])
        elif err.absolute_path:
            paths.add(str(list(err.absolute_path)[0]))
        else:
            paths.add("(root)")
    return not errors, sorted(paths)


def find_ajv() -> str | None:
    """A node_modules directory carrying ajv, or None.

    AJV_MODULE_PATH wins. Otherwise look where scripts/local_n8n.sh puts an
    n8n install, because that ajv is the one the workflow will actually use.
    """
    explicit = os.environ.get("AJV_MODULE_PATH")
    if explicit and (Path(explicit) / "ajv").exists():
        return str(Path(explicit).resolve())

    # N8N_HOME unset makes Path("") / "node_modules" a RELATIVE path, and a
    # relative path handed to require() resolves against the requiring
    # MODULE rather than the working directory -- so it found ajv, passed a
    # path node could not use, and reported "ajv ran: exit 3". Every
    # candidate is resolved to an absolute path, and empty roots are
    # skipped rather than silently becoming the current directory.
    roots = [os.environ.get("N8N_HOME"),
             str(Path(os.environ.get("TMPDIR", "/tmp")) / "premproj-n8n"),
             str(REPO)]
    for root in roots:
        if not root:
            continue
        base = (Path(root) / "node_modules").resolve()
        if (base / "ajv").exists():
            return str(base)
    return None


# The corpus. Every case is (name, control block, must_be_valid) and the
# invalid ones are here because they are the ways a real engine response
# goes wrong -- a missing required field, a hallucinated enum value, an
# invented property, and each of the three conditional rules the contract
# uses to keep routing honest.
BASE = {"CASE_VERSION": 1, "ENGINE_RUN_STATUS": "SUCCEEDED"}

CASES: list[tuple[str, dict, bool]] = [
    ("minimal valid", BASE, True),
    ("every scalar populated", {
        **BASE, "REVIEW_REQUIRED": True, "HOLD_FLAG_PRESENT": False,
        "MEDICAL_COORDINATION_PRESENT": False, "LIVE_RESEARCH_REQUIRED": False,
        "KNOWLEDGE_SUFFICIENT": True, "ROUTING_RECOMMENDATION": "NONE",
        "ENGINE1_ACTION_REQUIRED": False, "ENGINE2_ACTION_REQUIRED": False,
        "ENGINE3_ACTION_REQUIRED": False, "ENGINE4_REASSESSMENT_REQUIRED": False,
        "NEXT_ENGINE": "E7", "LOOP_COUNT": 0, "ERROR_STATE": None,
    }, True),
    ("knowledge-clock CASE_VERSION 0 (D18)", {**BASE, "CASE_VERSION": 0}, True),
    ("arrays populated", {
        **BASE, "RESEARCH_QUESTIONS": ["a", "b"],
        "NORMALIZATION_PHRASES": ["large post-meal glucose excursions"],
    }, True),

    ("no CASE_VERSION", {"ENGINE_RUN_STATUS": "SUCCEEDED"}, False),
    ("no ENGINE_RUN_STATUS", {"CASE_VERSION": 1}, False),
    ("neither required field", {}, False),
    ("CASE_VERSION as a string", {**BASE, "CASE_VERSION": "1"}, False),
    ("CASE_VERSION as a float", {**BASE, "CASE_VERSION": 1.5}, False),
    ("invented ENGINE_RUN_STATUS", {**BASE, "ENGINE_RUN_STATUS": "MAYBE"}, False),
    ("invented NEXT_ENGINE", {**BASE, "NEXT_ENGINE": "E8"}, False),
    ("invented ROUTING_RECOMMENDATION", {**BASE, "ROUTING_RECOMMENDATION": "ENGINE9"}, False),
    ("boolean as a string", {**BASE, "REVIEW_REQUIRED": "true"}, False),
    ("arrays of the wrong type", {**BASE, "RESEARCH_QUESTIONS": "just one"}, False),

    # additionalProperties is TRUE, and deliberately (D14): roughly 17
    # control-flow fields are strict now and the remaining ~200 handoff
    # fields wait for output design. An engine that emits a field nobody
    # has typed yet is not violating the contract, and rejecting it would
    # make every prompt revision a schema migration. Asserted rather than
    # assumed, because "should the contract be closed" is exactly the sort
    # of thing someone tightens without reading D14.
    ("an undefined property is allowed (D14)", {**BASE, "CONFIDENCE": 0.9}, True),
    ("...and several of them", {
        **BASE, "CONFIDENCE": 0.9, "MOOD": "upbeat"}, True),

    # The three conditional rules. These are where two JSON Schema
    # implementations are most likely to differ, so they matter most.
    ("routing without a reason", {**BASE, "ROUTING_RECOMMENDATION": "ENGINE2"}, False),
    ("routing with a reason", {
        **BASE, "ROUTING_RECOMMENDATION": "ENGINE2",
        "ROUTING_REASON": "adherence, not strategy",
    }, True),
    ("routing NONE needs no reason", {**BASE, "ROUTING_RECOMMENDATION": "NONE"}, True),
    ("live research while the library is sufficient", {
        **BASE, "LIVE_RESEARCH_REQUIRED": True, "KNOWLEDGE_SUFFICIENT": True,
    }, False),
    ("live research with no sufficiency finding at all", {
        **BASE, "LIVE_RESEARCH_REQUIRED": True,
    }, False),
    ("live research after an insufficiency finding", {
        **BASE, "LIVE_RESEARCH_REQUIRED": True, "KNOWLEDGE_SUFFICIENT": False,
    }, True),
    ("FAILED with no ERROR_STATE", {**BASE, "ENGINE_RUN_STATUS": "FAILED"}, False),
    ("FAILED with a null ERROR_STATE", {
        **BASE, "ENGINE_RUN_STATUS": "FAILED", "ERROR_STATE": None}, False),
    ("FAILED with an empty ERROR_STATE", {
        **BASE, "ENGINE_RUN_STATUS": "FAILED", "ERROR_STATE": ""}, False),
    ("FAILED with a reason", {
        **BASE, "ENGINE_RUN_STATUS": "FAILED", "ERROR_STATE": "provider timeout"}, True),
]


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent, like every other suite: put the registry back before
    # asserting anything about it. This suite deliberately deactivates the
    # contract to prove RUN_ENGINE refuses to validate against nothing, and
    # a run that dies mid-way would otherwise leave every later suite
    # raising ContractMissing.
    LC.load(conn)

    print("\nthe contract is a row, not a file (D23, migration 012)")
    document, digest = LC.active(conn, RE.SCHEMA_VERSION)
    check("an active contract is registered", isinstance(document, dict))
    check("it is the document the authored file contains",
          document == json.loads(
              (REPO / "schemas" / "orchestration"
               / LC.CONTRACTS[RE.SCHEMA_VERSION]).read_text()))
    check("the hash is of the file's bytes, not of the parsed jsonb",
          digest == LC.read_authored(RE.SCHEMA_VERSION)[2])
    check("exactly one active contract per schema_version",
          conn.execute(
              "select count(*) from orchestration_contracts where active and "
              "schema_version=%s", (RE.SCHEMA_VERSION,)).fetchone()[0] == 1)
    check("RUN_ENGINE names the registered version on every run",
          RE.SCHEMA_VERSION in LC.CONTRACTS)

    # Hard rule 5 and hard rule 7 together: n8n routes on these fields, and
    # validating against nothing is not validating.
    with rollback_after(conn):
        conn.execute("update orchestration_contracts set active=false, "
                     "superseded_at=now() where active")
        try:
            RE.validate_control(conn, {"CASE_VERSION": 1})
            check("no registered contract raises rather than accepting anything",
                  False, "validate_control returned instead of raising")
        except LC.ContractMissing as exc:
            check("no registered contract raises rather than accepting anything",
                  "will not validate a control block against nothing" in str(exc))
    check("the contract survived the rollback",
          conn.execute("select count(*) from orchestration_contracts "
                       "where active").fetchone()[0] == 1)

    try:
        with rollback_after(conn):
            conn.execute("update orchestration_contracts set document = "
                         "document || '{\"injected\": true}'::jsonb where active")
        check("a registered contract cannot be rewritten in place", False,
              "the UPDATE was accepted")
    except psycopg.errors.CheckViolation as exc:
        check("a registered contract cannot be rewritten in place",
              "append-only" in str(exc))

    try:
        with rollback_after(conn):
            conn.execute("insert into orchestration_contracts "
                         "(schema_version, source_file, document, document_hash) "
                         "values ('bogus.v1','x.json','{\"properties\":{}}'::jsonb,%s)",
                         ("0" * 64,))
        check("a schema that constrains nothing is refused", False,
              "the INSERT was accepted")
    except psycopg.errors.CheckViolation as exc:
        check("a schema that constrains nothing is refused",
              "ck_contract_has_properties" in str(exc))

    # Superseding, on content that has never been registered, so this
    # asserts an INSERT rather than a reactivation and stays true on a
    # second run against a used database.
    before = conn.execute("select count(*) from orchestration_contracts").fetchone()[0]
    with rollback_after(conn):
        conn.execute("update orchestration_contracts set active=false, "
                     "superseded_at=now() where active")
        revised = dict(document)
        revised["description"] = f"revision {os.urandom(8).hex()}"
        conn.execute("insert into orchestration_contracts "
                     "(schema_version, source_file, document, document_hash) "
                     "values (%s,'control_contract.v1.json',%s,%s)",
                     (RE.SCHEMA_VERSION, json.dumps(revised),
                      "a" * 63 + "f"))
        check("superseding inserts a version rather than overwriting one",
              conn.execute("select count(*) from orchestration_contracts"
                           ).fetchone()[0] == before + 1)
        check("the superseded document stays readable",
              conn.execute("select count(*) from orchestration_contracts "
                           "where document_hash=%s", (digest,)).fetchone()[0] == 1)
        check("still exactly one active contract",
              conn.execute("select count(*) from orchestration_contracts "
                           "where active").fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nthe contract still says what it is supposed to say")
    for name, control, want_valid in CASES:
        got_valid, _ = python_verdict(conn, control)
        if got_valid != want_valid:
            check(f"{name} -> {'valid' if want_valid else 'invalid'}", False,
                  f"jsonschema said {'valid' if got_valid else 'invalid'}")
    check(f"all {len(CASES)} contract cases behave as specified", True)

    # ------------------------------------------------------------------
    print("\njsonschema and ajv agree (the n8n port's foundation)")
    modules = find_ajv()
    node = shutil.which("node")
    if node is None or modules is None:
        print("  SKIP  node or ajv not available; run "
              "`bash scripts/local_n8n.sh install` or set AJV_MODULE_PATH")
        print("        the Python half above ran in full; only the "
              "cross-library comparison was skipped")
    else:
        payload = {"schema": document, "cases": [c for _, c, _ in CASES]}
        proc = subprocess.run(
            [node, str(AJV_SCRIPT)], input=json.dumps(payload),
            capture_output=True, text=True,
            env={**os.environ, "AJV_MODULE_PATH": modules})
        if proc.returncode != 0:
            check("ajv ran", False, f"exit {proc.returncode}: {proc.stderr[:300]}")
        else:
            out = json.loads(proc.stdout)
            check(f"ajv {out['ajv']} compiled the registered document", True)
            check("ajv is the major version n8n ships",
                  out["ajv"].split(".")[0] == "8", out["ajv"])

            disagreements = []
            for (name, control, _), ajv_result in zip(CASES, out["results"]):
                py_valid, py_paths = python_verdict(conn, control)
                if py_valid != ajv_result["valid"]:
                    disagreements.append(
                        f"{name}: python={py_valid} ajv={ajv_result['valid']}")
                elif not py_valid and py_paths != ajv_result["paths"]:
                    # Same verdict, different blame. This matters because the
                    # blamed field is what goes into the repair prompt, so a
                    # divergence here means n8n asks the model to fix a
                    # different thing than the reference implementation does.
                    disagreements.append(
                        f"{name}: python blamed {py_paths}, ajv blamed "
                        f"{ajv_result['paths']}")
            check(f"both validators agree on all {len(CASES)} cases, "
                  "verdict and blamed field",
                  not disagreements, "; ".join(disagreements[:3]))

            check("they agree on which cases are valid at all",
                  sum(1 for r in out["results"] if r["valid"])
                  == sum(1 for _, _, want in CASES if want),
                  str(sum(1 for r in out["results"] if r["valid"])))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


def restore_registry() -> None:
    """Reload the contract whatever happened above, for the same reason
    test_run_engine.py restores the canonical prompts."""
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        LC.load(conn)


if __name__ == "__main__":
    try:
        code = main()
    finally:
        restore_registry()
    sys.exit(code)
