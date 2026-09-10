#!/usr/bin/env python3
"""Functional tests for the concept layer (migration 002).

These assert behaviour the normalization layer depends on, not merely that
tables exist. Run against a database with migrations applied:

    DATABASE_URL=... python testing/test_concept_layer.py
"""

from __future__ import annotations

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
    """Assert a statement is rejected, and for the right reason."""
    try:
        with conn.transaction():
            conn.execute(sql, params)
        check(name, False, "statement was accepted but should have been rejected")
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), f"unexpected error: {exc}")


TEST_KEYS = [
    'ADIPOSITY', 'VISCERAL_ADIPOSE_TISSUE', 'SUBCUTANEOUS_ADIPOSE_TISSUE',
    'POSTPRANDIAL_GLUCOSE', 'SKELETAL_MUSCLE_GLUCOSE_DISPOSAL', 'PROVISIONAL_THING',
]


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: suites must re-run cleanly against a used database.
    # Clear merge links first so merged_into FKs do not block deletion.
    conn.execute("update concepts set status='ACTIVE', merged_into=NULL where merged_into is not null")
    conn.execute("delete from normalization_tests")
    conn.execute("delete from normalization_cache")
    conn.execute("delete from concept_proposals")
    conn.execute("delete from strategy_concepts where concept_id in "
                 "(select concept_id from concepts where canonical_key = any(%s))", (TEST_KEYS,))
    conn.execute("delete from concepts where canonical_key = any(%s)", (TEST_KEYS,))
    conn.execute("delete from cost_events where entity_id='s-1'")
    conn.execute("delete from job_runs where entity_id='doc-1'")

    print("\nnorm_phrase")
    cases = [
        ("Post-Meal Glucose Excursion!!", "post-meal glucose excursion"),
        ("  POSTPRANDIAL   glycemia ", "postprandial glycemia"),
        ("after-meal sugar spike.", "after-meal sugar spike"),
        ("HbA1c %", "hba1c %"),
        ("omega-3 (EPA/DHA)", "omega-3 epa/dha"),
    ]
    for raw, expected in cases:
        got = conn.execute("select norm_phrase(%s)", (raw,)).fetchone()[0]
        check(f"norm_phrase({raw!r})", got == expected, f"got {got!r}, want {expected!r}")

    # ------------------------------------------------------------------
    print("\nconcept creation and key discipline")

    def add_concept(key, name, ctype, definition=None, parent=None, status="SEEDED"):
        return conn.execute(
            """insert into concepts
                 (canonical_key, canonical_name, concept_type, definition,
                  parent_concept_id, status, origin_method)
               values (%s,%s,%s,%s,%s,%s,'SEED') returning concept_id""",
            (key, name, ctype, definition, parent, status),
        ).fetchone()[0]

    adiposity = add_concept(
        "ADIPOSITY", "Adiposity", "PHYSIOLOGY", "Body fat mass and distribution."
    )
    visceral = add_concept(
        "VISCERAL_ADIPOSE_TISSUE", "Visceral adipose tissue", "PHYSIOLOGY",
        "Fat within the abdominal cavity surrounding organs. Metabolically distinct from subcutaneous fat.",
        parent=adiposity,
    )
    subcut = add_concept(
        "SUBCUTANEOUS_ADIPOSE_TISSUE", "Subcutaneous adipose tissue", "PHYSIOLOGY",
        "Fat beneath the skin. Weaker association with metabolic risk than visceral fat.",
        parent=adiposity,
    )
    ppg = add_concept(
        "POSTPRANDIAL_GLUCOSE", "Postprandial glucose", "BIOMARKER",
        "Blood glucose following a meal.",
    )
    muscle = add_concept(
        "SKELETAL_MUSCLE_GLUCOSE_DISPOSAL", "Skeletal muscle glucose disposal",
        "PHYSIOLOGY", "Insulin-mediated and contraction-mediated glucose uptake by muscle.",
    )

    check("concepts inserted", all([adiposity, visceral, subcut, ppg, muscle]))

    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type) values (%s,%s,%s)",
        ("lowercase_key", "Bad", "PHYSIOLOGY"),
        "canonical_key shape enforced",
        "ck_canonical_key_shape",
    )
    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type) values (%s,%s,%s)",
        ("POSTPRANDIAL_GLUCOSE", "Duplicate", "BIOMARKER"),
        "duplicate live canonical_key rejected",
        "uq_concepts_canonical_key",
    )
    expect_error(
        conn,
        "insert into concepts (canonical_key, canonical_name, concept_type, status) values (%s,%s,%s,%s)",
        ("ORPHAN_MERGE", "Bad merge", "PHYSIOLOGY", "MERGED"),
        "MERGED requires merged_into",
        "ck_merged_into_only_when_merged",
    )

    # ------------------------------------------------------------------
    print("\naliases: many phrases -> one concept")
    for phrase in ["after-meal sugar spike", "post meal glucose excursion",
                   "postprandial glycemia", "PP glucose"]:
        conn.execute(
            """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
               values (%s,%s,'SEED',1.0,true)""",
            (ppg, phrase),
        )

    hits = conn.execute(
        """select c.canonical_key from concept_aliases a
             join concepts c on c.concept_id = a.concept_id
            where a.alias_norm = norm_phrase(%s)""",
        ("After-Meal Sugar Spike!",),
    ).fetchall()
    check("deterministic lookup resolves formatting variants",
          [r[0] for r in hits] == ["POSTPRANDIAL_GLUCOSE"], str(hits))

    expect_error(
        conn,
        "insert into concept_aliases (concept_id, alias_text, method) values (%s,%s,'SEED')",
        (ppg, "PP  glucose"),
        "duplicate normalized alias on same concept rejected",
        "uq_alias_norm_concept",
    )

    # One phrase legitimately mapping to several concepts must be allowed.
    conn.execute(
        "insert into concept_aliases (concept_id, alias_text, method) values (%s,%s,'SEED')",
        (muscle, "glucose uptake"),
    )
    conn.execute(
        "insert into concept_aliases (concept_id, alias_text, method) values (%s,%s,'SEED')",
        (ppg, "glucose uptake"),
    )
    multi = conn.execute(
        "select count(*) from concept_aliases where alias_norm = norm_phrase('glucose uptake')"
    ).fetchone()[0]
    check("one phrase -> multiple concepts permitted", multi == 2, f"got {multi}")

    # ------------------------------------------------------------------
    print("\nconfusable pairs")
    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, note, method)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE',%s,'SEED')""",
        (visceral, subcut,
         "Both are adipose tissue and embed closely. Distinct compartments with different metabolic risk. Never merge."),
    )
    mirrored = conn.execute(
        """select count(*) from concept_relations
            where relation_type='CONFUSABLE_DO_NOT_MERGE'
              and from_concept=%s and to_concept=%s""",
        (subcut, visceral),
    ).fetchone()[0]
    check("confusable relation auto-mirrored", mirrored == 1, f"got {mirrored}")

    # Scoped to THIS pair. The claim is that the view collapses the two
    # mirrored directions into one row -- not that the database contains
    # exactly one confusable pair in total, which is a different and much
    # weaker thing to know and which stops being true the moment anything
    # else seeds a pair. K1 generates confusable pairs from sibling
    # structure by design, so a global count here would fail on a seeded
    # ontology while the behaviour under test was still correct.
    keys = ["VISCERAL_ADIPOSE_TISSUE", "SUBCUTANEOUS_ADIPOSE_TISSUE"]
    pairs = conn.execute(
        """select concept_a, concept_b from v_confusable_pairs
            where concept_a = any(%s) and concept_b = any(%s)""",
        (keys, keys)).fetchall()
    check("v_confusable_pairs deduplicates direction", len(pairs) == 1, str(pairs))

    # ------------------------------------------------------------------
    print("\nproposal governance")
    # High confidence -> auto alias, no human involved.
    conn.execute(
        """insert into concept_proposals
             (raw_phrase, context, proposed_type, source_kind, candidate_concept,
              similarity, method, impact_score, decision, resulting_concept, resolved_by, resolved_at)
           values (%s,%s,'BIOMARKER','CLAIM_EXTRACTION',%s,0.96,'SEMANTIC',3.0,
                   'AUTO_ALIAS',%s,'system',now())""",
        ("two-hour post meal sugar", "extracted from trial abstract", ppg, ppg),
    )
    # Low confidence but low impact -> logged, not escalated.
    conn.execute(
        """insert into concept_proposals
             (raw_phrase, context, proposed_type, source_kind, similarity, method,
              impact_score, decision)
           values (%s,%s,'BEHAVIOUR','CLAIM_EXTRACTION',0.44,'SEMANTIC',0.5,'LOGGED')""",
        ("mindful plate awareness", "single blog mention, no evidence link"),
    )
    # Ambiguous AND high impact -> escalated.
    conn.execute(
        """insert into concept_proposals
             (raw_phrase, context, proposed_type, source_kind, candidate_concept,
              similarity, method, impact_score, decision)
           values (%s,%s,'PHYSIOLOGY','CLAIM_EXTRACTION',%s,0.79,'SEMANTIC',9.2,'ESCALATED')""",
        ("central adiposity", "appears across 40 strategies in a core Wave-1 domain", visceral),
    )

    queue = conn.execute("select raw_phrase, impact_score from v_concept_escalation_queue").fetchall()
    check("only high-impact ambiguity reaches the queue",
          len(queue) == 1 and queue[0][0] == "central adiposity", str(queue))

    auto = conn.execute(
        "select count(*) from concept_proposals where decision in ('AUTO_ALIAS','AUTO_CREATE','AUTO_MERGE','LOGGED')"
    ).fetchone()[0]
    check("low-impact and high-confidence items resolve without a human", auto == 2, f"got {auto}")

    # ------------------------------------------------------------------
    print("\nnormalization cache")
    conn.execute(
        """insert into normalization_cache (phrase_norm, concept_ids, method, confidence)
           values (norm_phrase(%s), %s, 'LLM', 0.88)""",
        ("large post-meal glucose excursions with low muscle stimulus", [ppg, muscle]),
    )
    cached = conn.execute(
        "select concept_ids from normalization_cache where phrase_norm = norm_phrase(%s)",
        ("Large post-meal glucose excursions with low muscle stimulus!",),
    ).fetchone()
    check("cache hit on formatting variant avoids repeat LLM call",
          cached is not None and set(cached[0]) == {ppg, muscle}, str(cached))

    expect_error(
        conn,
        "insert into normalization_cache (phrase_norm, concept_ids, method) values (%s,%s,'LLM')",
        ("empty case", []),
        "empty cache entry rejected",
        "ck_cache_nonempty",
    )

    # ------------------------------------------------------------------
    print("\nactive-concept isolation")
    proposed = add_concept("PROVISIONAL_THING", "Provisional thing", "DRIVER", status="PROPOSED")
    active_keys = [r[0] for r in conn.execute("select canonical_key from v_active_concepts")]
    check("PROPOSED concepts excluded from retrieval view",
          "PROVISIONAL_THING" not in active_keys and "POSTPRANDIAL_GLUCOSE" in active_keys,
          str(sorted(active_keys)))

    conn.execute(
        "update concepts set status='MERGED', merged_into=%s where concept_id=%s",
        (ppg, proposed),
    )
    active_keys = [r[0] for r in conn.execute("select canonical_key from v_active_concepts")]
    check("MERGED concepts excluded from retrieval view",
          "PROVISIONAL_THING" not in active_keys, str(sorted(active_keys)))

    # ------------------------------------------------------------------
    print("\nauto-generated normalization tests")
    # Negative pairs come from siblings under a shared parent: exactly where
    # a semantic matcher is most likely to merge wrongly.
    conn.execute("""
        insert into normalization_tests (phrase_a, phrase_b, expect_same, rationale, generated_from)
        select a.canonical_name, b.canonical_name, false,
               'Siblings under ' || p.canonical_key || '. Semantically adjacent, clinically distinct.',
               'SIBLING_PAIR'
        from concepts a
        join concepts b on a.parent_concept_id = b.parent_concept_id
                       and a.canonical_key < b.canonical_key
        join concepts p on p.concept_id = a.parent_concept_id
        where a.status in ('SEEDED','ACTIVE') and b.status in ('SEEDED','ACTIVE')
    """)
    # Positive pairs come from aliases already attached to one concept.
    conn.execute("""
        insert into normalization_tests (phrase_a, phrase_b, expect_same, rationale, generated_from)
        select a1.alias_text, a2.alias_text, true,
               'Both aliases of ' || c.canonical_key, 'ALIAS_PAIR'
        from concept_aliases a1
        join concept_aliases a2 on a1.concept_id = a2.concept_id
                               and a1.alias_text < a2.alias_text
        join concepts c on c.concept_id = a1.concept_id
        where a1.confirmed and a2.confirmed
    """)
    neg, pos = conn.execute(
        """select count(*) filter (where not expect_same),
                  count(*) filter (where expect_same) from normalization_tests"""
    ).fetchone()
    check("negative pairs generated from sibling structure", neg >= 1, f"got {neg}")
    check("positive pairs generated from alias structure", pos >= 1, f"got {pos}")
    print(f"        generated {pos} merge cases and {neg} do-not-merge cases with no manual authoring")

    # ------------------------------------------------------------------
    print("\ncost telemetry")
    conn.execute(
        """insert into cost_events (operation, model_role, model_name, entity_type,
                                    entity_id, input_tokens, output_tokens, cost_usd, duration_ms)
           values ('MERGE_DECISION','MODEL_RESEARCH','test-model','strategy','s-1',4200,310,0.021,1840)"""
    )
    row = conn.execute(
        "select operation, calls, cost_usd from v_cost_by_operation where operation='MERGE_DECISION'"
    ).fetchone()
    check("cost event recorded and rolled up", row is not None and row[1] == 1, str(row))

    # ------------------------------------------------------------------
    print("\njob resumability")
    conn.execute(
        """insert into job_runs (job_type, entity_type, entity_id, status, checkpoint)
           values ('K09_CLAIM_EXTRACTOR','document','doc-1','RUNNING','{"chapter": 3}')"""
    )
    expect_error(
        conn,
        """insert into job_runs (job_type, entity_type, entity_id, status)
           values ('K09_CLAIM_EXTRACTOR','document','doc-1','PENDING')""",
        (),
        "duplicate active job rejected",
        "uq_job_runs_active",
    )
    conn.execute("update job_runs set status='SUCCEEDED' where entity_id='doc-1'")
    conn.execute(
        """insert into job_runs (job_type, entity_type, entity_id, status)
           values ('K09_CLAIM_EXTRACTOR','document','doc-1','PENDING')"""
    )
    check("re-queue permitted once prior run completed",
          conn.execute("select count(*) from job_runs where entity_id='doc-1'").fetchone()[0] == 2)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
