#!/usr/bin/env python3
"""The one place a suite decides an optional dependency is missing.

CLAUDE.md **V3**. Three times now a suite has only passed where an optional
dependency happened to be configured, and been green in CI because CI
configures it:

| | what was missing | what the suite did |
|---|---|---|
| `pg_trgm` | the extension | called `similarity()` and died |
| `ajv` | the node module | indexed `'valid'` on an error dict, `KeyError` |
| `MODEL_EMBEDDING` | the env var | raised `BadVector` mid-run (bug 64) |

Each was fixed where it was found, and the next one formed somewhere else,
because "remember to guard optional dependencies" is not a mechanism. This
module is the mechanism, and `testing/test_optional_deps.py` is the
assertion that every suite uses it: it removes each optional dependency and
runs the suites that depend on it, and a suite that raises instead of
skipping fails there rather than on somebody's laptop.

### The rule

**An optional dependency must degrade to a NAMED skip, never an
exception.** Named matters: `SKIP` on its own tells a reader something was
not tested and not what, so the next person cannot tell a supported
configuration from a suite that quietly stopped testing anything.

### Why a skip and not a failure

`pgvector`, `pg_trgm` and `btree_gin` are absent on a supported
configuration (D15) — the system runs on metadata and full text there.
`MODEL_EMBEDDING` is unset on the VPS on purpose, because nothing there is
allowed to make a paid call yet. None of those is a broken environment, and
a suite that fails on them is telling the reader something false.
"""
from __future__ import annotations

import os

# The marker `run_bare.sh` and `test_optional_deps.py` both grep for. Every
# skip in the suite tree goes through `skip()` so the format is one thing.
SKIP_MARK = "  SKIP  "


# What is optional, and what its absence costs. One registry, so the suites,
# the central assertion and anyone reading this share a list rather than
# three lists that drift.
OPTIONAL_ENV = {
    "MODEL_EMBEDDING":
        "no embedding model is configured, so nothing can be embedded and "
        "the vector channel cannot run. D34 pins the model per column, so it "
        "is not a per-call choice this can default. Unset on the VPS on "
        "purpose: nothing there makes a paid call yet.",
}

OPTIONAL_CAPABILITY = {
    "vector":
        "pgvector is absent (D15): there are no embedding columns, and "
        "retrieval runs on metadata and full text.",
    "pg_trgm":
        "pg_trgm is absent: alias matching is exact-normalized and more "
        "phrases fall through to LLM resolution.",
    "btree_gin":
        "btree_gin is absent: some composite indexes are not created.",
}


def skip(dependency: str, consequence: str) -> None:
    """Report a named skip in the one format everything else greps for."""
    print(f"{SKIP_MARK}{dependency} is not available — {consequence}")
    print("        This is a supported configuration, not a failure.")


def env(name: str) -> str | None:
    """An env var's value, treating empty and whitespace as unset."""
    value = (os.environ.get(name) or "").strip()
    return value or None


def have_env(name: str, consequence: str | None = None) -> bool:
    """True when `name` is set; otherwise a named skip and False."""
    if env(name):
        return True
    skip(name, consequence or OPTIONAL_ENV.get(name, "it is not configured"))
    return False


def have_capability(conn, name: str, consequence: str | None = None) -> bool:
    """True when the optional extension is available on this database."""
    row = conn.execute(
        "select enabled from system_capabilities where capability=%s",
        (name,)).fetchone()
    if row and row[0]:
        return True
    skip(name, consequence or OPTIONAL_CAPABILITY.get(name, "it is not installed"))
    return False


def have(condition: bool, dependency: str, consequence: str) -> bool:
    """The general form, for a precondition that is neither.

    A suite that needs the K1 ontology seed, or a library with strategies
    in it, has the same obligation: say what is missing and skip, rather
    than fail as though the code were wrong.
    """
    if condition:
        return True
    skip(dependency, consequence)
    return False
