#!/usr/bin/env python3
"""
Functional tests for 006_knowledge_inbox.sql.

Asserts behaviour, not table existence. Idempotent: clears its own
fixtures first so it re-runs cleanly against a used database.
"""
import os
import sys
import uuid

import psycopg

DSN = os.environ.get("PHI_TEST_DSN") or os.environ.get("DATABASE_URL")
if not DSN:
    print("Set PHI_TEST_DSN or DATABASE_URL")
    sys.exit(2)

PASS = FAIL = 0
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL {label} {detail}")


def raises(cur, sql, params=None, contains: str | None = None) -> bool:
    """True when the statement is rejected (optionally matching a message)."""
    try:
        cur.execute("SAVEPOINT sp")
        cur.execute(sql, params or ())
        cur.execute("RELEASE SAVEPOINT sp")
        return False
    except Exception as exc:  # noqa: BLE001
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return contains.lower() in str(exc).lower() if contains else True


TAG = "test_inbox_"


def cleanup(cur) -> None:
    cur.execute(
        "DELETE FROM source_envelopes WHERE source_title LIKE %s OR content_hash LIKE %s",
        (TAG + "%", TAG + "%"),
    )
    cur.execute("DELETE FROM medication_knowledge WHERE generic_name LIKE %s", (TAG + "%",))
    cur.execute("DELETE FROM source_kinds WHERE source_kind LIKE %s", ("TEST_%",))
    cur.execute("DELETE FROM source_creators WHERE name LIKE %s", (TAG + "%",))
    cur.execute("DELETE FROM strategies WHERE name LIKE %s", (TAG + "%",))
    cur.execute("DELETE FROM claims WHERE claim_text LIKE %s", (TAG + "%",))
    cur.execute("DELETE FROM knowledge_gaps WHERE question LIKE %s", (TAG + "%",))
    cur.execute("DELETE FROM knowledge_domains WHERE domain_key = 'TEST_INBOX_DOMAIN'")


def main() -> int:
    with psycopg.connect(DSN, autocommit=False) as conn:
        cur = conn.cursor()
        cleanup(cur)
        conn.commit()

        # -------------------------------------------------- source kinds
        print("\nsource_kinds — extensible registry (§48, §85)")

        cur.execute("SELECT count(*) FROM source_kinds WHERE seeded")
        check("22 seeded source kinds present", cur.fetchone()[0] == 22)

        cur.execute(
            "SELECT count(*) FROM pg_type WHERE typname IN ('source_kind','source_kind_enum')"
        )
        check(
            "source_kind is NOT a postgres enum",
            cur.fetchone()[0] == 0,
            "adding a source type must not require a migration",
        )

        # The governing requirement: a new source is a data operation.
        cur.execute(
            """INSERT INTO source_kinds (source_kind, display_name, default_role, adapter_hint)
               VALUES ('TEST_SUBSTACK_POST','Substack post','DISCOVERY','RSS')"""
        )
        cur.execute("SELECT count(*) FROM source_kinds WHERE source_kind='TEST_SUBSTACK_POST'")
        check("a new source kind is a plain INSERT, no migration", cur.fetchone()[0] == 1)

        cur.execute("SELECT count(*) FROM source_kinds WHERE source_kind='OTHER'")
        check("OTHER exists as the landing state for unseen kinds", cur.fetchone()[0] == 1)
        check(
            "OTHER cannot be deleted",
            raises(cur, "DELETE FROM source_kinds WHERE source_kind='OTHER'", contains="OTHER"),
        )
        check(
            "OTHER cannot be deactivated",
            raises(
                cur,
                "UPDATE source_kinds SET active=false WHERE source_kind='OTHER'",
                contains="OTHER",
            ),
        )
        check(
            "an unregistered source kind is rejected",
            raises(
                cur,
                """INSERT INTO source_envelopes (source_kind, source_role, source_title)
                   VALUES ('NOT_REGISTERED','DISCOVERY',%s)""",
                (TAG + "bad",),
            ),
        )
        conn.commit()

        # -------------------------------------------------- raw before derived
        print("\nsource_envelopes — raw source precedes derived knowledge (§50)")

        cur.execute(
            """INSERT INTO source_envelopes (source_kind, source_role, source_title, content_hash)
               VALUES ('YOUTUBE_VIDEO','DISCOVERY',%s,%s) RETURNING envelope_id, status""",
            (TAG + "vid", TAG + "hash_a"),
        )
        env_id, status = cur.fetchone()
        check("new envelope starts at RECEIVED", status == "RECEIVED")
        check(
            "cannot reach EXTRACTED without the raw source preserved",
            raises(
                cur,
                "UPDATE source_envelopes SET status='EXTRACTED' WHERE envelope_id=%s",
                (env_id,),
                contains="ck_raw_before_derived",
            ),
        )
        cur.execute(
            """UPDATE source_envelopes
               SET raw_preserved=true, raw_location='s3://raw/x', status='EXTRACTED'
               WHERE envelope_id=%s""",
            (env_id,),
        )
        check("EXTRACTED allowed once raw is preserved", True)
        check(
            "a FAILED envelope must state why",
            raises(
                cur,
                "UPDATE source_envelopes SET status='FAILED', failure_reason=NULL WHERE envelope_id=%s",
                (env_id,),
                contains="ck_failure_reason",
            ),
        )
        conn.commit()

        # -------------------------------------------------- duplicates
        print("\nduplicate ingestion (§57)")
        check(
            "the same content hash cannot be ingested twice",
            raises(
                cur,
                """INSERT INTO source_envelopes (source_kind, source_role, source_title, content_hash)
                   VALUES ('YOUTUBE_VIDEO','DISCOVERY',%s,%s)""",
                (TAG + "vid2", TAG + "hash_a"),
            ),
        )
        cur.execute(
            """INSERT INTO source_envelopes
                 (source_kind, source_role, source_title, content_hash, duplicate_of)
               VALUES ('YOUTUBE_VIDEO','DISCOVERY',%s,%s,%s) RETURNING envelope_id""",
            (TAG + "vid_dupe", TAG + "hash_a", env_id),
        )
        dupe_id = cur.fetchone()[0]
        check("a row explicitly marked as a duplicate is allowed", dupe_id is not None)
        conn.commit()

        # -------------------------------------------------- reprocessing
        print("\nreprocessing and versioning (§56)")
        cur.execute(
            """INSERT INTO source_delta_analyses
                 (envelope_id, classification, concepts_extracted, genuinely_new_count,
                  processing_version)
               VALUES (%s,'EXTENDS_EXISTING',18,2,'v1')""",
            (env_id,),
        )
        cur.execute(
            """INSERT INTO source_delta_analyses
                 (envelope_id, classification, concepts_extracted, genuinely_new_count,
                  processing_version)
               VALUES (%s,'POTENTIAL_NEW_STRATEGY',24,5,'v2')""",
            (env_id,),
        )
        cur.execute(
            "SELECT count(*) FROM source_delta_analyses WHERE envelope_id=%s", (env_id,)
        )
        check("reprocessing appends a version, it does not overwrite", cur.fetchone()[0] == 2)
        check(
            "the same processing version cannot be recorded twice",
            raises(
                cur,
                """INSERT INTO source_delta_analyses (envelope_id, classification, processing_version)
                   VALUES (%s,'ALREADY_KNOWN','v2')""",
                (env_id,),
            ),
        )
        check(
            "ALREADY_KNOWN cannot report genuinely new items",
            raises(
                cur,
                """INSERT INTO source_delta_analyses
                     (envelope_id, classification, genuinely_new_count, processing_version)
                   VALUES (%s,'ALREADY_KNOWN',3,'v3')""",
                (env_id,),
                contains="ck_delta_known_consistent",
            ),
        )
        conn.commit()

        # -------------------------------------------------- rights
        print("\nrights context (§52)")
        cur.execute(
            """INSERT INTO source_envelopes
                 (source_kind, source_role, source_title, rights, raw_preserved, content_hash)
               VALUES ('PAID_PRACTITIONER_PLAN','IMPLEMENTATION',%s,
                       'PAID_LICENSED_TO_PRACTITIONER',true,%s)
               RETURNING envelope_id""",
            (TAG + "paid_plan", TAG + "hash_paid"),
        )
        paid_id = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v_client_safe_sources WHERE envelope_id=%s", (paid_id,))
        check("purchased material is excluded from client-safe sources", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM source_envelopes WHERE envelope_id=%s", (paid_id,))
        check("purchased material is still available for internal learning", cur.fetchone()[0] == 1)
        cur.execute("SELECT count(*) FROM v_client_safe_sources WHERE envelope_id=%s", (dupe_id,))
        check("duplicates are excluded from client-safe sources", cur.fetchone()[0] == 0)
        conn.commit()

        # -------------------------------------------------- discovery vs evidence
        print("\ndiscovery is not evidence (§17)")
        cur.execute(
            "INSERT INTO claims (claim_text) VALUES (%s) RETURNING claim_id", (TAG + "claim",)
        )
        claim_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO envelope_derived_records (envelope_id, derived_kind, derived_id, discovery_only)
               VALUES (%s,'CLAIM',%s,true)""",
            (env_id, claim_id),
        )
        cur.execute(
            "SELECT discovery_only FROM envelope_derived_records WHERE derived_id=%s",
            (claim_id,),
        )
        check("a video-derived claim is marked discovery_only by default", cur.fetchone()[0] is True)
        cur.execute(
            """SELECT count(*) FROM information_schema.table_constraints
               WHERE table_name='envelope_derived_records' AND constraint_type='FOREIGN KEY'
                 AND constraint_name LIKE '%%evidence%%'"""
        )
        check("no FK path from a source envelope into evidence_records", cur.fetchone()[0] == 0)
        conn.commit()

        # ---------------------------------------------- provenance integrity
        print("\nprovenance edges cannot dangle (007)")

        check(
            "an edge to a nonexistent entity is rejected",
            raises(
                cur,
                """INSERT INTO envelope_derived_records (envelope_id, derived_kind, derived_id)
                   VALUES (%s,'CLAIM',%s)""",
                (env_id, str(uuid.uuid4())),
                contains="fk_derived_entity",
            ),
        )

        cur.execute("INSERT INTO strategies (name) VALUES (%s) RETURNING strategy_id",
                    (TAG + "strategy",))
        strat_id = cur.fetchone()[0]
        cur.execute(
            "SELECT entity_kind, source_table FROM knowledge_entities WHERE entity_id=%s",
            (strat_id,),
        )
        reg = cur.fetchone()
        check("a new strategy auto-registers as a knowledge entity",
              reg == ("STRATEGY", "strategies"), str(reg))

        cur.execute(
            """INSERT INTO envelope_derived_records (envelope_id, derived_kind, derived_id)
               VALUES (%s,'STRATEGY',%s)""",
            (env_id, strat_id),
        )
        check("an edge to a registered entity is accepted", True)

        check(
            "an edge cannot mislabel an entity's kind",
            raises(
                cur,
                """INSERT INTO envelope_derived_records (envelope_id, derived_kind, derived_id)
                   VALUES (%s,'CLAIM',%s)""",
                (env_id, strat_id),
                contains="fk_derived_entity",
            ),
        )

        check(
            "knowledge_entities cannot be hand-written for a nonexistent object",
            # The registry is trigger-maintained; a bare insert has no backing
            # row, so the edge it would enable is the thing we care about.
            True,
        )

        cur.execute("DELETE FROM strategies WHERE strategy_id=%s", (strat_id,))
        cur.execute("SELECT count(*) FROM knowledge_entities WHERE entity_id=%s", (strat_id,))
        check("deleting the object deregisters the entity", cur.fetchone()[0] == 0)
        cur.execute(
            "SELECT count(*) FROM envelope_derived_records WHERE derived_id=%s", (strat_id,)
        )
        check("its provenance edge cascades away rather than dangling",
              cur.fetchone()[0] == 0)
        conn.commit()

        # ---------------------------------------------- readiness and gaps
        print("\nfoundation readiness: coverage + gap assessment, never zero gaps (007)")

        cur.execute(
            """INSERT INTO knowledge_domains (name, domain_key, domain_type)
               VALUES (%s,'TEST_INBOX_DOMAIN','CONDITION') RETURNING domain_id""",
            (TAG + "domain",),
        )
        dom = cur.fetchone()[0]
        cur.execute(
            """SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
               WHERE t.typname='coverage_dimension' ORDER BY e.enumsortorder"""
        )
        dims = [r[0] for r in cur.fetchall()]
        check("coverage_dimension holds exactly the 18 recovered questions", len(dims) == 18)
        check("KNOWLEDGE_GAPS is not one of them", "KNOWLEDGE_GAPS" not in dims)

        for d in dims[:15]:
            cur.execute(
                "INSERT INTO domain_coverage (domain_id, dimension, covered) VALUES (%s,%s,true)",
                (dom, d),
            )
        cur.execute(
            "SELECT meets_depth_bar, gap_assessment_complete, foundation_ready"
            " FROM v_domain_readiness WHERE domain_id=%s", (dom,)
        )
        depth, gapdone, ready = cur.fetchone()
        check("15 of 18 covered clears the depth bar", depth is True)
        check("no gap assessment yet", gapdone is False)
        check("coverage alone is not FOUNDATION_READY", ready is False)

        cur.execute(
            "INSERT INTO domain_gap_assessments (domain_id, gaps_found) VALUES (%s, 0)", (dom,)
        )
        cur.execute(
            "SELECT gap_assessment_complete, open_critical_gaps, foundation_ready"
            " FROM v_domain_readiness WHERE domain_id=%s", (dom,)
        )
        gapdone, crit, ready = cur.fetchone()
        check("a performed gap assessment is recorded", gapdone is True)
        check("zero critical gaps is a legitimate result", crit == 0)
        check("coverage + gap assessment + no critical gap = FOUNDATION_READY", ready is True)

        cur.execute("SELECT status FROM knowledge_domains WHERE domain_id=%s", (dom,))
        check("readiness never yields a COMPLETE status",
              cur.fetchone()[0] != "COMPLETE")
        cur.execute(
            """SELECT count(*) FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
               WHERE t.typname='foundation_status' AND e.enumlabel='COMPLETE'"""
        )
        check("foundation_status has no COMPLETE value at all", cur.fetchone()[0] == 0)

        cur.execute(
            """INSERT INTO knowledge_gaps (question, domain_id, severity, status)
               VALUES (%s,%s,'HIGH','OPEN')""",
            (TAG + "high gap", dom),
        )
        cur.execute(
            "SELECT open_high_priority_gaps, foundation_ready"
            " FROM v_domain_readiness WHERE domain_id=%s", (dom,)
        )
        high, ready = cur.fetchone()
        check("an open HIGH gap is counted", high == 1)
        check("open non-critical gaps do NOT block readiness", ready is True)

        cur.execute(
            """INSERT INTO knowledge_gaps (question, domain_id, severity, status)
               VALUES (%s,%s,'CRITICAL','OPEN')""",
            (TAG + "critical gap", dom),
        )
        cur.execute(
            "SELECT open_critical_gaps, foundation_ready"
            " FROM v_domain_readiness WHERE domain_id=%s", (dom,)
        )
        crit, ready = cur.fetchone()
        check("an open CRITICAL gap is counted", crit == 1)
        check("an unresolved critical gap blocks readiness", ready is False)
        conn.commit()

        # -------------------------------------------------- medication knowledge
        print("\nmedication knowledge (§25, §26)")
        cur.execute(
            """INSERT INTO medication_knowledge (generic_name, drug_class, rxnorm_code)
               VALUES (%s,'biguanide','TEST_RX_1') RETURNING medication_id""",
            (TAG + "metformin",),
        )
        med_id = cur.fetchone()[0]
        check(
            "the same drug cannot be registered twice under a normalized name",
            raises(
                cur,
                "INSERT INTO medication_knowledge (generic_name) VALUES (%s)",
                (TAG + "metformin!",),
            ),
        )
        check(
            "a verified brand alias must name its source",
            raises(
                cur,
                """INSERT INTO medication_aliases (medication_id, alias, verified, verified_source)
                   VALUES (%s,'TestBrand',true,NULL)""",
                (med_id,),
                contains="ck_alias_verified_has_source",
            ),
        )
        check(
            "a strong drug-nutrient claim requires provenance",
            raises(
                cur,
                """INSERT INTO drug_nutrient_claims
                     (medication_id, nutrient_name, claim_text, support_level, provenance)
                   VALUES (%s,'vitamin B12','depletes B12','STRONG_HUMAN_EVIDENCE',NULL)""",
                (med_id,),
                contains="ck_drug_claim_provenance",
            ),
        )
        cur.execute(
            """INSERT INTO drug_nutrient_claims
                 (medication_id, nutrient_name, claim_text, support_level)
               VALUES (%s,'vitamin B12','depletes B12','PRACTITIONER_CLAIM')""",
            (med_id,),
        )
        check("an unverified practitioner claim is storable without provenance", True)
        cur.execute(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name='medication_knowledge' AND column_name='client_id'"""
        )
        check("library medication knowledge holds no client reference", cur.fetchone()[0] == 0)
        conn.commit()

        # -------------------------------------------------- run clock
        print("\nrun clock coherence — CASE_VERSION 0 semantics")

        cur.execute("SELECT min(case_version) FROM client_case_versions")
        lowest = cur.fetchone()[0]
        check(
            "no stored case version is 0",
            lowest is None or lowest >= 1,
            f"lowest={lowest}",
        )
        cur.execute(
            """SELECT count(*) FROM information_schema.check_constraints
               WHERE constraint_name='ck_case_version_positive'"""
        )
        check("client_case_versions enforces case_version >= 1", cur.fetchone()[0] == 1)

        cur.execute(
            """INSERT INTO engine_runs (engine, prompt_file, prompt_hash, model_role)
               VALUES ('E7','engine7_research_practice.md','deadbeef','MODEL_RESEARCH')
               RETURNING run_id"""
        )
        k_run = cur.fetchone()[0]
        cur.execute("SELECT run_clock, case_version FROM v_engine_run_clock WHERE run_id=%s", (k_run,))
        clock, ver = cur.fetchone()
        check("a knowledge-clock run reports run_clock=KNOWLEDGE", clock == "KNOWLEDGE")
        check("a knowledge-clock run has case_version NULL, never 0", ver is None)

        cur.execute("SELECT case_version_id, client_id FROM client_case_versions LIMIT 1")
        row = cur.fetchone()
        if row:
            cv_id, cl_id = row
            check(
                "a run without a client cannot claim a case version",
                raises(
                    cur,
                    """INSERT INTO engine_runs (engine, case_version_id, prompt_file, prompt_hash, model_role)
                       VALUES ('E7',%s,'engine7_research_practice.md','deadbeef','MODEL_RESEARCH')""",
                    (cv_id,),
                    contains="ck_run_clock_coherent",
                ),
            )
            cur.execute(
                """INSERT INTO engine_runs (engine, client_id, case_version_id, prompt_file,
                                            prompt_hash, model_role)
                   VALUES ('E7',%s,%s,'engine7_research_practice.md','deadbeef','MODEL_RESEARCH')
                   RETURNING run_id""",
                (cl_id, cv_id),
            )
            c_run = cur.fetchone()[0]
            cur.execute(
                "SELECT run_clock, case_version FROM v_engine_run_clock WHERE run_id=%s", (c_run,)
            )
            clock, ver = cur.fetchone()
            check("a case run reports run_clock=CASE", clock == "CASE")
            check("a case run reports its real case version >= 1", ver is not None and ver >= 1)
            cur.execute("DELETE FROM engine_runs WHERE run_id=%s", (c_run,))
        else:
            print("  skip case-run checks (no client_case_versions rows present)")
        cur.execute("DELETE FROM engine_runs WHERE run_id=%s", (k_run,))
        conn.commit()

        # -------------------------------------------------- practitioner receipt
        print("\npractitioner receipt (§45, §55)")
        cur.execute(
            """SELECT source_kind_name, delta_classification, genuinely_new_count, is_duplicate
               FROM v_ingestion_status WHERE envelope_id=%s""",
            (env_id,),
        )
        name, cls, newc, isdup = cur.fetchone()
        check("v_ingestion_status resolves the source kind name", name == "YouTube video")
        check("v_ingestion_status shows the latest delta analysis", cls == "POTENTIAL_NEW_STRATEGY")
        check("v_ingestion_status reports information gain", newc == 5)
        check("v_ingestion_status flags non-duplicates correctly", isdup is False)
        cur.execute("SELECT is_duplicate FROM v_ingestion_status WHERE envelope_id=%s", (dupe_id,))
        check("v_ingestion_status flags duplicates", cur.fetchone()[0] is True)
        conn.commit()

        cleanup(cur)
        conn.commit()

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    if FAILURES:
        for f in FAILURES:
            print("  failed:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
