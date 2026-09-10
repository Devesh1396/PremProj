#!/usr/bin/env python3
"""The substantive reasoning actually flows downstream (D24).

Every prompt defines TWO machine-readable outputs. `<CONTROL_BLOCK>` is
~17 typed fields for routing and gating; `<..._HANDOFF>` is the reasoning
the next engine thinks with. RUN_ENGINE parsed only the first,
`EngineResult.structured` was always None, `engine_outputs.structured` was
written from an input key nothing sets, and CLIENT_NEW passed control
blocks downstream as `E7_HANDOFF` and `E1_HANDOFF`. The sequence executed;
the thinking did not move.

THESE TESTS CANNOT PASS ON CONTROL-ONLY OUTPUT. Each fixture handoff
carries a sentinel -- `SENT-E7-CASE-STRATEGY` and friends -- that appears
in exactly one block and nowhere else, and the assertions are that the
sentinel reaches a specific downstream INPUT. Asserting "structured is not
empty" would have passed against a control block; asserting that Engine
7's strategy sentinel is in the bytes sent to Engine 1 Pass B cannot.

The last section proves the negative directly: a provider that emits a
perfectly valid control block and no handoff must dead-letter.
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
import load_handoffs as LH
import run_engine as RE
import synthetic_intake as SI

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


class Recorder:
    """Captures exactly what each engine was SENT.

    The proof has to be about the input a downstream engine received, not
    about a variable in this process. `user_prompt` is the serialized
    structured_input, so a sentinel found in it is a sentinel that was
    actually transmitted.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []   # (engine, pass, user_prompt)

    def __call__(self, system_prompt: str, user_prompt: str, params: dict):
        self.sent.append((params.get("engine", "?"),
                          params.get("pass_label", "SINGLE"), user_prompt))
        return RE.fixture_provider(system_prompt, user_prompt, params)

    def input_to(self, engine: str, pass_label: str | None = None) -> str:
        for eng, passed, prompt in self.sent:
            if eng == engine and (pass_label is None or passed == pass_label):
                return prompt
        return ""

    def last_input_to(self, engine: str) -> str:
        for eng, _p, prompt in reversed(self.sent):
            if eng == engine:
                return prompt
        return ""


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    assert RE.select_provider()[1] == "fixture", \
        "test suite must run on the fixture provider"

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    SI.clear(conn)
    conn.execute("delete from concepts where origin_detail like 'C3_NORMALIZATION%'")

    # ------------------------------------------------------------------
    print("\nthe registry says what each engine owes, per mode (D24)")
    check("E1 has one mode and defaults to it",
          LH.resolve_mode("E1", None) == "SINGLE")
    for engine in ("E6", "E7"):
        try:
            LH.resolve_mode(engine, None)
            check(f"{engine} refuses to guess its mode", False, "returned a default")
        except LH.HandoffModeUnknown as exc:
            check(f"{engine} refuses to guess its mode", "no default" in str(exc))

    check("E6 INIT expects a full state, not a delta",
          LH.expected(conn, "E6", "INIT") == [("CASE_MEMORY_HANDOFF", True)],
          str(LH.expected(conn, "E6", "INIT")))
    update = dict(LH.expected(conn, "E6", "UPDATE"))
    check("E6 UPDATE requires the delta and only tolerates a state",
          update["CASE_MEMORY_DELTA"] is True
          and update["CASE_MEMORY_HANDOFF"] is False, str(update))
    rebuild = dict(LH.expected(conn, "E6", "REBUILD"))
    check("E6 REBUILD requires the state and only tolerates a delta",
          rebuild["CASE_MEMORY_HANDOFF"] is True
          and rebuild["CASE_MEMORY_DELTA"] is False, str(rebuild))
    check("E7 CASE and FOUNDATION are different blocks",
          LH.expected(conn, "E7", "CASE") != LH.expected(conn, "E7", "FOUNDATION"))
    try:
        LH.expected(conn, "E1", "NO_SUCH_MODE")
        check("an unregistered mode fails loudly", False, "returned expectations")
    except LH.HandoffMissing as exc:
        check("an unregistered mode fails loudly",
              "will not treat a run as successful" in str(exc))
    check("CONTROL_BLOCK is not registered as a handoff",
          conn.execute("select count(*) from engine_handoffs "
                       "where tag='CONTROL_BLOCK'").fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\nRUN_ENGINE separates the three outputs")
    client = SI.load_client(conn, SI.EXTERNAL_REF_COMPLETE)
    submission = IN.submit(conn, client, SI.COMPLETE_INTAKE)

    recorder = Recorder()
    original = RE.select_provider
    RE.select_provider = lambda: (recorder, "fixture")
    try:
        outcome = CN.run_new_client(conn, submission)
    finally:
        RE.select_provider = original

    check("the pipeline reaches the review queue",
          outcome.status == "AWAITING_REVIEW",
          outcome.stopped_because or outcome.status)

    rows = conn.execute(
        """select r.engine::text, r.pass::text, o.handoff_tag, o.handoff_mode,
                  o.structured, o.control, o.human_output
             from engine_runs r join engine_outputs o on o.run_id = r.run_id
            where r.cycle_id=%s order by r.started_at""",
        (outcome.cycle_id,)).fetchall()
    check("every run recorded a handoff tag",
          all(r[2] for r in rows), str([(r[0], r[2]) for r in rows]))
    check("every run recorded substantive fields, not an empty object",
          all([k for k in r[4] if not k.startswith("_")] for r in rows),
          str([(r[0], list(r[4])[:2]) for r in rows]))
    check("the handoff is never the control block",
          all(set(r[4]) != set(r[5]) for r in rows))
    check("...and carries fields the control contract does not define",
          all(any(k not in r[5] and not k.startswith("_") for k in r[4])
              for r in rows))
    check("the human-readable output excludes the machine blocks",
          all("<" not in r[6] and "HANDOFF" not in r[6] for r in rows),
          str([r[6][:40] for r in rows if "<" in r[6]])[:200])
    # Scoped to this cycle on purpose. v_runs_missing_handoff is global and
    # legitimately non-empty on a used database: every run recorded before
    # migration 013 has a NULL handoff_tag, because there was no column to
    # write. A global count assertion here would pass on an empty database
    # and fail on a real one, which is bug 42 again.
    check("nothing in this cycle succeeded without a handoff",
          conn.execute("select count(*) from v_runs_missing_handoff "
                       "where cycle_id=%s", (outcome.cycle_id,)).fetchone()[0] == 0)
    check("the raw block is kept so nothing is silently discarded",
          all("_raw" in r[4] and r[4]["_raw"].strip() for r in rows))
    check("...along with the field order it arrived in",
          all(r[4].get("_field_order") for r in rows))

    # ------------------------------------------------------------------
    print("\nsentinels prove the reasoning reached each next engine")

    def in_input(engine: str, sentinel_value: str, pass_label: str | None = None) -> bool:
        return sentinel_value in recorder.input_to(engine, pass_label)

    # 1. E6 initial state -> canonical V1, and on to E1 Pass A.
    v1 = conn.execute(
        "select canonical_state from client_case_versions where case_version_id=%s",
        (outcome.case_version_id,)).fetchone()[0]
    e6_init_sentinel = RE.sentinel("E6", "INIT", "PRIMARY-PROBLEM")
    check("E6's initial state sentinel is the canonical V1",
          v1.get("PRIMARY_HEALTH_PROBLEM") == e6_init_sentinel, str(v1)[:160])
    check("...and V1 is E6's OUTPUT, not the intake we fed it",
          "INTAKE_SUBMISSION_ID" not in v1 and "MISSING_DATA_POLICY" not in v1,
          str(sorted(v1))[:200])
    check("...and it reaches Engine 1 Pass A",
          in_input("E1", e6_init_sentinel, "A"))

    # 2. E7 strategies and evidence -> E1 Pass B. The entire reason E1 runs
    #    twice (D4), and this slot used to hold E7's routing booleans.
    for what in ("STRATEGY", "EVIDENCE", "EFFECT-MAGNITUDE", "APPLICABILITY",
                 "IMPLEMENTATION"):
        s = RE.sentinel("E7", "CASE", what)
        check(f"E7's {what.lower()} reaches Engine 1 Pass B",
              in_input("E1", s, "B"), s)
    check("E7 received Pass A's picture, not only its questions",
          in_input("E7", RE.sentinel("E1", "A", "DRIVER")))

    # 3. E1 Pass B's finalized strategy -> E2 and E3.
    pass_b_strategy = RE.sentinel("E1", "B", "STRATEGY")
    check("Engine 1 Pass B's strategy reaches Engine 2",
          in_input("E2", pass_b_strategy), pass_b_strategy)
    check("...and Engine 3", in_input("E3", pass_b_strategy))
    check("Pass B's nutrition objectives reach Engine 3",
          in_input("E3", RE.sentinel("E1", "B", "NUTRITION-OBJECTIVE")))
    check("Pass B's behaviour requirement reaches Engine 2",
          in_input("E2", RE.sentinel("E1", "B", "BEHAVIOUR-REQUIRED")))
    # It must be PASS B's picture, not Pass A's: Pass B is the one that has
    # seen Engine 7.
    check("Engine 2 gets Pass B's finalized picture, not Pass A's",
          not in_input("E2", RE.sentinel("E1", "A", "STRATEGY")),
          "Pass A's strategy sentinel leaked into Engine 2's input")

    # 4. E2's implementation -> E3.
    check("Engine 2's implementation steps reach Engine 3",
          in_input("E3", RE.sentinel("E2", "SINGLE", "IMPLEMENTATION-STEP")))
    check("...and its adherence risks",
          in_input("E3", RE.sentinel("E2", "SINGLE", "ADHERENCE-RISK")))

    # 5. E1, E2 and E3 -> the E6 rebuild.
    e6_update_input = recorder.last_input_to("E6")
    for name, s in (("Engine 1 Pass B", RE.sentinel("E1", "B", "STRATEGY")),
                    ("Engine 2", RE.sentinel("E2", "SINGLE", "BEHAVIOUR-PLAN")),
                    ("Engine 3", RE.sentinel("E3", "SINGLE", "MEAL-STRUCTURE"))):
        check(f"{name}'s handoff reaches the Engine 6 rebuild", s in e6_update_input, s)

    # 6. E6's rebuilt state -> canonical V2.
    v2, v2_delta = conn.execute(
        "select canonical_state, delta from client_case_versions "
        "where case_version_id=%s", (outcome.final_case_version_id,)).fetchone()
    check("E6's rebuilt state sentinel is the canonical V2",
          v2.get("PRIMARY_HEALTH_PROBLEM")
          == RE.sentinel("E6", "REBUILD", "PRIMARY-PROBLEM"), str(v2)[:160])
    check("...and V2 is not merely the input we fed the rebuild",
          "E1_HANDOFF" not in v2 and "NORMALIZED_CONCEPTS" not in v2,
          str(sorted(v2))[:200])
    check("V2 differs from V1: state moved, it was not copied",
          v2.get("PRIMARY_HEALTH_PROBLEM") != v1.get("PRIMARY_HEALTH_PROBLEM"))

    # ------------------------------------------------------------------
    print("\na delta is never stored as a state, and never discarded")
    check("the delta E6 also emitted is kept in the delta column",
          v2_delta and v2_delta.get("NEW_FACTS")
          == RE.sentinel("E6", "REBUILD", "DELTA-NEW-FACT"), str(v2_delta)[:160])
    check("...and not in canonical_state",
          "NEW_FACTS" not in v2 and "UPDATED_FACTS" not in v2, str(sorted(v2))[:200])
    check("V1 has no delta: nothing changed, it was established",
          conn.execute(
              "select delta from client_case_versions where case_version_id=%s",
              (outcome.case_version_id,)).fetchone()[0] is None)
    check("the rebuild row records which block became the state",
          conn.execute(
              """select o.handoff_tag from engine_runs r
                   join engine_outputs o on o.run_id=r.run_id
                  where r.cycle_id=%s and r.engine='E6'
                  order by r.started_at desc limit 1""",
              (outcome.cycle_id,)).fetchone()[0] == "CASE_MEMORY_HANDOFF")
    check("...and kept the delta beside it rather than dropping it",
          "CASE_MEMORY_DELTA" in conn.execute(
              """select o.secondary_handoffs from engine_runs r
                   join engine_outputs o on o.run_id=r.run_id
                  where r.cycle_id=%s and r.engine='E6'
                  order by r.started_at desc limit 1""",
              (outcome.cycle_id,)).fetchone()[0])

    # A delta can never reach canonical_state, even if a caller tries.
    try:
        CN._new_case_version(conn, client, None, "PHASE_1", "no state")
        check("a version cannot be created without a full state", False,
              "the insert was accepted")
    except CN.PipelineStopped as exc:
        check("a version cannot be created without a full state",
              "is not a case" in str(exc))

    # ------------------------------------------------------------------
    print("\nA VALID CONTROL BLOCK IS NOT EVIDENCE OF WORK")
    # The negative. This is the shape of every response before D24: the
    # control block parses, validates and routes, and there is no reasoning
    # anywhere in it.
    def control_only(system_prompt: str, user_prompt: str, params: dict):
        control = {
            "CASE_VERSION": params.get("case_version", 1),
            "ENGINE_RUN_STATUS": "SUCCEEDED",
            "REVIEW_REQUIRED": False,
            "ROUTING_RECOMMENDATION": "NONE",
            "NEXT_ENGINE": "NONE",
            "LOOP_COUNT": 0,
        }
        body = (f"a perfectly reasonable looking report\n\n<{RE.CONTROL_TAG}>\n"
                f"{json.dumps(control)}\n</{RE.CONTROL_TAG}>\n")
        return body, 10, 10

    RE.select_provider = lambda: (control_only, "fixture")
    try:
        bare = RE.run_engine(conn, RE.EngineRequest(
            engine="E6", mode="INIT", client_id=client,
            structured_input={"CASE_VERSION": 1}))
    finally:
        RE.select_provider = original

    check("a control-only response DEAD-LETTERS", bare.status == "DEAD_LETTER",
          bare.status)
    check("...naming the missing block and why it matters",
          "CASE_MEMORY_HANDOFF" in (bare.error or "")
          and "reasoning the next engine needs" in (bare.error or ""),
          str(bare.error)[:200])
    check("...and writes no engine_outputs row",
          conn.execute("select count(*) from engine_outputs where run_id=%s",
                       (bare.run_id,)).fetchone()[0] == 0)
    check("...and the control block being valid did not save it",
          conn.execute("select error_class::text from engine_runs where run_id=%s",
                       (bare.run_id,)).fetchone()[0] == "SCHEMA_INVALID")

    # A block with the right tag and nothing in it is not a handoff either.
    def empty_block(system_prompt: str, user_prompt: str, params: dict):
        body, _i, _o = control_only(system_prompt, user_prompt, params)
        return ("<CASE_MEMORY_HANDOFF>\n\n</CASE_MEMORY_HANDOFF>\n" + body), 10, 10

    RE.select_provider = lambda: (empty_block, "fixture")
    try:
        hollow = RE.run_engine(conn, RE.EngineRequest(
            engine="E6", mode="INIT", client_id=client,
            structured_input={"CASE_VERSION": 1}))
    finally:
        RE.select_provider = original
    check("an empty handoff block is not a handoff",
          hollow.status == "DEAD_LETTER", hollow.status)

    # And the pipeline as a whole must refuse it.
    stop_client, stop_sub = (SI.load_client(conn, SI.EXTERNAL_REF_MALE),
                             None)
    stop_sub = IN.submit(conn, stop_client, SI.MALE_INTAKE)
    RE.select_provider = lambda: (control_only, "fixture")
    try:
        stopped = CN.run_new_client(conn, stop_sub)
    finally:
        RE.select_provider = original
    check("CLIENT_NEW stops when engines produce only control blocks",
          stopped.status == "STOPPED", stopped.status)
    check("...at the first engine, before any case version exists",
          conn.execute(
              "select count(*) from client_case_versions where client_id=%s",
              (stop_client,)).fetchone()[0] == 0,
          str([s.name for s in stopped.steps]))

    SI.clear(conn)
    conn.execute("delete from concepts where origin_detail like 'C3_NORMALIZATION%'")

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
