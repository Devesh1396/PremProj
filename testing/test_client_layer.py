#!/usr/bin/env python3
"""Functional tests for the client / orchestration layer (migration 004).

The assertions that matter most:
  - exactly one current case version, enforced by index
  - E1 Pass A and Pass B cannot run different prompts
  - client-facing release is blocked while a HOLD flag is open
  - an LLM cannot clear a deterministic flag
  - proposed is not started; stopped is not failed
"""

from __future__ import annotations

import hashlib
import os
import sys

import psycopg

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def expect_error(conn, sql, params, name, fragment):
    try:
        with conn.transaction():
            conn.execute(sql, params)
        check(name, False, "accepted but should have been rejected")
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), f"unexpected: {exc}")


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    conn.execute("delete from clients where external_ref like 'T-%'")

    print("\nclient and case versioning")
    client = conn.execute(
        """insert into clients (external_ref, display_name, year_of_birth, sex,
                                country, region, locality, status)
           values ('T-001','Synthetic A',1983,'F','India','Gujarat','Ahmedabad','INTAKE')
           returning client_id"""
    ).fetchone()[0]
    check("client created", client is not None)

    expect_error(
        conn,
        "insert into clients (display_name, year_of_birth) values (%s,%s)",
        ("Bad", 1850),
        "impossible year of birth rejected",
        "ck_yob",
    )

    v1 = conn.execute(
        """insert into client_case_versions (client_id, case_version, canonical_state, phase, created_by)
           values (%s,1,%s,'PHASE_1','E6') returning case_version_id""",
        (client, '{"ACTIVE_CONDITIONS": ["PCOS","MASLD"], "CASE_VERSION": 1}'),
    ).fetchone()[0]

    expect_error(
        conn,
        """insert into client_case_versions (client_id, case_version, canonical_state)
           values (%s,2,%s)""",
        (client, '{"CASE_VERSION": 2}'),
        "two current versions rejected",
        "uq_case_current",
    )

    # Correct supersede: demote the old version, then insert the new one.
    conn.execute("update client_case_versions set is_current=false where case_version_id=%s", (v1,))
    v2 = conn.execute(
        """insert into client_case_versions
             (client_id, case_version, canonical_state, delta, change_reason, created_by)
           values (%s,2,%s,%s,'Week-4 follow-up','E6') returning case_version_id""",
        (client,
         '{"ACTIVE_CONDITIONS": ["PCOS","MASLD"], "CASE_VERSION": 2}',
         '{"NEW_RESPONSES": ["waist -3cm"]}'),
    ).fetchone()[0]
    hist = conn.execute(
        "select count(*) from client_case_versions where client_id=%s", (client,)
    ).fetchone()[0]
    cur = conn.execute(
        "select case_version from client_case_versions where client_id=%s and is_current", (client,)
    ).fetchone()[0]
    check("history retained on supersede", hist == 2 and cur == 2, f"hist={hist} cur={cur}")

    print("\nrouting depth")
    cycle = conn.execute(
        """insert into case_cycles (client_id, cycle_number, cycle_type, max_loops)
           values (%s,1,'NEW_CLIENT',3) returning cycle_id""",
        (client,),
    ).fetchone()[0]
    conn.execute("update case_cycles set loop_count=3 where cycle_id=%s", (cycle,))
    expect_error(
        conn,
        "update case_cycles set loop_count=4 where cycle_id=%s",
        (cycle,),
        "routing loop bound enforced",
        "ck_loop_bound",
    )
    conn.execute("update case_cycles set loop_count=0 where cycle_id=%s", (cycle,))

    print("\nproposed is not started")
    iv = conn.execute(
        """insert into client_interventions (client_id, name, source_engine, status, proposed_on)
           values (%s,'Meal sequencing','E1','PROPOSED',current_date) returning intervention_id""",
        (client,),
    ).fetchone()[0]
    expect_error(
        conn,
        "update client_interventions set started_on=current_date where intervention_id=%s",
        (iv,),
        "start date on a PROPOSED intervention rejected",
        "ck_started_requires_status",
    )
    conn.execute(
        "update client_interventions set status='STARTED', started_on=current_date where intervention_id=%s",
        (iv,),
    )
    check("start permitted once status advances",
          conn.execute(
              "select started_on is not null from client_interventions where intervention_id=%s", (iv,)
          ).fetchone()[0])

    # Stopped is not failed.
    conn.execute(
        """update client_interventions
              set status='STOPPED', ended_on=current_date,
                  stop_reason='Client travelling; paused by agreement',
                  outcome='IMPROVING'
            where intervention_id=%s""",
        (iv,),
    )
    row = conn.execute(
        "select status, outcome from client_interventions where intervention_id=%s", (iv,)
    ).fetchone()
    check("stopped intervention can still have a positive outcome",
          row[0] == "STOPPED" and row[1] == "IMPROVING", str(row))

    # ------------------------------------------------------------------
    print("\nE1 two-pass: same specification, invoked twice")
    prompt_text = "# ENGINE 1 - PREVENTION INTELLIGENCE\n(master specification)\n"
    good_hash = hashlib.sha256(prompt_text.encode()).hexdigest()
    forked_hash = hashlib.sha256((prompt_text + "\n(shortened)").encode()).hexdigest()

    pass_a = conn.execute(
        """insert into engine_runs (client_id, case_version_id, cycle_id, engine, pass,
                                    prompt_file, prompt_hash, model_role, status)
           values (%s,%s,%s,'E1','A','engine1_prevention.md',%s,'MODEL_ANALYSIS','SUCCEEDED')
           returning run_id""",
        (client, v2, cycle, good_hash),
    ).fetchone()[0]
    check("Pass A recorded", pass_a is not None)

    expect_error(
        conn,
        """insert into engine_runs (client_id, case_version_id, cycle_id, engine, pass,
                                    prompt_file, prompt_hash, model_role)
           values (%s,%s,%s,'E1','B','engine1_pass_b_lite.md',%s,'MODEL_ANALYSIS')""",
        (client, v2, cycle, forked_hash),
        "Pass B with a forked prompt rejected",
        "identical master Engine 1 specification",
    )

    pass_b = conn.execute(
        """insert into engine_runs (client_id, case_version_id, cycle_id, engine, pass,
                                    prompt_file, prompt_hash, model_role, status)
           values (%s,%s,%s,'E1','B','engine1_prevention.md',%s,'MODEL_ANALYSIS','SUCCEEDED')
           returning run_id""",
        (client, v2, cycle, good_hash),
    ).fetchone()[0]
    check("Pass B accepted with the identical prompt hash", pass_b is not None)

    hashes = {r[0] for r in conn.execute(
        "select prompt_hash from engine_runs where cycle_id=%s and engine='E1'", (cycle,))}
    check("both passes share one prompt hash", len(hashes) == 1, str(hashes))

    expect_error(
        conn,
        """insert into engine_runs (client_id, engine, pass, prompt_file, prompt_hash, model_role)
           values (%s,'E3','A','engine3_nutrition.md','abc','MODEL_ANALYSIS')""",
        (client,),
        "pass label rejected on a non-E1 engine",
        "ck_pass_only_for_e1",
    )

    print("\nengine outputs")
    conn.execute(
        """insert into engine_outputs (run_id, human_output, structured, control, schema_valid)
           values (%s,'(report)',%s,%s,true)""",
        (pass_b,
         '{"TOP_INTERVENTIONS": ["meal sequencing"]}',
         '{"CASE_VERSION": 2, "REVIEW_REQUIRED": true, "KNOWLEDGE_SUFFICIENT": true, "NEXT_ENGINE": "E2"}'),
    )
    ctrl = conn.execute(
        "select control->>'NEXT_ENGINE' from engine_outputs where run_id=%s", (pass_b,)
    ).fetchone()[0]
    check("control fields queryable for routing", ctrl == "E2", str(ctrl))

    # ------------------------------------------------------------------
    print("\nsafety gate")
    comm = conn.execute(
        """insert into client_communications (client_id, cycle_id, comm_type, content, released)
           values (%s,%s,'FIRST_ASSESSMENT','Your four-week plan...',false)
           returning communication_id""",
        (client, cycle),
    ).fetchone()[0]
    check("drafting client output is never blocked", comm is not None)

    hold = conn.execute(
        """insert into case_flags (client_id, cycle_id, rule_key, severity, source, detail)
           values (%s,%s,'INSULIN_PLUS_GLUCOSE_LOWERING','HOLD','DETERMINISTIC',
                   'Client on insulin; plan lowers glucose. Hypoglycaemia risk within days.')
           returning flag_id""",
        (client, cycle),
    ).fetchone()[0]

    expect_error(
        conn,
        "update client_communications set released=true, released_by=%s where communication_id=%s",
        ("practitioner:pd", comm),
        "release blocked while a HOLD flag is open",
        "open HOLD flag",
    )

    # An LLM-attributed actor cannot clear a deterministic flag.
    expect_error(
        conn,
        "update case_flags set status='RESOLVED', resolved_by=%s where flag_id=%s",
        ("llm:E5", hold),
        "LLM cannot clear a deterministic flag",
        "only be resolved by a practitioner",
    )

    conn.execute(
        """update case_flags set status='RESOLVED', resolved_by='practitioner:pd',
                                 resolution_note='Discussed with prescriber; dose review scheduled',
                                 resolved_at=now()
            where flag_id=%s""",
        (hold,),
    )
    conn.execute(
        "update client_communications set released=true, released_by='practitioner:pd', released_at=now() where communication_id=%s",
        (comm,),
    )
    check("release permitted once the practitioner resolves the flag",
          conn.execute(
              "select released from client_communications where communication_id=%s", (comm,)
          ).fetchone()[0])

    # NOTE flags do not block. This is what keeps the gate from becoming a
    # rubber stamp on a population that is mostly medicated.
    conn.execute(
        """insert into case_flags (client_id, cycle_id, rule_key, severity, source, detail)
           values (%s,%s,'ROUTINE_MONITORING','NOTE','LLM','Recheck ALT at week 12.')""",
        (client, cycle),
    )
    comm2 = conn.execute(
        """insert into client_communications (client_id, comm_type, content, released, released_by)
           values (%s,'PROGRESS','Week-4 update...',true,'practitioner:pd')
           returning communication_id""",
        (client,),
    ).fetchone()[0]
    check("NOTE flags do not block release", comm2 is not None)

    print("\nEngine 6 read path")
    state = conn.execute("select get_current_client_state(%s)", (client,)).fetchone()[0]
    check("current state returns the current version only",
          state["case_version"] == 2, str(state.get("case_version")))
    check("state reports open HOLD count", state["open_holds"] == 0, str(state["open_holds"]))

    conn.execute(
        """insert into client_labs (client_id, measured_on, marker, value, unit, is_baseline)
           values (%s, current_date - 60, 'HbA1c', 6.4, '%%', true),
                  (%s, current_date, 'HbA1c', 6.0, '%%', false),
                  (%s, current_date, 'ALT', 44, 'U/L', false)""",
        (client, client, client),
    )
    state = conn.execute("select get_current_client_state(%s)", (client,)).fetchone()[0]
    labs = {l["marker"]: l["value"] for l in state["latest_labs"]}
    check("latest lab per marker, not every historical row",
          labs == {"HbA1c": 6.0, "ALT": 44}, str(labs))

    timeline = conn.execute("select * from get_client_timeline(%s)", (client,)).fetchall()
    check("timeline spans labs and interventions", len(timeline) >= 4, f"{len(timeline)} events")

    print("\nreview queue")
    conn.execute(
        """insert into practitioner_reviews (client_id, cycle_id, run_id, decision)
           values (%s,%s,%s,'PENDING')""",
        (client, cycle, pass_b),
    )
    q = conn.execute("select engine, pass, open_holds from v_review_queue").fetchall()
    check("pending review surfaces with engine and pass", len(q) == 1 and q[0][1] == "B", str(q))

    print("\ninference is not fact")
    conn.execute(
        """insert into client_conditions (client_id, condition, status, is_inferred, confidence, source)
           values (%s,'Insulin resistance','UNDER_INVESTIGATION',true,'MODERATE','E1 inference')""",
        (client,),
    )
    inferred = conn.execute(
        "select count(*) from client_conditions where client_id=%s and is_inferred", (client,)
    ).fetchone()[0]
    check("inferred conditions flagged distinctly from diagnoses", inferred == 1)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
