#!/usr/bin/env python3
"""Functional tests for migration 005.

The central assertion: a query that FORGETS its client_id filter must
return nothing, not everything. Isolation is structural, not a discipline
the application layer is trusted to maintain.

Requires two connections: an admin connection to create fixtures, and a
phi_runtime connection to prove RLS actually binds.
"""

from __future__ import annotations

import json
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
    admin_dsn = os.environ["DATABASE_URL"]
    admin = psycopg.connect(admin_dsn, autocommit=True)

    admin.execute("delete from clients where external_ref like 'RLS-%'")

    # Runtime connection. Same host, different role, so RLS is in force.
    runtime_dsn = admin_dsn.replace("postgres@", "phi_runtime@").replace(
        "postgresql://postgres", "postgresql://phi_runtime")
    if "phi_runtime" not in runtime_dsn:
        runtime_dsn = admin_dsn + "&user=phi_runtime"
    runtime = psycopg.connect(runtime_dsn)

    print("\nrole configuration")
    row = admin.execute(
        "select rolsuper, rolbypassrls from pg_roles where rolname='phi_runtime'"
    ).fetchone()
    check("runtime role is not superuser and cannot bypass RLS",
          row == (False, False), str(row))
    forced = admin.execute(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname='client_labs'"
    ).fetchone()
    check("RLS enabled and FORCED (owner is subject too)", forced == (True, True), str(forced))

    print("\nfixtures")
    a = admin.execute(
        """insert into clients (external_ref, display_name, status)
           values ('RLS-A','Client A','ACTIVE') returning client_id"""
    ).fetchone()[0]
    b = admin.execute(
        """insert into clients (external_ref, display_name, status)
           values ('RLS-B','Client B','ACTIVE') returning client_id"""
    ).fetchone()[0]
    for cid, marker, val in ((a, "A_MARKER", 5.1), (b, "B_MARKER", 9.9)):
        admin.execute(
            """insert into client_labs (client_id, measured_on, marker, value, unit)
               values (%s, current_date, %s, %s, 'x')""", (cid, marker, val))
    check("two clients with distinguishable data created", a != b)

    # ------------------------------------------------------------------
    print("\nclient isolation (the requirement)")

    # Deliberately NO client_id filter. This is the accidental-omission case.
    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (a,))
        rows = runtime.execute("select marker from client_labs").fetchall()
    markers = {r[0] for r in rows}
    check("query WITHOUT a client_id filter returns only Client A",
          markers == {"A_MARKER"}, str(markers))

    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (a,))
        direct = runtime.execute(
            "select count(*) from client_labs where client_id=%s", (b,)).fetchone()[0]
    check("explicitly asking for Client B under Client A scope returns nothing",
          direct == 0, str(direct))

    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (b,))
        markers_b = {r[0] for r in runtime.execute("select marker from client_labs")}
    check("switching scope switches visible data", markers_b == {"B_MARKER"}, str(markers_b))

    # Default deny: no context at all.
    with runtime.transaction():
        none_rows = runtime.execute("select count(*) from client_labs").fetchone()[0]
    check("no client context returns ZERO rows, not all rows",
          none_rows == 0, str(none_rows))

    print("\ntransaction-local scope (pooled connection safety)")
    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (a,))
        inside = runtime.execute("select current_client_scope()").fetchone()[0]
    # Same connection, new transaction. Scope must NOT persist.
    with runtime.transaction():
        after = runtime.execute("select current_client_scope()").fetchone()[0]
        leaked = runtime.execute("select count(*) from client_labs").fetchone()[0]
    check("scope set inside a transaction", str(inside) == str(a))
    check("scope does NOT persist into the next transaction on the same connection",
          after is None and leaked == 0, f"scope={after} rows={leaked}")

    print("\nwrites are scoped too")
    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (a,))
        try:
            runtime.execute(
                """insert into client_labs (client_id, measured_on, marker, value)
                   values (%s, current_date, 'SMUGGLED', 1)""", (b,))
            check("cannot write into another client under scope A", False,
                  "insert succeeded")
        except psycopg.Error as exc:
            check("cannot write into another client under scope A",
                  "row-level security" in str(exc).lower(), str(exc)[:90])

    print("\npractitioner cross-client read path")
    prac_dsn = admin_dsn.replace("postgresql://postgres", "postgresql://phi_practitioner")
    prac = psycopg.connect(prac_dsn)
    with prac.transaction():
        seen = {r[0] for r in prac.execute("select marker from client_labs")}
    check("practitioner role sees across clients (the deliberate path)",
          {"A_MARKER", "B_MARKER"} <= seen, str(seen))
    with prac.transaction():
        try:
            prac.execute(
                "insert into client_labs (client_id, measured_on, marker) values (%s, current_date, 'X')",
                (a,))
            check("practitioner role is read-only", False, "insert succeeded")
        except psycopg.Error as exc:
            check("practitioner role is read-only",
                  "permission denied" in str(exc).lower(), str(exc)[:90])
    prac.close()

    # ------------------------------------------------------------------
    print("\nassessment envelope: one assessment, several representations")
    asm = admin.execute(
        """insert into client_assessments
             (client_id, instrument, instrument_version, scoring_version,
              payload_schema_version, status, assessed_on, source, provenance_note)
           values (%s,'REAL_HEALTH_TEST','rht-2026.1','scoring-1.0','v0-unfrozen',
                   'COMPLETED', current_date, 'REAL_HEALTH_TEST','Client completed RHT')
           returning assessment_id""",
        (a,),
    ).fetchone()[0]
    layers = {
        "RAW_SIGNALS": {"sleep_duration_hours": 5.5, "sleep_regularity": "irregular"},
        "DERIVED_SCORES": {"sleep_load_score": "HIGH", "recovery_subscore": 34},
        "INTERPRETATION": {"summary": "Recovery and sleep burden may be important"},
        "DIRECTION": {"priorities": ["sleep regularity", "recovery load"]},
    }
    for lt, payload in layers.items():
        admin.execute(
            """insert into assessment_layers (assessment_id, layer_type, payload, generated_by)
               values (%s,%s,%s,'RHT')""",
            (asm, lt, json.dumps(payload)))

    pkg = admin.execute(
        "select layer_count, observation_cardinality, layers from v_assessment_package where assessment_id=%s",
        (asm,)).fetchone()
    check("four layers present under one assessment", pkg[0] == 4, str(pkg[0]))
    check("package declares itself a single observation",
          pkg[1] == "SINGLE_ASSESSMENT", str(pkg[1]))
    check("raw, derived and interpretation all reachable",
          pkg[2]["RAW_SIGNALS"]["sleep_duration_hours"] == 5.5
          and pkg[2]["DERIVED_SCORES"]["sleep_load_score"] == "HIGH"
          and "Recovery" in pkg[2]["INTERPRETATION"]["summary"], str(pkg[2])[:120])

    distinct_assessments = admin.execute(
        "select count(distinct assessment_id) from assessment_layers where assessment_id=%s",
        (asm,)).fetchone()[0]
    check("three representations do not become three independent observations",
          distinct_assessments == 1, str(distinct_assessments))

    expect_error(
        admin,
        "insert into assessment_layers (assessment_id, layer_type, payload) values (%s,'RAW_SIGNALS','{}')",
        (asm,),
        "duplicate layer type on one assessment rejected",
        "assessment_layers_assessment_id_layer_type_key",
    )
    expect_error(
        admin,
        """insert into client_assessments (client_id, instrument, status)
           values (%s,'REAL_HEALTH_TEST','COMPLETED')""",
        (a,),
        "COMPLETED assessment without a date rejected",
        "ck_completed_needs_date",
    )

    print("\nabsence means NOT_ASSESSED, never normal")
    status_b = admin.execute(
        "select get_assessment_status(%s,'REAL_HEALTH_TEST')", (b,)).fetchone()[0]
    status_a = admin.execute(
        "select get_assessment_status(%s,'REAL_HEALTH_TEST')", (a,)).fetchone()[0]
    check("client with no assessment reports NOT_ASSESSED",
          status_b == "NOT_ASSESSED", str(status_b))
    check("client with an assessment reports COMPLETED", status_a == "COMPLETED", str(status_a))
    check("NOT_ASSESSED and NOT_AVAILABLE are distinct states",
          {"NOT_ASSESSED", "NOT_AVAILABLE"} <= set(
              r[0] for r in admin.execute("select unnest(enum_range(null::assessment_status))::text")))

    # ------------------------------------------------------------------
    print("\ncase event spine")
    ev = admin.execute(
        """insert into case_events
             (client_id, source, occurred_at, reported_by, raw_text, confidence)
           values (%s,'CONSULTATION', now(), 'practitioner:pd',
                   'Dinner usually 23:00 because shop closes 22:15. Wife cooks. Walking stopped, knee discomfort.',
                   'REPORTED')
           returning event_id""",
        (a,),
    ).fetchone()[0]
    check("consultation event recorded without altering canonical state",
          admin.execute(
              "select altered_canonical_state from case_events where event_id=%s", (ev,)
          ).fetchone()[0] is False)

    expect_error(
        admin,
        """insert into case_events (client_id, source, altered_canonical_state)
           values (%s,'WHATSAPP',true)""",
        (a,),
        "event claiming a state change must name the version",
        "ck_altered_needs_version",
    )

    sources = {r[0] for r in admin.execute("select unnest(enum_range(null::event_source))::text")}
    check("all required event sources modelled",
          {"CONSULTATION","PHONE","WHATSAPP","EMAIL","PRACTITIONER_OBSERVATION",
           "LAB_REPORT","FOOD_LOG","ASSESSMENT","FOLLOWUP","CLIENT_MESSAGE"} <= sources,
          str(sorted(sources)))

    # ------------------------------------------------------------------
    print("\ncandidate facts: confidence is not authorization")
    thread = admin.execute(
        "insert into chat_threads (client_id, title, created_by) values (%s,'Case chat','practitioner:pd') returning thread_id",
        (a,)).fetchone()[0]
    cand = admin.execute(
        """insert into candidate_facts
             (client_id, thread_id, extracted_text, fact_type, extraction_confidence)
           values (%s,%s,'Dinner around 23:00','meal_timing',0.98) returning candidate_id""",
        (a, thread)).fetchone()[0]

    expect_error(
        admin,
        "update candidate_facts set status='APPROVED' where candidate_id=%s",
        (cand,),
        "0.98 extraction confidence alone cannot approve a fact",
        "not authorization",
    )
    expect_error(
        admin,
        """update candidate_facts set status='APPROVED',
               authorization_type='PRACTITIONER_APPROVAL', approved_by='llm:E6'
            where candidate_id=%s""",
        (cand,),
        "an LLM actor cannot approve a client fact",
        "requires a practitioner actor",
    )
    admin.execute(
        """update candidate_facts
              set status='APPROVED', authorization_type='PRACTITIONER_APPROVAL',
                  approved_by='practitioner:pd', decided_at=now()
            where candidate_id=%s""", (cand,))
    check("practitioner approval accepted",
          admin.execute("select status from candidate_facts where candidate_id=%s",
                        (cand,)).fetchone()[0] == "APPROVED")

    # Explicit instruction path: "Save this: ..."
    explicit = admin.execute(
        """insert into candidate_facts
             (client_id, extracted_text, extraction_confidence, status,
              authorization_type, approved_by, decided_at)
           values (%s,'Taking iron 100mg daily since Monday',0.91,'APPROVED',
                   'EXPLICIT_PRACTITIONER_INSTRUCTION','practitioner:pd',now())
           returning candidate_id""", (a,)).fetchone()[0]
    check("explicit practitioner instruction counts as approval", explicit is not None)

    # Trusted structured ingestion path (intake, RHT, parsed labs).
    trusted = admin.execute(
        """insert into candidate_facts
             (client_id, extracted_text, status, authorization_type, approved_by, decided_at)
           values (%s,'HbA1c 6.1 from uploaded report','APPROVED',
                   'TRUSTED_STRUCTURED_INGESTION','system:lab_parser',now())
           returning candidate_id""", (a,)).fetchone()[0]
    check("trusted structured ingestion follows its own path", trusted is not None)

    print("\nchat scoping")
    general = admin.execute(
        "insert into chat_threads (client_id, title, created_by) values (NULL,'General','practitioner:pd') returning thread_id"
    ).fetchone()[0]
    admin.execute(
        "insert into chat_messages (thread_id, role, content) values (%s,'practitioner','What do we know about creatine?')",
        (general,))
    admin.execute(
        "insert into chat_messages (thread_id, client_id, role, content) values (%s,%s,'practitioner','Why is she not losing weight?')",
        (thread, b))   # deliberately wrong client_id; trigger must correct it
    corrected = admin.execute(
        "select client_id from chat_messages where thread_id=%s", (thread,)).fetchone()[0]
    check("message client_id forced to match its thread", corrected == a, f"{corrected} vs {a}")

    with runtime.transaction():
        # No client scope: general thread visible, client thread not.
        visible = {r[0] for r in runtime.execute("select coalesce(title,'') from chat_threads")}
    check("general chat readable with no client context", "General" in visible, str(visible))
    check("client thread hidden with no client context", "Case chat" not in visible, str(visible))

    print("\ndraft versus delivery")
    draft = admin.execute(
        """insert into client_communications
             (client_id, comm_type, content, released, comm_status, origin)
           values (%s,'WHATSAPP_REPLY','Draft reply...',false,'DRAFT','PRACTITIONER_CHAT')
           returning communication_id""", (a,)).fetchone()[0]
    check("chat can generate a draft freely", draft is not None)

    admin.execute(
        """insert into case_flags (client_id, rule_key, severity, source, detail)
           values (%s,'CRITICAL_LAB_THRESHOLD','HOLD','DETERMINISTIC','ALT 340 U/L')""",
        (a,))
    expect_error(
        admin,
        "update client_communications set released=true, comm_status='RELEASED' where communication_id=%s",
        (draft,),
        "delivery still gated even when the draft came from chat",
        "open HOLD flag",
    )
    still_draft = admin.execute(
        "select comm_status from client_communications where communication_id=%s", (draft,)
    ).fetchone()[0]
    check("draft remains viewable while delivery is blocked", still_draft == "DRAFT")

    # Setting either field alone must drive the other, and the gate must
    # still fire. Callers cannot desynchronise them.
    expect_error(
        admin,
        "update client_communications set comm_status='RELEASED' where communication_id=%s",
        (draft,),
        "setting status alone still hits the gate",
        "open HOLD flag",
    )
    admin.execute(
        """update case_flags set status='RESOLVED', resolved_by='practitioner:pd', resolved_at=now()
            where client_id=%s and severity='HOLD' and status='OPEN'""", (a,))
    admin.execute(
        "update client_communications set comm_status='RELEASED' where communication_id=%s", (draft,))
    synced = admin.execute(
        "select released, comm_status from client_communications where communication_id=%s",
        (draft,)).fetchone()
    check("setting status alone syncs the released flag", synced == (True, "RELEASED"), str(synced))

    # ------------------------------------------------------------------
    print("\nmissing data reports")
    for engine, field, sev, constrained, rht in [
        ("E1", "sleep_quality", "HIGH", True, True),
        ("E2", "sleep_quality", "MODERATE", True, True),
        ("E1", "fasting_insulin", "HIGH", True, False),
        ("E3", "cooking_time_available", "LOW", False, False),
    ]:
        admin.execute(
            """insert into missing_data_reports
                 (engine, client_id, missing_field, why_it_mattered, severity,
                  constrained_reasoning, rht_would_supply)
               values (%s,%s,%s,'needed for reasoning',%s,%s,%s)""",
            (engine, a, field, sev, constrained, rht))
    admin.execute(
        """insert into missing_data_reports
             (engine, client_id, missing_field, severity, constrained_reasoning, rht_would_supply)
           values ('E1',%s,'sleep_quality','HIGH',true,true)""", (b,))

    rec = {r[0]: r for r in admin.execute(
        "select missing_field, reports, distinct_clients, rht_would_supply, classification from v_missing_data_recurrence")}
    check("recurrence aggregated across clients",
          rec["sleep_quality"][1] == 3 and rec["sleep_quality"][2] == 2, str(rec["sleep_quality"]))
    check("RHT-supplied gaps flagged so intake does not duplicate RHT",
          rec["sleep_quality"][3] is True and rec["fasting_insulin"][3] is False)
    check("classification stays NULL until a human triages",
          all(r[4] is None for r in rec.values()), str([r[4] for r in rec.values()]))

    unclassified = admin.execute(
        "select count(*) from missing_data_reports where classification is null").fetchone()[0]
    check("reporting a gap never auto-changes intake", unclassified == 5, str(unclassified))

    runtime.close()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
