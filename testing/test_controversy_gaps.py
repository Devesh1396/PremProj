#!/usr/bin/env python3
"""K12 and K13 — controversy, negative knowledge, gaps. Step 19.

Engine 7 §R2b, §R14, §R15, §49, §68, §70; migration 025; hard rules 3 and 11.

Everything here drives the real scripts through the real `RUN_ENGINE` with
only the transport replaced (V2), and every optional dependency degrades
through `preflight` (V3).

The four properties that make these passes worth having, each of which a
plausible implementation loses:

1. **A controversy needs two positions.** One is a consensus statement or a
   gap, and stored here it is retrieved as a live disagreement. Enforced at
   COMMIT, so a half-written controversy cannot land.
2. **Negative knowledge must be able to stop the next search.** Without
   what was examined and what would make us look again it cannot, which is
   the only job it has.
3. **A pass that ran and found nothing is not the same as no pass.** That
   distinction is hard rule 11, and it is the difference between "this
   domain is settled" and "nobody has looked".
4. **Escalation is capped and ranks by impact.** Hard rule 3. An uncapped
   queue is the recurring manual job the whole system exists to avoid.
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

import knowledge_controversy as KC
import knowledge_gap as KG
import preflight
import run_engine as RE

FAILS: list[str] = []
PREFIX = "CGTEST_"


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
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), str(exc)[:220])
        return
    check(name, False, "no error was raised")


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------

def clear(conn) -> None:
    conn.execute(
        "delete from controversies where domain_id in "
        "  (select domain_id from knowledge_domains where domain_key like %s)",
        (PREFIX + "%",))
    conn.execute(
        "delete from negative_knowledge where domain_id in "
        "  (select domain_id from knowledge_domains where domain_key like %s)",
        (PREFIX + "%",))
    conn.execute(
        "delete from knowledge_gaps where domain_id in "
        "  (select domain_id from knowledge_domains where domain_key like %s)",
        (PREFIX + "%",))
    conn.execute("delete from strategies where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from concepts where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from knowledge_domains where domain_key like %s",
                 (PREFIX + "%",))


def seed(conn) -> dict:
    """One domain at moderate coverage with material accumulated in it."""
    domain_id = str(conn.execute(
        "insert into knowledge_domains (name, domain_key, domain_type, "
        "description, discovered_by) values (%s,%s,'OTHER',%s,'CGTEST') "
        "returning domain_id",
        (PREFIX + "metabolic", PREFIX + "DOMAIN_A", "fixture")).fetchone()[0])

    for dimension in conn.execute(
            "select unnest(enum_range(null::coverage_dimension))::text limit 7"
    ).fetchall():
        conn.execute(
            "insert into domain_coverage (domain_id, dimension, covered, item_count) "
            "values (%s,%s::coverage_dimension,true,4) "
            "on conflict (domain_id, dimension) do update set covered=true",
            (domain_id, dimension[0]))

    strategies = {}
    for n in range(4):
        cid = str(conn.execute(
            "insert into concepts (canonical_key, canonical_name, concept_type, "
            "status, origin_method) values (%s,%s,'DRIVER','ACTIVE','SEED') "
            "returning concept_id",
            (f"{PREFIX}CONCEPT_{n}", f"cgtest concept {n}")).fetchone()[0])
        conn.execute(
            "insert into concept_domains (concept_id, domain_id, source) "
            "values (%s,%s,'K1_SEED')", (cid, domain_id))
        sid = str(conn.execute(
            "insert into strategies (name, canonical_key, summary, mechanism, "
            "evidence_confidence, knowledge_status) "
            "values (%s,%s,%s,%s,'MODERATE','AI_DISCOVERED_CANDIDATE') "
            "returning strategy_id",
            (f"{PREFIX}strategy {n}", f"{PREFIX}S_{n}",
             f"a strategy about cgtest concept {n}",
             "a mechanism")).fetchone()[0])
        conn.execute(
            "insert into strategy_concepts (strategy_id, concept_id, link_role, "
            "weight) values (%s,%s,'INDICATED_FOR',1.0)", (sid, cid))
        strategies[n] = sid
    return {"domain_id": domain_id, "domain_key": PREFIX + "DOMAIN_A",
            "strategies": strategies}


def stub(tag: str, fields: dict):
    """A provider emitting one handoff block plus the control block.

    `RUN_ENGINE`'s real provider contract; the parser, the handoff registry
    and the control contract are all the real ones (V2).
    """
    body = "".join(f"{k}: {v}\n" for k, v in fields.items())

    def provider(system_prompt, user_prompt, params):
        return (
            "the report\n"
            f"<{tag}>\n{body}</{tag}>\n"
            '<CONTROL_BLOCK>\n{"CASE_VERSION": 0, "ENGINE_RUN_STATUS": '
            '"SUCCEEDED"}\n</CONTROL_BLOCK>\n'), 10, 10
    return provider


def with_provider(provider, fn):
    original = RE.select_provider
    RE.select_provider = lambda: (provider, "fixture")
    try:
        return fn()
    finally:
        RE.select_provider = original


TWO_SIDED = {
    "question": "Does a high-fat breakfast worsen postprandial glucose?",
    "summary": "Trials disagree on direction.",
    "why_studies_disagree": "Different meal composition and timing windows.",
    "population_differences": "Mostly European cohorts; no vegetarian Indian data.",
    "current_consensus": None,
    "current_uncertainty": "Whether the effect survives habitual adaptation.",
    "practical_interpretation": "Measure rather than assume.",
    "positions": [
        {"position": "It worsens the glucose peak",
         "evidence_summary": "Two crossover trials, n=24 and n=31",
         "population_context": "European adults", "held_by": "group A"},
        {"position": "It blunts the glucose peak",
         "evidence_summary": "One RCT, n=60, 12 weeks",
         "population_context": "Mixed", "held_by": "group B"},
    ],
}

ONE_SIDED = dict(TWO_SIDED, question="A one-sided question",
                 positions=[TWO_SIDED["positions"][0]])

GOOD_NEGATIVE = {
    "claim_or_strategy": "chromium picolinate for insulin sensitivity",
    "why_investigated": "Repeatedly suggested by creators in this domain.",
    "evidence_examined": "Two meta-analyses and four RCTs.",
    "finding": "No consistent effect outside frank deficiency.",
    "current_interpretation": "Not worth recommending.",
    "revisit_trigger": "A trial in vegetarian Indian adults with deficiency.",
}


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)
    fx = seed(conn)

    # ==================================================================
    print("\na controversy with one position is not a controversy")

    # Written directly, so the DATABASE is what refuses it -- not the
    # script's own filter, which is tested separately below.
    try:
        with conn.transaction():
            solo = conn.execute(
                "insert into controversies (question, domain_id) "
                "values (%s,%s) returning controversy_id",
                (PREFIX + "solo", fx["domain_id"])).fetchone()[0]
            conn.execute(
                "insert into controversy_positions (controversy_id, position, "
                "evidence_summary) values (%s,'only side','some evidence')",
                (solo,))
        check("a single-position controversy is refused at COMMIT", False,
              "it was accepted")
    except psycopg.Error as exc:
        check("a single-position controversy is refused at COMMIT",
              "position" in str(exc).lower(), str(exc)[:180])

    # And two positions in the same transaction is accepted -- otherwise
    # the constraint would be unsatisfiable rather than protective.
    with conn.transaction():
        pair = conn.execute(
            "insert into controversies (question, domain_id) values (%s,%s) "
            "returning controversy_id",
            (PREFIX + "pair", fx["domain_id"])).fetchone()[0]
        for side in ("one side", "the other"):
            conn.execute(
                "insert into controversy_positions (controversy_id, position, "
                "evidence_summary) values (%s,%s,'evidence')", (pair, side))
    check("two positions written in one transaction is accepted",
          conn.execute("select count(*) from controversy_positions "
                       " where controversy_id=%s", (pair,)).fetchone()[0] == 2)

    expect_error(
        conn,
        "insert into controversy_positions (controversy_id, position, "
        "evidence_summary) values (%s,'no evidence',NULL)", (pair,),
        "a position with no evidence summary is refused",
        "ck_position_has_evidence")

    # Removing a position must not leave a one-sided controversy behind.
    try:
        with conn.transaction():
            conn.execute(
                "delete from controversy_positions where controversy_id=%s "
                "  and position='one side'", (pair,))
        check("deleting a position back down to one is refused", False,
              "it was accepted")
    except psycopg.Error as exc:
        check("deleting a position back down to one is refused",
              "position" in str(exc).lower(), str(exc)[:180])

    conn.execute("delete from controversies where question like %s", (PREFIX + "%",))

    # ==================================================================
    print("\nnegative knowledge must be able to stop the next search")

    for missing in ("why_investigated", "evidence_examined", "revisit_trigger"):
        record = dict(GOOD_NEGATIVE)
        record[missing] = ""
        expect_error(
            conn,
            "insert into negative_knowledge (claim_or_strategy, domain_id, "
            " why_investigated, evidence_examined, finding, revisit_trigger) "
            "values (%s,%s,%s,%s,%s,%s)",
            (record["claim_or_strategy"], fx["domain_id"],
             record["why_investigated"], record["evidence_examined"],
             record["finding"], record["revisit_trigger"]),
            f"negative knowledge with no {missing} is refused",
            "ck_negative_is_actionable")

    # ==================================================================
    print("\nK12 drives the real engine and writes what it is given")

    payload = stub("RESEARCH_PRACTICE_CONTROVERSY", {
        "MODE": "CONTROVERSY",
        "DOMAIN_REFERENCE": fx["domain_key"],
        "CONTROVERSIES_JSON": json.dumps([TWO_SIDED, ONE_SIDED]),
        "NEGATIVE_KNOWLEDGE_JSON": json.dumps(
            [GOOD_NEGATIVE, dict(GOOD_NEGATIVE, revisit_trigger="")]),
    })
    domain = (fx["domain_id"], fx["domain_key"], "metabolic")
    out = with_provider(payload, lambda: KC.assess_one(conn, domain))

    check("the controversy with two positions was written",
          out["controversies"] == 1, str(out))
    check("the one-sided one was refused, not written",
          out["refused"] >= 1, str(out))
    check("the complete negative finding was written",
          out["negative"] == 1, str(out))
    check("and the one with no revisit trigger was not",
          conn.execute(
              "select count(*) from negative_knowledge where domain_id=%s",
              (fx["domain_id"],)).fetchone()[0] == 1)

    positions = conn.execute(
        "select count(*) from controversy_positions p join controversies c "
        "  using (controversy_id) where c.domain_id=%s",
        (fx["domain_id"],)).fetchone()[0]
    check("its positions came with it", positions == 2, str(positions))

    # ==================================================================
    print("\nhard rule 12: derived knowledge registers itself")

    for kind, table, column in (("CONTROVERSY", "controversies", "controversy_id"),
                                ("NEGATIVE_KNOWLEDGE", "negative_knowledge",
                                 "negative_id")):
        registered = conn.execute(
            f"select count(*) from knowledge_entities ke "
            f"  join {table} t on t.{column} = ke.entity_id "
            f" where t.domain_id = %s and ke.entity_kind = %s::derived_kind",
            (fx["domain_id"], kind)).fetchone()[0]
        check(f"every {kind} row is in knowledge_entities", registered >= 1,
              str(registered))

    # ==================================================================
    print("\na pass that found nothing is not the same as no pass")

    state = conn.execute(
        "select pass_performed, controversies, negative_findings, overdue "
        "  from v_controversy_state where domain_id=%s",
        (fx["domain_id"],)).fetchone()
    check("the governance row records that the pass ran", state[0] is True, str(state))
    check("and the domain is no longer overdue", state[3] is False, str(state))

    conn.execute("delete from controversies where domain_id=%s", (fx["domain_id"],))
    conn.execute("delete from negative_knowledge where domain_id=%s",
                 (fx["domain_id"],))
    empty = conn.execute(
        "select pass_performed, controversies, overdue from v_controversy_state "
        " where domain_id=%s", (fx["domain_id"],)).fetchone()
    check("with everything removed the pass STILL reads as performed",
          empty[0] is True and empty[1] == 0 and empty[2] is False, str(empty))

    conn.execute("delete from domain_controversy_assessments where domain_id=%s",
                 (fx["domain_id"],))
    never = conn.execute(
        "select pass_performed, overdue from v_controversy_state where domain_id=%s",
        (fx["domain_id"],)).fetchone()
    check("and without the row it reads as OVERDUE, not as settled",
          never[0] is False and never[1] is True, str(never))

    # ==================================================================
    print("\nK12 refuses to read across nothing")

    conn.execute("delete from strategy_concepts where strategy_id in "
                 "  (select strategy_id from strategies where canonical_key like %s)",
                 (PREFIX + "%",))
    thin = with_provider(payload, lambda: KC.assess_one(conn, domain))
    check("a domain with no accumulated material is TOO_THIN, not assessed",
          thin["outcome"] == "TOO_THIN", str(thin))
    check("and no governance row was written for a pass that did not happen",
          conn.execute("select count(*) from domain_controversy_assessments "
                       " where domain_id=%s", (fx["domain_id"],)).fetchone()[0] == 0)
    for n, sid in fx["strategies"].items():
        conn.execute(
            "insert into strategy_concepts (strategy_id, concept_id, link_role, weight) "
            "select %s, concept_id, 'INDICATED_FOR', 1.0 from concepts "
            " where canonical_key=%s", (sid, f"{PREFIX}CONCEPT_{n}"))

    # ==================================================================
    print("\nK13: a gap status is a closed set, and resolution is coherent")

    expect_error(
        conn,
        "insert into knowledge_gaps (question, domain_id, status) "
        "values ('lowercase status',%s,'open')", (fx["domain_id"],),
        "a free-text gap status is refused", "ck_gap_status")

    expect_error(
        conn,
        "insert into knowledge_gaps (question, domain_id, status) "
        "values ('resolved with nothing',%s,'RESOLVED')", (fx["domain_id"],),
        "a RESOLVED gap with no resolution is refused",
        "ck_gap_resolution_coherent")

    # ==================================================================
    print("\nK13 drives the real engine")

    gap_payload = stub("RESEARCH_PRACTICE_GAPS", {
        "MODE": "GAP",
        "DOMAIN_REFERENCE": fx["domain_key"],
        "GAPS_JSON": json.dumps([
            {"question": "What dose works in vegetarian Indian adults?",
             "severity": "CRITICAL", "why_it_matters": "the core population",
             "what_would_close_it": "a trial in that population"},
            {"question": "How long does the effect persist?",
             "severity": "HIGH", "why_it_matters": "follow-up planning"},
            {"question": "What dose works in vegetarian Indian adults?",
             "severity": "LOW"},
            {"question": "An unrecognised severity", "severity": "URGENT"},
        ]),
        "ASSESSMENT_JSON": json.dumps(
            {"dimensions_examined": ["MECHANISM"], "note": "CGTEST pass"}),
    })
    gap_out = with_provider(gap_payload, lambda: KG.assess_one(conn, domain))
    check("the new gaps were written", gap_out["gaps"] == 3, str(gap_out))
    check("the repeated question was recognised, not re-raised",
          gap_out["already_recorded"] == 1, str(gap_out))

    severities = dict(conn.execute(
        "select severity::text, count(*) from knowledge_gaps "
        " where domain_id=%s group by 1", (fx["domain_id"],)).fetchall())
    check("an unrecognised severity lands at MEDIUM, not promoted",
          severities.get("MEDIUM") == 1, str(severities))
    check("CRITICAL and HIGH were preserved",
          severities.get("CRITICAL") == 1 and severities.get("HIGH") == 1,
          str(severities))

    # ==================================================================
    print("\nhard rule 11: readiness is not completion")

    ready = conn.execute(
        "select gap_assessment_complete, open_critical_gaps, foundation_ready, "
        "       dimensions_covered from v_domain_readiness where domain_id=%s",
        (fx["domain_id"],)).fetchone()
    check("the gap pass is recorded as performed", ready[0] is True, str(ready))
    check("an open CRITICAL gap keeps foundation_ready false",
          ready[1] == 1 and ready[2] is False, str(ready))

    critical = conn.execute(
        "select gap_id::text from knowledge_gaps where domain_id=%s "
        "  and severity='CRITICAL'", (fx["domain_id"],)).fetchone()[0]
    KG.resolve(conn, critical, "a trial in that population reported")
    after = conn.execute(
        "select open_critical_gaps, open_high_priority_gaps, foundation_ready "
        "  from v_domain_readiness where domain_id=%s", (fx["domain_id"],)).fetchone()
    check("resolving it clears the critical count", after[0] == 0, str(after))
    check("open non-critical gaps do NOT block readiness",
          after[1] >= 1, str(after))
    check("foundation_ready still needs the 14-dimension depth bar",
          after[2] is False, f"{after} with {ready[3]} dimensions")

    try:
        KG.resolve(conn, critical, "   ")
        check("a gap cannot be resolved with an empty resolution", False,
              "it was accepted")
    except KG.GapAssessmentFailed:
        check("a gap cannot be resolved with an empty resolution", True)

    # ==================================================================
    print("\nhard rule 3: escalation is capped and ranks by impact")

    before = conn.execute(
        "select count(*) from knowledge_gaps where domain_id=%s and status='OPEN'",
        (fx["domain_id"],)).fetchone()[0]
    taken = KG.escalate(conn, cap=1)
    check("only the cap is taken up", len(taken) == 1, str(len(taken)))
    check("and it is the most severe open gap",
          taken and taken[0]["severity"] == "HIGH", str(taken))
    still_open = conn.execute(
        "select count(*) from knowledge_gaps where domain_id=%s and status='OPEN'",
        (fx["domain_id"],)).fetchone()[0]
    check("the rest stay OPEN rather than being dropped",
          still_open == before - 1, f"{before} -> {still_open}")
    check("an escalated gap is still in the queue, as RESEARCHING",
          conn.execute("select status from v_knowledge_gap_queue "
                       " where gap_id=%s::uuid",
                       (taken[0]["gap_id"],)).fetchone()[0] == "RESEARCHING")

    # The queue's order is what the cap depends on, so it must be
    # deterministic -- driven twice through the real view.
    first = [r[0] for r in conn.execute(
        "select gap_id::text from v_knowledge_gap_queue").fetchall()]
    second = [r[0] for r in conn.execute(
        "select gap_id::text from v_knowledge_gap_queue").fetchall()]
    check("the queue's order is deterministic", first == second)

    # ==================================================================
    print("\nthe two passes are registered modes, not hard-coded ones")

    modes = {r[0] for r in conn.execute(
        "select mode from engine_handoffs where engine='E7' and active").fetchall()}
    check("CONTROVERSY and GAP are registry rows",
          {"CONTROVERSY", "GAP"} <= modes, str(sorted(modes)))
    clock = conn.execute(
        "select bool_and(not client_required) from engine_handoffs "
        " where engine='E7' and mode in ('CONTROVERSY','GAP')").fetchone()[0]
    check("both are knowledge-clock work, needing no client", clock is True)

    for mode in ("CONTROVERSY", "GAP"):
        expect_error(
            conn,
            "insert into engine_runs (engine, engine_mode, client_id, "
            " prompt_hash, status) select 'E7',%s,client_id,'x','RUNNING' "
            " from clients limit 1", (mode,),
            f"an E7 {mode} run with a client is refused before insert",
            "client")

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_controversy_gaps: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
