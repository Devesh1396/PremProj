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
from pathlib import Path

from urllib.parse import quote, unquote, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import psycopg
import run_engine as RE_SCOPE

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



def _role_password(env_var: str) -> str | None:
    """The role's own password, or None where the server does not want one.

    Roles are created without a password by migration 005; docs/OPERATIONS.md
    step 5 sets them with ALTER ROLE afterwards, on the VPS and locally
    alike. So the password does not live in DATABASE_URL and has to come
    from the environment. None is returned when it is unset, which keeps
    trust/peer development setups working.
    """
    value = os.environ.get(env_var, "").strip()
    return value or None


def _with_user(dsn: str, user: str, password: str | None = None) -> str:
    """Return dsn with its credentials replaced, preserving everything else.

    The admin password MUST be dropped rather than carried over: it does not
    authenticate this role, and silently reusing it would either fail
    confusingly or, worse, succeed and mean the connection is not the role
    the test thinks it is.
    """
    parts = urlsplit(dsn)
    if parts.scheme:  # URL form
        host = parts.hostname or ""
        # Percent-encode: a generated password may contain @ : / or #, any
        # of which re-parses the DSN into a different host or database.
        credentials = quote(user, safe="")
        if password is not None:
            credentials += f":{quote(password, safe='')}"
        netloc = f"{credentials}@{host}" + (f":{parts.port}" if parts.port else "")
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    # keyword/value form: drop any existing user=/password= and append ours
    kv = [t for t in dsn.split() if not t.startswith(("user=", "password="))]
    kv.append(f"user={user}")
    if password is not None:
        kv.append(f"password={password}")
    return " ".join(kv)


def check_dsn_rewriting() -> None:
    """_with_user decides which ROLE the isolation tests run as.

    Get it wrong and every assertion below still passes -- as the wrong
    role, against a superuser that RLS does not bind. So it is asserted
    directly rather than trusted.
    """
    print("\ndsn rewriting")
    url = _with_user("postgresql://phi_admin:adminpw@db.internal:5432/phi",
                     "phi_runtime", "runtimepw")
    check("URL form takes the role's own credentials",
          url == "postgresql://phi_runtime:runtimepw@db.internal:5432/phi", url)
    check("URL form does not carry the admin password over",
          "adminpw" not in url, url)
    check("URL form keeps host, port and database",
          urlsplit(url).hostname == "db.internal"
          and urlsplit(url).port == 5432
          and urlsplit(url).path == "/phi", url)

    no_port = _with_user("postgresql://phi_admin:adminpw@db.internal/phi",
                         "phi_runtime", "runtimepw")
    check("URL form without a port stays without one",
          no_port == "postgresql://phi_runtime:runtimepw@db.internal/phi", no_port)

    # A generated password (openssl rand) can contain @ : / #. Unescaped,
    # "pa@ss" turns the host into "ss" and the connection goes somewhere else
    # entirely -- or fails in a way that looks like a server problem.
    escaped = _with_user("postgresql://phi_admin@db.internal:5432/phi",
                         "phi_runtime", "p@ss:w/rd#1")
    # urlsplit does not decode, so the raw component must be the escaped
    # form and only unquoting it may give the password back. libpq
    # percent-decodes URI components, which is why encoding is the fix.
    check("special characters in a password are percent-encoded",
          urlsplit(escaped).hostname == "db.internal"
          and urlsplit(escaped).password == "p%40ss%3Aw%2Frd%231"
          and unquote(urlsplit(escaped).password) == "p@ss:w/rd#1", escaped)

    kv = _with_user("host=db.internal port=5432 dbname=phi user=phi_admin "
                    "password=adminpw", "phi_runtime", "runtimepw")
    check("keyword/value form replaces user and password",
          " user=phi_runtime" in kv and " password=runtimepw" in kv
          and "phi_admin" not in kv and "adminpw" not in kv, kv)

    trust = _with_user("postgresql://phi_admin@db.internal/phi", "phi_runtime")
    check("no password given emits no password (trust/peer setups)",
          trust == "postgresql://phi_runtime@db.internal/phi", trust)


def main() -> int:
    check_dsn_rewriting()

    admin_dsn = os.environ["DATABASE_URL"]
    admin = psycopg.connect(admin_dsn, autocommit=True)

    admin.execute("delete from clients where external_ref like 'RLS-%'")

    # Runtime connection. Same host, different role, so RLS is in force.
    # Rewrite the username properly rather than string-replacing "postgres":
    # per docs/OPERATIONS.md the admin role is phi_admin, so any assumption
    # that the admin DSN says "postgres" is wrong on a real deployment, and
    # appending "&user=" to a DSN with no query string produces a DSN whose
    # database name is literally "phi&user=phi_runtime".
    runtime_dsn = _with_user(admin_dsn, "phi_runtime",
                             _role_password("POSTGRES_RUNTIME_PASSWORD"))
    runtime = psycopg.connect(runtime_dsn)

    # ------------------------------------------------------------------
    print("\nthe client/clock rule comes from the registry, not a second list")

    # 015 hard-coded ('FOUNDATION','UPDATE','INBOX') inside the trigger,
    # under a comment saying not to. Harmless until a fifth clock mode is
    # registered, at which point every correct call to it is rejected with
    # a message about a case with no case. 020 moved the rule to
    # engine_handoffs.client_required, so registering a mode is enough.
    admin.execute("delete from engine_handoffs where mode='COHTEST'")
    admin.execute(
        "insert into engine_handoffs (engine, mode, tag, required, prompt_ref, "
        "                             note, client_required) "
        "values ('E7','COHTEST','RESEARCH_PRACTICE_FOUNDATION_HANDOFF',true,"
        "        'test','a clock mode registered at runtime',false)")
    run_id = str(__import__("uuid").uuid4())
    admin.execute(
        "insert into engine_runs (run_id, engine, engine_mode, prompt_file, "
        "                         prompt_hash, model_role) "
        "values (%s,'E7','COHTEST','engine7_research_practice.md','x','MODEL_RESEARCH')",
        (run_id,))
    check("a newly registered clock mode runs with NO client, no code change",
          admin.execute("select client_id from engine_runs where run_id=%s",
                        (run_id,)).fetchone()[0] is None)
    expect_error(
        admin,
        "insert into engine_runs (engine, engine_mode, client_id, prompt_file, "
        "                         prompt_hash, model_role) "
        "values ('E7','COHTEST',gen_random_uuid(),'x','y','MODEL_RESEARCH')",
        (),
        "...and is still refused a client",
        "knowledge-clock run")
    admin.execute("delete from engine_runs where run_id=%s", (run_id,))
    admin.execute("delete from engine_handoffs where mode='COHTEST'")

    expect_error(
        admin,
        "insert into engine_runs (engine, engine_mode, prompt_file, prompt_hash, "
        "                         model_role) "
        "values ('E7','NOSUCHMODE','x','y','MODEL_RESEARCH')",
        (),
        "an UNREGISTERED mode is refused, and says that is the problem",
        "no active handoff is registered")

    print("\nrole configuration")
    # Assert the identity of the connection, not just the properties of the
    # role in pg_roles. Every isolation assertion below is meaningless if
    # this connection is not actually phi_runtime.
    #
    # Inside an explicit transaction block deliberately: this connection is
    # NOT autocommit, so a bare execute() would open a transaction and leave
    # it open, turning every later `with runtime.transaction()` into a
    # savepoint instead of a top-level transaction -- and transaction-local
    # client scope would then leak between them.
    with runtime.transaction():
        check("runtime connection is authenticated as phi_runtime",
              runtime.execute("select current_user").fetchone()[0] == "phi_runtime")
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
    prac_dsn = _with_user(admin_dsn, "phi_practitioner",
                          _role_password("POSTGRES_PRACTITIONER_PASSWORD"))
    prac = psycopg.connect(prac_dsn)
    with prac.transaction():
        check("practitioner connection is authenticated as phi_practitioner",
              prac.execute("select current_user").fetchone()[0] == "phi_practitioner")
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

    # ------------------------------------------------------------------
    # Intake (009). This is where a real client's name, date of birth and
    # labs first enter the system, so the isolation is asserted here rather
    # than trusted to the migration having listed the right tables.
    print("\nintake tables are client-scoped (009)")
    for table in ("intake_submissions", "intake_sections", "client_report_files"):
        forced = admin.execute(
            "select relrowsecurity, relforcerowsecurity from pg_class where relname=%s",
            (table,)).fetchone()
        check(f"{table}: RLS enabled and FORCED", forced == (True, True), str(forced))

    sub_a = admin.execute(
        """insert into intake_submissions (client_id, raw_payload, captured_by)
           values (%s,%s,'test') returning submission_id""",
        (a, json.dumps({"sections": {"GOALS": {"consultation_reason": "A_INTAKE_MARKER"}}}))
    ).fetchone()[0]
    sub_b = admin.execute(
        """insert into intake_submissions (client_id, raw_payload, captured_by)
           values (%s,%s,'test') returning submission_id""",
        (b, json.dumps({"sections": {"GOALS": {"consultation_reason": "B_INTAKE_MARKER"}}}))
    ).fetchone()[0]
    for cid, sid_, marker in ((a, sub_a, "A_SECTION"), (b, sub_b, "B_SECTION")):
        admin.execute(
            """insert into intake_sections (submission_id, client_id, section, payload)
               values (%s,%s,'GOALS',%s)""", (sid_, cid, json.dumps({"marker": marker})))
        admin.execute(
            """insert into client_report_files (client_id, report_kind, original_filename)
               values (%s,'LAB_PANEL',%s)""", (cid, marker + "_report.pdf"))

    with runtime.transaction():
        runtime.execute("select set_client_scope(%s)", (a,))
        subs = runtime.execute(
            "select raw_payload from intake_submissions").fetchall()
        secs = runtime.execute("select payload from intake_sections").fetchall()
        files = runtime.execute(
            "select original_filename from client_report_files").fetchall()
    # No client_id filter in any of those queries. That is the point.
    check("intake_submissions: Client A's scope returns only Client A",
          len(subs) == 1 and "A_INTAKE_MARKER" in json.dumps(subs[0][0]), str(subs))
    check("intake_sections: Client A's scope returns only Client A",
          len(secs) == 1 and secs[0][0].get("marker") == "A_SECTION", str(secs))
    check("client_report_files: Client A's scope returns only Client A",
          len(files) == 1 and files[0][0].startswith("A_SECTION"), str(files))

    with runtime.transaction():
        unscoped = runtime.execute("select count(*) from intake_submissions").fetchone()[0]
        unscoped_f = runtime.execute("select count(*) from client_report_files").fetchone()[0]
    check("with no client scope, intake returns ZERO rows, not all rows",
          unscoped == 0 and unscoped_f == 0, f"{unscoped}/{unscoped_f}")

    # A submission cannot be written into another client's record.
    try:
        with runtime.transaction():
            runtime.execute("select set_client_scope(%s)", (a,))
            runtime.execute(
                """insert into intake_submissions (client_id, raw_payload)
                   values (%s,'{}'::jsonb)""", (b,))
        check("runtime cannot file an intake under a client it is not scoped to",
              False, "accepted")
    except psycopg.Error as exc:
        check("runtime cannot file an intake under a client it is not scoped to",
              "row-level security" in str(exc).lower() or "policy" in str(exc).lower(),
              str(exc)[:90])

    # The shared practitioner connection was closed with its own section, so
    # this opens a fresh one rather than reaching for a dead handle.
    prac_intake = psycopg.connect(prac_dsn)
    try:
        with prac_intake.transaction():
            seen = prac_intake.execute(
                "select count(distinct client_id) from client_report_files").fetchone()[0]
        check("practitioner reads intake across clients (the deliberate path)",
              seen >= 2, str(seen))
    finally:
        prac_intake.close()

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

    # ------------------------------------------------------------------
    # D25. The test that is close to meaningless in Python and essential in
    # n8n: n8n's Postgres node POOLS connections, so the same physical
    # connection serves Client A's run and then Client B's. Scope is
    # transaction-local (005 passes `true` to set_config) precisely so that
    # cannot leak, and this proves it on ONE connection rather than
    # trusting the flag.
    #
    # Until D25 nothing exercised this at all: RUN_ENGINE connects as
    # phi_admin, which is SUPERUSER and bypasses RLS entirely, so every
    # engine run this system has made went around the policies rather than
    # through them.
    print("\nengine runs are client-scoped on a POOLED connection (D25)")
    os.environ["LLM_API_KEY"] = ""
    assert RE_SCOPE.select_provider()[1] == "fixture", \
        "this suite must never call a live provider"
    # A SEPARATE connection, autocommit, standing in for one n8n Postgres
    # node's pooled connection serving two clients in turn.
    pooled = psycopg.connect(runtime_dsn, autocommit=True)
    try:
        check("the pooled connection is phi_runtime, not a superuser",
              pooled.execute("select current_user, "
                             "(select rolsuper from pg_roles where rolname=current_user)"
                             ).fetchone() == ("phi_runtime", False))

        run_a = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
            engine="E6", mode="INIT", client_id=a,
            structured_input={"CASE_VERSION": 1}))
        run_b = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
            engine="E6", mode="INIT", client_id=b,
            structured_input={"CASE_VERSION": 1}))
        check("two clients ran back to back on ONE connection",
              run_a.status == "SUCCEEDED" and run_b.status == "SUCCEEDED",
              f"{run_a.status} / {run_b.status}")

        # The leak this guards: after B's run, the connection must not be
        # able to see A's row. No client_id filter -- the policy is the
        # only thing that can exclude it.
        with pooled.transaction():
            pooled.execute("select set_client_scope(%s)", (b,))
            visible = {str(r[0]) for r in pooled.execute(
                "select run_id from engine_runs").fetchall()}
        check("under B's scope, A's run is invisible",
              run_b.run_id in visible and run_a.run_id not in visible,
              f"{len(visible)} runs visible")

        with pooled.transaction():
            pooled.execute("select set_client_scope(%s)", (a,))
            visible_a = {str(r[0]) for r in pooled.execute(
                "select run_id from engine_runs").fetchall()}
        check("...and under A's scope, B's run is invisible",
              run_a.run_id in visible_a and run_b.run_id not in visible_a)

        # No scope at all is default-deny, not "everything". The one
        # exception is a knowledge-clock run, which has no client by design.
        unscoped = pooled.execute(
            "select count(*) from engine_runs where client_id is not null").fetchone()[0]
        check("with no scope set, no client run is visible", unscoped == 0, str(unscoped))

        # A knowledge-clock run has no client and must still be writable
        # and readable -- migration 014. Before it, this raised
        # InsufficientPrivilege no matter what scope was set.
        clock = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
            engine="E7", mode="FOUNDATION", model_role="MODEL_RESEARCH",
            structured_input={"CASE_VERSION": 0}))
        check("a knowledge-clock run writes with no client at all",
              clock.status == "SUCCEEDED", clock.error or clock.status)
        check("...and is readable without a scope",
              str(clock.run_id) in {str(r[0]) for r in pooled.execute(
                  "select run_id from engine_runs where client_id is null").fetchall()})
        check("...and its output is readable too",
              pooled.execute("select count(*) from engine_outputs where run_id=%s",
                             (clock.run_id,)).fetchone()[0] == 1)

        # 015. The four shapes a run's client and mode can disagree in.
        # 014's guard only caught one of them and permitted an E7 CASE run
        # with no client, which is a case with no case.
        print("\n  client/mode coherence is enforced BEFORE the insert (015)")
        for label, engine, mode, client, role in (
                ("E7 CASE with no client", "E7", "CASE", None, "MODEL_RESEARCH"),
                ("E7 FOUNDATION with a client", "E7", "FOUNDATION", a, "MODEL_RESEARCH"),
                ("E7 UPDATE with a client", "E7", "UPDATE", a, "MODEL_RESEARCH"),
                ("E7 INBOX with a client", "E7", "INBOX", a, "MODEL_RESEARCH"),
                ("E1 with no client", "E1", None, None, "MODEL_ANALYSIS"),
                ("E6 INIT with no client", "E6", "INIT", None, "MODEL_ANALYSIS")):
            try:
                RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
                    engine=engine, mode=mode, client_id=client, model_role=role,
                    structured_input={"CASE_VERSION": 1 if client else 0}))
                check(f"{label} is rejected", False, "the insert was accepted")
            except psycopg.errors.CheckViolation as exc:
                check(f"{label} is rejected",
                      "client" in str(exc).lower(), str(exc)[:90])

        for label, engine, mode, client, role in (
                ("E7 CASE with a client", "E7", "CASE", a, "MODEL_RESEARCH"),
                ("E7 FOUNDATION with none", "E7", "FOUNDATION", None, "MODEL_RESEARCH"),
                ("E7 INBOX with none", "E7", "INBOX", None, "MODEL_RESEARCH"),
                ("E6 REBUILD with a client", "E6", "REBUILD", a, "MODEL_ANALYSIS")):
            ok = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
                engine=engine, mode=mode, client_id=client, model_role=role,
                structured_input={"CASE_VERSION": 1 if client else 0}))
            check(f"{label} is accepted", ok.status == "SUCCEEDED",
                  ok.error or ok.status)

        check("the mode is on the RUN, not only on a successful output",
              admin.execute(
                  "select engine_mode from engine_runs where run_id=%s",
                  (run_a.run_id,)).fetchone()[0] == "INIT")
        check("nothing incoherent was written",
              admin.execute(
                  "select count(*) from v_engine_run_incoherent "
                  "where engine_mode is not null").fetchone()[0] == 0,
              str(admin.execute(
                  "select engine::text, engine_mode, problem "
                  "from v_engine_run_incoherent limit 3").fetchall()))

        # ------------------------------------------------------------------
        # 015. A failed CASE response is the client's clinical record in a
        # different shape. dead_letter_jobs had no client_id and no RLS at
        # all, so every raw payload was readable under ANY scope.
        print("\n  dead-letter payloads are client-scoped (015)")

        def refuses(system, user, params):
            # Prose, no machine blocks: the run dead-letters and the RAW
            # RESPONSE is what lands in dead_letter_jobs.raw_payload.
            #
            # It echoes the case back, which is what makes this a PHI test
            # rather than a column test. A model that fails mid-analysis
            # routinely restates what it was given -- "for this client,
            # HbA1c 6.4, I cannot..." -- and that restatement is the
            # client's clinical record sitting in a table that had no
            # client_id and no RLS at all.
            return f"I could not complete this. The case as given: {user}", 10, 10

        secret_a = "SENTINEL-LABS-CLIENT-A-HbA1c-6.4"
        secret_b = "SENTINEL-LABS-CLIENT-B-HbA1c-5.1"
        original_provider = RE_SCOPE.select_provider
        RE_SCOPE.select_provider = lambda: (refuses, "fixture")
        try:
            dead_a = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
                engine="E6", mode="INIT", client_id=a,
                structured_input={"CASE_VERSION": 1, "LABS": secret_a}))
            dead_b = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
                engine="E6", mode="INIT", client_id=b,
                structured_input={"CASE_VERSION": 1, "LABS": secret_b}))
        finally:
            RE_SCOPE.select_provider = original_provider

        check("both runs dead-lettered",
              dead_a.status == "DEAD_LETTER" and dead_b.status == "DEAD_LETTER")
        check("the dead letter records which client's data it holds",
              admin.execute(
                  "select client_id from dead_letter_jobs where entity_id=%s",
                  (dead_a.run_id,)).fetchone()[0] is not None)

        # The leak. No client_id filter -- RLS is the only thing that can
        # exclude the other client's clinical text.
        with pooled.transaction():
            pooled.execute("select set_client_scope(%s)", (b,))
            payloads = " ".join(
                json.dumps(r[0]) for r in pooled.execute(
                    "select raw_payload from dead_letter_jobs").fetchall())
        check("under B's scope, A's failed payload is invisible",
              secret_b in payloads and secret_a not in payloads,
              f"A leaked: {secret_a in payloads}")

        with pooled.transaction():
            pooled.execute("select set_client_scope(%s)", (a,))
            payloads_a = " ".join(
                json.dumps(r[0]) for r in pooled.execute(
                    "select raw_payload from dead_letter_jobs").fetchall())
        check("...and under A's scope, B's is invisible",
              secret_a in payloads_a and secret_b not in payloads_a)

        unscoped = " ".join(json.dumps(r[0]) for r in pooled.execute(
            "select raw_payload from dead_letter_jobs").fetchall())
        check("with no scope set, no client payload is visible at all",
              secret_a not in unscoped and secret_b not in unscoped)

        check("RLS is FORCED, so even a table owner cannot read past it",
              admin.execute(
                  "select relforcerowsecurity from pg_class "
                  "where relname='dead_letter_jobs'").fetchone()[0])

        # A dead letter that genuinely has no client stays global -- a
        # knowledge-clock failure carries no client data and hiding it
        # would make the knowledge track undebuggable.
        RE_SCOPE.select_provider = lambda: (refuses, "fixture")
        try:
            clock_dead = RE_SCOPE.run_engine(pooled, RE_SCOPE.EngineRequest(
                engine="E7", mode="FOUNDATION", model_role="MODEL_RESEARCH",
                structured_input={"CASE_VERSION": 0}))
        finally:
            RE_SCOPE.select_provider = original_provider
        check("a knowledge-clock dead letter has no client and stays readable",
              pooled.execute(
                  "select count(*) from dead_letter_jobs "
                  "where entity_id=%s and client_id is null",
                  (clock_dead.run_id,)).fetchone()[0] == 1)

        # Triage without reading anyone's clinical text.
        triage = admin.execute(
            "select job_type, failures, clients_affected from v_dead_letter_triage "
            "where job_type like 'RUN_ENGINE_%' order by failures desc limit 1"
        ).fetchone()
        check("triage counts failures without exposing raw_payload",
              triage is not None and triage[1] >= 2, str(triage))
        check("...and the view has no raw_payload column",
              "raw_payload" not in {r[0] for r in admin.execute(
                  "select column_name from information_schema.columns "
                  "where table_name='v_dead_letter_triage'").fetchall()})
    finally:
        pooled.close()

    runtime.close()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
