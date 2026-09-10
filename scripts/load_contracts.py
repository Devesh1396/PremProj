#!/usr/bin/env python3
"""Load the orchestration contract into the runtime registry.

schemas/orchestration/*.json is the AUTHORED form. orchestration_contracts
is the RUNTIME form (D23, migration 012) -- what RUN_ENGINE validates
against, so n8n can route without a copy of this repository.

The sibling of scripts/load_prompts.py and deliberately the same shape:
one writer, append-only, exactly one active document per schema_version,
and a --check that reports READINESS rather than drift.

    python3 scripts/load_contracts.py            # load, report what changed
    python3 scripts/load_contracts.py --check    # verify only, change nothing
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO / "schemas" / "orchestration"

# schema_version -> authored file. The key is what engine_runs.schema_version
# has carried since 004; the two must agree or a run cites a contract that
# cannot be looked up.
CONTRACTS = {
    "control_contract.v1": "control_contract.v1.json",
}


class ContractMissing(RuntimeError):
    """No contract available for a schema_version.

    The contract's PromptMissing. RUN_ENGINE raises rather than validating
    against nothing: a control block nobody checked is not a validated
    control block, and hard rule 5 has n8n routing on those fields.
    """


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def read_authored(schema_version: str) -> tuple[str, dict, str]:
    """Return (filename, parsed document, sha256 of the file's bytes)."""
    filename = CONTRACTS[schema_version]
    path = SCHEMA_DIR / filename
    if not path.exists():
        raise ContractMissing(
            f"{path} is missing. RUN_ENGINE will not validate against nothing.")
    raw = path.read_bytes()
    if not raw.strip():
        raise ContractMissing(f"{path} is empty.")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractMissing(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or not document.get("properties"):
        raise ContractMissing(
            f"{path} has no properties. A schema that constrains nothing "
            "accepts everything, which is the same as having no contract.")
    # Hash the BYTES, not the parsed object. json.dumps of a parsed document
    # depends on Python's separators and key order; the file is what someone
    # reviewed.
    return filename, document, hashlib.sha256(raw).hexdigest()


def load(conn: psycopg.Connection, check_only: bool = False) -> list[tuple[str, str]]:
    """Sync the registry to the authored files. Returns (version, action) rows."""
    actions: list[tuple[str, str]] = []

    for schema_version in CONTRACTS:
        filename, document, digest = read_authored(schema_version)

        current = conn.execute(
            "select contract_id, document_hash from orchestration_contracts "
            "where schema_version=%s and active",
            (schema_version,)).fetchone()

        if current and current[1] == digest:
            actions.append((schema_version, "unchanged"))
            continue

        if check_only:
            actions.append((schema_version,
                            "would-load" if current is None else "would-supersede"))
            continue

        if current is not None:
            conn.execute(
                "update orchestration_contracts set active=false, superseded_at=now() "
                "where contract_id=%s", (current[0],))

        prior = conn.execute(
            "select contract_id from orchestration_contracts "
            "where schema_version=%s and document_hash=%s",
            (schema_version, digest)).fetchone()
        if prior is not None:
            conn.execute(
                "update orchestration_contracts set active=true, superseded_at=null "
                "where contract_id=%s", (prior[0],))
            actions.append((schema_version, "reactivated"))
            continue

        conn.execute(
            "insert into orchestration_contracts "
            "(schema_version, source_file, document, document_hash) "
            "values (%s,%s,%s,%s)",
            (schema_version, filename, json.dumps(document), digest))
        actions.append((schema_version, "loaded" if current is None else "superseded"))

    return actions


def active(conn: psycopg.Connection, schema_version: str) -> tuple[dict, str]:
    """Return (document, document_hash) for the active contract.

    The runtime read path. The n8n port issues the identical SELECT and
    feeds the result to ajv, so the two validators cannot disagree about
    WHICH schema they are enforcing -- only, in principle, about JSON
    Schema itself, which is what the parity suite exists to rule out.
    """
    row = conn.execute(
        "select document, document_hash from orchestration_contracts "
        "where schema_version=%s and active", (schema_version,)).fetchone()
    if row is None:
        raise ContractMissing(
            f"No active contract registered for {schema_version}. Run "
            "`python3 scripts/load_contracts.py`. RUN_ENGINE will not "
            "validate a control block against nothing.")
    return row[0], row[1]


def main() -> int:
    check_only = "--check" in sys.argv
    with psycopg.connect(dsn(), autocommit=True) as conn:
        try:
            actions = load(conn, check_only=check_only)
        except ContractMissing as exc:
            print(f"ContractMissing: {exc}", file=sys.stderr)
            return 2

        for version, action in actions:
            print(f"  {version}  {action}")

        rows = conn.execute(
            "select schema_version, source_file, left(document_hash,12), "
            "       property_count, required_count "
            "  from v_active_contracts").fetchall()
        print()
        print(f"ACTIVE CONTRACTS  ({len(rows)} of {len(CONTRACTS)})")
        for version, filename, short, props, req in rows:
            print(f"  {version:22s} {filename:26s} {short}  "
                  f"{props} properties, {req} required")

    if len(rows) != len(CONTRACTS):
        missing = sorted(set(CONTRACTS) - {r[0] for r in rows})
        print(f"\nNOT READY: no active contract for {', '.join(missing)}. "
              "RUN_ENGINE will raise ContractMissing.", file=sys.stderr)
        return 1

    changed = [(v, a) for v, a in actions if a != "unchanged"]
    if check_only and changed:
        print(f"\n{len(changed)} contract(s) differ from the authored files: "
              + ", ".join(f"{v} ({a})" for v, a in changed)
              + "\nRun `python3 scripts/load_contracts.py` to load them.",
              file=sys.stderr)
        return 1

    if check_only:
        print(f"\nREADY: all {len(rows)} contracts active and matching "
              "schemas/orchestration/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
