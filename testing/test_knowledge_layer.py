#!/usr/bin/env python3
"""Functional tests for the knowledge layer (migration 003).

The central assertion is the cross-condition retrieval test: a strategy
filed under one condition must be reachable through the physiology it
targets. That is the difference between a knowledge library and three
disease folders.
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
    try:
        with conn.transaction():
            conn.execute(sql, params)
        check(name, False, "accepted but should have been rejected")
    except psycopg.Error as exc:
        check(name, fragment.lower() in str(exc).lower(), f"unexpected: {exc}")


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: suites must re-run cleanly against a used database.
    conn.execute("delete from knowledge_domains where domain_key='INSULIN_RESISTANCE'")
    conn.execute(
        "delete from strategies where canonical_key = any(%s) or name = any(%s)",
        (['PROGRESSIVE_RESISTANCE_TRAINING', 'MEAL_SEQUENCING_FIBRE_PROTEIN_FIRST',
          'REFINED_CARBOHYDRATE_REDUCTION'],
         ['Speculative idea', 'Orphan strategy', 'Unattributed model output']))
    conn.execute("delete from source_items where doi in ('10.1000/example','10.1000/heldout')"
                 " or url='https://example.com/ep1'")
    conn.execute("delete from knowledge_sources where base_identifier in"
                 " ('podcast:example','journal:example')")
    conn.execute("delete from source_creators where name='Example Coach'")
    conn.execute("delete from foods where lower(canonical_name)='indian gooseberry'")

    # Concepts from 002. Reuse if the concept-layer test already ran.
    def concept(key, name, ctype, definition=None, parent=None):
        row = conn.execute(
            "select concept_id from concepts where canonical_key=%s", (key,)
        ).fetchone()
        if row:
            return row[0]
        return conn.execute(
            """insert into concepts (canonical_key, canonical_name, concept_type,
                                     definition, parent_concept_id, status, origin_method)
               values (%s,%s,%s,%s,%s,'SEEDED','SEED') returning concept_id""",
            (key, name, ctype, definition, parent),
        ).fetchone()[0]

    insulin_sens = concept("INSULIN_SENSITIVITY", "Insulin sensitivity", "PHYSIOLOGY")
    hepatic_fat  = concept("HEPATIC_FAT", "Hepatic fat", "PHYSIOLOGY")
    ppg          = concept("POSTPRANDIAL_GLUCOSE", "Postprandial glucose", "BIOMARKER")
    triglyc      = concept("SERUM_TRIGLYCERIDES", "Serum triglycerides", "BIOMARKER")
    muscle       = concept("SKELETAL_MUSCLE_GLUCOSE_DISPOSAL",
                           "Skeletal muscle glucose disposal", "PHYSIOLOGY")
    pcos         = concept("PCOS", "Polycystic ovary syndrome", "CONDITION")
    masld        = concept("MASLD", "Metabolic dysfunction-associated steatotic liver disease", "CONDITION")
    prediab      = concept("PREDIABETES", "Prediabetes", "CONDITION")
    vegetarian   = concept("VEGETARIAN_DIET_PATTERN", "Vegetarian diet pattern", "POPULATION")

    print("\ndomains")
    dom = conn.execute(
        """insert into knowledge_domains (name, domain_key, domain_type, is_core_domain, wave1_priority)
           values ('Insulin resistance','INSULIN_RESISTANCE','PHYSIOLOGY',true,100)
           returning domain_id"""
    ).fetchone()[0]
    check("core domain created", dom is not None)

    expect_error(
        conn,
        "insert into knowledge_domains (name, domain_key, domain_type) values (%s,%s,%s)",
        ("Bad", "lower_case", "PHYSIOLOGY"),
        "domain_key shape enforced",
        "ck_domain_key",
    )

    # 18 coverage dimensions - one per question recovered from Engine 7
    # section 35. Gap assessment is governance and lives in
    # domain_gap_assessments, not here. 15 covered -> meets the depth bar.
    dims = [r[0] for r in conn.execute(
        "select unnest(enum_range(null::coverage_dimension))::text")]
    check("18 coverage dimensions defined", len(dims) == 18, f"got {len(dims)}")
    check("gap assessment is not a coverage dimension",
          not any("GAP" in d for d in dims), str([d for d in dims if "GAP" in d]))
    for i, d in enumerate(dims):
        conn.execute(
            "insert into domain_coverage (domain_id, dimension, covered) values (%s,%s,%s)",
            (dom, d, i < 15),
        )
    row = conn.execute(
        "select dimensions_covered, meets_depth_bar, missing_dimensions from v_domain_readiness where domain_id=%s",
        (dom,),
    ).fetchone()
    check("readiness computed from coverage rows", row[0] == 15 and row[1] is True, str(row))
    check("uncovered dimensions reported", len(row[2]) == 3, str(row[2]))

    # Coverage alone is not readiness: a gap pass must have been run.
    row = conn.execute(
        "select gap_assessment_complete, foundation_ready from v_domain_readiness where domain_id=%s",
        (dom,),
    ).fetchone()
    check("coverage without a gap assessment is not FOUNDATION_READY",
          row[0] is False and row[1] is False, str(row))

    print("\nprovenance is database-enforced")
    expect_error(
        conn,
        """insert into strategies (name, knowledge_status) values (%s,'VERIFIED')""",
        ("Unattributed model output",),
        "VERIFIED without provenance rejected",
        "ck_provenance_required",
    )
    cand = conn.execute(
        """insert into strategies (name, knowledge_status)
           values ('Speculative idea','AI_DISCOVERED_CANDIDATE') returning strategy_id"""
    ).fetchone()[0]
    check("AI candidate permitted without provenance", cand is not None)

    print("\nstrategies and the concept join")

    def strategy(key, name, summary, mechanism):
        return conn.execute(
            """insert into strategies
                 (canonical_key, name, summary, mechanism, knowledge_status,
                  provenance_note, evidence_confidence, outcomes_to_track)
               values (%s,%s,%s,%s,'EVIDENCE_LINKED',%s,'MODERATE',%s)
               returning strategy_id""",
            (key, name, summary, mechanism,
             "Extracted from indexed trial; evidence linked.",
             "fasting glucose, waist, ALT"),
        ).fetchone()[0]

    # Deliberately filed with a PCOS indication only. Cross-condition
    # retrieval must still surface it for a MASLD case via physiology.
    s_resist = strategy(
        "PROGRESSIVE_RESISTANCE_TRAINING", "Progressive resistance training",
        "Structured resistance work increasing load over time.",
        "Increases muscle mass and contraction-mediated glucose uptake.")
    s_seq = strategy(
        "MEAL_SEQUENCING_FIBRE_PROTEIN_FIRST", "Meal sequencing: fibre and protein first",
        "Consume viscous fibre and protein before starch within a meal.",
        "Slows gastric emptying and blunts the postprandial glucose rise.")
    s_carb = strategy(
        "REFINED_CARBOHYDRATE_REDUCTION", "Refined carbohydrate reduction",
        "Reduce refined starch load, especially in the evening meal.",
        "Lowers de novo lipogenesis substrate and postprandial excursion.")

    links = [
        (s_resist, muscle, "TARGETS"), (s_resist, insulin_sens, "TARGETS"),
        (s_resist, ppg, "TARGETS"), (s_resist, pcos, "INDICATED_FOR"),
        (s_seq, ppg, "TARGETS"), (s_seq, insulin_sens, "TARGETS"),
        (s_seq, prediab, "INDICATED_FOR"), (s_seq, vegetarian, "POPULATION"),
        (s_carb, hepatic_fat, "TARGETS"), (s_carb, triglyc, "TARGETS"),
        (s_carb, ppg, "TARGETS"), (s_carb, masld, "INDICATED_FOR"),
    ]
    for sid, cid, role in links:
        conn.execute(
            "insert into strategy_concepts (strategy_id, concept_id, link_role) values (%s,%s,%s)",
            (sid, cid, role),
        )
    check("strategy-concept links created", len(links) == 12)

    # ------------------------------------------------------------------
    print("\ncross-condition retrieval (evaluation layer C)")

    # Diagnosis-only retrieval: what a disease-folder library would return
    # for a MASLD client.
    by_disease = {r[0] for r in conn.execute(
        """select s.canonical_key from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
            where sc.concept_id = %s and sc.link_role = 'INDICATED_FOR'""",
        (masld,),
    )}
    check("diagnosis-only retrieval is narrow (this is the failure mode)",
          by_disease == {"REFINED_CARBOHYDRATE_REDUCTION"}, str(by_disease))

    # Concept-based retrieval for the same client: vegetarian woman with
    # PCOS + MASLD + prediabetes, high triglycerides, low muscle activity.
    # Retrieval runs on the underlying targets, not the diagnosis labels.
    targets = [insulin_sens, hepatic_fat, ppg, triglyc, muscle]
    by_physiology = {r[0]: r[1] for r in conn.execute(
        """select s.canonical_key, count(*) as hits
             from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
            where sc.concept_id = any(%s)
              and sc.link_role = 'TARGETS'
              and s.knowledge_status <> 'AI_DISCOVERED_CANDIDATE'
            group by s.canonical_key
            order by hits desc""",
        (targets,),
    )}
    check("concept retrieval crosses conditions",
          set(by_physiology) == {"PROGRESSIVE_RESISTANCE_TRAINING",
                                 "MEAL_SEQUENCING_FIBRE_PROTEIN_FIRST",
                                 "REFINED_CARBOHYDRATE_REDUCTION"},
          str(by_physiology))
    check("resistance training surfaces for a MASLD case despite PCOS-only indication",
          "PROGRESSIVE_RESISTANCE_TRAINING" in by_physiology
          and "PROGRESSIVE_RESISTANCE_TRAINING" not in by_disease)
    print(f"        diagnosis-only: {len(by_disease)} strategy   "
          f"concept-based: {len(by_physiology)} strategies")

    print("\nsource roles: discovery is not evidence")
    creator = conn.execute(
        """insert into source_creators (name, creator_type, discovery_reason)
           values ('Example Coach','COACH','Repeatedly proposes a specific implementation method')
           returning creator_id"""
    ).fetchone()[0]
    podcast = conn.execute(
        """insert into knowledge_sources (source_name, source_type, source_roles, creator_id, base_identifier)
           values ('Example Podcast','PODCAST','{DISCOVERY,IMPLEMENTATION}',%s,'podcast:example')
           returning source_id""",
        (creator,),
    ).fetchone()[0]
    journal = conn.execute(
        """insert into knowledge_sources (source_name, source_type, source_roles, base_identifier)
           values ('Example Journal','JOURNAL','{EVIDENCE}','journal:example') returning source_id"""
    ).fetchone()[0]

    # Scoped to the two rows this block just created. It used to be an
    # exact set over the WHOLE table, which held only while nothing else
    # in the database had ever carried the EVIDENCE role -- and K10
    # legitimately registers one ('Independent evidence (K10)') the first
    # time it records an identifiable study, in production as well as in
    # test_knowledge_factory. An assertion that depends on the rest of the
    # database being empty is not testing what it says it is.
    ev_sources = {r[0] for r in conn.execute(
        "select source_name from knowledge_sources "
        " where 'EVIDENCE' = any(source_roles) and source_id = any(%s::uuid[])",
        ([str(podcast), str(journal)],))}
    check("podcast excluded from evidence-role sources",
          ev_sources == {"Example Journal"}, str(ev_sources))

    expect_error(
        conn,
        "insert into knowledge_sources (source_name, source_type, source_roles) values (%s,%s,%s)",
        ("Roleless", "BLOG", []),
        "source without a role rejected",
        "ck_source_roles_nonempty",
    )

    print("\ndeduplication signals")
    item = conn.execute(
        """insert into source_items (source_id, title, doi, ingestion_status)
           values (%s,'A trial','10.1000/example','EXTRACTED') returning item_id""",
        (journal,),
    ).fetchone()[0]
    expect_error(
        conn,
        "insert into source_items (source_id, title, doi) values (%s,%s,%s)",
        (journal, "Same trial, syndicated", "10.1000/EXAMPLE"),
        "same DOI (case-insensitive) rejected",
        "uq_item_doi",
    )
    conn.execute(
        """insert into source_items (source_id, title, url, ingestion_status)
           values (%s,'Podcast episode 1','https://example.com/ep1','EXTRACTED')""",
        (podcast,),
    )
    expect_error(
        conn,
        "insert into source_items (source_id, title, url) values (%s,%s,%s)",
        (podcast, "Duplicate discovery of same episode", "https://example.com/ep1"),
        "same canonical URL rejected",
        "uq_item_url",
    )

    print("\nheld-out sources (evaluation layer B)")
    held = conn.execute(
        """insert into source_items (source_id, title, doi, ingestion_status, held_out, held_out_batch)
           values (%s,'Held-out trial','10.1000/heldout','EXTRACTED',true,'wave1_holdout_a')
           returning item_id""",
        (journal,),
    ).fetchone()[0]
    synth_pool = conn.execute(
        "select count(*) from source_items where not held_out and ingestion_status='EXTRACTED'"
    ).fetchone()[0]
    holdout = conn.execute(
        "select count(*) from source_items where held_out_batch='wave1_holdout_a'"
    ).fetchone()[0]
    check("held-out items separable from the synthesis pool",
          holdout == 1 and synth_pool >= 2, f"holdout={holdout} pool={synth_pool}")

    print("\nevidence quality control")
    expect_error(
        conn,
        "insert into evidence_records (design, publication_year) values ('RCT', %s)",
        (2999,),
        "impossible publication year rejected",
        "ck_pub_year",
    )
    ev = conn.execute(
        """insert into evidence_records (item_id, citation, publication_year, design,
                                          population, sample_size, results_summary)
           values (%s,'Example 2023',2023,'RCT','Adults with prediabetes',120,'Reduced postprandial glucose')
           returning evidence_id""",
        (item,),
    ).fetchone()[0]
    conn.execute(
        "insert into strategy_evidence (strategy_id, evidence_id, relationship) values (%s,%s,'SUPPORTS')",
        (s_seq, ev),
    )
    # The same evidence can also limit a different strategy.
    conn.execute(
        "insert into strategy_evidence (strategy_id, evidence_id, relationship) values (%s,%s,'LIMITS')",
        (s_carb, ev),
    )
    check("one evidence record can support one strategy and limit another",
          conn.execute("select count(*) from strategy_evidence").fetchone()[0] == 2)

    print("\npractice experience stays separate from evidence")
    expect_error(
        conn,
        """insert into practice_strategy_outcomes (strategy_id, cohort_criteria, n_clients)
           values (%s,'Vegetarian women, central adiposity',3)""",
        (s_seq,),
        "cohort below minimum rejected",
        "ck_min_cohort",
    )
    conn.execute(
        """insert into practice_strategy_outcomes
             (strategy_id, cohort_criteria, n_clients, adherence_summary, outcome_summary)
           values (%s,'Vegetarian women, central adiposity',18,'High','Consistent waist reduction')""",
        (s_seq,),
    )
    fks = conn.execute("""
        select count(*) from information_schema.table_constraints tc
          join information_schema.constraint_column_usage ccu
            on tc.constraint_name = ccu.constraint_name
         where tc.table_name = 'practice_strategy_outcomes'
           and tc.constraint_type = 'FOREIGN KEY'
           and ccu.table_name = 'evidence_records'
    """).fetchone()[0]
    check("no structural path merges practice data into evidence", fks == 0, f"found {fks} FKs")

    print("\nquality control sweep")
    issues = {r[0] for r in conn.execute("select distinct issue from v_quality_issues")}
    check("candidate strategy without concept link is not flagged",
          "strategy_without_concept_link" not in issues, str(issues))
    orphan = conn.execute(
        """insert into strategies (name, knowledge_status, provenance_note, outcomes_to_track)
           values ('Orphan strategy','VERIFIED','From a source','waist') returning strategy_id"""
    ).fetchone()[0]
    issues = {r[0] for r in conn.execute("select distinct issue from v_quality_issues")}
    check("verified strategy without concept link is flagged",
          "strategy_without_concept_link" in issues, str(issues))
    check("verified strategy without evidence is flagged",
          "strategy_without_evidence" in issues, str(issues))

    print("\nknowledge floors instrumentation")
    floors = {r[0]: r[1] for r in conn.execute("select metric, current from v_knowledge_floors")}
    check("floors report live counts", floors.get("strategy_cards", 0) >= 3, str(floors))
    check("all eight floors tracked", len(floors) == 8, str(sorted(floors)))

    print("\nnon-silent knowledge change")
    conn.execute(
        """insert into knowledge_updates (entity_type, entity_id, old_state, new_state, reason, triggered_by)
           values ('strategy',%s,'{"evidence_confidence":"MODERATE"}','{"evidence_confidence":"LIMITED"}',
                   'New trial failed to replicate the effect','K15_KNOWLEDGE_REVIEW')""",
        (s_carb,),
    )
    check("evidence change recorded with prior state and reason",
          conn.execute(
              "select count(*) from knowledge_updates where entity_id=%s", (s_carb,)
          ).fetchone()[0] == 1)

    print("\nseasonality does not overclaim")
    food = conn.execute(
        """insert into foods (canonical_name, regional_names, food_type)
           values ('Indian gooseberry', array['amla','nellikai','avla'], 'fruit') returning food_id"""
    ).fetchone()[0]
    conn.execute(
        """insert into food_seasonality (food_id, country, region, month_start, month_end, availability, confidence)
           values (%s,'India','Gujarat',10,2,'Peak winter availability','APPROXIMATE')""",
        (food,),
    )
    expect_error(
        conn,
        "insert into food_seasonality (food_id, country, month_start) values (%s,'India',13)",
        (food,),
        "invalid month rejected",
        "ck_month_start",
    )
    regional = conn.execute(
        "select canonical_name from foods where %s = any(regional_names)", ("amla",)
    ).fetchone()
    check("food reachable by regional name", regional is not None, str(regional))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
