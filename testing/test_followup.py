#!/usr/bin/env python3
"""CLIENT_FOLLOWUP and E4. Step 21.

BUILD_GUIDE step 21; migration `027`; D6, D42, D43. Hard rules 3, 5, 8, 9.

    follow-up -> E6 UPDATE -> E4 -> routing -> E1/E2/E3 -> E6 -> review

Everything here drives the real pipeline through the real `RUN_ENGINE` with
only the transport replaced (V2), and every optional dependency degrades
through `preflight` (V3).

The four properties a plausible follow-up pipeline loses:

1. **Routing reads a TYPED field.** `ROUTING_RECOMMENDATION`, never prose
   (hard rule 5), and an unknown value stops the pipeline rather than
   quietly routing nowhere.
2. **The routing budget is real.** `ck_loop_bound` refuses the hop past
   `max_loops`, so a case cannot cycle on its own recommendation.
3. **An outcome that changes leaves what it changed from.** IMPROVING
   becoming WORSENING is a clinical fact and a bare UPDATE loses it.
4. **A follow-up is processed once.** Re-running one spends another hop and
   writes a second set of outcomes over the first.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import client_followup as CF
import client_new as CN
import preflight
import run_engine as RE

FAILS: list[str] = []
PREFIX = "FUTEST_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def clear(conn) -> None:
    conn.execute("delete from clients where external_ref like %s", (PREFIX + "%",))


def seed_case(conn, ref: str, interventions=("fibre before carbohydrate",
                                             "walk after dinner")) -> dict:
    """A client mid-case: a version, a closed cycle, and live interventions."""
    client_id = str(conn.execute(
        "insert into clients (external_ref, display_name, year_of_birth, status) "
        "values (%s,%s,1980,'ACTIVE') returning client_id",
        (PREFIX + ref, PREFIX + ref)).fetchone()[0])
    conn.execute("select set_client_scope(%s::uuid)", (client_id,))
    conn.execute(
        "insert into client_case_versions (client_id, case_version, phase, "
        " canonical_state, is_current, change_reason, created_by) "
        "values (%s::uuid,1,'PHASE_1',%s::jsonb,true,%s,'FUTEST')",
        (client_id, json.dumps({"PRIMARY_HEALTH_PROBLEM": "fixture"}), "FUTEST"))
    ids = {}
    for name in interventions:
        ids[name] = str(conn.execute(
            "insert into client_interventions (client_id, name, status, "
            " source_engine, proposed_on) "
            "values (%s::uuid,%s,'ONGOING','E3',current_date) "
            "returning intervention_id", (client_id, name)).fetchone()[0])
    return {"client_id": client_id, "interventions": ids}


def submit_followup(conn, client_id: str, period: str = "week 6") -> str:
    return str(conn.execute(
        "insert into client_followups (client_id, review_period, submitted_on, "
        " raw_answers) values (%s::uuid,%s,current_date,%s::jsonb) "
        "returning followup_id",
        (client_id, period, json.dumps({"energy": "better", "sleep": "same"}))
    ).fetchone()[0])


def with_control(overrides: dict, outcomes: list | None = None):
    """The fixture provider, with E4's control block and outcomes steered.

    Wraps the REAL `fixture_provider` rather than replacing it, so the
    control contract, the handoff registry and the parser are all the
    production ones and only the two values under test differ (V2).
    """
    original = RE.fixture_provider

    def provider(system_prompt, user_prompt, params):
        text, tin, tout = original(system_prompt, user_prompt, params)
        if params.get("engine") != "E4":
            return text, tin, tout
        block = json.loads(text.split("<CONTROL_BLOCK>")[1]
                                .split("</CONTROL_BLOCK>")[0])
        block.update(overrides)
        text = (text.split("<CONTROL_BLOCK>")[0]
                + "<CONTROL_BLOCK>\n" + json.dumps(block) + "\n</CONTROL_BLOCK>"
                + text.split("</CONTROL_BLOCK>")[1])
        if outcomes is not None:
            head, rest = text.split("<PROGRESS_OUTCOMES>")
            _body, tail = rest.split("</PROGRESS_OUTCOMES>")
            text = (head + "<PROGRESS_OUTCOMES>\nOUTCOMES_JSON:\n"
                    + json.dumps(outcomes) + "\n</PROGRESS_OUTCOMES>" + tail)
        return text, tin, tout
    return provider


def run_with(conn, provider, followup_id: str):
    original = RE.select_provider
    RE.select_provider = lambda: (provider, "fixture")
    try:
        return CF.run_followup(conn, followup_id)
    finally:
        RE.select_provider = original


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    # ==================================================================
    print("\na follow-up needs a plan to be a response to")

    bare = str(conn.execute(
        "insert into clients (external_ref, display_name, status) "
        "values (%s,%s,'ACTIVE') returning client_id",
        (PREFIX + "bare", PREFIX + "bare")).fetchone()[0])
    conn.execute("select set_client_scope(%s::uuid)", (bare,))
    no_case = submit_followup(conn, bare)
    stopped = CF.run_followup(conn, no_case)
    check("a client with no case version is refused",
          stopped.status == "STOPPED" and "no plan" in (stopped.stopped_because or ""),
          str(stopped.stopped_because)[:120])

    empty = seed_case(conn, "no_plan", interventions=())
    nothing = submit_followup(conn, empty["client_id"])
    stopped2 = CF.run_followup(conn, nothing)
    check("a client with no live interventions is refused",
          stopped2.status == "STOPPED"
          and "no live interventions" in (stopped2.stopped_because or ""),
          str(stopped2.stopped_because)[:140])
    check("and it did NOT open a cycle or spend a hop",
          conn.execute("select count(*) from case_cycles where client_id=%s::uuid",
                       (empty["client_id"],)).fetchone()[0] == 0)

    # ==================================================================
    print("\nthe cycle runs, and routing reads a TYPED field")

    fx = seed_case(conn, "routed")
    followup = submit_followup(conn, fx["client_id"])
    result = run_with(conn, with_control({"ROUTING_RECOMMENDATION": "NONE"}),
                      followup)
    check("the pipeline reaches the review queue",
          result.status == "AWAITING_REVIEW",
          result.stopped_because or result.status)
    names = [s.name for s in result.steps]
    check("NONE runs no replanning engine",
          names == ["CYCLE_OPEN", "E6_UPDATE", "E4", "E4_OUTCOMES", "ROUTING",
                    "E6_FINAL", "CASE_VERSION", "SAFETY_RULES", "REVIEW_QUEUED"],
          str(names))
    check("...and says why in the routing step",
          result.routed == () and "NONE" in (result.routing_reason or ""),
          str(result.routing_reason))

    # ==================================================================
    print("\nE4's outcomes become rows, through the history function")

    outcomes = conn.execute(
        "select name, outcome::text, times_assessed, never_assessed "
        "  from v_intervention_response where client_id=%s::uuid order by name",
        (fx["client_id"],)).fetchall()
    check("every live intervention got an outcome",
          len(outcomes) == 2 and all(r[2] == 1 for r in outcomes), str(outcomes))
    check("the fixture reported TOO_EARLY, not a fabricated STABLE",
          all(r[1] == "TOO_EARLY" for r in outcomes), str(outcomes))
    check("and none reads as never_assessed any more",
          not any(r[3] for r in outcomes), str(outcomes))

    history = conn.execute(
        "select old_outcome::text, new_outcome::text, adherence, evidence "
        "  from intervention_outcome_history where client_id=%s::uuid limit 1",
        (fx["client_id"],)).fetchone()
    check("the history records what the outcome replaced",
          history[0] == "NOT_TRACKED" and history[1] == "TOO_EARLY", str(history))
    check("and keeps adherence SEPARATE from the outcome",
          history[2] is not None and history[3] is not None, str(history))

    # ==================================================================
    print("\na follow-up is processed once")

    again = CF.run_followup(conn, followup)
    check("re-running the same follow-up is refused",
          again.status == "STOPPED"
          and "already processed" in (again.stopped_because or ""),
          str(again.stopped_because)[:120])
    check("the outcome count did not double",
          conn.execute("select count(*) from intervention_outcome_history "
                       " where client_id=%s::uuid", (fx["client_id"],)
                       ).fetchone()[0] == 2)
    check("and it left the follow-up queue",
          conn.execute("select count(*) from v_followup_queue "
                       " where followup_id=%s::uuid", (followup,)).fetchone()[0] == 0)

    # ==================================================================
    print("\nan outcome that changes leaves what it changed from")

    second = submit_followup(conn, fx["client_id"], period="week 12")
    worse = [{"name": name, "outcome": "WORSENING",
              "adherence": "carried out most days",
              "evidence": "fasting glucose up 12 mg/dL"}
             for name in fx["interventions"]]
    second_out = run_with(
        conn, with_control({"ROUTING_RECOMMENDATION": "ENGINE1",
                      "ROUTING_REASON": "FUTEST routed ENGINE1"}, worse), second)
    check("the second cycle completed",
          second_out.status == "AWAITING_REVIEW",
          second_out.stopped_because or second_out.status)
    check("and it recorded an outcome for every live intervention",
          second_out.outcomes_recorded == 2, str(second_out.outcomes_recorded))

    trail = conn.execute(
        "select old_outcome::text, new_outcome::text from "
        " intervention_outcome_history where intervention_id=%s::uuid "
        " order by recorded_at", (list(fx["interventions"].values())[0],)).fetchall()
    check("both assessments are in the history, in order",
          [r[1] for r in trail] == ["TOO_EARLY", "WORSENING"], str(trail))
    check("and the second says what it replaced",
          trail[1][0] == "TOO_EARLY", str(trail))

    # ==================================================================
    print("\nhard rule 9: a worsening marker is a NOTE that does not block")

    flags = conn.execute(
        "select rule_key, severity::text from case_flags "
        " where client_id=%s::uuid and status='OPEN'", (fx["client_id"],)).fetchall()
    check("WORSENING_MARKER fired — the rule can finally reach a written column",
          ("WORSENING_MARKER", "NOTE") in flags, str(flags))
    readiness = conn.execute(
        "select open_holds, open_notes from v_release_readiness "
        " where client_id=%s::uuid", (fx["client_id"],)).fetchone()
    check("it is a NOTE and opens no HOLD", readiness[0] == 0 and readiness[1] >= 1,
          str(readiness))

    # ==================================================================
    print("\nrouting runs what the typed field named, and nothing else")

    fx2 = seed_case(conn, "multiple")
    f2 = submit_followup(conn, fx2["client_id"])
    multi = run_with(conn, with_control({"ROUTING_RECOMMENDATION": "MULTIPLE",
                      "ROUTING_REASON": "FUTEST routed MULTIPLE"}), f2)
    check("MULTIPLE runs E1, E2 and E3",
          multi.routed == ("E1", "E2", "E3"), str(multi.routed))
    steps = [s.name for s in multi.steps]
    check("...in that order, with normalization before E1",
          steps.index("NORMALIZE") < steps.index("E1") < steps.index("E2")
          < steps.index("E3"), str(steps))
    check("and the new plan items were recorded",
          "E2_PLAN_ITEMS" in steps and "E3_PLAN_ITEMS" in steps, str(steps))

    fx3 = seed_case(conn, "engine3")
    f3 = submit_followup(conn, fx3["client_id"])
    one = run_with(conn, with_control({"ROUTING_RECOMMENDATION": "ENGINE3",
                      "ROUTING_REASON": "FUTEST routed ENGINE3"}), f3)
    check("ENGINE3 runs E3 alone", one.routed == ("E3",), str(one.routed))
    check("...and does not run E1 or E2",
          "E1" not in [s.name for s in one.steps]
          and "E2" not in [s.name for s in one.steps],
          str([s.name for s in one.steps]))

    fx4 = seed_case(conn, "coordination")
    f4 = submit_followup(conn, fx4["client_id"])
    coord = run_with(conn,
                     with_control({"ROUTING_RECOMMENDATION": "MEDICAL_COORDINATION",
                      "ROUTING_REASON": "FUTEST routed MEDICAL_COORDINATION"}),
                     f4)
    check("MEDICAL_COORDINATION replans nothing and still queues a review",
          coord.routed == () and coord.status == "AWAITING_REVIEW",
          str(coord.routed))

    # ==================================================================
    print("\nhard rule 5: an unknown recommendation stops, it does not guess")

    fx5 = seed_case(conn, "unknown")
    f5 = submit_followup(conn, fx5["client_id"])
    bad = run_with(conn, with_control({"ROUTING_RECOMMENDATION": "ENGINE9",
                      "ROUTING_REASON": "FUTEST routed ENGINE9"}), f5)
    # The control contract's enum refuses ENGINE9 before routing sees it,
    # which is the stronger of the two refusals. Either way the pipeline
    # must STOP rather than route on a value nothing defines.
    check("the pipeline stops rather than routing on it",
          bad.status == "STOPPED", str(bad.status))
    check("and the follow-up is NOT marked processed",
          conn.execute("select processed_at from client_followups "
                       " where followup_id=%s::uuid", (f5,)).fetchone()[0] is None)

    try:
        CF.route({"ROUTING_RECOMMENDATION": "ENGINE9",
                      "ROUTING_REASON": "FUTEST routed ENGINE9"})
        check("route() itself refuses an undefined recommendation", False,
              "it returned")
    except CN.PipelineStopped as exc:
        check("route() itself refuses an undefined recommendation",
              "control contract" in str(exc), str(exc)[:100])

    # ==================================================================
    print("\nhard rule 3: the routing budget is real")

    fx6 = seed_case(conn, "budget")
    spent = None
    for n in range(1, 6):
        f = submit_followup(conn, fx6["client_id"], period=f"week {n}")
        outcome = run_with(conn, with_control({"ROUTING_RECOMMENDATION": "NONE"}), f)
        if outcome.status == "STOPPED":
            spent = (n, outcome.stopped_because)
            break
    check("a cycle per follow-up does NOT exhaust the budget",
          spent is None,
          f"stopped on follow-up {spent[0]}: {spent[1]}" if spent else "")

    cycle = conn.execute(
        "select cycle_id::text, loop_count, max_loops from case_cycles "
        " where client_id=%s::uuid order by opened_at desc limit 1",
        (fx6["client_id"],)).fetchone()
    check("each follow-up opened its own cycle and spent one hop",
          cycle[1] == 1, str(cycle))

    for _ in range(cycle[2] - 1):
        CN.spend_routing_hop(conn, cycle[0])
    try:
        CN.spend_routing_hop(conn, cycle[0])
        check("spending past max_loops is refused", False, "it was allowed")
    except CN.PipelineStopped as exc:
        check("spending past max_loops is refused",
              "routing budget" in str(exc), str(exc)[:100])

    # ==================================================================
    print("\nthe case version is a STATE, never the delta")

    version = conn.execute(
        "select canonical_state, delta, case_version from client_case_versions "
        " where client_id=%s::uuid and is_current", (fx["client_id"],)).fetchone()
    check("the follow-up appended a version rather than overwriting",
          version[2] >= 2, str(version[2]))
    check("canonical_state is a full state, not a delta",
          "NEW_FACTS" not in json.dumps(version[0] or {}), str(version[0])[:120])
    check("and the delta is kept in its own column",
          version[1] is not None and "NEW_FACTS" in json.dumps(version[1]),
          str(version[1])[:120])

    # ==================================================================
    print("\nE4's outcomes cannot invent a response to a plan nobody made")

    fx7 = seed_case(conn, "invented")
    f7 = submit_followup(conn, fx7["client_id"])
    ghost = [{"name": "an intervention this client never had",
              "outcome": "IMPROVING"}]
    run_with(conn, with_control({"ROUTING_RECOMMENDATION": "NONE"}, ghost), f7)
    check("an outcome naming nothing live is dropped, not written",
          conn.execute("select count(*) from intervention_outcome_history "
                       " where client_id=%s::uuid", (fx7["client_id"],)
                       ).fetchone()[0] == 0)

    ghost_step = [s for s in conn.execute(
        "select processing_note from client_followups where followup_id=%s::uuid",
        (f7,)).fetchall()]
    check("and the follow-up is still processed and queued for review",
          bool(ghost_step) and conn.execute(
              "select count(*) from practitioner_reviews where client_id=%s::uuid",
              (fx7["client_id"],)).fetchone()[0] == 1)

    # ==================================================================
    print("\nstopping an intervention needs a reason")

    target = list(fx2["interventions"].values())[0]
    try:
        with conn.transaction():
            conn.execute(
                "select record_intervention_outcome(%s::uuid,'LIMITED_RESPONSE',"
                "  'STOPPED',null,null,null,null,null)", (target,))
        check("a STOPPED intervention with no reason is refused", False,
              "it was accepted")
    except psycopg.Error as exc:
        check("a STOPPED intervention with no reason is refused",
              "reason" in str(exc).lower(), str(exc)[:120])

    conn.execute(
        "select record_intervention_outcome(%s::uuid,'LIMITED_RESPONSE',"
        "  'STOPPED',null,null,null,null,%s)", (target, "client could not sustain it"))
    stopped_row = conn.execute(
        "select status::text, stop_reason, ended_on from client_interventions "
        " where intervention_id=%s::uuid", (target,)).fetchone()
    check("with a reason it stops, and dates itself",
          stopped_row[0] == "STOPPED" and stopped_row[1] and stopped_row[2],
          str(stopped_row))

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_followup: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
