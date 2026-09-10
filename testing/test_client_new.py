#!/usr/bin/env python3
"""CLIENT_NEW — a submitted intake through to the practitioner's queue.

BUILD_GUIDE step 15, MASTER_SPEC phase 4.

The assertions are about the SHAPE of the pipeline, not that it ran. That
it ran is the easy half; what matters is what it refuses to do:

  - it never sends anything to a client, and never drafts anything to send
  - an open HOLD flag does not stop the analysis (hard rule 9)
  - a failed engine stops the pipeline instead of feeding nothing forward
  - both Engine 1 passes record ONE prompt hash (D4)
  - history is appended, never overwritten
  - an incomplete intake still gets a case (D22)
  - the same submission cannot initialize a second case
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing" / "fixtures"))

import psycopg
import client_new as CN
import intake as IN
import run_engine as RE
import synthetic_intake as SI

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def submit_fixture(conn, ref: str, payload: dict) -> tuple[str, str]:
    client_id = SI.load_client(conn, ref)
    return client_id, IN.submit(conn, client_id, payload)


def main() -> int:
    # Never a live provider. A suite that spends money per run is a suite
    # nobody runs.
    os.environ["LLM_API_KEY"] = ""
    assert RE.select_provider()[1] == "fixture", \
        "test suite must run on the fixture provider"

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    SI.clear(conn)
    conn.execute("delete from concepts where canonical_key like 'PHRASE_%' "
                 "or origin_detail like 'C3_NORMALIZATION%'")

    # ------------------------------------------------------------------
    print("\nthe phase 4 pipeline, end to end on a complete intake")
    client, submission = submit_fixture(
        conn, SI.EXTERNAL_REF_COMPLETE, SI.COMPLETE_INTAKE)
    outcome = CN.run_new_client(conn, submission)
    check("the pipeline reaches the review queue",
          outcome.status == "AWAITING_REVIEW",
          outcome.stopped_because or outcome.status)

    names = [s.name for s in outcome.steps]
    check("it runs the phase 4 sequence in order",
          names == ["INTAKE_EXTRACT", "CYCLE_OPEN", "E6_INIT", "CASE_VERSION_1",
                    "E1_PASS_A", "NORMALIZE",
                    # Step 23. After normalization because the block is
                    # filtered by the case's resolved concepts, and before
                    # E7 because both E7 and Pass B receive it (D45).
                    "PRACTICE_EXPERIENCE",
                    "E7", "E1_PASS_B", "E2", "E3",
                    # Step 20. The plan becomes rows, and only then do the
                    # deterministic rules run -- a rule that matches on an
                    # intervention name has nothing to match against until
                    # the plan exists (D6). SAFETY_RULES before
                    # REVIEW_QUEUED so the practitioner sees the flags with
                    # the case rather than after deciding.
                    "E2_PLAN_ITEMS", "E3_PLAN_ITEMS",
                    "E6_UPDATE", "CASE_VERSION_2",
                    "SAFETY_RULES", "REVIEW_QUEUED"],
          str(names))
    check("every engine step succeeded",
          all(s.status in ("OK", "SUCCEEDED") for s in outcome.steps),
          str([(s.name, s.status) for s in outcome.steps if s.status
               not in ("OK", "SUCCEEDED")]))

    engines = [r[0] for r in conn.execute(
        "select engine::text from engine_runs where cycle_id=%s order by started_at",
        (outcome.cycle_id,)).fetchall()]
    check("seven engine runs are recorded against the cycle",
          engines == ["E6", "E1", "E7", "E1", "E2", "E3", "E6"], str(engines))

    # ------------------------------------------------------------------
    print("\nEngine 4 and Engine 5 do not run (and that is the point)")
    check("Engine 4 never runs: there is no response data to learn from",
          "E4" not in engines)
    check("Engine 5 never runs: release is gated on a decision that does "
          "not exist yet", "E5" not in engines)
    check("nothing was drafted for a client",
          conn.execute(
              "select count(*) from client_communications where client_id=%s",
              (client,)).fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\nthe practitioner is the decision maker (hard rule 3, hard rule 9)")
    review = conn.execute(
        """select decision::text, run_id, cycle_id, notes from practitioner_reviews
            where review_id=%s""", (outcome.review_id,)).fetchone()
    check("a review is queued PENDING", review[0] == "PENDING", str(review[0]))
    check("...attached to the run that produced the analysis",
          str(review[1]) is not None and str(review[2]) == outcome.cycle_id)
    check("...and says plainly that nothing has been sent",
          "No client-facing output has been drafted or sent" in review[3])
    check("the queue view surfaces it",
          conn.execute(
              "select count(*) from v_review_queue where client_id=%s",
              (client,)).fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nboth Engine 1 passes are the same specification (D4)")
    hashes = conn.execute(
        "select distinct prompt_hash from engine_runs where cycle_id=%s and engine='E1'",
        (outcome.cycle_id,)).fetchall()
    check("one prompt hash across Pass A and Pass B", len(hashes) == 1, str(hashes))
    passes = sorted(r[0] for r in conn.execute(
        "select pass::text from engine_runs where cycle_id=%s and engine='E1'",
        (outcome.cycle_id,)).fetchall())
    check("both passes are recorded as A and B", passes == ["A", "B"], str(passes))
    check("every run cites the registered contract version",
          {r[0] for r in conn.execute(
              "select distinct schema_version from engine_runs where cycle_id=%s",
              (outcome.cycle_id,)).fetchall()} == {RE.SCHEMA_VERSION})

    # ------------------------------------------------------------------
    print("\nhistory is appended, never overwritten (phase 6)")
    versions = conn.execute(
        """select case_version, is_current, phase, change_reason
             from client_case_versions where client_id=%s order by case_version""",
        (client,)).fetchall()
    check("two case versions exist", len(versions) == 2, str(versions))
    check("version 1 is retained and no longer current",
          versions[0][0] == 1 and versions[0][1] is False, str(versions[0]))
    check("version 2 is current", versions[1][0] == 2 and versions[1][1] is True)
    check("each version says why it exists",
          all(v[3] for v in versions), str([v[3] for v in versions]))
    check("get_current_client_state returns version 2",
          conn.execute("select get_current_client_state(%s)",
                       (client,)).fetchone()[0]["case_version"] == 2)

    state, final_delta = conn.execute(
        "select canonical_state, delta from client_case_versions "
        "where case_version_id=%s", (outcome.final_case_version_id,)).fetchone()
    # Before D24 this asserted the state carried E1_CONTROL / E2_CONTROL /
    # E3_CONTROL -- which was the bug written down as a test: the version
    # was built from the INPUT we handed Engine 6, and what it carried were
    # control blocks. The state is now Engine 6's own <CASE_MEMORY_HANDOFF>.
    check("the final state is Engine 6's own canonical state",
          state.get("PRIMARY_HEALTH_PROBLEM")
          == RE.sentinel("E6", "REBUILD", "PRIMARY-PROBLEM"), str(sorted(state))[:200])
    check("...not the input the rebuild was given",
          "E1_HANDOFF" not in state and "NORMALIZED_CONCEPTS" not in state,
          str(sorted(state))[:200])
    check("...and the delta Engine 6 also reported is kept beside it",
          final_delta and final_delta.get("NEW_FACTS"), str(final_delta)[:120])

    # ------------------------------------------------------------------
    print("\nno client identity reaches an engine")
    # STRIP_IDENTITY_FROM_ENGINE_PAYLOADS: the payload carries client_id and
    # clinical facts, never the display name.
    display_name = conn.execute(
        "select display_name from clients where client_id=%s", (client,)).fetchone()[0]
    leaked = conn.execute(
        """select count(*) from engine_runs r
             join engine_outputs o on o.run_id = r.run_id
            where r.cycle_id=%s and o.structured::text like %s""",
        (outcome.cycle_id, f"%{display_name}%")).fetchone()[0]
    check("the display name is in no engine output", leaked == 0, str(leaked))
    check("...and not in the canonical state either",
          display_name not in json.dumps(state), display_name)

    # ------------------------------------------------------------------
    print("\nthe submission cannot initialize a second case")
    again = CN.run_new_client(conn, submission)
    check("a converted submission is refused", again.status == "ALREADY_CONVERTED",
          again.status)
    check("...with a reason rather than a crash",
          "already initialized" in (again.stopped_because or ""),
          str(again.stopped_because))
    check("no second version 1 was created",
          conn.execute(
              "select count(*) from client_case_versions where client_id=%s and case_version=1",
              (client,)).fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nan open HOLD flag does not stop the analysis (hard rule 9)")
    held_client, held_sub = submit_fixture(
        conn, SI.EXTERNAL_REF_MALE, SI.MALE_INTAKE)
    conn.execute(
        """insert into case_flags (client_id, rule_key, severity, source, detail, status)
           values (%s,'TEST_HOLD','HOLD','PRACTITIONER','synthetic hold','OPEN')""",
        (held_client,))
    held = CN.run_new_client(conn, held_sub)
    check("the pipeline runs to the queue with a HOLD open",
          held.status == "AWAITING_REVIEW", held.stopped_because or held.status)
    check("...having still sent nothing",
          conn.execute(
              "select count(*) from client_communications where client_id=%s",
              (held_client,)).fetchone()[0] == 0)
    check("the HOLD is still open and still visible in the queue",
          conn.execute(
              "select open_holds from v_review_queue where client_id=%s",
              (held_client,)).fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nan incomplete intake still gets a case (D22)")
    sparse_client, sparse_sub = submit_fixture(
        conn, SI.EXTERNAL_REF_SPARSE, SI.SPARSE_INTAKE)
    sparse = CN.run_new_client(conn, sparse_sub)
    check("a sparse intake reaches the review queue",
          sparse.status == "AWAITING_REVIEW",
          sparse.stopped_because or sparse.status)
    # The gaps live in missing_data_reports and travel to Engine 6 in its
    # INPUT; the canonical state is Engine 6's answer, not that input. So
    # assert the gaps where they actually are, and assert that the sparse
    # intake still produced a state at all.
    sparse_e6_input = IN.to_e6_input(conn, sparse_sub)
    check("the sparse intake still reported its gaps to Engine 6",
          len(sparse_e6_input["HIGH_PRIORITY_MISSING_DATA"]) >= 3,
          str(len(sparse_e6_input["HIGH_PRIORITY_MISSING_DATA"])))
    check("...and unasked sections were UNKNOWN, never defaulted",
          sparse_e6_input["FOOD_ENVIRONMENT"] == IN.UNKNOWN,
          str(sparse_e6_input["FOOD_ENVIRONMENT"]))
    check("...and the gaps are recorded against the submission",
          conn.execute(
              """select count(*) from missing_data_reports
                  where submission_id=%s and severity in ('CRITICAL','HIGH')""",
              (sparse_sub,)).fetchone()[0] >= 3)
    sparse_state = conn.execute(
        "select canonical_state from client_case_versions "
        "where client_id=%s and case_version=1", (sparse_client,)).fetchone()[0]
    check("an incomplete intake still yields a real canonical state",
          sparse_state.get("PRIMARY_HEALTH_PROBLEM")
          == RE.sentinel("E6", "INIT", "PRIMARY-PROBLEM"), str(sorted(sparse_state))[:160])

    # ------------------------------------------------------------------
    print("\na failed engine stops the pipeline rather than guessing")
    stop_client, stop_sub = submit_fixture(
        conn, SI.EXTERNAL_REF_MALFORMED, SI.MALFORMED_INTAKE)

    def refuses(system, user, params):
        # Well-formed, and says it failed. A control block with good manners
        # is still a failure, and the pipeline must read the field rather
        # than the fact that a response arrived.
        if params.get("engine") == "E7":
            # A COMPLETE response -- handoff and all -- whose control block
            # declares FAILED. Since D24 a response without its handoff
            # dead-letters, which would stop the pipeline for a different
            # reason and stop this test proving what it claims: that the
            # pipeline reads the declared status rather than the fact that
            # a well-formed response arrived.
            blocks = RE.fixture_handoffs("E7", "CASE", params)
            return ("no\n"
                    + "".join(f"<{t}>\n{b}\n</{t}>\n" for t, b in blocks.items())
                    + '<CONTROL_BLOCK>\n'
                      '{"CASE_VERSION":1,"ENGINE_RUN_STATUS":"FAILED",'
                      '"ERROR_STATE":"library unreachable"}\n</CONTROL_BLOCK>'), 10, 10
        return RE.fixture_provider(system, user, params)

    original = RE.select_provider
    RE.select_provider = lambda: (refuses, "fixture")
    try:
        stopped = CN.run_new_client(conn, stop_sub)
    finally:
        RE.select_provider = original

    check("the pipeline stops", stopped.status == "STOPPED", stopped.status)
    check("...naming the engine and its reason",
          "E7" in (stopped.stopped_because or "")
          and "library unreachable" in (stopped.stopped_because or ""),
          str(stopped.stopped_because))
    reached = [s.name for s in stopped.steps]
    check("...before running anything downstream of it",
          "E1_PASS_B" not in reached and "E2" not in reached and "E3" not in reached,
          str(reached))
    check("...and queues no review for an analysis that did not happen",
          stopped.review_id is None
          and conn.execute(
              "select count(*) from v_review_queue where client_id=%s",
              (stop_client,)).fetchone()[0] == 0)
    check("the case version created before the failure is retained",
          conn.execute(
              "select count(*) from client_case_versions where client_id=%s",
              (stop_client,)).fetchone()[0] == 1)

    # ------------------------------------------------------------------
    print("\nrouting depth is bounded (ck_loop_bound)")
    budget = conn.execute(
        "select loop_count, max_loops from case_cycles where cycle_id=%s",
        (outcome.cycle_id,)).fetchone()
    check("a straight-line pipeline spends ONE hop, not one per engine",
          budget[0] == 1, f"{budget[0]} of {budget[1]} for 7 engine calls")
    check("...which is well inside the default budget", budget[0] <= budget[1])

    exhausted = CN.open_cycle(conn, client, max_loops=1)
    CN.spend_routing_hop(conn, exhausted)
    try:
        CN.spend_routing_hop(conn, exhausted)
        check("spending past the budget is refused", False, "the UPDATE was accepted")
    except CN.PipelineStopped as exc:
        check("spending past the budget is refused",
              "routing budget" in str(exc) and "unbounded loop" in str(exc))
    check("the cycle was not left over its own limit",
          conn.execute("select loop_count <= max_loops from case_cycles where cycle_id=%s",
                       (exhausted,)).fetchone()[0])

    # ------------------------------------------------------------------
    print("\nnormalization ran, and proposed rather than invented")
    proposals = conn.execute(
        """select count(*) from concepts
            where status='PROPOSED' and origin_detail like 'C3_NORMALIZATION%'"""
    ).fetchone()[0]
    check("unmatched Pass A phrases became PROPOSED concepts", proposals >= 1,
          str(proposals))
    check("...and none of them is ACTIVE or SEEDED",
          conn.execute(
              """select count(*) from concepts
                  where origin_detail like 'C3_NORMALIZATION%'
                    and status in ('ACTIVE','SEEDED')""").fetchone()[0] == 0)
    # The bug this pipeline found: a phrase with punctuation produced a key
    # the database rejects, and D2's own example phrase contains a hyphen.
    check("a phrase with punctuation produces a legal canonical_key",
          conn.execute(
              """select count(*) from concepts
                  where origin_detail like 'C3_NORMALIZATION%'
                    and canonical_key !~ '^[A-Z][A-Z0-9_]{2,79}$'""").fetchone()[0] == 0)

    SI.clear(conn)
    conn.execute("delete from concepts where canonical_key like 'PHRASE_%' "
                 "or origin_detail like 'C3_NORMALIZATION%'")

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
