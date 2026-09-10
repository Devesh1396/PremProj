#!/usr/bin/env python3
"""Practice intelligence. Step 23.

BUILD_GUIDE step 23; migration `029`; D9, D43, D45. Hard rules 3, 4, 6, 8.

    de-identified aggregation into practice_strategy_outcomes,
    minimum cohort 5, never merged with evidence

`practice_strategy_outcomes` has carried `ck_min_cohort` since migration
`003` and NOTHING HAS EVER WRITTEN A ROW, so the constraint has been
passing every insert it never saw. This suite is the first thing that puts
a cohort through it.

The five properties a plausible aggregation loses:

1. **Practice experience never becomes evidence** (D9, hard rule 6). The
   existing check counts foreign keys; it does not check the other half of
   the rule, "no view joins them". Step 23 adds the FIRST two views that
   touch the table, so that half stops being free here.
2. **The cohort counts PEOPLE.** Five intervention rows from two clients
   is one person's record with a count on it, and a client with three
   interventions of the same strategy contributes ONE observation.
3. **The denominator travels with the numerator.** Five improved out of
   five assessed, where thirty were exposed and twenty-five never looked
   at, is a selection effect with a number in front of it.
4. **No client text is copied out.** Every summary is composed from
   counts. `trg_practice_deidentified` is the backstop, not the plan.
5. **Adherence is never folded into outcome** (D43). A cohort nobody
   measured has not shown the strategy fails.

A note on what is NOT claimed: `practice_deidentified()` is SECURITY
DEFINER so the display-name check cannot pass merely because RLS hid the
client from the caller. That property is asserted structurally
(`prosecdef`), not behaviourally -- every role that can write this table
either bypasses RLS already or has had its write revoked, so there is no
caller left with which to demonstrate the difference. Saying so is better
than a test that appears to prove it.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))
sys.path.insert(0, str(REPO / "testing" / "fixtures"))

import psycopg

import client_new as CN
import practice_intelligence as PI
import run_engine as RE
import synthetic_intake as SI

FAILS: list[str] = []
PREFIX = "PXTEST_"
STRATEGY_MARK = "PXTEST practice fixture"
# A token nothing would invent, written into a client's stop_reason. If it
# reaches the aggregate, client free text is being copied out.
LEAK_TOKEN = "PXLEAKTOKEN9137"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def refuses(conn, name: str, sql: str, params: tuple, expect: str) -> None:
    """Drive the real constraint. A refusal is only a refusal if it names
    what was wrong -- an insert that fails for an unrelated reason would
    otherwise read as the rule holding."""
    try:
        with conn.transaction():
            conn.execute(sql, params)
        check(name, False, "it was accepted")
    except psycopg.Error as exc:
        check(name, expect.lower() in str(exc).lower(), str(exc)[:160])


def clear(conn) -> None:
    conn.execute(
        "delete from practice_strategy_outcomes where strategy_id in "
        " (select strategy_id from strategies where provenance_note = %s)",
        (STRATEGY_MARK,))
    conn.execute("delete from clients where external_ref like %s", (PREFIX + "%",))
    conn.execute("delete from strategies where provenance_note = %s", (STRATEGY_MARK,))


def make_strategy(conn, name: str) -> str:
    return str(conn.execute(
        "insert into strategies (name, knowledge_status, provenance_note, "
        "                        outcomes_to_track) "
        "values (%s,'AI_DISCOVERED_CANDIDATE',%s,%s) returning strategy_id",
        (f"{PREFIX}{name}", STRATEGY_MARK, "fixture")).fetchone()[0])


def make_client(conn, ref: str, display: str | None = None) -> str:
    cid = str(conn.execute(
        "insert into clients (external_ref, display_name, year_of_birth, status) "
        "values (%s,%s,1980,'ACTIVE') returning client_id",
        (PREFIX + ref, display or (PREFIX + ref))).fetchone()[0])
    conn.execute("select set_client_scope(%s::uuid)", (cid,))
    return cid


def give(conn, client_id: str, strategy_id: str, *, started: bool = True,
         outcome: str | None = None, adherence_pct=None, days_ago: int = 60,
         status: str = "ONGOING", stop_reason: str | None = None,
         name: str = "fixture intervention") -> str:
    """One intervention, optionally started, optionally assessed.

    `started=False` is a PROPOSED plan nobody carried out -- not practice
    experience, and the cohort must not count it.
    """
    start = date.today() - timedelta(days=days_ago)
    iid = str(conn.execute(
        "insert into client_interventions (client_id, strategy_id, name, status, "
        "  source_engine, proposed_on, started_on) "
        "values (%s::uuid,%s::uuid,%s,%s,'E3',%s,%s) returning intervention_id",
        (client_id, strategy_id, name,
         status if started else "PROPOSED", start,
         start if started else None)).fetchone()[0])
    if adherence_pct is not None:
        conn.execute(
            "insert into client_intervention_exposure (intervention_id, "
            "  period_start, adherence_pct) values (%s::uuid,%s,%s)",
            (iid, start, adherence_pct))
    if outcome is not None:
        conn.execute(
            "select record_intervention_outcome(%s::uuid,%s::outcome_direction,"
            "  %s::intervention_status,null,null,null,null,%s)",
            (iid, outcome, status if status != "ONGOING" else None, stop_reason))
    return iid


def summarise_for(conn, strategy_id: str) -> dict:
    return PI.summarise(PI.observations(conn, strategy_id))


def cohort_row(conn, strategy_id: str) -> dict:
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "select * from v_practice_cohort_candidates where strategy_id=%s::uuid",
            (strategy_id,)).fetchone()


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)

    # ==================================================================
    print("\nD9: practice experience is structurally separate from evidence")

    fks = conn.execute("""
        select count(*) from information_schema.table_constraints tc
          join information_schema.constraint_column_usage ccu
            on tc.constraint_name = ccu.constraint_name
         where tc.table_name = 'practice_strategy_outcomes'
           and tc.constraint_type = 'FOREIGN KEY'
           and ccu.table_name = 'evidence_records'""").fetchone()[0]
    check("no foreign key merges practice data into evidence", fks == 0, str(fks))

    # The other half of D9, asserted over the WHOLE schema rather than
    # over the two views step 23 happens to add. The rule has to survive
    # the next view somebody writes.
    joined = [r[0] for r in conn.execute("""
        select distinct u.view_name
          from information_schema.view_table_usage u
         where u.table_name = 'practice_strategy_outcomes'
           and exists (select 1 from information_schema.view_table_usage v
                        where v.view_name = u.view_name
                          and v.table_name = 'evidence_records')""").fetchall()]
    check("no view joins practice experience to evidence", not joined, str(joined))

    touching = {r[0] for r in conn.execute("""
        select distinct view_name from information_schema.view_table_usage
         where table_name = 'practice_strategy_outcomes'""").fetchall()}
    check("the check has something to check: views do touch the table",
          touching >= {"v_practice_experience"}, str(touching))

    idcols = [r[0] for r in conn.execute("""
        select column_name from information_schema.columns
         where table_name = 'practice_strategy_outcomes'
           and column_name in ('client_id','external_ref','display_name')
        """).fetchall()]
    check("the aggregate has no column for a client identifier",
          not idcols, str(idcols))

    secdef = conn.execute(
        "select prosecdef from pg_proc where proname='practice_deidentified'"
    ).fetchone()[0]
    check("the de-identification check is SECURITY DEFINER, so RLS cannot "
          "hide the client it is checking for", secdef is True)

    runtime_writes = conn.execute("""
        select count(*) from information_schema.role_table_grants
         where table_name='practice_strategy_outcomes' and grantee='phi_runtime'
           and privilege_type in ('INSERT','UPDATE','DELETE')""").fetchone()[0]
    runtime_reads = conn.execute("""
        select count(*) from information_schema.role_table_grants
         where table_name='practice_strategy_outcomes' and grantee='phi_runtime'
           and privilege_type = 'SELECT'""").fetchone()[0]
    check("phi_runtime reads practice aggregates and cannot create one",
          runtime_writes == 0 and runtime_reads == 1,
          f"writes={runtime_writes} reads={runtime_reads}")

    # ==================================================================
    print("\nthe cohort counts PEOPLE, and it counts them once")

    s_rows = make_strategy(conn, "five rows two clients")
    c1, c2 = make_client(conn, "rows1"), make_client(conn, "rows2")
    for i in range(3):
        conn.execute("select set_client_scope(%s::uuid)", (c1,))
        give(conn, c1, s_rows, outcome="IMPROVING", days_ago=90 - i,
             name=f"repeat {i}")
    for i in range(2):
        conn.execute("select set_client_scope(%s::uuid)", (c2,))
        give(conn, c2, s_rows, outcome="STABLE", days_ago=90 - i,
             name=f"repeat {i}")

    row = cohort_row(conn, s_rows)
    check("five intervention rows from two clients is a cohort of two",
          row["n_clients_assessed"] == 2 and row["n_interventions"] == 5,
          str(dict(row)))
    check("and it does not reach the minimum",
          row["meets_cohort_minimum"] is False and "short of the minimum"
          in (row["blocked_reason"] or ""), str(row["blocked_reason"]))

    obs = summarise_for(conn, s_rows)
    check("one client contributes one observation, not one per intervention",
          obs["n_clients"] == 2
          and sum(obs["outcome_counts"].values()) == 2,
          str(obs["outcome_counts"]))

    # ==================================================================
    print("\na proposal nobody started is not practice experience")

    s_prop = make_strategy(conn, "never started")
    for i in range(6):
        cid = make_client(conn, f"prop{i}")
        give(conn, cid, s_prop, started=False)
    row = cohort_row(conn, s_prop)
    check("six clients were offered it and the cohort is zero",
          row["n_clients_exposed"] == 0 and row["n_interventions"] == 0,
          str(dict(row)))
    check("and the reason says nobody started it",
          "no client has started" in (row["blocked_reason"] or ""),
          str(row["blocked_reason"]))

    # ==================================================================
    print("\nthe denominator travels with the numerator")

    s_sel = make_strategy(conn, "selection effect")
    for i in range(5):
        cid = make_client(conn, f"sel_seen{i}")
        give(conn, cid, s_sel, outcome="IMPROVING", adherence_pct=90)
    for i in range(7):
        cid = make_client(conn, f"sel_unseen{i}")
        give(conn, cid, s_sel)                       # started, never assessed

    row = cohort_row(conn, s_sel)
    check("exposed counts everyone who started; assessed counts who was looked at",
          row["n_clients_exposed"] == 12 and row["n_clients_assessed"] == 5,
          str(dict(row)))
    check("five assessed clients reaches the minimum",
          row["meets_cohort_minimum"] is True)

    obs = summarise_for(conn, s_sel)
    check("the summary states how many were never assessed",
          "7 never assessed" in obs["outcome_summary"], obs["outcome_summary"])
    check("n_clients is the assessed count, not the exposed count",
          obs["n_clients"] == 5 and obs["n_clients_exposed"] == 12,
          f"{obs['n_clients']}/{obs['n_clients_exposed']}")

    # A cohort where nobody was assessed is a standing failure to look,
    # and it must not read the same as a cohort that is merely small.
    s_blind = make_strategy(conn, "nobody assessed")
    for i in range(9):
        cid = make_client(conn, f"blind{i}")
        give(conn, cid, s_blind)
    row = cohort_row(conn, s_blind)
    check("nine started and none assessed says exactly that",
          "NONE has been assessed" in (row["blocked_reason"] or ""),
          str(row["blocked_reason"]))

    # ==================================================================
    print("\nthe minimum is 5, in the view and in the constraint")

    s_four = make_strategy(conn, "four clients")
    for i in range(4):
        cid = make_client(conn, f"four{i}")
        give(conn, cid, s_four, outcome="IMPROVING", adherence_pct=85)
    check("four assessed clients does not reach the minimum",
          cohort_row(conn, s_four)["meets_cohort_minimum"] is False)
    check("and the runner skips it", not any(
        r["strategy"].endswith("four clients")
        for r in PI.run(conn, execute=False)["rows"]))

    refuses(conn, "the constraint refuses a cohort of four independently",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients) values (%s::uuid,'four',4)", (s_four,), "ck_min_cohort")
    conn.execute(
        "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
        " n_clients) values (%s::uuid,'five',5)", (s_four,))
    check("and accepts five, so the view and the constraint agree on the bar",
          conn.execute("select count(*) from practice_strategy_outcomes where "
                       "strategy_id=%s::uuid", (s_four,)).fetchone()[0] == 1)
    conn.execute("delete from practice_strategy_outcomes where strategy_id=%s::uuid",
                 (s_four,))

    # ==================================================================
    print("\na distribution must account for the whole cohort")

    refuses(conn, "outcome_counts that do not sum to n_clients are refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, outcome_counts) values (%s::uuid,'partial',7,%s::jsonb)",
            (s_sel, json.dumps({"IMPROVING": 4})),
            "ck_practice_outcomes_account_for_cohort")
    refuses(conn, "adherence_counts that do not sum to n_clients are refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, adherence_counts) values (%s::uuid,'partial',7,%s::jsonb)",
            (s_sel, json.dumps({"HIGH": 2})),
            "ck_practice_adherence_accounts_for_cohort")
    refuses(conn, "a cohort larger than the clients exposed is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, n_clients_exposed) values (%s::uuid,'impossible',9,5)",
            (s_sel,), "ck_practice_counts_coherent")
    refuses(conn, "a generated aggregate that cannot say out of how many is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, generation_method) values (%s::uuid,'bare',9,'X')",
            (s_sel,), "ck_practice_generated_complete")

    # ==================================================================
    print("\nde-identification is enforced, not claimed")

    named = conn.execute("select display_name from clients where external_ref=%s",
                         (PREFIX + "sel_seen0",)).fetchone()[0]
    # A client whose external_ref is NOT also their display name, so the
    # refusal below is attributable to the reference rule. Every other
    # fixture client has display_name = external_ref, which would let the
    # display-name rule fire first and make this check prove nothing.
    ref_only = PREFIX + "REFONLY_QX41"
    conn.execute("insert into clients (external_ref, display_name, status) "
                 "values (%s,null,'ACTIVE')", (ref_only,))
    refuses(conn, "a UUID in the aggregate is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients) values (%s::uuid,%s,5)",
            (s_sel, f"clients like {c1}"), "UUID")
    refuses(conn, "a client display name in the aggregate is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, outcome_summary) values (%s::uuid,'ok',5,%s)",
            (s_sel, f"strong response, especially for {named}"), "names a client")
    refuses(conn, "a client external reference in the aggregate is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, drop_out) values (%s::uuid,'ok',5,%s)",
            (s_sel, f"one drop-out ({ref_only})"), "external reference")
    refuses(conn, "an email address in the aggregate is refused",
            "insert into practice_strategy_outcomes (strategy_id, cohort_criteria,"
            " n_clients, common_side_effects) values (%s::uuid,'ok',5,%s)",
            (s_sel, "reported by anita.k@example.com"), "email")

    # ==================================================================
    print("\nthe aggregate is counts, never copied client text")

    s_leak = make_strategy(conn, "stop reasons")
    for i in range(5):
        cid = make_client(conn, f"leak{i}")
        give(conn, cid, s_leak, outcome="LIMITED_RESPONSE", status="STOPPED",
             stop_reason=f"{LEAK_TOKEN} could not sustain the evening walk",
             adherence_pct=40)
    leaked = summarise_for(conn, s_leak)
    blob = " ".join(str(v) for v in leaked.values())
    check("a distinctive stop reason does not reach the aggregate",
          LEAK_TOKEN not in blob, blob[:160])
    check("but the count of stops does",
          "5 stop(s) recorded" in leaked["common_failure_reasons"],
          leaked["common_failure_reasons"])
    check("side effects are left NULL rather than invented",
          leaked["common_side_effects"] is None)

    # ==================================================================
    print("\nadherence sits beside the outcome, never folded into it (D43)")

    s_unmeasured = make_strategy(conn, "unmeasured adherence")
    for i in range(5):
        cid = make_client(conn, f"unm{i}")
        give(conn, cid, s_unmeasured, outcome="STABLE")     # no adherence_pct
    unm = summarise_for(conn, s_unmeasured)
    check("an unmeasured cohort is UNKNOWN, never assumed adherent",
          unm["adherence_counts"] == {"UNKNOWN": 5}, str(unm["adherence_counts"]))
    check("and the summary says a neutral result here is untested, not ineffective",
          "untested, not ineffective" in unm["adherence_summary"],
          unm["adherence_summary"])

    s_measured = make_strategy(conn, "measured adherence")
    for i in range(5):
        cid = make_client(conn, f"mea{i}")
        give(conn, cid, s_measured, outcome="STABLE", adherence_pct=90)
    mea = summarise_for(conn, s_measured)
    check("a measured cohort carries no such caveat",
          "untested" not in mea["adherence_summary"], mea["adherence_summary"])
    check("the caveat is about the cohort, not boilerplate on every row",
          mea["adherence_counts"] == {"HIGH": 5}, str(mea["adherence_counts"]))

    # ==================================================================
    print("\nthe latest outcome per client is the one that counts")

    s_moved = make_strategy(conn, "outcome moved")
    for i in range(5):
        cid = make_client(conn, f"moved{i}")
        iid = give(conn, cid, s_moved, outcome="IMPROVING", adherence_pct=90)
        conn.execute(
            "select record_intervention_outcome(%s::uuid,'WORSENING'::outcome_direction,"
            "  null,null,null,null,null,null)", (iid,))
    moved = summarise_for(conn, s_moved)
    check("an improvement that later worsened counts once, as WORSENING",
          moved["outcome_counts"] == {"WORSENING": 5},
          str(moved["outcome_counts"]))
    check("and the range reads from the worst present, not from history",
          moved["outcome_range"] == "WORSENING only", moved["outcome_range"])

    # ==================================================================
    print("\nthe runner plans by default and is idempotent when it writes")

    before = conn.execute("select count(*) from practice_strategy_outcomes "
                          "where generation_method is not null").fetchone()[0]
    planned = PI.run(conn, execute=False)
    after = conn.execute("select count(*) from practice_strategy_outcomes "
                         "where generation_method is not null").fetchone()[0]
    check("a plan run writes nothing", before == after and planned["rows"],
          f"{before}->{after}, {len(planned['rows'])} planned")

    first = PI.run(conn, execute=True)
    check("execute creates one aggregate per ready strategy",
          first["created"] == first["ready"] and first["created"] >= 5,
          f"created {first['created']} of {first['ready']} ready")

    stamps = {r[0]: r[1] for r in conn.execute(
        "select strategy_id::text, generated_at from practice_strategy_outcomes "
        " where generation_method is not null").fetchall()}
    second = PI.run(conn, execute=True)
    check("a second run over unchanged data writes nothing",
          second["unchanged"] == second["ready"] and second["created"] == 0,
          f"unchanged {second['unchanged']}, created {second['created']}")
    stamps2 = {r[0]: r[1] for r in conn.execute(
        "select strategy_id::text, generated_at from practice_strategy_outcomes "
        " where generation_method is not null").fetchall()}
    check("and generated_at does not move, so an unchanged row does not "
          "look freshly derived", stamps == stamps2)

    # New data changes the aggregate rather than adding a second one.
    cid = make_client(conn, "sel_late")
    give(conn, cid, s_sel, outcome="WORSENING", adherence_pct=30)
    third = PI.run(conn, execute=True)
    check("a changed cohort updates in place, never accumulates a second row",
          third["updated"] == 1
          and conn.execute("select count(*) from practice_strategy_outcomes "
                           " where strategy_id=%s::uuid", (s_sel,)).fetchone()[0] == 1,
          f"updated {third['updated']}")
    stored = conn.execute(
        "select n_clients, n_clients_exposed, outcome_counts from "
        " practice_strategy_outcomes where strategy_id=%s::uuid", (s_sel,)).fetchone()
    check("and the stored row reflects the new client",
          stored[0] == 6 and stored[1] == 13 and stored[2]["WORSENING"] == 1,
          str(stored))

    # V2: repeat anything whose fixture generates identifiers. The
    # per-client pick is a DISTINCT ON with a tie-break; ten runs is what
    # distinguishes deterministic from lucky.
    baseline = json.dumps(summarise_for(conn, s_sel), sort_keys=True, default=str)
    identical = all(
        json.dumps(summarise_for(conn, s_sel), sort_keys=True, default=str) == baseline
        for _ in range(10))
    check("ten aggregations of the same rows are byte-identical", identical)

    # ==================================================================
    print("\nthe block is labelled, and the label is in the row")

    block = PI.practice_block(conn)
    check("the block is not empty once aggregates exist", len(block) >= 5,
          str(len(block)))
    check("every entry says what it is and what it is not",
          all(e["basis"] == "INTERNAL_PRACTICE_OBSERVATION"
              and e["evidence_status"] == "NOT_EVIDENCE"
              and "NOT trial evidence" in e["caveat"] for e in block))
    check("no entry carries a client identifier",
          not any("client_id" in e for e in block))

    by_strategy = PI.practice_block(conn, strategy_ids=[s_sel])
    check("the block filters to named strategies", len(by_strategy) == 1
          and by_strategy[0]["strategy_name"].endswith("selection effect"),
          str([e["strategy_name"] for e in by_strategy]))
    check("a filter matching nothing returns nothing, not everything",
          PI.practice_block(conn, concept_ids=[
              "00000000-0000-0000-0000-000000000001"]) == [])

    # ==================================================================
    print("\nthe block reaches the engines as its own top-level key")

    assert RE.select_provider()[1] == "fixture", "must run on the fixture provider"
    SI.clear(conn)
    conn.execute("delete from concepts where canonical_key like 'PHRASE_%' "
                 "or origin_detail like 'C3_NORMALIZATION%'")
    import intake as IN
    client_id = SI.load_client(conn, SI.EXTERNAL_REF_COMPLETE)
    submission = IN.submit(conn, client_id, SI.COMPLETE_INTAKE)

    seen: dict[str, dict] = {}
    original_run = CN._run

    def capture(conn_, outcome_, label, **kw):
        seen[label] = kw.get("structured_input") or {}
        return original_run(conn_, outcome_, label, **kw)

    CN._run = capture
    try:
        result = CN.run_new_client(conn, submission)
    finally:
        CN._run = original_run

    check("the pipeline still completes with the practice block wired in",
          result.status in ("AWAITING_REVIEW", "HELD"),
          result.stopped_because or result.status)
    for label in ("E7", "E1_PASS_B"):
        payload = seen.get(label, {})
        check(f"{label} receives PRACTICE_EXPERIENCE as a top-level key",
              "PRACTICE_EXPERIENCE" in payload, str(sorted(payload)[:8]))
        check(f"{label}'s practice block is not folded into a handoff",
              "PRACTICE_EXPERIENCE" not in json.dumps(
                  payload.get("E7_HANDOFF") or payload.get("E1_PASS_A_HANDOFF") or ""))
    steps = {s.name: s for s in result.steps}
    check("the run reports what practice experience it had",
          "PRACTICE_EXPERIENCE" in steps, str(sorted(steps)[:12]))

    clear(conn)
    SI.clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_practice: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
