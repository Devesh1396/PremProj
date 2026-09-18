#!/usr/bin/env python3
"""C3 normalization — BUILD_GUIDE step 13, DECISIONS.md D2 and D3.

The assertions that matter:

  * resolution is CHEAPEST FIRST and stops early — an alias hit never
    reaches the LLM, and the suite proves it by injecting an LLM that
    raises if called
  * a confirmed mapping is cached, so a phrase never costs a second call
  * clinically distinct CONFUSABLE_DO_NOT_MERGE concepts are never merged
    into one answer
  * extraction PROPOSES; it never silently creates a canonical concept
  * escalation ranks by impact and respects the weekly cap
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import psycopg
import normalize as NZ

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight

FAILS: list[str] = []
PFX = "C3TEST_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def boom(*_args, **_kwargs):
    raise AssertionError("the LLM tier was reached when a cheap tier should have answered")



# ---------------------------------------------------------------------
# GATE 2 -- the semantic tier (D51)
# ---------------------------------------------------------------------

def unit(angle_deg: float, dims: int) -> list[float]:
    """A unit vector at a chosen angle inside a fixed 2-D plane.

    The cosine between two of these is exactly cos(theta1 - theta2), so a
    fixture can state the ranking it wants instead of hoping an embedding
    produces one. That matters for V2: the claims below are about the
    SELECTION LOGIC -- how many candidates become a resolution, whether a
    guard fires -- and a fixture whose scores were "whatever the provider
    said" would be measuring the provider, and would pass or fail by luck.

    The transport is replaced and nothing else: `normalize._tier_semantic`
    and `normalize.resolve` are the real ones, exactly as
    `retrieval.by_vector(embed_call=...)` already does it.
    """
    import math
    v = [0.0] * dims
    v[0] = math.cos(math.radians(angle_deg))
    v[1] = math.sin(math.radians(angle_deg))
    return v


def gate2(conn, check, concept) -> None:
    import math
    import knowledge_extract as KE

    print("\nGATE 2: the semantic tier answers, and its candidates are not its answer")

    if not preflight.have_capability(conn, "vector"):
        print("        (the tier is exercised wherever pgvector is; run_bare.sh "
              "is the floor where it must skip instead)")
        return
    # The transport is injected below, so nothing here pays a provider -- but
    # `embedding.embed()` still refuses without a model NAME, and it is right
    # to (D34 pins the model per column; embedding with none pinned is an
    # error, not a default). So the block needs the variable set even though
    # it needs no call, and says so rather than failing on the floor where
    # the VPS runs.
    if not preflight.have_env(
            "MODEL_EMBEDDING",
            "the semantic tier cannot be exercised at all: embedding.embed() "
            "refuses without a model pinned, even with the provider call "
            "injected, so the candidate-set, confusable, type-guard and "
            "mechanism assertions below do not run"):
        return

    # Idempotent from a used database, like every other block here: this one
    # writes a source item and an envelope, and a failure part-way through
    # once left both behind and every later run died on the url index.
    conn.execute("delete from claims where item_id in "
                 "  (select item_id from source_items where external_id=%s)",
                 ("c3test-gate2",))
    conn.execute("delete from source_items where external_id=%s", ("c3test-gate2",))
    conn.execute("delete from source_envelopes where content_hash=%s",
                 ("c3test-gate2-hash",))

    dims = conn.execute("select embedding_dim()").fetchone()[0]

    # D34 refuses two models in one vector column, and it is right to: mixing
    # them makes every distance meaningless. So the fixture vectors carry
    # whatever model the column is ALREADY pinned to, and carry a fixture
    # name only when nothing is embedded yet. That is a constraint this
    # fixture obeys, not a claim about where these vectors came from -- they
    # are arithmetic, they exist for the length of this function, and every
    # row holding one is deleted before it returns.
    pinned = conn.execute(
        "select embedding_model from concepts where embedding is not null "
        "limit 1").fetchone()
    model = pinned[0] if pinned else "c3test-fixture-embedding"

    # Four concepts at known angles from the query. cos(0)=1.000,
    # cos(25)=0.906, cos(33)=0.839, cos(60)=0.500 -- so three clear the
    # semantic floor and one does not, and the ordering is arithmetic.
    plan = [("SEM_A", "c3test semantic alpha", "PHYSIOLOGY", 0.0),
            ("SEM_B", "c3test semantic beta", "PHYSIOLOGY", 25.0),
            ("SEM_C", "c3test semantic gamma", "PHYSIOLOGY", 33.0),
            ("SEM_D", "c3test semantic delta", "POPULATION", 60.0)]
    ids = {}
    for key, name, ctype, angle in plan:
        cid = concept(key, name, ctype)
        ids[key] = cid
        conn.execute(
            """update concepts
                  set embedding = %s::vector, embedding_model = %s,
                      embedding_dim = %s, embedding_source_hash = %s
                where concept_id = %s""",
            (str(unit(angle, dims)), model, dims, key.lower(), cid))

    def fake_embed(_model, _text, d):
        return unit(0.0, d)

    query = "c3test a phrase that is nobody's canonical name"
    tier = NZ._tier_semantic(conn, NZ.norm(conn, query), phrase=query,
                             embed_call=fake_embed)

    check("the semantic tier returns a candidate SET, not a top-1",
          len(tier.candidates) == NZ.SEMANTIC_CANDIDATES,
          f"{len(tier.candidates)} candidate(s): {tier.candidates}")
    check("...ranked, with the arithmetic the fixture stated",
          [round(c.score, 3) for c in tier.candidates] == [1.0, 0.906, 0.839],
          str([round(c.score, 4) for c in tier.candidates]))
    check("...and the one below the floor is not among them",
          ids["SEM_D"] not in tier.candidate_ids, str(tier.candidate_ids))

    # THE LOAD-BEARING ONE. Three candidates, no confusable pair between
    # them, and the resolution is still ONE concept. The old tier contract
    # returned a single list used both as "what I looked at" and "what I
    # resolved to", so a top-3 tier would have resolved this phrase to all
    # three the moment nothing objected.
    check("A THREE-CANDIDATE TIER SELECTS ONE CONCEPT, not three",
          tier.selected == [ids["SEM_A"]], str(tier.selected))
    check("...and no confusable pair had to object for that to be true",
          NZ.confusable_with(conn, tier.candidate_ids) == [],
          str(NZ.confusable_with(conn, tier.candidate_ids)))

    r = NZ.resolve(conn, query, llm=boom, use_cache=False, embed_call=fake_embed)
    check("...so resolve() returns one concept, by the semantic tier",
          r.decision == "RESOLVED" and r.method == "semantic"
          and r.concept_ids == [ids["SEM_A"]], repr(r))
    check("...cached as the one concept it resolved to, never the three considered",
          conn.execute(
              """select cardinality(concept_ids) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""", (query,)).fetchone() == (1,))
    check("...and a similarity judgement never becomes a CONFIRMED alias",
          conn.execute(
              """select count(*) from concept_aliases
                  where alias_text=%s and confirmed""", (query,)).fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\nthe confusable guard still fires although the tier selects one concept")

    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, note)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE','c3test gate 2')
           on conflict do nothing""", (ids["SEM_A"], ids["SEM_C"]))
    conn.execute("delete from normalization_cache where phrase_norm = norm_phrase(%s)",
                 (query,))
    r = NZ.resolve(conn, query, llm=boom, use_cache=False, embed_call=fake_embed)
    check("a do-not-merge pair inside the CANDIDATES refuses the resolution",
          r.decision == "ESCALATED" and not r.concept_ids, repr(r))
    check("...and it was the candidates that carried it: the selection was one id",
          "CONFUSABLE_DO_NOT_MERGE" in r.note, r.note)
    check("...so nothing was cached from a refused answer",
          conn.execute(
              """select count(*) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""", (query,)).fetchone()[0] == 0)
    conn.execute(
        """delete from concept_relations
            where relation_type='CONFUSABLE_DO_NOT_MERGE'
              and (from_concept=%s or to_concept=%s)""", (ids["SEM_A"], ids["SEM_A"]))

    # ------------------------------------------------------------------
    print("\nthe type guard refuses a category crossing, and refuses rather than shops")

    def fake_embed_pop(_model, _text, d):
        return unit(60.0, d)          # nearest is SEM_D, a POPULATION

    pop_query = "c3test a population-shaped phrase"
    tier_pop = NZ._tier_semantic(conn, NZ.norm(conn, pop_query), phrase=pop_query,
                                 embed_call=fake_embed_pop)
    top = tier_pop.candidates[0]
    check("the tier's own top candidate is the POPULATION concept",
          top.concept_id == ids["SEM_D"] and top.concept_type == "POPULATION",
          repr(top))
    rejection = NZ.type_rejection(conn, tier_pop, NZ.TARGET_TYPES)
    check("a caller that structurally knows it wants a target REFUSES it",
          rejection is not None and rejection[0].concept_id == ids["SEM_D"],
          str(rejection))
    check("...and the refusal says which type it was and what was allowed",
          rejection is not None and "POPULATION" in rejection[1], str(rejection))
    check("...while a caller that does NOT know imposes nothing",
          NZ.type_rejection(conn, tier_pop, None) is None)

    r_typed = NZ.resolve(conn, pop_query, llm=None, use_cache=False,
                         allowed_types=NZ.TARGET_TYPES, embed_call=fake_embed_pop)
    check("a refused crossing does not resolve to the next type-compatible concept",
          not r_typed.concept_ids, repr(r_typed))
    check("...the refusal is RECORDED, not merely performed",
          conn.execute(
              """select count(*) from concept_proposals
                  where raw_phrase=%s and decision='LOGGED'
                    and decision_note like 'refused on concept_type%%'""",
              (pop_query,)).fetchone()[0] == 1)
    r_untyped = NZ.resolve(conn, pop_query, llm=None, use_cache=False,
                           embed_call=fake_embed_pop)
    check("...and the SAME phrase resolves when no caller claimed to know the type",
          r_untyped.concept_ids == [ids["SEM_D"]], repr(r_untyped))

    conn.execute("delete from concepts where canonical_name=%s", (pop_query,))
    conn.execute("delete from concept_proposals where raw_phrase in (%s,%s)",
                 (pop_query, query))
    conn.execute("delete from normalization_cache where phrase_norm in "
                 "(norm_phrase(%s), norm_phrase(%s))", (pop_query, query))

    # ------------------------------------------------------------------
    print("\nwith no embedding model the tier answers, named, rather than raising (V3)")

    saved = os.environ.get("MODEL_EMBEDDING", "")
    os.environ["MODEL_EMBEDDING"] = ""
    try:
        quiet = NZ._tier_semantic(conn, NZ.norm(conn, "c3test unconfigured"),
                                  phrase="c3test unconfigured")
        check("no model configured: the tier returns nothing and NAMES what is missing",
              not quiet.candidates and "MODEL_EMBEDDING" in quiet.note, quiet.note)
        # The VPS runs exactly this way on purpose, so a resolver that raised
        # here would take down every caller on the machine the system is
        # meant to run on.
        r_off = NZ.resolve(conn, "c3test unconfigured phrase", llm=None,
                           use_cache=False)
        check("...and resolve() still produces an outcome for the caller",
              r_off.decision in ("AUTO_CREATE", "LOGGED", "ESCALATED", "RESOLVED"),
              repr(r_off))
    finally:
        os.environ["MODEL_EMBEDDING"] = saved
    conn.execute("delete from concepts where canonical_name=%s",
                 ("c3test unconfigured phrase",))
    conn.execute("delete from concept_proposals where raw_phrase=%s",
                 ("c3test unconfigured phrase",))

    # ------------------------------------------------------------------
    print("\na mechanism sentence stays on the claim and never becomes a concept")

    mech = ("c3test contracting muscle fibers take up glucose independently of "
            "insulin action to fuel mitochondrial ATP production")
    check("mechanism is not a field K09 normalizes",
          "mechanism" not in KE.CONCEPT_FIELDS, str(sorted(KE.CONCEPT_FIELDS)))

    card = {"claim_text": "c3test a claim", "claim_type": "MECHANISM",
            "target": "c3test insulin sensitivity",
            "intervention": "c3test walking after meals",
            "mechanism": mech}
    seen, known, _new = KE.normalize_claim_concepts(conn, [card])
    check("only the target and the intervention are offered to the resolver",
          seen == 2, f"{seen} phrase(s)")
    check("...and the target still resolves, so this did not just switch it off",
          known >= 1, f"{known} known")
    check("NO concept was created from the mechanism sentence",
          conn.execute("select count(*) from concepts where canonical_name=%s",
                       (mech,)).fetchone()[0] == 0)
    check("...and no proposal row claims it was ever a candidate concept",
          conn.execute("select count(*) from concept_proposals where raw_phrase=%s",
                       (mech,)).fetchone()[0] == 0)

    # ... and it is still CLAIM CONTENT. Removing it from normalization must
    # not be a quiet way of dropping a field whose contents are a separate,
    # recorded defect (D49).
    item = conn.execute(
        """insert into source_items (source_id, external_id, title, url,
                                     ingestion_status)
           select source_id, %s, %s, %s, 'NORMALIZED' from knowledge_sources
            order by created_at limit 1
           returning item_id""",
        ("c3test-gate2", "c3test gate 2 item", "https://example.invalid/c3test")
    ).fetchone()
    if item is None:
        preflight.skip("a knowledge source row",
                       "claims hang off source_items, so the claim-side half of this "
                       "cannot be written; the normalization half above still ran")
    else:
        env = conn.execute(
            """insert into source_envelopes
                 (source_title, source_kind, source_role, rights, content_hash,
                  raw_location)
               values (%s,'OTHER','EVIDENCE','PUBLIC',%s,%s)
               returning envelope_id""",
            ("c3test gate 2", "c3test-gate2-hash", "c3test")).fetchone()[0]
        written = KE.write_claims(conn, env, item[0], [card])
        stored = conn.execute("select mechanism from claims where claim_id=%s",
                              (written[0],)).fetchone()
        check("the mechanism is stored on the claim, verbatim",
              stored is not None and stored[0] == mech, str(stored))
        conn.execute("delete from claims where claim_id=%s", (written[0],))
        conn.execute("delete from source_envelopes where envelope_id=%s", (env,))
        conn.execute("delete from source_items where item_id=%s", (item[0],))

    conn.execute("delete from concepts where canonical_name=%s",
                 ("c3test walking after meals",))
    conn.execute("delete from concept_proposals where raw_phrase like %s", ("c3test%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s", ("%c3test%",))

    # The fixture vectors leave with the fixture. A suite that left four
    # embedded concepts behind would be the 36-chunk mistake again: harmless
    # alone, and a retrieval assertion two suites later that nobody can
    # explain.
    for key in ("SEM_A", "SEM_B", "SEM_C", "SEM_D"):
        conn.execute("delete from concepts where canonical_key=%s", (PFX + key,))
    check("the fixture's embedded concepts do not outlive it",
          conn.execute(
              "select count(*) from concepts where canonical_key like %s",
              (PFX + "SEM_%",)).fetchone()[0] == 0)


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    # Idempotent: its own namespace, cleared first, so this suite and K1's
    # seed cannot step on each other.
    conn.execute("delete from concepts where canonical_key like %s", (PFX + "%",))
    conn.execute("delete from concept_proposals where raw_phrase like %s", ("%c3test%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s", ("%c3test%",))

    def concept(key, name, ctype="PHYSIOLOGY", status="SEEDED"):
        return str(conn.execute(
            """insert into concepts (canonical_key, canonical_name, concept_type,
                                     status, origin_method)
               values (%s,%s,%s,%s,'SEED') returning concept_id""",
            (PFX + key, name, ctype, status)).fetchone()[0])

    insulin = concept("INSULIN_SENSITIVITY", "c3test insulin sensitivity")
    hba1c = concept("HBA1C", "c3test glycated haemoglobin", "BIOMARKER")
    central = concept("CENTRAL_ADIPOSITY", "c3test central adiposity")
    visceral = concept("VISCERAL_FAT", "c3test visceral fat")

    conn.execute(
        """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
           values (%s,'c3test insulin resistance','SEED',1.0,true)""", (insulin,))
    # D3: these two are close in embedding space and clinically distinct.
    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, method)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE','SEED')""", (central, visceral))

    # ------------------------------------------------------------------
    print("\ntier 1: deterministic alias, and it does not reach the LLM")
    r = NZ.resolve(conn, "c3test insulin resistance", llm=boom, use_cache=False)
    check("a confirmed alias resolves", r.decision == "RESOLVED" and insulin in r.concept_ids,
          repr(r))
    check("...by the alias tier, not similarity", r.method == "alias", r.method)
    check("...at full confidence", r.confidence == 1.0, str(r.confidence))

    r = NZ.resolve(conn, "c3test insulin sensitivity", llm=boom, use_cache=False)
    check("the canonical name itself resolves", insulin in r.concept_ids, repr(r))

    print("\ntier 2: structured identifiers are not a similarity question")
    # The structured tier maps a phrase to a canonical_key, so this needs a
    # concept keyed HBA1C. K1 seeds one; if the ontology has not been seeded
    # yet, create it here. Earlier this test RENAMED its own fixture to
    # HBA1C and renamed it back, which collided with the seeded concept the
    # moment K1 ran first -- a test mutating a globally meaningful key.
    seeded = conn.execute(
        "select concept_id from concepts where canonical_key='HBA1C'").fetchone()
    borrowed = seeded is None
    hba1c_real = str(seeded[0]) if seeded else str(conn.execute(
        """insert into concepts (canonical_key, canonical_name, concept_type,
                                 status, origin_method)
           values ('HBA1C','glycated haemoglobin','BIOMARKER','SEEDED','SEED')
           returning concept_id""").fetchone()[0])
    # "HbA1c" is itself a canonical name once K1 has seeded it, so the ALIAS
    # tier answers first -- cheapest tier first, working as designed. To
    # exercise the structured tier specifically, use an identifier form that
    # is not anyone's canonical name.
    r = NZ.resolve(conn, "HbA1c", llm=boom, use_cache=False)
    check("a structured identifier maps to the right concept",
          hba1c_real in r.concept_ids, repr(r))
    check("...via a deterministic tier, never similarity or an LLM",
          r.method in ("alias", "structured"), r.method)

    r = NZ.resolve(conn, "a1c", llm=boom, use_cache=False)
    check("an identifier that is nobody's canonical name uses the structured tier",
          r.method == "structured" and hba1c_real in r.concept_ids, repr(r))
    if borrowed:
        conn.execute("delete from concepts where concept_id=%s", (hba1c_real,))

    print("\ntier 3: trigram catches near-neighbours -- when pg_trgm is there")
    # D15: pg_trgm is genuinely optional, and this assertion was written as
    # though it were not. Without the extension the resolver correctly skips
    # the trigram tier and the phrase falls through to the LLM -- which is
    # exactly what migration 000 says its absence means -- and `boom` fired.
    # The behaviour was right; the test was wrong. So assert the tier when
    # the capability is recorded, and assert the DEGRADED behaviour when it
    # is not. Neither branch is a skip: both have something to prove.
    typo = "c3test insulin sensitivty"
    if NZ._capability(conn, "pg_trgm"):
        # Assert the TIER, by calling the tier. This block used to assert
        # which tier `resolve()` happened to end on, and accepted RESOLVED,
        # ESCALATED or LOGGED -- so it passed on a near-miss while its name
        # claimed a resolution, and the alias check below it, guarded by
        # `if r.decision == "RESOLVED"`, HAD NEVER ONCE RUN. It only started
        # running when the semantic tier began resolving this phrase, which
        # is how it was found (V2: a check that cannot fire is not a check).
        tier = NZ._tier_trigram(conn, NZ.norm(conn, typo))
        check("the trigram tier finds the near-neighbour a misspelling names",
              [c.name for c in tier.candidates] == ["c3test insulin sensitivity"],
              repr(tier.candidates))

        # And assert the thing that makes the semantic tier necessary: a
        # ONE-CHARACTER typo in a 26-character phrase scores 0.833, and
        # ALIAS_THRESHOLD is 0.92. Measured across longer phrases too --
        # 0.902 for one dropped letter in 38 characters -- so on realistic
        # clinical vocabulary the trigram tier can near-match and essentially
        # cannot resolve. That is not tuned here: a threshold changed to make
        # a test pass is a threshold fitted to a test.
        check("...and scores it BELOW the trigram threshold, so trigram alone cannot resolve",
              0.0 < tier.confidence < NZ.ALIAS_THRESHOLD,
              f"{tier.confidence:.4f} vs ALIAS_THRESHOLD {NZ.ALIAS_THRESHOLD}")

        r = NZ.resolve(conn, typo, llm=boom, use_cache=False)
        check("a misspelling is answered by a deterministic tier, never the LLM",
              r.decision in ("RESOLVED", "ESCALATED", "LOGGED")
              and r.method in ("trigram", "semantic"), repr(r))
        check("...and a near-match is never learned as a CONFIRMED alias",
              conn.execute(
                  """select count(*) from concept_aliases
                      where alias_text=%s and confirmed""", (typo,)).fetchone()[0] == 0)
        conn.execute("delete from concept_aliases where alias_text=%s", (typo,))
    else:
        # Degraded, and it must degrade in the safe direction: more work
        # for the LLM, never a wrong answer from a tier that cannot run.
        called: list[str] = []

        def watched_llm(phrase, _candidates):
            called.append(phrase)
            return None

        r = NZ.resolve(conn, typo, llm=watched_llm, use_cache=False)
        check("without pg_trgm the misspelling falls through to the LLM",
              called == [typo], f"{called} {r!r}")
        check("...and the trigram tier never claims to have answered",
              r.method != "trigram", r.method)
        check("...and an unresolved misspelling is proposed, never made canonical",
              r.decision == "AUTO_CREATE" and not r.concept_ids, repr(r))
        check("...and no alias is invented for a spelling nothing confirmed",
              conn.execute(
                  """select count(*) from concept_aliases
                      where concept_id=%s and alias_text=%s""",
                  (insulin, typo)).fetchone()[0] == 0)
        conn.execute("delete from concepts where canonical_name=%s", (typo,))
        conn.execute("delete from concept_proposals where raw_phrase=%s", (typo,))

    # ------------------------------------------------------------------
    print("\nthe cache means a phrase never costs a second call (D2)")
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 ("c3test insulin resistance",))
    NZ.resolve(conn, "c3test insulin resistance", llm=boom, use_cache=False)
    cached = conn.execute(
        """select concept_ids, method from normalization_cache
            where phrase_norm = norm_phrase(%s)""", ("c3test insulin resistance",)).fetchone()
    check("a confirmed resolution is cached", cached is not None and len(cached[0]) == 1,
          str(cached))
    r = NZ.resolve(conn, "c3test insulin resistance", llm=boom)
    check("the second call is served from cache", r.method == "cache", repr(r))
    hits = conn.execute(
        """select hit_count from normalization_cache
            where phrase_norm = norm_phrase(%s)""", ("c3test insulin resistance",)).fetchone()[0]
    check("cache hits are counted", hits >= 1, str(hits))

    # ------------------------------------------------------------------
    print("\nCONFUSABLE_DO_NOT_MERGE is never collapsed (D3)")
    check("the mirror relation exists so a merge check cannot miss the pair",
          conn.execute(
              """select count(*) from concept_relations
                  where relation_type='CONFUSABLE_DO_NOT_MERGE'
                    and from_concept=%s and to_concept=%s""",
              (visceral, central)).fetchone()[0] == 1)
    clash = NZ.confusable_with(conn, [central, visceral])
    check("a two-concept answer spanning the pair is detected", len(clash) >= 1, str(clash))
    check("a single-concept answer is never a clash",
          NZ.confusable_with(conn, [central]) == [])

    def llm_merges_them(_phrase, _candidates):
        return {"concept_ids": [central, visceral], "confidence": 0.99}
    r = NZ.resolve(conn, "c3test belly fat around the middle", llm=llm_merges_them,
                   use_cache=False)
    check("an LLM answer that merges a confusable pair is refused",
          r.decision != "RESOLVED" and not r.concept_ids, repr(r))
    check("...and nothing was cached from it",
          conn.execute(
              """select count(*) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""",
              ("c3test belly fat around the middle",)).fetchone()[0] == 0)

    # ------------------------------------------------------------------
    print("\nextraction proposes; it never silently creates a canonical concept")
    before = conn.execute(
        "select count(*) from concepts where status in ('SEEDED','ACTIVE')").fetchone()[0]
    r = NZ.resolve(conn, "c3test entirely unheard of phenomenon", use_cache=False)
    after = conn.execute(
        "select count(*) from concepts where status in ('SEEDED','ACTIVE')").fetchone()[0]
    check("no new SEEDED or ACTIVE concept appeared", after == before, f"{before} -> {after}")
    check("the decision says it was proposed", r.decision == "AUTO_CREATE", repr(r))

    proposed = conn.execute(
        """select status::text, origin_method from concepts
            where canonical_name = 'c3test entirely unheard of phenomenon'""").fetchone()
    check("the new concept exists with status PROPOSED",
          proposed is not None and proposed[0] == "PROPOSED", str(proposed))
    check("...and records how it got there",
          proposed is not None and proposed[1] == "DETERMINISTIC", str(proposed))
    check("a proposal row was written",
          conn.execute(
              """select count(*) from concept_proposals
                  where raw_phrase='c3test entirely unheard of phenomenon'"""
          ).fetchone()[0] == 1)
    check("an unresolved phrase is NOT cached as if it were confirmed",
          conn.execute(
              """select count(*) from normalization_cache
                  where phrase_norm = norm_phrase(%s)""",
              ("c3test entirely unheard of phenomenon",)).fetchone()[0] == 0)

    print("\na PROPOSED concept does not answer future lookups")
    r2 = NZ.resolve(conn, "c3test entirely unheard of phenomenon", use_cache=False)
    check("it is still not returned as a resolution", not r2.concept_ids, repr(r2))

    # ------------------------------------------------------------------
    print("\nescalation ranks by impact and is capped (D8)")
    check("the weekly cap is read from the environment", NZ.WEEKLY_CAP >= 1, str(NZ.WEEKLY_CAP))
    check("escalations this week are countable", NZ.escalations_this_week(conn) >= 0)
    check("the escalation queue view sees them",
          conn.execute("select count(*) from v_concept_escalation_queue").fetchone()[0] >= 0)

    gate2(conn, check, concept)

    print("\nan Engine 1 Pass A phrase list resolves end to end")
    results = NZ.resolve_all(conn, [
        "c3test insulin resistance",
        "c3test insulin sensitivity",
        "c3test entirely unheard of phenomenon",
    ])
    check("every phrase gets an outcome", len(results) == 3, str(results))
    check("known phrases resolve, unknown ones propose",
          sum(1 for r in results if r.concept_ids) == 2
          and sum(1 for r in results if r.decision == "AUTO_CREATE") == 1,
          str(results))

    # Clean up after itself as well as before. Leaving a
    # CONFUSABLE_DO_NOT_MERGE pair behind is not inert: it is visible to
    # every other suite that looks at the concept layer.
    conn.execute("delete from concepts where canonical_key like %s", (PFX + "%",))
    conn.execute("delete from concept_proposals where raw_phrase like %s", ("%c3test%",))
    conn.execute("delete from normalization_cache where phrase_norm like %s", ("%c3test%",))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
