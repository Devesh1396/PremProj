#!/usr/bin/env python3
"""Step 18 — evaluation layers A-E. D7; migration 024.

    python3 scripts/evaluate.py --generate         # (re)build layers A, B, C
    python3 scripts/evaluate.py --run A            # score one layer
    python3 scripts/evaluate.py --run all
    python3 scripts/evaluate.py --answer-key       # extract held-out sources (B)
    python3 scripts/evaluate.py --spot-check       # draw a sample (D)
    python3 scripts/evaluate.py --verdict SAMPLE STRATEGY VERDICT
    python3 scripts/evaluate.py --report           # E, and where each layer stands

### There is no gold benchmark, and that is the design (D7)

Engine 7 exists because the practitioner cannot personally author, read
and remember the whole knowledge universe. A benchmark whose answers come
from practitioner recall makes practitioner recall the ceiling on measured
success -- so every expectation here is derived from something the system
already holds and did not invent for the occasion:

| | expectation comes from |
|---|---|
| A | the K1 ontology seed, which predates every extraction |
| B | a HELD-OUT source, extracted separately and kept out of the library |
| C | how many domains the library could possibly span |
| D | the practitioner, marking a small sample -- QC, never authoring |
| E | layer D's verdicts, as a RATE |

### Layer A does not hand retrieval the answer

Each domain's seeded family is SPLIT: a few concepts become the query
text, the rest become what must come back, and the two sets never overlap.
A query built from the same concepts it expects would be answered by
string equality and would measure nothing (V2). `query_concepts` is left
empty for the same reason -- feeding the spine the family it is being
asked to find is the same mistake wearing a different hat.

### Layer B never lets the answer key into the library

Held-out claims land in `holdout_answer_keys`, which nothing in K10 or K11
reads, and their phrases are resolved with `normalize.resolve(...,
read_only=True)` -- the same tiers, writing nothing. The ordinary path
would create PROPOSED concepts and trigram aliases from the held-out
vocabulary, and the library would have learned from the material it is
being measured against.

### Layer C measures breadth against an achievable ceiling

"Not three disease folders" is a claim about how many domains a page
spans. The ceiling is how many domains the library HAS strategies in --
computed, never assumed. A library holding one domain cannot span two, and
scoring it 0.3 for that would be measuring the library's age.

### Scores are instrumentation, not definitions of quality (A4)

`EVAL_SCORE_FLOOR` is an engineering tripwire and is recorded WITH each
run, along with whether pgvector was available and how big the library
was. Recall with vectors and recall without them are different numbers
and must never be trended as one line.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg

import knowledge_extract as KE
import normalize
import retrieval as RT
import run_engine as RE

# Layer A needs a family big enough to split. Below this the split leaves
# too few on either side for the score to mean anything.
MIN_FAMILY = int(os.environ.get("EVAL_MIN_FAMILY", "8"))
PROBE_TERMS = int(os.environ.get("EVAL_PROBE_TERMS", "3"))

# "Run per domain from MODERATE coverage, not at the end" (BUILD_PLAN
# layer C). Moderate is well below the ~14-of-18 depth bar that
# foundation readiness needs: the point is to correct the normalization
# layer while re-tagging is still cheap.
MODERATE_COVERAGE = int(os.environ.get("EVAL_MODERATE_COVERAGE", "6"))

PAGE = int(os.environ.get("EVAL_PAGE", "20"))
SCORE_FLOOR = float(os.environ.get("EVAL_SCORE_FLOOR", "0.30"))

# Layer D is the one human touchpoint and it stays small (hard rule 3).
SPOT_CHECK_ITEMS = int(os.environ.get("EVAL_SPOT_CHECK_ITEMS", "10"))

ANSWER_KEY_VERSION = "layerB.v1"


class EvaluationError(RuntimeError):
    """Something the runner will not paper over."""


def dsn() -> str:
    return os.environ["DATABASE_URL"]


# =====================================================================
# Layer A — the seeded domain structure
# =====================================================================

def generate_a(conn) -> int:
    """One test per domain whose seeded family is large enough to split.

    Deterministic: the split is by `canonical_key`, so regenerating gives
    the same tests and two runs are comparable. A random split would make
    every regeneration a different benchmark.
    """
    conn.execute("delete from retrieval_tests where layer='A' "
                 "  and generated_from = 'K1_SEED_FAMILY_SPLIT'")
    made = 0
    domains = conn.execute(
        """select d.domain_id, d.domain_key, d.name, count(*) as family
             from concept_domains cd
             join knowledge_domains d using (domain_id)
             join concepts c on c.concept_id = cd.concept_id
            where c.status in ('SEEDED','ACTIVE')
            group by 1, 2, 3
           having count(*) >= %s
            order by 2""", (MIN_FAMILY,)).fetchall()

    for domain_id, domain_key, name, _family in domains:
        members = conn.execute(
            """select c.concept_id::text, c.canonical_name
                 from concept_domains cd
                 join concepts c on c.concept_id = cd.concept_id
                where cd.domain_id = %s and c.status in ('SEEDED','ACTIVE')
                order by c.canonical_key""", (domain_id,)).fetchall()
        probes, expected = members[:PROBE_TERMS], members[PROBE_TERMS:]
        if not expected:
            continue
        # The query names the probes; the expectation is everything else.
        # The two sets are disjoint by construction, so nothing here can be
        # answered by returning the query back.
        query = f"{name}: " + ", ".join(term for _id, term in probes)
        conn.execute(
            """insert into retrieval_tests
                 (layer, metric, query_text, expected_concepts, domain_id,
                  generated_from)
               values ('A','CONCEPT_RECALL',%s,%s::uuid[],%s,
                       'K1_SEED_FAMILY_SPLIT')""",
            (query, [cid for cid, _ in expected], domain_id))
        made += 1
    return made


# =====================================================================
# Layer B — held-out sources
# =====================================================================

def held_out_items(conn) -> list[tuple]:
    return conn.execute(
        "select item_id::text, title, content_hash from source_items "
        " where held_out order by first_seen").fetchall()


def extract_answer_key(conn, item_id: str, content_hash: str) -> int:
    """Extract a held-out source SEPARATELY, into the answer-key table.

    This drives the REAL extractor -- `knowledge_extract`'s own input
    builder and Claim Card parser, through `RUN_ENGINE` in E7 `INBOX` mode
    -- because an answer key produced by a different extractor would be in
    a different vocabulary from the library, and the comparison would be
    measuring the two extractors against each other (V2).

    What differs is only the DESTINATION: `holdout_answer_keys`, which no
    part of K10 or K11 reads, and read-only concept resolution.
    """
    # The same tuple shape `knowledge_extract.pending()` produces, because
    # `KE.build_input` consumes it positionally and the answer key must be
    # built from exactly the payload the library's own extraction sees.
    envelope = conn.execute(
        """select e.envelope_id, e.source_title, e.source_kind,
                  e.source_role::text, e.rights::text, e.content_hash,
                  e.source_version
             from source_envelopes e where e.content_hash = %s
             order by e.source_version desc limit 1""",
        (content_hash,)).fetchone()
    if envelope is None:
        raise EvaluationError(
            f"held-out item {item_id} has no envelope; it was never ingested, "
            "so there is nothing to extract an answer key from.")

    pieces = KE.chunks_for(conn, content_hash)
    if not pieces:
        raise EvaluationError(
            f"held-out item {item_id} has no chunks. K08 must run before an "
            "answer key can exist.")

    result = RE.run_engine(
        conn,
        RE.EngineRequest(
            engine="E7", mode="INBOX", model_role="MODEL_EXTRACTION",
            structured_input=KE.build_input(envelope, pieces),
            run_context={"stage": "LAYER_B_ANSWER_KEY",
                         "item_id": str(item_id),
                         "processing_version": ANSWER_KEY_VERSION}))
    if result.status != "SUCCEEDED":
        raise EvaluationError(
            f"the answer-key extraction did not succeed ({result.status}): "
            f"{result.error}")

    cards = KE.claim_cards(result)
    conn.execute("delete from holdout_answer_keys where item_id=%s", (item_id,))
    written = 0
    for card in cards:
        if not isinstance(card, dict):
            continue
        text = (card.get("claim_text") or "").strip()
        if not text:
            continue
        concept_ids: list[str] = []
        for key in ("target", "intervention", "mechanism"):
            phrase = (card.get(key) or "").strip()
            if not phrase:
                continue
            res = normalize.resolve(conn, phrase,
                                    context="layer B answer key",
                                    read_only=True)
            for cid in res.concept_ids:
                if cid not in concept_ids:
                    concept_ids.append(cid)
        conn.execute(
            """insert into holdout_answer_keys
                 (item_id, claim_text, claim_type, target, concept_ids, run_id)
               values (%s,%s,%s,%s,%s::uuid[],%s)""",
            (item_id, text, card.get("claim_type"), card.get("target"),
             concept_ids, result.run_id))
        written += 1
    return written


def generate_b(conn) -> int:
    """One test per held-out item that has an answer key with concepts.

    An item whose claims resolved to NOTHING gets no test, and that is the
    honest outcome: the library has no vocabulary for what the source
    said, so there is nothing it could be expected to retrieve. Recording
    it as a test with an empty expectation would score it 1.0 for knowing
    nothing -- which `ck_test_has_expectation` refuses anyway.
    """
    conn.execute("delete from retrieval_tests where layer='B'")
    made = 0
    for item_id, title, _hash in held_out_items(conn):
        rows = conn.execute(
            "select claim_text, concept_ids from holdout_answer_keys "
            " where item_id=%s order by extracted_at, key_id", (item_id,)
        ).fetchall()
        if not rows:
            continue
        expected: list[str] = []
        for _text, ids in rows:
            for cid in ids or []:
                if str(cid) not in expected:
                    expected.append(str(cid))
        if not expected:
            continue
        # The query is the SOURCE'S OWN language, not the concepts it
        # resolved to -- that is what "can the library be reached from
        # this material" means.
        claims = " ".join(text for text, _ in rows)[:900]
        conn.execute(
            """insert into retrieval_tests
                 (layer, metric, query_text, expected_concepts, item_id,
                  generated_from)
               values ('B','CONCEPT_RECALL',%s,%s::uuid[],%s,
                       'HELD_OUT_ANSWER_KEY')""",
            (f"{title or 'held-out source'}: {claims}", expected, item_id))
        made += 1
    return made


# =====================================================================
# Layer C — cross-domain synthetic cases
# =====================================================================

def domains_at_moderate_coverage(conn) -> list[tuple]:
    return conn.execute(
        """select d.domain_id, d.domain_key, d.name,
                  count(*) filter (where dc.covered) as covered
             from knowledge_domains d
             join domain_coverage dc using (domain_id)
            where d.active
            group by 1, 2, 3
           having count(*) filter (where dc.covered) >= %s
            order by 2""", (MODERATE_COVERAGE,)).fetchall()


def generate_c(conn) -> int:
    """A synthetic case anchored in each domain that has reached moderate
    coverage -- per domain and early, not once at the end.

    The case's concepts are the domain's own. What is measured is whether
    the page reaches BEYOND them, because a real case does: the vegetarian
    PCOS + fatty liver + prediabetes client needs sleep, appetite,
    behaviour and implementation material, and a page of three disease
    folders is the documented failure.
    """
    conn.execute("delete from retrieval_tests where layer='C'")
    made = 0
    for domain_id, _key, name, _covered in domains_at_moderate_coverage(conn):
        members = conn.execute(
            """select c.concept_id::text, c.canonical_name
                 from concept_domains cd
                 join concepts c on c.concept_id = cd.concept_id
                where cd.domain_id = %s and c.status in ('SEEDED','ACTIVE')
                order by c.canonical_key
                limit 6""", (domain_id,)).fetchall()
        if not members:
            continue
        conn.execute(
            """insert into retrieval_tests
                 (layer, metric, query_text, query_concepts, expected_concepts,
                  domain_id, generated_from)
               values ('C','DOMAIN_BREADTH',%s,%s::uuid[],%s::uuid[],%s,
                       'SYNTHETIC_CROSS_DOMAIN_CASE')""",
            (f"a case presenting with {name}: "
             + ", ".join(term for _id, term in members),
             [cid for cid, _ in members], [cid for cid, _ in members],
             domain_id))
        made += 1
    return made


# =====================================================================
# Scoring
# =====================================================================

def library_domains(conn) -> int:
    """How many domains the library could possibly span. Layer C's ceiling."""
    return conn.execute(
        """select count(distinct cd.domain_id)
             from strategies s
             join strategy_concepts sc on sc.strategy_id = s.strategy_id
             join concept_domains cd on cd.concept_id = sc.concept_id
            where s.knowledge_status <> 'DEPRECATED'""").fetchone()[0]


def domains_of(conn, concept_ids: list[str]) -> set:
    if not concept_ids:
        return set()
    return {str(r[0]) for r in conn.execute(
        "select distinct domain_id from concept_domains "
        " where concept_id = any(%s::uuid[])", (concept_ids,)).fetchall()}


def reached_concepts(conn, result: dict) -> list[str]:
    """Which concepts a retrieval actually touched.

    A returned concept row IS a concept; a returned strategy or pattern
    reaches the concepts it is bucketed under. Chunks reach none -- they
    are bucketed by source item -- so they contribute nothing here, which
    is correct rather than a gap: a chunk is not tagged to the ontology.
    """
    ids: list[str] = []
    for row in result["results"]:
        if row["kind"] == "concept" and row["id"] not in ids:
            ids.append(row["id"])
        for bucket in row["buckets"]:
            if bucket not in ids:
                ids.append(bucket)
    return ids


def score_test(conn, test: dict, page: dict) -> dict:
    """Score one test by ITS OWN metric, read from the row (024)."""
    reached = reached_concepts(conn, page)
    channels = sorted({c for row in page["results"] for c in row["channels"]})

    if test["metric"] == "CONCEPT_RECALL":
        expected = test["expected_concepts"]
        hit = [cid for cid in expected if cid in reached]
        score = len(hit) / len(expected)
        note = f"{len(hit)}/{len(expected)} expected concepts reached"
        if len(expected) > PAGE:
            # This is recall@PAGE, and a family larger than the page is
            # bounded above by PAGE/expected before retrieval is judged at
            # all. The score is NOT adjusted for it -- rescaling a measure
            # after reading it is how a measure stops meaning anything --
            # but the ceiling travels with the number so it cannot be read
            # as "this domain is indexed worse than that one".
            note += f" (recall@{PAGE}: the page cannot hold more than {PAGE})"
        return {"expected": len(expected), "hit": len(hit),
                "returned": len(page["results"]), "score": score,
                "channels": channels, "note": note}

    if test["metric"] == "DOMAIN_BREADTH":
        ceiling = library_domains(conn)
        covered = domains_of(conn, reached)
        if ceiling == 0:
            # No strategy in the library is tagged to any domain, so no
            # page could span one. Scoring this 0.0 would report a
            # retrieval failure for an empty library; it is UNSCORABLE and
            # says so.
            return {"expected": 0, "hit": 0, "returned": len(page["results"]),
                    "score": 0.0, "channels": channels,
                    "note": "UNSCORABLE: the library spans no domain yet",
                    "unscorable": True}
        hit = min(len(covered), ceiling)
        return {"expected": ceiling, "hit": hit,
                "returned": len(page["results"]), "score": hit / ceiling,
                "channels": channels,
                "note": f"{hit} of {ceiling} available domains on the page"}

    raise EvaluationError(f"no scoring rule for metric {test['metric']}")


def run_layer(conn, layer: str, embed_call=None) -> dict:
    """Score every active test in a layer through the REAL retrieval path."""
    tests = conn.execute(
        """select test_id::text, metric::text, query_text, query_concepts,
                  expected_concepts
             from retrieval_tests where layer=%s and active
             order by created_at, test_id""", (layer,)).fetchall()
    if not tests:
        return {"layer": layer, "tests": 0,
                "note": "no tests defined; nothing to measure"}

    vector_on = RT.vector_available(conn)
    library = conn.execute(
        "select count(*) from strategies where knowledge_status <> 'DEPRECATED'"
    ).fetchone()[0]

    run_id = str(conn.execute(
        """insert into retrieval_test_runs
             (layer, vector_enabled, library_size, score_floor)
           values (%s,%s,%s,%s) returning run_id""",
        (layer, vector_on, library, SCORE_FLOOR)).fetchone()[0])

    scored = 0
    passed = 0
    total = 0.0
    unscorable = 0
    for test_id, metric, query, query_concepts, expected in tests:
        page = RT.retrieve(
            conn, query=query,
            concept_ids=[str(c) for c in (query_concepts or [])],
            limit=PAGE, embed_call=embed_call, telemetry=False)
        outcome = score_test(
            conn,
            {"metric": metric,
             "expected_concepts": [str(c) for c in (expected or [])]},
            page)
        is_unscorable = outcome.pop("unscorable", False)
        ok = (not is_unscorable) and outcome["score"] >= SCORE_FLOOR
        conn.execute(
            """insert into retrieval_test_results
                 (run_id, test_id, expected, hit, returned, score, passed,
                  channels, note)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, test_id, outcome["expected"], outcome["hit"],
             outcome["returned"], round(outcome["score"], 4), ok,
             outcome["channels"], outcome["note"]))
        if is_unscorable:
            unscorable += 1
            continue
        scored += 1
        total += outcome["score"]
        passed += 1 if ok else 0

    # An unscorable test is excluded from the mean rather than counted as
    # zero. A library too young to span a domain has not failed retrieval.
    mean = round(total / scored, 4) if scored else None
    note = (f"{unscorable} test(s) unscorable" if unscorable else None)
    conn.execute(
        """update retrieval_test_runs
              set finished_at = now(), tests_run = %s, tests_passed = %s,
                  mean_score = %s, note = %s
            where run_id = %s""",
        (len(tests), passed, mean, note, run_id))
    return {"layer": layer, "run_id": run_id, "tests": len(tests),
            "scored": scored, "passed": passed, "unscorable": unscorable,
            "mean_score": mean, "vector_enabled": vector_on,
            "library_size": library}


# =====================================================================
# Layer D — the practitioner spot check
# =====================================================================

def outstanding_sample(conn) -> str | None:
    row = conn.execute(
        "select sample_id::text from spot_check_samples "
        " where reviewed_at is null order by sampled_at limit 1").fetchone()
    return row[0] if row else None


def sample_spot_check(conn, embed_call=None) -> dict:
    """Draw ONE small sample for the practitioner to mark.

    It reuses a layer C synthetic case rather than asking anyone to think
    of a query, and it refuses to draw a second sample while one is still
    unreviewed. Hard rule 3: no milestone may create a recurring manual
    job. A queue that grows whether or not anyone looks at it is exactly
    that job, arriving quietly.
    """
    pending = outstanding_sample(conn)
    if pending:
        return {"sample_id": pending, "created": False,
                "note": "a sample is already awaiting review; "
                        "one at a time, by design (hard rule 3)"}

    case = conn.execute(
        """select t.test_id::text, t.query_text, t.query_concepts
             from retrieval_tests t
            where t.layer='C' and t.active
            order by (select max(s.sampled_at) from spot_check_samples s
                       where s.context = t.test_id::text) nulls first,
                     t.test_id
            limit 1""").fetchone()
    if case is None:
        return {"created": False,
                "note": "no layer C case exists yet; run --generate first"}

    test_id, query, query_concepts = case
    page = RT.retrieve(conn, query=query,
                       concept_ids=[str(c) for c in (query_concepts or [])],
                       limit=SPOT_CHECK_ITEMS, embed_call=embed_call,
                       telemetry=False)
    strategies = [row for row in page["results"] if row["kind"] == "strategy"]
    if not strategies:
        return {"created": False,
                "note": "the case retrieved no strategy; there is nothing to "
                        "spot check, and inventing something to show would "
                        "make the sample about the sampler"}

    sample_id = str(conn.execute(
        """insert into spot_check_samples (query_text, context, items_presented)
           values (%s,%s,%s) returning sample_id""",
        (query, test_id, len(strategies))).fetchone()[0])
    for position, row in enumerate(strategies):
        conn.execute(
            """insert into spot_check_items (sample_id, strategy_id, position)
               values (%s,%s,%s)""", (sample_id, row["id"], position))
    return {"sample_id": sample_id, "created": True,
            "items": len(strategies), "query": query}


def record_verdict(conn, sample_id: str, strategy_id: str, verdict: str,
                   note: str | None = None) -> None:
    updated = conn.execute(
        """update spot_check_items set verdict=%s, note=%s, decided_at=now()
            where sample_id=%s and strategy_id=%s returning 1""",
        (verdict, note, sample_id, strategy_id)).fetchone()
    if not updated:
        raise EvaluationError(
            f"strategy {strategy_id} is not in sample {sample_id}. A verdict "
            "on something that was not presented is not a spot check.")
    remaining = conn.execute(
        "select count(*) from spot_check_items "
        " where sample_id=%s and verdict is null", (sample_id,)).fetchone()[0]
    if remaining == 0:
        conn.execute(
            "update spot_check_samples set reviewed_at=now() "
            " where sample_id=%s and reviewed_at is null", (sample_id,))


def record_missing(conn, sample_id: str, note: str) -> None:
    """D7's fourth verdict: something important did NOT come back.

    It belongs to the sample, not to any row in it, and the constraint
    refuses it without a note -- "something was missing" that does not say
    what cannot become a knowledge gap or a query fix.
    """
    conn.execute(
        "update spot_check_samples set important_item_missing=true, "
        "       missing_note=%s where sample_id=%s", (note, sample_id))


# =====================================================================
# Reporting
# =====================================================================

def report(conn) -> None:
    print("\nLAYERS A-C")
    print(f"{'layer':<6}{'tests':>7}{'last run':>22}{'run':>6}{'pass':>6}"
          f"{'mean':>8}  vectors")
    for row in conn.execute(
            "select layer, description, tests_defined, last_run_at, tests_run, "
            "       tests_passed, mean_score, vector_enabled "
            "  from v_evaluation_state order by layer").fetchall():
        layer, description, defined, at, run, ok, mean, vectors = row
        when = at.strftime("%Y-%m-%d %H:%M") if at else "never"
        print(f"{layer:<6}{defined:>7}{when:>22}"
              f"{('-' if run is None else run):>6}"
              f"{('-' if ok is None else ok):>6}"
              f"{('-' if mean is None else f'{mean:.3f}'):>8}"
              f"  {'yes' if vectors else ('no' if vectors is False else '-')}")
        print(f"       {description}")

    print("\nLAYER D — spot checks")
    pending = outstanding_sample(conn)
    print(f"  awaiting review     : {pending or 'none'}")

    print("\nLAYER E — discovery value, as a RATE (never a count)")
    rows = conn.execute(
        "select month, samples, items_reviewed, unexpected_useful_rate, "
        "       irrelevant_rate, samples_with_a_gap "
        "  from v_discovery_value_trend").fetchall()
    if not rows:
        print("  no reviewed sample yet. A rate needs a denominator.")
    else:
        print(f"  {'month':<12}{'samples':>9}{'reviewed':>10}"
              f"{'unexpected':>12}{'irrelevant':>12}{'gaps':>6}")
        for month, samples, reviewed, unexpected, irrelevant, gaps in rows:
            print(f"  {str(month):<12}{samples:>9}{reviewed:>10}"
                  f"{('-' if unexpected is None else f'{unexpected:.3f}'):>12}"
                  f"{('-' if irrelevant is None else f'{irrelevant:.3f}'):>12}"
                  f"{gaps:>6}")
        print("  D7: expect this to DECLINE as the practitioner absorbs what "
              "the system surfaces.")
        print("      A near-zero rate EARLY is the warning sign, not a success.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 18 evaluation layers A-E")
    ap.add_argument("--generate", action="store_true",
                    help="(re)build the layer A, B and C test sets")
    ap.add_argument("--answer-key", action="store_true",
                    help="extract held-out sources into the layer B answer key")
    ap.add_argument("--run", choices=["A", "B", "C", "all"])
    ap.add_argument("--spot-check", action="store_true", help="draw a layer D sample")
    ap.add_argument("--verdict", nargs=3,
                    metavar=("SAMPLE", "STRATEGY", "VERDICT"))
    ap.add_argument("--missing", nargs=2, metavar=("SAMPLE", "NOTE"))
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if not any([args.generate, args.answer_key, args.run, args.spot_check,
                args.verdict, args.missing, args.report]):
        ap.error("nothing to do; try --report")

    with psycopg.connect(dsn(), autocommit=True) as conn:
        if args.answer_key:
            for item_id, title, content_hash in held_out_items(conn):
                written = extract_answer_key(conn, item_id, content_hash)
                print(f"  {title or item_id}: {written} answer-key claim(s)")

        if args.generate:
            print(f"  layer A : {generate_a(conn)} test(s)")
            print(f"  layer B : {generate_b(conn)} test(s)")
            print(f"  layer C : {generate_c(conn)} test(s)")

        if args.run:
            for layer in (["A", "B", "C"] if args.run == "all" else [args.run]):
                print(f"  {run_layer(conn, layer)}")

        if args.spot_check:
            print(f"  {sample_spot_check(conn)}")

        if args.verdict:
            record_verdict(conn, *args.verdict)
            print("  verdict recorded")

        if args.missing:
            record_missing(conn, args.missing[0], args.missing[1])
            print("  gap recorded on the sample")

        if args.report:
            report(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
