#!/usr/bin/env python3
"""The runtime input contract declared in a prompt's build-owned Addendum.

D52c, and the pipeline scope D52d adds. ONE parser, read by
`test_client_new.py` (which asserts CLIENT_NEW's invocations match) and by
`test_followup.py` (which asserts the follow-up's do NOT silently fall
under them). Two copies of this regex would be two definitions of the
contract, and the whole point of a declaration is that there is one.

### The key is `PIPELINE ENGINE/MODE/PASS`, and the pipeline is load-bearing

`(engine, mode, pass)` does not determine the payload. Measured on the real
pipelines:

    CLIENT_NEW      E6/REBUILD/SINGLE -> CASE_VERSION, CANONICAL_STATE,
                                         NORMALIZED_CONCEPTS,
                                         E1_HANDOFF, E2_HANDOFF, E3_HANDOFF
    CLIENT_FOLLOWUP E6/REBUILD/SINGLE -> CASE_VERSION, CLIENT_ID,
                                         CURRENT_STATE, REVIEW_PERIOD,
                                         FOLLOWUP_ANSWERS, FOLLOWUP_STRUCTURED,
                                         LIVE_INTERVENTIONS, PRACTICE_EXPERIENCE,
                                         E4_HANDOFF, E6_DELTA,
                                         E1_HANDOFF, E2_HANDOFF, E3_HANDOFF

`client_new.py` and `client_followup.py` both call `engine="E6",
mode="REBUILD"`, for the same stated reason (a delta cannot be mechanically
merged into a state), and hand it completely different things. `E2/SINGLE`
and `E3/SINGLE` collide the same way once Engine 4 routes to them.

So a three-part key would have made CLIENT_NEW's declaration look like the
governing contract for a follow-up invocation, and the follow-up payload
would read as a violation of a contract that was never about it. The
declaration says which pipeline it speaks for, and a lookup that does not
carry the pipeline finds the wrong one.

### Declaring nothing is a position, and it has to be expressible

CLIENT_FOLLOWUP's contract is deliberately NOT written down: a declaration
is a COMPLETE set, and completing it means settling every block that path
sends, which is a separate cleanup. With the pipeline in the key that
absence is representable — there is simply no `CLIENT_FOLLOWUP` line.
Without it, the absence could not be stated at all, because a line already
existed for the same triple.
"""
from __future__ import annotations

import re

# `RUNTIME_INPUT_CONTRACT CLIENT_NEW E6/REBUILD = A, B, C`
# `RUNTIME_INPUT_CONTRACT CLIENT_NEW E1/SINGLE/A = A, B`
DECLARATION = re.compile(
    r"^RUNTIME_INPUT_CONTRACT[ \t]+(?P<pipeline>[A-Z][A-Z0-9_]*)"
    r"[ \t]+(?P<engine>E\d)/(?P<mode>[A-Z_]+)"
    r"(?:/(?P<pass>[A-Z]+))?[ \t]*=[ \t]*(?P<blocks>.+)$", re.M)

# Engine 6's INIT run receives the converted intake submission, whose fields
# the intake schema names and no prompt does. The sentinel expands to what
# `intake.to_e6_input()` itself produces -- never a hand-written list, which
# would go stale the moment the intake schema changed.
INTAKE_SENTINEL = "INTAKE_PAYLOAD"


def declarations(conn, engine: str) -> dict:
    """Every declaration in `engine`'s ACTIVE prompt row.

    Keyed `(pipeline, engine, mode, pass)`; `pass` defaults to SINGLE.
    Reads the registry, not the file: the registry is what the runtime
    loads, and a file edited without `load_prompts.py` is not in force.
    """
    row = conn.execute(
        "select content from engine_prompts "
        " where engine=%s::engine_id and active", (engine,)).fetchone()
    if row is None:
        return {}
    out = {}
    for m in DECLARATION.finditer(row[0]):
        key = (m.group("pipeline"), m.group("engine"), m.group("mode"),
               m.group("pass") or "SINGLE")
        out[key] = {b.strip() for b in m.group("blocks").split(",") if b.strip()}
    return out


def expand(declared: set, intake_keys: set) -> set:
    """Resolve the one sentinel against what the real converter produced."""
    if INTAKE_SENTINEL in declared:
        return (declared - {INTAKE_SENTINEL}) | intake_keys
    return declared


def compare(sent: set, declared: set) -> tuple[list, list]:
    """(sent but not declared, declared but not sent). Both directions.

    A check that only looked one way would pass a declaration promising
    blocks that never arrive, which is a contract that describes a payload
    nobody sends.
    """
    return sorted(sent - declared), sorted(declared - sent)
