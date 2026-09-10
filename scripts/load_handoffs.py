#!/usr/bin/env python3
"""Load the expected substantive handoff tags into the runtime registry.

The third instance of the pattern 010 and 012 established, and deliberately
not a third bespoke mechanism (D24): the prompts became rows so n8n could
read a specification, the control contract became a row so n8n could
validate one, and these are rows so n8n can tell whether an engine actually
produced its reasoning.

Every prompt defines TWO machine-readable outputs. `<CONTROL_BLOCK>` is
~17 typed fields for routing and gating; `<..._HANDOFF>` is the
substantive reasoning the next engine thinks with. They are never
interchangeable, and until this existed RUN_ENGINE parsed only the first.

THE MAP BELOW IS NOT AUTHORITATIVE -- prompts/ is. Every tag is verified to
appear in the engine's registered prompt before anything is loaded, so a
tag that has been renamed in a specification fails the load rather than
silently registering a block no engine will ever emit.
"""
from __future__ import annotations

import os
import re
import sys

import psycopg

import load_prompts

# (engine, mode) -> [(tag, required, prompt_ref, note)]
#
# Modes are the vocabulary of the registry table itself, not an enum (D19).
# SINGLE means "this engine emits the same block whatever it was asked to
# do" -- five of the seven do.
HANDOFFS: dict[tuple[str, str], list[tuple[str, bool, str, str]]] = {
    ("E1", "SINGLE"): [(
        "PREVENTION_INTELLIGENCE_HANDOFF", True, "engine1 §63",
        "The finalized clinical picture: drivers, targets, interventions, "
        "nutrition objectives, movement objectives, behaviour required. What "
        "Engines 2 and 3 make executable.")],
    ("E2", "SINGLE"): [(
        "BEHAVIOUR_INTELLIGENCE_HANDOFF", True, "engine2",
        "Behaviour made executable. Engine 3 needs it to know what the "
        "client can actually carry out.")],
    ("E3", "SINGLE"): [(
        "NUTRITION_IMPLEMENTATION_HANDOFF", True, "engine3",
        "Nutrition made executable.")],
    ("E4", "SINGLE"): [(
        "PROGRESS_INTELLIGENCE_HANDOFF", True, "engine4",
        "What the response taught us. Drives follow-up routing.")],
    ("E5", "SINGLE"): [(
        "CLIENT_COMMUNICATION_HANDOFF", True, "engine5",
        "The client-facing communication. Release is gated on practitioner "
        "approval; producing it is not.")],

    # E6 §A1: the full handoff establishes or rebuilds state, the delta
    # records an incremental change, and the delta is the normal path on
    # follow-up. A delta is not a state.
    ("E6", "INIT"): [(
        "CASE_MEMORY_HANDOFF", True, "engine6 §73 / §A1",
        "Full canonical state, establishing it for the first time. "
        "client_case_versions.canonical_state is exactly this block.")],
    ("E6", "REBUILD"): [
        ("CASE_MEMORY_HANDOFF", True, "engine6 §73 / §A1",
         "Full canonical state, rebuilt after the engines that ran in this "
         "cycle. Required because canonical_state must be a complete state."),
        ("CASE_MEMORY_DELTA", False, "engine6 §74",
         "What changed, when Engine 6 also reports it. Optional here and "
         "kept rather than discarded: it is the only record of the change."),
    ],
    ("E6", "UPDATE"): [
        ("CASE_MEMORY_DELTA", True, "engine6 §74 / §A1",
         "Only what changed. The normal follow-up path. NEVER stored as "
         "canonical_state -- a description of a change is not a case."),
        ("CASE_MEMORY_HANDOFF", False, "engine6 §73",
         "A full state, if Engine 6 chose to restate one."),
    ],

    ("E7", "CASE"): [(
        "RESEARCH_PRACTICE_CASE_HANDOFF", True, "engine7 §R9",
        "Strategies, evidence, expected effects, applicability, "
        "implementation notes, outcomes to track. What Engine 1 Pass B "
        "reasons over -- the entire reason E1 runs twice (D4).")],
    ("E7", "FOUNDATION"): [(
        "RESEARCH_PRACTICE_FOUNDATION_HANDOFF", True, "engine7 §R8",
        "Knowledge-clock output. CASE_VERSION 0 (D18).")],
}

# Which mode an engine runs in when the caller does not say. Five engines
# have one mode; E6 and E7 have no safe default, because guessing wrong
# means expecting a delta where a state was needed or the reverse.
DEFAULT_MODE = {"E1": "SINGLE", "E2": "SINGLE", "E3": "SINGLE",
                "E4": "SINGLE", "E5": "SINGLE"}


class HandoffModeUnknown(RuntimeError):
    """No registered mode for this engine, or none supplied where required."""


class HandoffMissing(RuntimeError):
    """No registry entry at all for an (engine, mode).

    Raised loudly rather than defaulting to "expect nothing": an engine
    whose handoff nobody registered would otherwise pass every check while
    producing no reasoning, which is the failure this registry exists to
    make impossible.
    """


def dsn() -> str:
    return os.environ["DATABASE_URL"]


def verify_against_prompts(conn: psycopg.Connection) -> list[str]:
    """Every registered tag must appear in the engine's registered prompt.

    prompts/ is authoritative; the map above is a claim about it. A tag
    renamed in a specification must fail the load, not register a block no
    engine will ever emit.

    Read from the PROMPT REGISTRY rather than the working tree, so this
    checks what RUN_ENGINE will actually send (D23).
    """
    problems: list[str] = []
    for (engine, mode), entries in HANDOFFS.items():
        try:
            _, content, _ = load_prompts.active(conn, engine)
        except load_prompts.PromptMissing as exc:
            problems.append(f"{engine}: {exc}")
            continue
        for tag, _required, ref, _note in entries:
            # The CLOSING tag on its own line, not the opening one.
            #
            # Matching the bare word would hit a section heading that merely
            # names the tag, and several prompts have those -- Engine 7 §3046
            # calls that out itself: "The section headings below name the
            # tags; that is not the same as emitting them."
            #
            # But matching the standalone OPENING tag is too strict, and
            # Engine 7 is why. <RESEARCH_PRACTICE_FOUNDATION_HANDOFF> appears
            # only inside its §R8 heading; its closing tag is on its own line
            # above the fields, and §3046 compensates in prose ("and the same
            # form for ..."). That is a wrinkle in one specification, not a
            # renamed tag, and prompts/ is authoritative and not ours to
            # tidy (hard rule 1).
            #
            # The closing tag standalone is present for all nine and is the
            # reliable structural marker that the prompt defines the block.
            if not re.search(rf"^</{tag}>\s*$", content, re.MULTILINE):
                problems.append(
                    f"{engine}/{mode}: <{tag}> ({ref}) has no standalone "
                    "closing tag in the registered prompt -- the block it "
                    "names is not defined there")
    return problems


def load(conn: psycopg.Connection, check_only: bool = False) -> list[tuple[str, str]]:
    """Sync the registry to HANDOFFS. Returns (label, action) rows."""
    problems = verify_against_prompts(conn)
    if problems:
        raise HandoffMissing(
            "the registry disagrees with the registered prompts:\n  "
            + "\n  ".join(problems))

    actions: list[tuple[str, str]] = []
    for (engine, mode), entries in HANDOFFS.items():
        for tag, required, ref, note in entries:
            label = f"{engine}/{mode}/{tag}"
            current = conn.execute(
                "select required, prompt_ref, note, active from engine_handoffs "
                "where engine=%s and mode=%s and tag=%s",
                (engine, mode, tag)).fetchone()
            if current and tuple(current) == (required, ref, note, True):
                actions.append((label, "unchanged"))
                continue
            if check_only:
                actions.append((label, "would-load" if current is None else "would-update"))
                continue
            conn.execute(
                """insert into engine_handoffs (engine, mode, tag, required, prompt_ref, note)
                   values (%s,%s,%s,%s,%s,%s)
                   on conflict (engine, mode, tag) do update
                     set required=excluded.required, prompt_ref=excluded.prompt_ref,
                         note=excluded.note, active=true, loaded_at=now()""",
                (engine, mode, tag, required, ref, note))
            actions.append((label, "loaded" if current is None else "updated"))

    if not check_only:
        # A tag removed from the map is deactivated, never deleted: a run
        # already recorded against it must stay explicable.
        registered = {(e, m, t) for (e, m), es in HANDOFFS.items() for t, *_ in es}
        for engine, mode, tag in conn.execute(
                "select engine::text, mode, tag from engine_handoffs where active"
        ).fetchall():
            if (engine, mode, tag) not in registered:
                conn.execute(
                    "update engine_handoffs set active=false "
                    "where engine=%s and mode=%s and tag=%s", (engine, mode, tag))
                actions.append((f"{engine}/{mode}/{tag}", "deactivated"))

    return actions


def expected(conn: psycopg.Connection, engine: str, mode: str) -> list[tuple[str, bool]]:
    """[(tag, required)] for one (engine, mode). The runtime read path.

    The n8n port issues the identical SELECT, so Python and the workflow
    cannot disagree about what an engine owes.
    """
    rows = conn.execute(
        "select tag, required from engine_handoffs "
        "where engine=%s and mode=%s and active order by required desc, tag",
        (engine, mode)).fetchall()
    if not rows:
        raise HandoffMissing(
            f"no handoff registered for {engine}/{mode}. RUN_ENGINE will not "
            "treat a run as successful without knowing what reasoning it was "
            "supposed to produce. Register it in scripts/load_handoffs.py, or "
            "pass the mode the engine actually ran in.")
    return [(r[0], r[1]) for r in rows]


def resolve_mode(engine: str, mode: str | None) -> str:
    """The mode to look up, or a loud failure.

    E6 and E7 have no default on purpose. Guessing means expecting a delta
    where a full state was needed, or the reverse, and both produce a case
    record that is quietly wrong.
    """
    if mode:
        return mode
    if engine in DEFAULT_MODE:
        return DEFAULT_MODE[engine]
    raise HandoffModeUnknown(
        f"{engine} emits a different handoff depending on what it was asked "
        f"to do and has no default. Pass mode= explicitly: "
        f"{', '.join(sorted(m for (e, m) in HANDOFFS if e == engine))}.")


def main() -> int:
    check_only = "--check" in sys.argv
    with psycopg.connect(dsn(), autocommit=True) as conn:
        try:
            actions = load(conn, check_only=check_only)
        except (HandoffMissing, load_prompts.PromptMissing) as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

        changed = [(l, a) for l, a in actions if a != "unchanged"]
        for label, action in changed or actions[:0]:
            print(f"  {label}  {action}")

        rows = conn.execute(
            "select engine::text, mode, coalesce(required_tags,'{}'), "
            "       coalesce(optional_tags,'{}') "
            "  from v_engine_handoff_registry").fetchall()
        print(f"HANDOFF REGISTRY  ({len(rows)} engine/mode combinations)")
        for engine, mode, req, opt in rows:
            extra = f"  (+optional {', '.join(opt)})" if opt else ""
            print(f"  {engine}  {mode:<11s} {', '.join(req)}{extra}")

    missing = sorted({e for (e, _m) in HANDOFFS} - {r[0] for r in rows})
    if missing:
        print(f"\nNOT READY: no handoff registered for {', '.join(missing)}.",
              file=sys.stderr)
        return 1
    if check_only and changed:
        print(f"\n{len(changed)} registry row(s) differ from the map.",
              file=sys.stderr)
        return 1
    if check_only:
        print(f"\nREADY: {len(rows)} engine/mode combinations, every tag "
              "present in its registered prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
