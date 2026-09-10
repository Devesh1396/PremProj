#!/usr/bin/env python3
"""Load the seven engine specifications into the runtime prompt registry.

prompts/*.md is the AUTHORED form. engine_prompts is the RUNTIME form
(DECISIONS.md D23) — the thing RUN_ENGINE reads, so n8n needs no
filesystem and no copy of this repository.

This script is the registry's only writer, and it runs as phi_admin, in
the same class as applying a migration.

Append-only. Loading unchanged content is a no-op. Loading changed content
inserts a new version and deactivates the old one; the old row stays
readable because engine_runs.prompt_hash cites it as the text that
produced an output.

    python3 scripts/load_prompts.py            # load, report what changed
    python3 scripts/load_prompts.py --check    # report only, change nothing
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO / "prompts"

# The one map of engine -> specification file. run_engine.py imports this
# rather than keeping a second copy: two dictionaries that must agree are
# one dictionary and a latent bug.
ENGINE_PROMPTS = {
    "E1": "engine1_prevention.md",
    "E2": "engine2_behaviour.md",
    "E3": "engine3_nutrition.md",
    "E4": "engine4_progress.md",
    "E5": "engine5_communication.md",
    "E6": "engine6_memory.md",
    "E7": "engine7_research_practice.md",
}


class PromptMissing(RuntimeError):
    """No specification available for an engine.

    Raised by the loader when the authored file is absent or empty, and by
    RUN_ENGINE when the registry has no active row. Hard rule 7: RUN_ENGINE
    raises rather than falling back to a stub, because an output that
    cannot be traced to a specification is worse than no output.
    """


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def read_authored(engine: str) -> tuple[str, str, str]:
    """Return (filename, content, sha256) for one engine's authored file."""
    filename = ENGINE_PROMPTS[engine]
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise PromptMissing(
            f"{path} is missing. Place the canonical master specification "
            "there. Nothing will be loaded and RUN_ENGINE will not fall back "
            "to a stub."
        )
    content = path.read_text()
    if not content.strip():
        raise PromptMissing(f"{path} is empty.")
    return filename, content, hashlib.sha256(content.encode()).hexdigest()


def load(conn: psycopg.Connection, check_only: bool = False) -> list[tuple[str, str]]:
    """Sync the registry to the authored files. Returns (engine, action) rows."""
    actions: list[tuple[str, str]] = []

    for engine in ENGINE_PROMPTS:
        filename, content, digest = read_authored(engine)

        current = conn.execute(
            "select prompt_id, prompt_file, prompt_hash from engine_prompts "
            "where engine=%s and active",
            (engine,),
        ).fetchone()

        if current and current[2] == digest and current[1] == filename:
            actions.append((engine, "unchanged"))
            continue

        if check_only:
            actions.append((engine, "would-load" if current is None else "would-supersede"))
            continue

        if current is not None:
            # Deactivate before inserting: uq_engine_prompt_active permits
            # exactly one active row per engine, so the order matters.
            conn.execute(
                "update engine_prompts set active=false, superseded_at=now() "
                "where prompt_id=%s",
                (current[0],),
            )

        # A version of this exact text may already exist and have been
        # superseded -- reverting a prompt is a legitimate act. Reactivate
        # rather than violating uq_engine_prompt_version.
        prior = conn.execute(
            "select prompt_id from engine_prompts where prompt_file=%s and prompt_hash=%s",
            (filename, digest),
        ).fetchone()
        if prior is not None:
            conn.execute(
                "update engine_prompts set active=true, superseded_at=null "
                "where prompt_id=%s",
                (prior[0],),
            )
            actions.append((engine, "reactivated"))
            continue

        conn.execute(
            "insert into engine_prompts (engine, prompt_file, content, prompt_hash) "
            "values (%s,%s,%s,%s)",
            (engine, filename, content, digest),
        )
        actions.append((engine, "loaded" if current is None else "superseded"))

    return actions


def active(conn: psycopg.Connection, engine: str) -> tuple[str, str, str]:
    """Return (prompt_file, content, prompt_hash) for an engine's active row.

    The runtime read path. Used by run_engine.py, and by the n8n port
    through the identical SELECT.
    """
    row = conn.execute(
        "select prompt_file, content, prompt_hash from engine_prompts "
        "where engine=%s and active",
        (engine,),
    ).fetchone()
    if row is None:
        raise PromptMissing(
            f"No active prompt registered for {engine}. Run "
            "`python3 scripts/load_prompts.py`. RUN_ENGINE will not fall back "
            "to a stub: an output that cannot be traced to a specification is "
            "worse than no output."
        )
    return row[0], row[1], row[2]


def main() -> int:
    check_only = "--check" in sys.argv
    with psycopg.connect(dsn(), autocommit=True) as conn:
        try:
            actions = load(conn, check_only=check_only)
        except PromptMissing as exc:
            print(f"PromptMissing: {exc}", file=sys.stderr)
            return 2

        for engine, action in actions:
            print(f"  {engine}  {action}")

        rows = conn.execute(
            "select engine, prompt_file, left(prompt_hash,12), content_chars "
            "from v_active_engine_prompts "
            "join engine_prompts using (engine, prompt_file, prompt_hash) "
            "where active order by engine"
        ).fetchall()
        print()
        print("ACTIVE REGISTRY")
        for engine, filename, short, chars in rows:
            print(f"  {engine}  {filename:34s} {short}  {chars:>7,} chars")

    changed = [a for _, a in actions if a not in ("unchanged",)]
    if check_only and changed:
        print(f"\n{len(changed)} prompt(s) differ from the registry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
