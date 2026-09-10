#!/usr/bin/env python3
"""Step 18 — evaluation layers A-E. D7, A3; migration 024.

CLAUDE.md V2 throughout: every score here comes from calling the real
`retrieval.retrieve()` over a real library, and every expectation comes
from something the system already held. Nothing in this suite writes both
halves of a comparison.

The three properties that make these layers worth having, and that a
plausible-looking implementation would quietly lose:

1. **Layer A must not hand retrieval the answer.** The probe terms and the
   expected concepts are disjoint by construction. A test that queries for
   what it expects back is answered by string equality.
2. **Layer B must not teach the library the answer key.** Held-out claims
   land in `holdout_answer_keys`, and their phrases resolve READ-ONLY. The
   ordinary resolver creates PROPOSED concepts and trigram aliases — so
   the library would learn the held-out vocabulary while being measured
   against it. This suite counts concepts, aliases and cache rows across
   the extraction and asserts none moved.
3. **An empty expectation is never a perfect score.** Recall over nothing
   is undefined, not 1.0, and a young library must not report success for
   knowing nothing.
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

import evaluate as EV
import normalize
import retrieval as RT
import run_engine as RE

FAILS: list[str] = []
PREFIX = "EVALTEST_"


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
        check(name, fragment.lower() in str(exc).lower(), str(exc)[:200])
        return
    check(name, False, "no error was raised")


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------

FAMILY = ["GLYCAEMIC_VARIABILITY", "POSTPRANDIAL_GLUCOSE", "FASTING_INSULIN",
          "HEPATIC_STEATOSIS", "VISCERAL_ADIPOSITY", "TRIGLYCERIDE_HANDLING",
          "SLEEP_CONTINUITY", "APPETITE_SIGNALLING", "RESISTANCE_TRAINING",
          "VEGETARIAN_PROTEIN"]

SECOND_FAMILY = ["MEAL_SEQUENCING", "FIBRE_FIRST", "WALK_AFTER_MEALS",
                 "SLEEP_HYGIENE", "PROTEIN_DISTRIBUTION", "STRESS_LOAD",
                 "MEAL_TIMING", "COOKING_METHOD"]


def clear(conn) -> None:
    conn.execute("delete from spot_check_samples where query_text like %s",
                 (PREFIX + "%",))
    conn.execute(
        "delete from spot_check_items where strategy_id in "
        "  (select strategy_id from strategies where canonical_key like %s)",
        (PREFIX + "%",))
    conn.execute(
        "delete from retrieval_tests where generated_from like %s or query_text like %s",
        (PREFIX + "%", PREFIX + "%"))
    conn.execute("delete from retrieval_test_runs where note like %s", (PREFIX + "%",))
    conn.execute(
        "delete from holdout_answer_keys where item_id in "
        "  (select item_id from source_items where content_hash like %s)",
        (PREFIX + "%",))
    conn.execute("delete from source_envelopes where content_hash like %s",
                 (PREFIX + "%",))
    conn.execute("delete from source_items where content_hash like %s",
                 (PREFIX + "%",))
    conn.execute("delete from strategies where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from concepts where canonical_key like %s", (PREFIX + "%",))
    conn.execute("delete from knowledge_domains where domain_key like %s",
                 (PREFIX + "%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s",
                 ("%" + PREFIX.lower() + "%",))


def seed(conn) -> dict:
    """Two seeded domains with disjoint concept families, and a small
    library of strategies tagged across both."""
    ids = {"domains": {}, "concepts": {}, "strategies": {}}
    for key, name, family in (("A", "metabolic drivers", FAMILY),
                              ("B", "implementation", SECOND_FAMILY)):
        domain_id = str(conn.execute(
            "insert into knowledge_domains (name, domain_key, domain_type, "
            "description, discovered_by) "
            "values (%s,%s,'OTHER',%s,'EVALTEST') returning domain_id",
            (f"{PREFIX}{name}", f"{PREFIX}DOMAIN_{key}",
             f"{PREFIX} fixture domain")).fetchone()[0])
        ids["domains"][key] = domain_id
        for term in family:
            cid = str(conn.execute(
                "insert into concepts (canonical_key, canonical_name, "
                "concept_type, status, origin_method, definition) "
                "values (%s,%s,'DRIVER','ACTIVE','SEED',%s) returning concept_id",
                (PREFIX + term, term.lower().replace("_", " "),
                 f"the {term.lower().replace('_', ' ')} concept")).fetchone()[0])
            ids["concepts"][term] = cid
            conn.execute(
                "insert into concept_domains (concept_id, domain_id, source) "
                "values (%s,%s,'K1_SEED')", (cid, domain_id))

    # One strategy per concept, so every concept is reachable through the
    # spine and the domain ceiling is genuinely 2.
    for term, cid in ids["concepts"].items():
        sid = str(conn.execute(
            "insert into strategies (name, canonical_key, summary, mechanism, "
            "knowledge_status) values (%s,%s,%s,%s,'AI_DISCOVERED_CANDIDATE') "
            "returning strategy_id",
            (f"{PREFIX}{term} strategy", f"{PREFIX}S_{term}",
             f"addresses {term.lower().replace('_', ' ')}",
             f"the mechanism of {term.lower().replace('_', ' ')}")).fetchone()[0])
        conn.execute(
            "insert into strategy_concepts (strategy_id, concept_id, link_role, "
            "weight) values (%s,%s,'INDICATED_FOR',1.0)", (sid, cid))
        ids["strategies"][term] = sid
    return ids


def seed_held_out(conn) -> str:
    """A held-out source, ingested and chunked but never synthesised (A3)."""
    item_id = str(conn.execute(
        "insert into source_items (title, content_hash, ingestion_status, "
        "held_out, held_out_batch) "
        "values (%s,%s,'NORMALIZED',true,'EVALTEST') returning item_id",
        (PREFIX + "held out source", PREFIX + "holdout")).fetchone()[0])
    conn.execute(
        # raw_preserved: §50 refuses a NORMALIZED envelope without the
        # original it was derived from (ck_raw_before_derived).
        "insert into source_envelopes (source_kind, source_role, source_title, "
        "rights, content_hash, status, processing_version, raw_preserved, "
        "raw_location) "
        "values ('RESEARCH_PAPER','EVIDENCE',%s,'PUBLIC',%s,'NORMALIZED',"
        "        'k08.v1',true,'EVALTEST fixture')",
        (PREFIX + "held out source", PREFIX + "holdout"))
    doc = str(conn.execute(
        "insert into source_documents (item_id, document_type) "
        "values (%s,'TEST') returning document_id", (item_id,)).fetchone()[0])
    conn.execute(
        "insert into knowledge_chunks (document_id, chunk_index, text, metadata) "
        "values (%s,0,%s,%s)",
        (doc, "postprandial glucose falls when fibre is eaten first",
         json.dumps({"location": "(body)"})))
    return item_id


def stub_engine(cards: list[dict]):
    """A provider returning the Claim Cards handoff K09's own parser reads.

    Signature and return shape are `RUN_ENGINE`'s real provider contract
    (system_prompt, user_prompt, params) -> (text, in_tokens, out_tokens).
    The transport is replaced; `KE.claim_cards`, `RUN_ENGINE`, the handoff
    registry and the control contract are all the real ones (V2).
    """
    payload = json.dumps(cards)

    def provider(system_prompt, user_prompt, params):
        return (
            "the report\n"
            "<RESEARCH_PRACTICE_CLAIMS>\n"
            "MODE: INBOX\n"
            "SOURCE_REFERENCE: evaltest\n"
            f"CLAIMS_JSON:\n{payload}\n"
            "</RESEARCH_PRACTICE_CLAIMS>\n"
            "<RESEARCH_PRACTICE_INBOX_HANDOFF>\n"
            "MODE: INBOX\nSOURCE_REFERENCE: evaltest\nSOURCE_KIND: OTHER\n"
            f"CLAIMS_IDENTIFIED: {len(cards)}\n"
            "INFORMATION_GAIN_SUMMARY: held-out answer key\n"
            "</RESEARCH_PRACTICE_INBOX_HANDOFF>\n"
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


def main() -> int:
    os.environ["LLM_API_KEY"] = ""
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    clear(conn)
    fx = seed(conn)

    # ==================================================================
    print("\nthe seeded structure layer A scores against")

    seeded = conn.execute(
        "select count(*) from concept_domains cd join concepts c using (concept_id) "
        " where c.origin_method='SEED' and c.canonical_key not like %s",
        (PREFIX + "%",)).fetchone()[0]
    from_prose = conn.execute(
        """select count(*) from (
             select distinct c.concept_id, d.domain_id
               from concepts c
               cross join lateral regexp_matches(c.origin_detail,
                          'DOMAIN ([A-Z])(?![A-Z])', 'g') as m(letter)
               join knowledge_domains d on d.domain_key = 'DOMAIN_' || m.letter[1]
              where c.origin_method='SEED' and c.origin_detail is not null) x"""
    ).fetchone()[0]
    check("the concept-domain edges match the provenance they were derived from",
          seeded == from_prose and seeded > 0, f"{seeded} rows vs {from_prose} in prose")

    # ==================================================================
    print("\nlayer A: the query and the expectation are disjoint")

    made = EV.generate_a(conn)
    check("a test is generated per family large enough to split", made >= 2, str(made))

    rows = conn.execute(
        "select query_text, expected_concepts, query_concepts from retrieval_tests "
        " where layer='A' and domain_id = %s", (fx["domains"]["A"],)).fetchall()
    check("the fixture domain got one", len(rows) == 1, str(len(rows)))
    query, expected, query_concepts = rows[0]
    expected = [str(c) for c in expected]
    probe_names = query.split(": ", 1)[1].split(", ")
    probe_ids = [str(r[0]) for r in conn.execute(
        "select concept_id from concepts where canonical_name = any(%s)",
        (probe_names,)).fetchall()]
    check("no probe term is also an expected answer",
          not (set(probe_ids) & set(expected)),
          f"overlap {set(probe_ids) & set(expected)}")
    check("the spine is NOT handed the family it must find",
          list(query_concepts or []) == [], str(query_concepts))
    check("everything not probed is expected",
          len(expected) == len(FAMILY) - EV.PROBE_TERMS,
          f"{len(expected)} expected of {len(FAMILY)}")

    # ==================================================================
    print("\nan empty expectation cannot exist")

    expect_error(
        conn,
        "insert into retrieval_tests (layer, metric, query_text, "
        " expected_concepts, generated_from) "
        "values ('A','CONCEPT_RECALL','nothing expected','{}','EVALTEST')",
        (), "a test with no expected concepts is refused",
        "ck_test_has_expectation")

    expect_error(
        conn,
        "insert into retrieval_tests (layer, metric, query_text, "
        " expected_concepts, generated_from) "
        "values ('B','CONCEPT_RECALL','no source',%s,'EVALTEST')",
        ([list(fx["concepts"].values())[0]],),
        "a layer B test with no held-out item is refused", "ck_layer_b_has_item")

    # ==================================================================
    print("\nlayer A is scored by the real retrieval path")

    result = EV.run_layer(conn, "A")
    check("the run scored every test", result["scored"] == result["tests"],
          str(result))
    stored = conn.execute(
        "select expected, hit, score, channels, note from retrieval_test_results "
        " where run_id=%s and test_id in (select test_id from retrieval_tests "
        "   where domain_id=%s)", (result["run_id"], fx["domains"]["A"])).fetchone()
    check("the fixture domain's result was recorded", stored is not None)
    if stored:
        expected_n, hit, score, channels, note = stored
        check("hit never exceeds expected", hit <= expected_n, f"{hit}/{expected_n}")
        check("the score is the recall it reports",
              abs(float(score) - hit / expected_n) < 1e-4, f"{score} vs {hit}/{expected_n}")
        check("the channels that found it are recorded", bool(channels), str(channels))

    check("the run records whether vectors were available",
          result["vector_enabled"] == RT.vector_available(conn), str(result))
    floor = conn.execute(
        "select score_floor from retrieval_test_runs where run_id=%s",
        (result["run_id"],)).fetchone()[0]
    check("and the floor it judged against", float(floor) == EV.SCORE_FLOOR, str(floor))

    # ==================================================================
    print("\nbug 63: a multi-term query must match something")

    # The regression that layer A found. `websearch_to_tsquery` ANDs every
    # term, so this query matched NOTHING and layer A scored 0.00 across
    # all fourteen domains. Driving the real `by_fts`.
    hits = RT.by_fts(conn, "postprandial glucose and hepatic steatosis and sleep",
                     include_held_out=False)
    check("a query naming three unrelated things still matches",
          len(hits) >= 3, f"{len(hits)} hit(s)")
    check("and a query of pure stop words matches nothing, without raising",
          RT.by_fts(conn, "the and of", include_held_out=False) == [])

    # ==================================================================
    print("\nlayer B: the answer key never reaches the library")

    item_id = seed_held_out(conn)
    before = conn.execute(
        "select (select count(*) from concepts), (select count(*) from concept_aliases), "
        "       (select count(*) from normalization_cache), "
        "       (select count(*) from claims), (select count(*) from strategies)"
    ).fetchone()

    cards = [{"claim_text": "fibre before carbohydrate lowers the glucose peak",
              "claim_type": "INTERVENTION_EFFECT",
              "target": "postprandial glucose",
              "intervention": "fibre first",
              "mechanism": "gastric emptying"}]
    written = with_provider(
        stub_engine(cards),
        lambda: EV.extract_answer_key(conn, item_id, PREFIX + "holdout"))
    check("the held-out source produced an answer key", written == 1, str(written))

    after = conn.execute(
        "select (select count(*) from concepts), (select count(*) from concept_aliases), "
        "       (select count(*) from normalization_cache), "
        "       (select count(*) from claims), (select count(*) from strategies)"
    ).fetchone()
    check("no concept was created from held-out vocabulary",
          after[0] == before[0], f"{before[0]} -> {after[0]}")
    check("no alias either", after[1] == before[1], f"{before[1]} -> {after[1]}")
    check("nothing was cached", after[2] == before[2], f"{before[2]} -> {after[2]}")
    check("no claim row: the answer key is not library content (A3)",
          after[3] == before[3], f"{before[3]} -> {after[3]}")
    check("and no strategy", after[4] == before[4], f"{before[4]} -> {after[4]}")

    key = conn.execute(
        "select claim_text, concept_ids, run_id from holdout_answer_keys "
        " where item_id=%s", (item_id,)).fetchone()
    check("the key landed in holdout_answer_keys", key is not None)
    check("and it records the run that produced it", key and key[2] is not None)
    check("its phrases resolved against the EXISTING ontology",
          key and str(fx["concepts"]["POSTPRANDIAL_GLUCOSE"]) in
          [str(c) for c in (key[1] or [])],
          str(key[1]) if key else "")

    made_b = EV.generate_b(conn)
    check("a layer B test was generated from it", made_b == 1, str(made_b))
    b_test = conn.execute(
        "select query_text, expected_concepts, item_id from retrieval_tests "
        " where layer='B'").fetchone()
    check("the query is the SOURCE's language, not its concept ids",
          b_test and "fibre before carbohydrate" in b_test[0], str(b_test[0])[:80])
    b_result = EV.run_layer(conn, "B")
    check("layer B scores through the same retrieval path",
          b_result["tests"] == 1 and b_result["scored"] == 1, str(b_result))

    # ==================================================================
    print("\nread-only resolution is the mechanism, and it is testable alone")

    novel = f"{PREFIX} a phrase nothing has ever seen before"
    snapshot = conn.execute(
        "select (select count(*) from concepts), (select count(*) from concept_proposals)"
    ).fetchone()
    res = normalize.resolve(conn, novel, context="EVALTEST", read_only=True)
    after_ro = conn.execute(
        "select (select count(*) from concepts), (select count(*) from concept_proposals)"
    ).fetchone()
    check("an unmatched phrase resolves to nothing in read-only mode",
          res.concept_ids == [] and res.decision == "UNRESOLVED",
          f"{res.decision} {res.concept_ids}")
    check("and creates neither a concept nor a proposal",
          after_ro == snapshot, f"{snapshot} -> {after_ro}")

    res2 = normalize.resolve(conn, novel, context="EVALTEST")
    check("the ORDINARY path does create one — the difference is real",
          bool(res2.concept_ids) or res2.decision in ("AUTO_CREATE", "LOGGED",
                                                      "ESCALATED"),
          f"{res2.decision} {res2.concept_ids}")
    conn.execute("delete from concepts where canonical_name = %s", (novel,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (novel,))

    # ==================================================================
    print("\nlayer C: breadth against an achievable ceiling")

    for dimension in conn.execute(
            "select unnest(enum_range(null::coverage_dimension))::text "
            " limit %s", (EV.MODERATE_COVERAGE,)).fetchall():
        conn.execute(
            "insert into domain_coverage (domain_id, dimension, covered, item_count) "
            "values (%s,%s::coverage_dimension,true,3) "
            "on conflict (domain_id, dimension) do update set covered=true",
            (fx["domains"]["A"], dimension[0]))

    made_c = EV.generate_c(conn)
    check("a case is generated for the domain at moderate coverage",
          made_c >= 1, str(made_c))
    c_test = conn.execute(
        "select metric::text, query_concepts from retrieval_tests "
        " where layer='C' and domain_id=%s", (fx["domains"]["A"],)).fetchone()
    check("it is scored on DOMAIN_BREADTH, not recall",
          c_test and c_test[0] == "DOMAIN_BREADTH", str(c_test))
    check("and the case's own concepts ARE handed to the spine",
          c_test and len(c_test[1] or []) > 0, str(c_test))

    ceiling = EV.library_domains(conn)
    check("the ceiling is what the library spans, not a constant",
          ceiling >= 2, f"{ceiling} domain(s)")

    c_result = EV.run_layer(conn, "C")
    c_row = conn.execute(
        "select expected, hit, score, note from retrieval_test_results "
        " where run_id=%s limit 1", (c_result["run_id"],)).fetchone()
    check("breadth is scored against that ceiling",
          c_row and c_row[0] == ceiling, f"{c_row} vs ceiling {ceiling}")
    check("a case anchored in one domain reaches beyond it",
          c_row and c_row[1] >= 2, str(c_row))

    # ==================================================================
    print("\nan unscorable test is not a zero")

    conn.execute("update strategies set knowledge_status='DEPRECATED', "
                 "provenance_note='EVALTEST ceiling' where canonical_key like %s",
                 (PREFIX + "%",))
    empty_ceiling = EV.library_domains(conn)
    if empty_ceiling == 0:
        blind = EV.run_layer(conn, "C")
        check("with no domain in the library the run is UNSCORABLE",
              blind["unscorable"] >= 1, str(blind))
        check("and unscorable tests are excluded from the mean, not counted 0",
              blind["mean_score"] is None or blind["scored"] < blind["tests"],
              str(blind))
    else:
        print(f"  SKIP  another suite's strategies still span {empty_ceiling} "
              "domain(s); the empty-library branch cannot be reached here.")
    conn.execute("update strategies set knowledge_status='AI_DISCOVERED_CANDIDATE' "
                 " where canonical_key like %s", (PREFIX + "%",))

    # ==================================================================
    print("\nlayer D: a small sample, one at a time")

    drawn = EV.sample_spot_check(conn)
    check("a sample was drawn from a layer C case", drawn.get("created"), str(drawn))
    sample_id = drawn["sample_id"]
    check("it is capped at the configured size",
          drawn["items"] <= EV.SPOT_CHECK_ITEMS, str(drawn["items"]))

    again = EV.sample_spot_check(conn)
    check("a second sample is refused while one is unreviewed (hard rule 3)",
          not again.get("created") and again.get("sample_id") == sample_id,
          str(again))

    items = [str(r[0]) for r in conn.execute(
        "select strategy_id from spot_check_items where sample_id=%s order by position",
        (sample_id,)).fetchall()]
    try:
        EV.record_verdict(conn, sample_id, items[0], "EXPECTED_USEFUL")
        EV.record_verdict(conn, sample_id, items[1], "UNEXPECTED_USEFUL")
        check("verdicts are recorded", True)
    except Exception as exc:
        check("verdicts are recorded", False, str(exc))

    unreviewed = conn.execute(
        "select reviewed_at from spot_check_samples where sample_id=%s",
        (sample_id,)).fetchone()[0]
    check("the sample is not closed while items are unmarked", unreviewed is None)

    outsider = conn.execute(
        "select strategy_id::text from strategies where canonical_key like %s "
        " and strategy_id <> all(%s::uuid[]) limit 1",
        (PREFIX + "%", items)).fetchone()
    if outsider:
        try:
            EV.record_verdict(conn, sample_id, outsider[0], "IRRELEVANT")
            check("a verdict on something never presented is refused", False,
                  "it was accepted")
        except EV.EvaluationError:
            check("a verdict on something never presented is refused", True)
    else:
        print("  SKIP  every fixture strategy is in the sample; no outsider to try.")

    for strategy_id in items[2:]:
        EV.record_verdict(conn, sample_id, strategy_id, "IRRELEVANT")
    closed = conn.execute(
        "select reviewed_at from spot_check_samples where sample_id=%s",
        (sample_id,)).fetchone()[0]
    check("marking the last item closes the sample", closed is not None)

    expect_error(
        conn,
        "update spot_check_samples set important_item_missing=true where sample_id=%s",
        (sample_id,), "'something was missing' with no note is refused",
        "ck_missing_needs_note")
    EV.record_missing(conn, sample_id, "no vegetarian protein option appeared")
    check("with a note it is accepted",
          conn.execute("select missing_note from spot_check_samples "
                       " where sample_id=%s", (sample_id,)).fetchone()[0] is not None)

    # ==================================================================
    print("\nlayer E: a RATE, never a count")

    row = conn.execute(
        "select items_presented, items_reviewed, unexpected_useful, "
        "       unexpected_useful_rate, irrelevant_rate "
        "  from v_discovery_value where sample_id=%s", (sample_id,)).fetchone()
    presented, reviewed, unexpected, rate, irrelevant_rate = row
    check("the rate's denominator is what was REVIEWED, not what was shown",
          abs(float(rate) - unexpected / reviewed) < 1e-4,
          f"{rate} vs {unexpected}/{reviewed} (presented {presented})")
    check("one UNEXPECTED_USEFUL in the sample gives a rate below 1",
          0 < float(rate) < 1, str(rate))
    check("irrelevant is reported alongside it",
          float(irrelevant_rate) > 0, str(irrelevant_rate))

    trend = conn.execute(
        "select samples, items_reviewed, unexpected_useful_rate "
        "  from v_discovery_value_trend limit 1").fetchone()
    check("the trend pools items rather than averaging per-sample rates",
          trend is not None and trend[1] >= reviewed, str(trend))

    # A half-reviewed sample must not report half the rate: the denominator
    # moves with the numerator. Proved by unmarking one item and re-reading.
    conn.execute(
        "update spot_check_items set verdict=null, decided_at=null "
        " where sample_id=%s and strategy_id=%s", (sample_id, items[-1]))
    partial = conn.execute(
        "select items_reviewed, unexpected_useful_rate from v_discovery_value "
        " where sample_id=%s", (sample_id,)).fetchone()
    check("un-reviewing an item shrinks the denominator, not the rate's meaning",
          partial[0] == reviewed - 1 and float(partial[1]) > float(rate),
          f"{rate} -> {partial[1]} over {partial[0]}")

    # ==================================================================
    print("\nthe state view never reports an unmeasured layer as passing")

    states = {r[0]: r for r in conn.execute(
        "select layer, tests_defined, tests_run, mean_score from v_evaluation_state"
    ).fetchall()}
    check("all three automated layers are listed", set(states) == {"A", "B", "C"},
          str(sorted(states)))
    for layer, (_l, defined, run, mean) in states.items():
        if defined == 0:
            check(f"layer {layer} with no tests reports no score",
                  mean is None or run is None, str(states[layer]))

    clear(conn)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_evaluation: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
