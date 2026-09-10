#!/usr/bin/env python3
"""CLIENT_NEW — a submitted intake through to the practitioner's queue.

BUILD_GUIDE step 15, MASTER_SPEC phase 4.

    intake -> extract -> E6 v1
           -> E1 Pass A -> normalization -> E7 -> E1 Pass B
           -> E2 -> E3 -> E6 v2
           -> practitioner review queue.  STOP.

Three things about that shape are decisions rather than transcription.

**It is a fixed pipeline, not a routing loop.** MASTER_SPEC phase 4 lists
this sequence; phase 5 (CLIENT_FOLLOWUP) is the one that routes on
`ROUTING_RECOMMENDATION` and needs a depth bound. So `NEXT_ENGINE` is not
consulted here to choose what runs next -- a new client always needs all
of E1, E2 and E3, and following the field would mean an engine could
decide to skip the nutrition plan. The control block still GATES: a run
that did not succeed stops the pipeline, and `REVIEW_REQUIRED` decides
what lands in the queue.

`loop_count` is ROUTING DEPTH, not a count of engine calls -- migration
004 says so on the constraint itself: "Prevents Engine 4 -> 1/2/3 -> 4
cycling without bound", and `max_loops` defaults to 3, which is fewer than
this pipeline has engines. Charging a hop per engine made a correct
CLIENT_NEW run exhaust its budget at E1 Pass B. A straight line consumes
one hop, and it is charged once, on entry, so a caller that re-enters the
same cycle repeatedly trips `ck_loop_bound` rather than running the
engines again.

**It stops at the queue, and E5 is not part of it.** Hard rule 9: safety
gates release, not analysis. Everything above is internal reasoning and is
never gated; the client-facing communication is the only gated step, it
requires a practitioner decision that does not exist yet at this point,
and `trg_block_unapproved_communication` enforces that independently. A
CLIENT_NEW that ran E5 would either be bypassing the review it just
queued, or blocking on a human inside a workflow -- both wrong.

Consequently an open HOLD flag does **not** stop this pipeline. That is
the rule, not an oversight: analysis and drafting continue, delivery does
not.

**Engine 4 does not run.** There is no response data yet to learn from.

Nothing here writes a display name into an engine payload
(`STRIP_IDENTITY_FROM_ENGINE_PAYLOADS`): the E6 input is built by
`intake.to_e6_input`, which carries `client_id` and clinical facts only.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import psycopg

import intake as IN
import normalize as NZ
import run_engine as RE

# Engines that are internal reasoning, in the order phase 4 specifies.
# E4 is absent because there is no response data yet; E5 is absent because
# it is gated on a practitioner decision.
PIPELINE_DESCRIPTION = "E6 -> E1(A) -> normalize -> E7 -> E1(B) -> E2 -> E3 -> E6 -> review"


@dataclass
class Step:
    """One thing that happened, in order, whether or not it was an engine."""
    name: str
    status: str
    run_id: str | None = None
    detail: str = ""


@dataclass
class Outcome:
    client_id: str
    submission_id: str
    cycle_id: str | None = None
    case_version_id: str | None = None
    final_case_version_id: str | None = None
    review_id: str | None = None
    status: str = "RUNNING"
    stopped_because: str | None = None
    steps: list[Step] = field(default_factory=list)

    def step(self, name: str, status: str, run_id: str | None = None,
             detail: str = "") -> Step:
        s = Step(name, status, run_id, detail)
        self.steps.append(s)
        return s

    def __repr__(self) -> str:
        done = " ".join(f"{s.name}:{s.status}" for s in self.steps)
        return f"<CLIENT_NEW {self.status} {done}>"


class PipelineStopped(RuntimeError):
    """An engine did not succeed. The pipeline stops rather than guessing.

    A missing E1 Pass A is not a smaller Pass B input, it is no input at
    all. Continuing would produce an E2 behaviour plan derived from
    nothing and record it against the client as though it meant something.
    """


def open_cycle(conn: psycopg.Connection, client_id: str,
               max_loops: int | None = None) -> str:
    """Open the next NEW_CLIENT cycle for this client.

    cycle_number is derived rather than passed in: (client_id, cycle_number)
    is unique, and letting a caller choose it is how two concurrent runs
    collide.
    """
    nxt = conn.execute(
        "select coalesce(max(cycle_number), 0) + 1 from case_cycles where client_id=%s",
        (client_id,)).fetchone()[0]
    if max_loops is None:
        return str(conn.execute(
            """insert into case_cycles (client_id, cycle_number, cycle_type)
               values (%s,%s,'NEW_CLIENT') returning cycle_id""",
            (client_id, nxt)).fetchone()[0])
    return str(conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type, max_loops)
           values (%s,%s,'NEW_CLIENT',%s) returning cycle_id""",
        (client_id, nxt, max_loops)).fetchone()[0])


def spend_routing_hop(conn: psycopg.Connection, cycle_id: str) -> None:
    """Charge ONE routing hop against the cycle's budget.

    `ck_loop_bound` (loop_count <= max_loops) does the refusing; this turns
    the constraint violation into a message that says what actually
    happened. A hop is one pass through the engines, not one engine call --
    `max_loops` defaults to 3 and this pipeline runs seven engines, so
    charging per call would make every correct run fail.
    """
    try:
        with conn.transaction():
            conn.execute(
                "update case_cycles set loop_count = loop_count + 1 where cycle_id=%s",
                (cycle_id,))
    except psycopg.errors.CheckViolation as exc:
        budget = conn.execute(
            "select loop_count, max_loops from case_cycles where cycle_id=%s",
            (cycle_id,)).fetchone()
        raise PipelineStopped(
            f"cycle {cycle_id} has already used its routing budget "
            f"({budget[0]} of {budget[1]} hops). Re-running the engines "
            "against it would be the unbounded loop ck_loop_bound exists to "
            "stop. Open a new cycle, or raise max_loops deliberately."
        ) from exc


def _run(conn: psycopg.Connection, outcome: Outcome, name: str, **kwargs) -> Any:
    """Run one engine, record the step, and stop the pipeline if it failed."""
    result = RE.run_engine(conn, RE.EngineRequest(
        client_id=outcome.client_id, cycle_id=outcome.cycle_id,
        case_version_id=outcome.case_version_id, **kwargs))
    outcome.step(name, result.status, result.run_id,
                 result.error or (f"handoff {result.handoff_tag}"
                                  if result.handoff_tag else "NO HANDOFF"))
    if result.status != "SUCCEEDED":
        raise PipelineStopped(
            f"{name} did not succeed ({result.status}): {result.error}. "
            "The pipeline stops rather than feeding a missing output to the "
            "next engine.")
    # ENGINE_RUN_STATUS is the engine's own verdict and is not the same as
    # the run completing. A run that returned a well-formed control block
    # saying FAILED is a failure with good manners.
    declared = (result.control or {}).get("ENGINE_RUN_STATUS")
    if declared in ("FAILED", "INSUFFICIENT_INPUT"):
        raise PipelineStopped(
            f"{name} reported {declared}: "
            f"{(result.control or {}).get('ERROR_STATE') or 'no reason given'}")
    # Belt and braces over RUN_ENGINE's own enforcement. A run that
    # SUCCEEDED carries a handoff by construction since D24, and if that
    # ever stops being true this pipeline must not be the thing that
    # quietly passes a control block downstream as reasoning.
    if not result.structured:
        raise PipelineStopped(
            f"{name} succeeded but produced no substantive handoff. The "
            "control block routes; it is not what the next engine reasons "
            "over, and passing it on as though it were is the failure this "
            "check exists to make impossible.")
    return result


def _new_case_version(conn: psycopg.Connection, client_id: str,
                      state: dict | None, phase: str, reason: str,
                      delta: dict | None = None) -> str:
    """Append a case version and make it current.

    Never overwrites history (MASTER_SPEC phase 6): the previous row stays,
    with is_current cleared. The version number is derived inside the same
    statement pair so two callers cannot both think they are version 2.

    `state` must be a FULL state -- Engine 6's <CASE_MEMORY_HANDOFF>. A
    <CASE_MEMORY_DELTA> goes in `delta`, which 004 created for it, and is
    never passed here as `state`: get_current_client_state() would then
    return a description of a change as though it were the case.
    """
    if not state:
        raise PipelineStopped(
            "Engine 6 produced no full canonical state, so there is nothing "
            "to record as this version. A delta describes a change and is "
            "not a case; refusing to store one as canonical_state.")
    conn.execute(
        "update client_case_versions set is_current=false "
        "where client_id=%s and is_current", (client_id,))
    return str(conn.execute(
        """insert into client_case_versions
             (client_id, case_version, canonical_state, delta, phase,
              change_reason, created_by, is_current)
           values (%s,
                   (select coalesce(max(case_version), 0) + 1
                      from client_case_versions where client_id=%s),
                   %s,%s,%s,%s,'E6',true)
           returning case_version_id""",
        (client_id, client_id, json.dumps(state),
         json.dumps(delta) if delta else None,
         phase, reason)).fetchone()[0])


def run_new_client(conn: psycopg.Connection, submission_id: str,
                   llm=None, max_loops: int | None = None) -> Outcome:
    """Run the phase-4 pipeline for one submitted intake.

    `llm` is the callable C3 uses when the deterministic tiers cannot
    resolve a phrase. Omitted, normalization still runs and unresolved
    phrases are PROPOSED rather than invented -- which is the correct
    degraded behaviour, not a reason to skip the step.
    """
    row = conn.execute(
        "select client_id, status::text from intake_submissions where submission_id=%s",
        (submission_id,)).fetchone()
    if row is None:
        raise PipelineStopped(f"no intake submission {submission_id}")
    client_id, submission_status = str(row[0]), row[1]
    outcome = Outcome(client_id=client_id, submission_id=str(submission_id))

    if submission_status == "CONVERTED":
        outcome.status = "ALREADY_CONVERTED"
        outcome.stopped_because = (
            "this submission has already initialized a case. Converting it "
            "again would create a second version 1.")
        return outcome

    try:
        # ------------------------------------------------------------------
        # Intake -> the typed case tables, and the E6 input.
        counts = IN.extract(conn, submission_id)
        outcome.step("INTAKE_EXTRACT", "OK", detail=json.dumps(counts))

        e6_input = IN.to_e6_input(conn, submission_id)
        outcome.cycle_id = open_cycle(conn, client_id, max_loops)
        # One hop, charged once, before any engine runs. Charging after
        # would let a pipeline that crashes halfway be retried forever.
        spend_routing_hop(conn, outcome.cycle_id)
        outcome.step("CYCLE_OPEN", "OK", detail=outcome.cycle_id)

        # ------------------------------------------------------------------
        # E6 initial state. Runs on whatever intake produced, complete or
        # not: an incomplete intake gets a case, not a rejection (D22).
        #
        # canonical_state comes from E6's OWN <CASE_MEMORY_HANDOFF>, not
        # from the input we handed it. Migration 004 calls the column "Full
        # canonical state (CASE_MEMORY_HANDOFF)" and it means it: storing
        # the pre-E6 input there recorded the question rather than Engine
        # 6's answer, and every engine downstream read it through
        # get_current_client_state().
        e6_init = _run(conn, outcome, "E6_INIT", engine="E6", mode="INIT",
                       structured_input=e6_input)
        outcome.case_version_id = _new_case_version(
            conn, client_id, e6_init.structured, "PHASE_1",
            f"Initialized from intake submission {submission_id}",
            delta=e6_init.secondary_handoffs.get("CASE_MEMORY_DELTA"))
        IN.mark_converted(conn, submission_id, outcome.case_version_id)
        outcome.step("CASE_VERSION_1", "OK", detail=outcome.case_version_id)

        # Read back through the same column every engine reads, so what the
        # pipeline hands downstream is what get_current_client_state()
        # would return rather than a local variable that happens to agree.
        case_state = conn.execute(
            "select canonical_state from client_case_versions where case_version_id=%s",
            (outcome.case_version_id,)).fetchone()[0]

        # What each engine hands the next is its SUBSTANTIVE handoff, never
        # its control block. The control block is ~17 typed routing fields
        # (D14); it contains no strategies, no evidence, no targets. Passing
        # it as `E7_HANDOFF` and `E1_HANDOFF` -- which is what this pipeline
        # did before D24 -- meant the sequence executed while almost none of
        # the reasoning moved.
        #
        # CASE_VERSION comes from the DATABASE, not from the handoff.
        #
        # A handoff block is line-oriented `KEY: text` -- the format every
        # prompt specifies -- so every value in it is a STRING. Engine 6
        # writes `CASE_VERSION: 1` and it parses as "1", which the control
        # contract then rejects as not an integer, correctly. The lesson is
        # not to coerce per field: it is that typed values come from typed
        # places. `client_case_versions.case_version` is an integer column
        # assigned by the insert, and D18 rests on stored versions starting
        # at 1. Engine 6's line is its claim; the row is the fact.
        case_version = conn.execute(
            "select case_version from client_case_versions where case_version_id=%s",
            (outcome.case_version_id,)).fetchone()[0]
        case_input = {"CASE_VERSION": case_version,
                      "CANONICAL_STATE": case_state}

        # ------------------------------------------------------------------
        # E1 Pass A. Same specification as Pass B, different context and
        # stopping point (D4) -- the two runs must record one prompt hash,
        # and trg_enforce_two_pass rejects the insert if they do not.
        # No hand-written "MODE" key. RUN_ENGINE injects the resolved mode
        # into the runtime envelope for every engine, so a caller cannot
        # forget it -- which is exactly what happened to E6 and E7 while E1
        # looked fine because this line existed.
        pass_a = _run(conn, outcome, "E1_PASS_A", engine="E1", pass_label="A",
                      mode="SINGLE", structured_input=case_input)

        # ------------------------------------------------------------------
        # C3. Pass A emits clinical phrases; Engine 7 should retrieve on
        # canonical concepts. Cheapest tier first, LLM last, and an
        # unresolved phrase is proposed rather than created (D2, D3).
        phrases = pass_a.control.get("NORMALIZATION_PHRASES") or []
        resolutions = NZ.resolve_all(conn, phrases, llm=llm) if phrases else []
        resolved = [r for r in resolutions if r.concept_ids]
        outcome.step("NORMALIZE", "OK",
                     detail=f"{len(resolved)} of {len(phrases)} phrases resolved")

        # ------------------------------------------------------------------
        # E7 in CASE mode. CASE_VERSION is the real version here, not 0:
        # 0 is reserved for knowledge-clock runs (D18), and this run is
        # about one client's case.
        #
        # RESEARCH_QUESTIONS is one of the few things that legitimately
        # comes from the control block: it is a typed control-contract
        # field, and Pass A's substantive picture travels alongside it so
        # Engine 7 retrieves against the case rather than against a list of
        # questions with no context.
        e7 = _run(conn, outcome, "E7", engine="E7", mode="CASE",
                  model_role="MODEL_RESEARCH",
                  structured_input={
                      **case_input,
                      "CASE_RESEARCH_QUESTIONS": pass_a.control.get(
                          "RESEARCH_QUESTIONS", []),
                      "E1_PASS_A_HANDOFF": pass_a.structured,
                      "NORMALIZED_CONCEPTS": [
                          {"phrase": r.phrase, "concept_ids": r.concept_ids,
                           "method": r.method}
                          for r in resolved],
                  })

        # ------------------------------------------------------------------
        # E1 Pass B, with the E7 slot populated. Not a smaller Engine 1.
        # The E7 slot, populated. This is the entire reason Engine 1 runs
        # twice (D4), and it was being filled with E7's control block --
        # eight routing booleans instead of strategies, evidence, expected
        # effects, applicability and implementation notes.
        pass_b = _run(conn, outcome, "E1_PASS_B", engine="E1", pass_label="B",
                      mode="SINGLE",
                      structured_input={
                          **case_input,
                          "E7_HANDOFF": e7.structured,
                          "E1_PASS_A_HANDOFF": pass_a.structured,
                      })

        # ------------------------------------------------------------------
        # E2 makes behaviour executable, E3 makes nutrition executable.
        # Both run: a new client needs both, and this is not the place to
        # let an engine decide otherwise.
        e2 = _run(conn, outcome, "E2", engine="E2",
                  structured_input={**case_input,
                                    "E1_HANDOFF": pass_b.structured})
        e3 = _run(conn, outcome, "E3", engine="E3",
                  structured_input={**case_input,
                                    "E1_HANDOFF": pass_b.structured,
                                    "E2_HANDOFF": e2.structured})

        # ------------------------------------------------------------------
        # E6 update. A new version, never an overwrite.
        # REBUILD, not UPDATE.
        #
        # Engine 6 §A1: the full <CASE_MEMORY_HANDOFF> establishes or
        # REBUILDS state; the <CASE_MEMORY_DELTA> records an incremental
        # change and "is the normal path on follow-up". This is not a
        # follow-up -- the case is still being established, across this one
        # cycle, and version 2 must carry a complete state because
        # canonical_state is NOT NULL and every engine reads it through
        # get_current_client_state().
        #
        # A delta cannot be mechanically merged into a state: its fields
        # (NEW_FACTS, UPDATED_FACTS, RESOLVED_ITEMS) describe changes and do
        # not map onto the state's fields. Doing it anyway would be
        # inventing E6's semantics. So REBUILD asks for the full state, and
        # the delta -- optional in that mode -- is kept in the `delta`
        # column 004 created for it rather than discarded. CLIENT_FOLLOWUP
        # is where UPDATE and the delta path belong.
        e6_update_input = {
            **case_input,
            "CASE_VERSION": case_version + 1,
            "E1_HANDOFF": pass_b.structured,
            "E2_HANDOFF": e2.structured,
            "E3_HANDOFF": e3.structured,
            "NORMALIZED_CONCEPTS": [
                {"phrase": r.phrase, "concept_ids": r.concept_ids} for r in resolved],
        }
        e6_rebuild = _run(conn, outcome, "E6_UPDATE", engine="E6", mode="REBUILD",
                          structured_input=e6_update_input)
        outcome.final_case_version_id = _new_case_version(
            conn, client_id, e6_rebuild.structured, "PHASE_1",
            "Rebuilt after E1 Pass B, E2 and E3",
            delta=e6_rebuild.secondary_handoffs.get("CASE_MEMORY_DELTA"))
        outcome.step("CASE_VERSION_2", "OK", detail=outcome.final_case_version_id)

        # ------------------------------------------------------------------
        # The queue. This is where CLIENT_NEW ends.
        #
        # A new client is queued whatever the control block says. Engine 1
        # sets REVIEW_REQUIRED on its own analysis, but "the engines did not
        # ask for review" is not a reason to send a first plan to a client
        # unseen -- and the practitioner remains the professional decision
        # maker. The field is recorded so a later step can tell the two
        # apart.
        outcome.review_id = str(conn.execute(
            """insert into practitioner_reviews (client_id, cycle_id, run_id, decision, notes)
               values (%s,%s,%s,'PENDING',%s) returning review_id""",
            (client_id, outcome.cycle_id, pass_b.run_id,
             "CLIENT_NEW complete. E1 Pass A and Pass B, E7, E2, E3 and the "
             "E6 update are recorded. Engines requested review: "
             f"{bool(pass_b.control.get('REVIEW_REQUIRED'))}. "
             "No client-facing output has been drafted or sent."
             )).fetchone()[0])
        outcome.step("REVIEW_QUEUED", "OK", detail=outcome.review_id)

        outcome.status = "AWAITING_REVIEW"
        return outcome

    except PipelineStopped as exc:
        outcome.status = "STOPPED"
        outcome.stopped_because = str(exc)
        return outcome


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"\nusage: python3 scripts/client_new.py <submission_id>\n"
              f"pipeline: {PIPELINE_DESCRIPTION}")
        return 2
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        outcome = run_new_client(conn, sys.argv[1])
    print(f"status: {outcome.status}")
    for step in outcome.steps:
        print(f"  {step.name:16s} {step.status:12s} {step.detail[:70]}")
    if outcome.stopped_because:
        print(f"\nstopped: {outcome.stopped_because}")
    return 0 if outcome.status == "AWAITING_REVIEW" else 1


if __name__ == "__main__":
    sys.exit(main())
