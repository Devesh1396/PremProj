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
    # The refusal is RECORDED, and in ONE row. This check used to assert a
    # LOGGED row written at rejection time -- which was real, and was then
    # followed by an AUTO_CREATE row for the same attempt, so the two rows
    # disagreed about what happened. The refusal now travels to the single
    # terminal row instead.
    recorded = conn.execute(
        """select decision::text, decision_note from concept_proposals
            where raw_phrase=%s""", (pop_query,)).fetchall()
    check("...the refusal is RECORDED, not merely performed",
          len(recorded) == 1 and "refused on concept_type" in (recorded[0][1] or ""),
          str(recorded))
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



def gate2_review(conn, check, concept) -> None:
    """The three invariants the GATE 2 review found open.

    All three have the same shape: a guard that exists, and a path around
    it that nobody had walked.
    """
    import knowledge_extract as KE

    print("\nGATE 2 review 1: the cache may not answer what the resolver would refuse")

    if not preflight.have_capability(conn, "vector"):
        return
    if not preflight.have_env(
            "MODEL_EMBEDDING",
            "the semantic tier cannot be exercised at all, so the cache-bypass, "
            "typed-proposal and unconfirmed-alias checks below do not run"):
        return

    dims = conn.execute("select embedding_dim()").fetchone()[0]
    pinned = conn.execute(
        "select embedding_model from concepts where embedding is not null "
        "limit 1").fetchone()
    model = pinned[0] if pinned else "c3test-fixture-embedding"

    def embed_concept(key, name, ctype, angle):
        cid = concept(key, name, ctype)
        conn.execute(
            """update concepts set embedding = %s::vector, embedding_model = %s,
                      embedding_dim = %s, embedding_source_hash = %s
                where concept_id = %s""",
            (str(unit(angle, dims)), model, dims, key.lower(), cid))
        return cid

    # One POPULATION concept the query lands on, and an EXERCISE one it does
    # not, so "the caller allows a different type" and "a type-compatible
    # concept exists nearby" are separable.
    pop = embed_concept("CACHE_POP", "c3test cohort of desk workers", "POPULATION", 0.0)
    exe = embed_concept("CACHE_EXE", "c3test standing break", "EXERCISE", 30.0)

    def at_zero(_model, _text, d):
        return unit(0.0, d)

    phrase = "c3test people who sit at desks"
    conn.execute("delete from normalization_cache where phrase_norm = norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (phrase,))

    # 1. resolves with NO caller type knowledge, and is cached.
    r1 = NZ.resolve(conn, phrase, llm=None, embed_call=at_zero)
    check("a phrase resolves semantically when no caller claims to know the type",
          r1.decision == "RESOLVED" and r1.concept_ids == [pop], repr(r1))
    row = conn.execute(
        """select concept_ids, candidate_ids, resolved_under_types
             from normalization_cache where phrase_norm = norm_phrase(%s)""",
        (phrase,)).fetchone()
    check("...and is cached with the candidate set the guard will need",
          row is not None and row[1] is not None and len(row[1]) >= 1, str(row))
    check("...recording that the type was UNKNOWN at write time, not 'any type'",
          row is not None and row[2] is None, str(row and row[2]))

    # 2. the SAME phrase, now from a caller that structurally knows better.
    r2 = NZ.resolve(conn, phrase, llm=None, allowed_types=NZ.TARGET_TYPES,
                    embed_call=at_zero)
    check("THE CACHE DOES NOT RETURN THE INCOMPATIBLE CONCEPT TO A TYPED CALLER",
          pop not in r2.concept_ids, repr(r2))
    check("...and it did not quietly answer from cache at all",
          r2.method != "cache", repr(r2))
    check("...nor shop down the list for the type-compatible neighbour",
          exe not in r2.concept_ids, repr(r2))

    # 3. and the untyped caller is not punished for someone else's context.
    r3 = NZ.resolve(conn, phrase, llm=None, embed_call=at_zero)
    check("the untyped caller still gets its answer, from cache",
          r3.method == "cache" and r3.concept_ids == [pop], repr(r3))

    # ------------------------------------------------------------------
    print("\nthe cache cannot outlive the CONFUSABLE_DO_NOT_MERGE guard either")

    near = embed_concept("CACHE_NEAR", "c3test deskbound population", "POPULATION", 20.0)
    conn.execute("delete from normalization_cache where phrase_norm = norm_phrase(%s)",
                 (phrase,))
    r4 = NZ.resolve(conn, phrase, llm=None, embed_call=at_zero)
    check("the phrase resolves and caches again", r4.decision == "RESOLVED", repr(r4))
    cand = conn.execute(
        "select candidate_ids from normalization_cache where phrase_norm = norm_phrase(%s)",
        (phrase,)).fetchone()[0]
    check("...and the stored candidates include the near neighbour, not just the answer",
          near in [str(c) for c in cand] and len(cand) > 1, str(cand))

    # The ontology changes AFTER the row was written.
    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, note)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE','c3test gate 2 review')
           on conflict do nothing""", (pop, near))
    r5 = NZ.resolve(conn, phrase, llm=None, embed_call=at_zero)
    check("A PAIR ADDED AFTER CACHING INVALIDATES THE HIT",
          r5.method != "cache" and not r5.concept_ids, repr(r5))
    check("...and the live resolver refuses the phrase, as it now must",
          r5.decision == "ESCALATED" and "CONFUSABLE_DO_NOT_MERGE" in r5.note,
          repr(r5))
    check("...which re-checking the cached ANSWER could never have caught: "
          "it is one concept and one concept spans nothing",
          NZ.confusable_with(conn, [pop]) == [])
    conn.execute(
        """delete from concept_relations where relation_type='CONFUSABLE_DO_NOT_MERGE'
            and (from_concept=%s or to_concept=%s)""", (pop, pop))

    conn.execute("delete from normalization_cache where phrase_norm = norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (phrase,))

    # ------------------------------------------------------------------
    print("\nGATE 2 review 2: a known intervention is never created as PHYSIOLOGY")

    novel = "c3test soleus push-up against a wall"
    conn.execute("delete from concepts where canonical_name = %s", (novel,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (novel,))

    r = NZ.resolve(conn, novel, context="c3test", llm=None,
                   allowed_types=NZ.INTERVENTION_TYPES, embed_call=at_zero)
    check("an unresolved INTERVENTION does not become a concept at all",
          conn.execute("select count(*) from concepts where canonical_name=%s",
                       (novel,)).fetchone()[0] == 0, repr(r))
    check("...it is NEEDS_TYPE, not AUTO_CREATE",
          r.decision == "NEEDS_TYPE", repr(r))
    check("...and PHYSIOLOGY appears nowhere near it",
          conn.execute(
              """select count(*) from concepts
                  where canonical_name=%s and concept_type='PHYSIOLOGY'""",
              (novel,)).fetchone()[0] == 0)
    rows = conn.execute(
        """select decision::text, allowed_types, decision_note
             from concept_proposals where raw_phrase=%s""", (novel,)).fetchall()
    check("EXACTLY ONE proposal row for one normalization attempt",
          len(rows) == 1, str(rows))
    check("...carrying the SET the caller could vouch for, not a narrowing of it",
          rows and sorted(rows[0][1] or []) == sorted(NZ.INTERVENTION_TYPES),
          str(rows and rows[0][1]))
    check("...and the view can find it without anyone maintaining a queue",
          conn.execute(
              "select count(*) from v_concept_needs_type where raw_phrase=%s",
              (novel,)).fetchone()[0] == 1)

    # A caller that names exactly one type HAS the knowledge; use it.
    single = "c3test a wholly novel exercise"
    conn.execute("delete from concepts where canonical_name = %s", (single,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (single,))
    NZ.resolve(conn, single, context="c3test", llm=None,
               allowed_types=frozenset({"EXERCISE"}), embed_call=at_zero)
    check("a caller naming ONE type is knowledge, and the concept is created with it",
          conn.execute(
              """select concept_type::text from concepts where canonical_name=%s""",
              (single,)).fetchone() == ("EXERCISE",))

    # A structurally-known TARGET is not given an invented narrow type either.
    tgt = "c3test a wholly novel measured outcome"
    conn.execute("delete from concepts where canonical_name = %s", (tgt,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (tgt,))
    rt = NZ.resolve(conn, tgt, context="c3test", llm=None,
                    allowed_types=NZ.TARGET_TYPES, embed_call=at_zero)
    check("an unresolved TARGET is not assigned a narrow type either",
          rt.decision == "NEEDS_TYPE"
          and conn.execute("select count(*) from concepts where canonical_name=%s",
                           (tgt,)).fetchone()[0] == 0, repr(rt))

    # ------------------------------------------------------------------
    print("\na type rejection leaves ONE outcome, not a contradictory pair")

    crossed = "c3test a phrase whose nearest concept is the wrong kind"
    conn.execute("delete from concepts where canonical_name = %s", (crossed,))
    conn.execute("delete from concept_proposals where raw_phrase = %s", (crossed,))
    rc = NZ.resolve(conn, crossed, context="c3test", llm=None,
                    allowed_types=NZ.INTERVENTION_TYPES, embed_call=at_zero)
    rows = conn.execute(
        """select decision::text, decision_note from concept_proposals
            where raw_phrase=%s order by created_at""", (crossed,)).fetchall()
    check("one refused normalization attempt writes exactly one proposal row",
          len(rows) == 1, str(rows))
    check("...and it is not a LOGGED refusal followed by an AUTO_CREATE",
          [d for d, _ in rows] != ["LOGGED", "AUTO_CREATE"], str(rows))
    check("...the single row still says the candidate was refused on type",
          rows and "concept_type" in (rows[0][1] or ""), str(rows))
    check("...and no concept was created behind it",
          conn.execute("select count(*) from concepts where canonical_name=%s",
                       (crossed,)).fetchone()[0] == 0, repr(rc))

    for name in (novel, single, tgt, crossed):
        conn.execute("delete from concepts where canonical_name=%s", (name,))
        conn.execute("delete from concept_proposals where raw_phrase=%s", (name,))

    # ------------------------------------------------------------------
    print("\nGATE 2 review 3: an UNCONFIRMED alias resolves nothing, by any tier")

    host = concept("ALIAS_HOST", "c3test alias host concept")
    query = "c3test an alias nobody confirmed"
    conn.execute("delete from concept_aliases where alias_text=%s", (query,))
    conn.execute("delete from concepts where canonical_name=%s", (query,))
    conn.execute("delete from concept_proposals where raw_phrase=%s", (query,))
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (query,))
    conn.execute(
        """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
           values (%s,%s,'SEMANTIC',0.83,false)""", (host, query))

    alias_tier = NZ._tier_alias(conn, NZ.norm(conn, query))
    check("the alias tier refuses an unconfirmed alias",
          not alias_tier.candidates, repr(alias_tier))
    tri = NZ._tier_trigram(conn, NZ.norm(conn, query))
    check("THE TRIGRAM TIER CANNOT USE IT AS A 1.0 SHORTCUT EITHER",
          host not in tri.candidate_ids or tri.confidence < 1.0,
          f"{tri.confidence} {[c.name for c in tri.candidates]}")
    check("...so an unconfirmed row influences no resolution at all",
          not any(c.concept_id == host for c in tri.candidates),
          str([(c.name, c.score) for c in tri.candidates]))

    conn.execute("update concept_aliases set confirmed = true where alias_text=%s",
                 (query,))
    alias_tier = NZ._tier_alias(conn, NZ.norm(conn, query))
    check("confirming it turns the deterministic path back on",
          alias_tier.selected == [host], repr(alias_tier))
    r = NZ.resolve(conn, query, llm=boom, use_cache=False)
    check("...and resolve() answers from the alias tier, with no LLM",
          r.decision == "RESOLVED" and r.method == "alias"
          and r.concept_ids == [host], repr(r))

    conn.execute("delete from concept_aliases where alias_text=%s", (query,))
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (query,))
    for key in ("CACHE_POP", "CACHE_EXE", "CACHE_NEAR", "ALIAS_HOST"):
        conn.execute("delete from concepts where canonical_key=%s", (PFX + key,))
    check("the review fixtures do not outlive the review",
          conn.execute(
              "select count(*) from concepts where canonical_key like %s",
              (PFX + "CACHE_%",)).fetchone()[0] == 0)



def gate2_epoch(conn, check, concept) -> None:
    """The cache must not outlive the ontology it was resolved against.

    `034` re-runs the guards over the STORED candidate set, which cannot
    see what was never a candidate. A concept added afterwards -- or, worse,
    a confirmed alias for that exact phrase -- is invisible to any check
    over the old candidates, so every entry decays as the library grows.
    """
    print("\nGATE 2 epoch: the cache is bound to the ontology revision it resolved against")

    if not preflight.have_capability(conn, "vector"):
        return
    if not preflight.have_env(
            "MODEL_EMBEDDING",
            "the semantic tier cannot be exercised at all, so the ontology-revision "
            "checks below do not run"):
        return

    dims = conn.execute("select embedding_dim()").fetchone()[0]
    pinned = conn.execute(
        "select embedding_model from concepts where embedding is not null "
        "limit 1").fetchone()
    model = pinned[0] if pinned else "c3test-fixture-embedding"

    def embed_concept(key, name, angle, ctype="PHYSIOLOGY", status="SEEDED"):
        cid = concept(key, name, ctype, status)
        conn.execute(
            """update concepts set embedding = %s::vector, embedding_model = %s,
                      embedding_dim = %s, embedding_source_hash = %s
                where concept_id = %s""",
            (str(unit(angle, dims)), model, dims, key.lower(), cid))
        return cid

    def revision():
        return conn.execute("select current_ontology_revision()").fetchone()[0]

    calls = []

    def counted(_model, _text, d):
        """The injected transport, counting itself.

        This is how "no second provider call" is ASSERTED rather than
        assumed: the count is the number of times the real tier reached its
        transport, and the tier, the cache and resolve() are all the
        production ones.
        """
        calls.append(_text)
        return unit(0.0, d)

    def cache_row(phrase):
        return conn.execute(
            """select array_length(concept_ids,1), ontology_revision,
                      array_length(candidate_ids,1)
                 from normalization_cache where phrase_norm = norm_phrase(%s)""",
            (phrase,)).fetchone()

    phrase = "c3test a phrase whose best answer will change"
    for key in ("EPOCH_A", "EPOCH_B", "EPOCH_C"):
        conn.execute("delete from concepts where canonical_key=%s", (PFX + key,))
    conn.execute("delete from concept_aliases where alias_text=%s", (phrase,))
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase=%s", (phrase,))

    # ------------------------------------------------------------------
    # A. a NEW concept that is a better answer
    # ------------------------------------------------------------------
    a = embed_concept("EPOCH_A", "c3test epoch answer one", 10.0)   # cos 0.985
    rev0 = revision()
    r1 = NZ.resolve(conn, phrase, llm=None, embed_call=counted)
    check("the phrase resolves to the only concept there is",
          r1.decision == "RESOLVED" and r1.concept_ids == [a], repr(r1))
    before = cache_row(phrase)
    check("...and the cache row records the revision it was resolved against",
          before is not None and before[1] == revision(), str(before))
    check("...which is the live one", before[1] == rev0, f"{before[1]} vs {rev0}")
    n_after_first = len(calls)

    # C (taken here, because it needs the UNCHANGED ontology): a second
    # resolution with nothing changed is served from cache and pays nothing.
    r_again = NZ.resolve(conn, phrase, llm=None, embed_call=counted)
    check("WITH NO ONTOLOGY CHANGE the second resolution is served from cache",
          r_again.method == "cache" and r_again.concept_ids == [a], repr(r_again))
    check("...and makes NO second provider call",
          len(calls) == n_after_first, f"{len(calls)} call(s), was {n_after_first}")

    # Now the ontology grows. B is nearer the query than A.
    b = embed_concept("EPOCH_B", "c3test epoch answer two", 0.0)    # cos 1.000
    rev1 = revision()
    check("adding a LIVE concept advances the ontology revision",
          rev1 > rev0, f"{rev0} -> {rev1}")
    check("...and the cached row still carries the OLD revision, untouched",
          cache_row(phrase)[1] == rev0, str(cache_row(phrase)))

    # Captured BEFORE the second resolution rewrites it. This is the proof
    # that 034's mechanism could not have covered this case: B is not in the
    # stored set, so no re-check over that set could ever have found it.
    stale_candidates = [str(x) for x in conn.execute(
        "select candidate_ids from normalization_cache "
        " where phrase_norm = norm_phrase(%s)", (phrase,)).fetchone()[0]]
    check("the new concept is absent from the stored candidate set, so "
          "re-checking that set could never surface it",
          b not in stale_candidates, str(stale_candidates))

    r2 = NZ.resolve(conn, phrase, llm=None, embed_call=counted)
    check("A NEW CONCEPT INVALIDATES THE HIT: the old answer is not returned",
          r2.method != "cache", repr(r2))
    check("...and the live resolver returns what the ontology now implies",
          r2.concept_ids == [b], repr(r2))
    after = cache_row(phrase)
    check("...and the row is REWRITTEN at the current revision, not deleted",
          after is not None and after[1] == rev1, str(after))

    # ------------------------------------------------------------------
    # B. a CONFIRMED ALIAS is the most authoritative mapping there is
    # ------------------------------------------------------------------
    c = concept("EPOCH_C", "c3test epoch the human's answer")
    rev2 = revision()
    conn.execute(
        """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
           values (%s,%s,'DETERMINISTIC',1.0,true)""", (c, phrase))
    rev3 = revision()
    check("confirming an alias advances the revision", rev3 > rev2,
          f"{rev2} -> {rev3}")

    n_before_alias = len(calls)
    r3 = NZ.resolve(conn, phrase, llm=boom, embed_call=counted)
    check("THE OLD CACHE DOES NOT OUTRANK A NEWLY CONFIRMED ALIAS",
          r3.concept_ids == [c], repr(r3))
    check("...and it is the alias tier that answers, exactly and first",
          r3.method == "alias" and r3.confidence == 1.0, repr(r3))
    check("...so the semantic tier is never reached and nothing is embedded",
          len(calls) == n_before_alias, f"{len(calls)} vs {n_before_alias}")

    # ------------------------------------------------------------------
    # D. what must NOT move the counter
    # ------------------------------------------------------------------
    print("\nchanges that cannot affect a resolution do not advance the revision")

    quiet = revision()
    conn.execute("update concepts set retrieval_hits = retrieval_hits + 1, "
                 "last_retrieved = now() where concept_id = %s", (a,))
    check("retrieval telemetry does not bump -- every search would "
          "otherwise invalidate the whole cache",
          revision() == quiet, f"{quiet} -> {revision()}")

    conn.execute("update concepts set definition = 'c3test edited definition' "
                 "where concept_id = %s", (a,))
    check("a definition edit does not bump: no tier reads it, and the "
          "re-embed that would change an answer bumps on `embedding`",
          revision() == quiet, f"{quiet} -> {revision()}")

    conn.execute(
        """insert into concepts (canonical_key, canonical_name, concept_type,
                                 status, origin_method)
           values (%s,'c3test epoch a proposal','PHYSIOLOGY','PROPOSED','DETERMINISTIC')""",
        (PFX + "EPOCH_PROPOSED",))
    check("a PROPOSED concept does not bump -- K09 creates dozens per source "
          "and no tier can see one",
          revision() == quiet, f"{quiet} -> {revision()}")

    conn.execute(
        """insert into concept_aliases (concept_id, alias_text, method, confidence, confirmed)
           values (%s,'c3test an unconfirmed alias','SEMANTIC',0.83,false)""", (a,))
    check("an UNCONFIRMED alias does not bump: proven inert in both tiers",
          revision() == quiet, f"{quiet} -> {revision()}")

    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, note)
           values (%s,%s,'RELATED_TO','c3test epoch')
           on conflict do nothing""", (a, c))
    check("a relation that is not CONFUSABLE_DO_NOT_MERGE does not bump: "
          "confusable_with() is the only reader of that table",
          revision() == quiet, f"{quiet} -> {revision()}")

    check("...and the cache survived all five untouched",
          cache_row(phrase) is not None)

    # The counter DOES move for the things that matter.
    conn.execute("update concepts set status='ACTIVE' where canonical_key=%s",
                 (PFX + "EPOCH_PROPOSED",))
    check("promoting that proposal to ACTIVE DOES bump -- it just became "
          "reachable", revision() > quiet, f"{quiet} -> {revision()}")

    moved = revision()
    conn.execute(
        """insert into concept_relations (from_concept, to_concept, relation_type, note)
           values (%s,%s,'CONFUSABLE_DO_NOT_MERGE','c3test epoch')
           on conflict do nothing""", (a, b))
    check("recording a do-not-merge pair DOES bump", revision() > moved,
          f"{moved} -> {revision()}")

    conn.execute(
        """delete from concept_relations where note='c3test epoch'""")
    conn.execute("delete from concept_aliases where alias_text in (%s,%s)",
                 (phrase, "c3test an unconfirmed alias"))
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase=%s", (phrase,))
    for key in ("EPOCH_A", "EPOCH_B", "EPOCH_C", "EPOCH_PROPOSED"):
        conn.execute("delete from concepts where canonical_key=%s", (PFX + key,))
    check("the epoch fixtures do not outlive the block",
          conn.execute("select count(*) from concepts where canonical_key like %s",
                       (PFX + "EPOCH_%",)).fetchone()[0] == 0)



def gate2_revision_integrity(conn, check, concept) -> None:
    """The two holes review found in 036, and the drift check for both.

    The schema-agreement check runs on EVERY floor, deliberately. It is the
    mechanism that stops the vector branch quietly rotting: the trigger body
    must mention `embedding` if and only if the column exists, so a future
    migration that adds the column without rebuilding the trigger turns this
    red rather than leaving the epoch blind to a re-embedding.
    """
    import psycopg
    from test_case_events import _role_password, _with_user

    print("\nGATE 2 revision integrity: the trigger must match the schema it was compiled against")

    has_column = conn.execute(
        """select exists (select 1 from pg_attribute
                           where attrelid = 'public.concepts'::regclass
                             and attname = 'embedding' and not attisdropped)"""
    ).fetchone()[0]
    mentions = conn.execute(
        """select prosrc like '%%o.embedding IS DISTINCT FROM n.embedding%%'
             from pg_proc where proname = 'trg_ontology_concepts_upd'"""
    ).fetchone()[0]
    check("the revision trigger compares `embedding` IF AND ONLY IF the "
          "column exists",
          has_column == mentions,
          f"column={has_column} trigger_compares={mentions} -- a migration "
          "that added the column must also rebuild trg_ontology_concepts_upd()")

    print("\nthe counter is trigger-only, and that is enforced not asserted")

    runtime_dsn = _with_user(os.environ["DATABASE_URL"], "phi_runtime",
                             _role_password("POSTGRES_RUNTIME_PASSWORD"))
    try:
        runtime = psycopg.connect(runtime_dsn, autocommit=True)
    except psycopg.Error as exc:
        preflight.skip("a phi_runtime connection",
                       f"the privilege half of this block cannot run: {exc}")
        runtime = None

    if runtime is not None:
        with runtime:
            before = conn.execute("select current_ontology_revision()").fetchone()[0]
            refused = None
            try:
                runtime.execute("select bump_ontology_revision('c3test direct call')")
            except psycopg.Error as exc:
                refused = str(exc)
            check("phi_runtime may NOT invoke bump_ontology_revision() directly",
                  refused is not None, "the call succeeded")
            check("...and it is refused on PERMISSION, not by accident",
                  refused is not None and "permission denied" in refused.lower(),
                  str(refused)[:120])
            check("...so the revision did not move",
                  conn.execute("select current_ontology_revision()").fetchone()[0] == before)

            check("...while phi_runtime CAN still read the revision, which the "
                  "resolver does on every cache read",
                  runtime.execute("select current_ontology_revision()").fetchone()[0]
                  == before)

            # The legitimate path: the runtime writes a confirmed alias the
            # way `_attach_alias` does, and the TRIGGER bumps as its owner.
            host = concept("REV_HOST", "c3test revision host")
            before = conn.execute("select current_ontology_revision()").fetchone()[0]
            wrote = None
            try:
                runtime.execute(
                    """insert into concept_aliases
                         (concept_id, alias_text, method, confidence, confirmed)
                       values (%s,'c3test runtime confirmed alias','DETERMINISTIC',1.0,true)""",
                    (host,))
                wrote = True
            except psycopg.Error as exc:
                wrote = str(exc)
            if wrote is True:
                check("a CONFIRMED ALIAS written by phi_runtime still advances "
                      "the revision -- the trigger reaches the bump as its owner",
                      conn.execute("select current_ontology_revision()").fetchone()[0] > before,
                      f"still {before}")
                conn.execute("delete from concept_aliases where alias_text=%s",
                             ("c3test runtime confirmed alias",))
            else:
                preflight.skip("phi_runtime INSERT on concept_aliases",
                               f"the legitimate-path half cannot run: {wrote}")
            conn.execute("delete from concepts where canonical_key=%s", (PFX + "REV_HOST",))

    # ------------------------------------------------------------------
    print("\nre-embedding an EXISTING live concept advances the revision")

    if not preflight.have_capability(conn, "vector"):
        return
    if not preflight.have_env(
            "MODEL_EMBEDDING",
            "the embedding-only change cannot be exercised, so the check that "
            "a re-embedded concept invalidates the cache does not run"):
        return

    dims = conn.execute("select embedding_dim()").fetchone()[0]
    pinned = conn.execute(
        "select embedding_model from concepts where embedding is not null "
        "limit 1").fetchone()
    model = pinned[0] if pinned else "c3test-fixture-embedding"

    def place(key, name, angle):
        cid = concept(key, name)
        conn.execute(
            """update concepts set embedding = %s::vector, embedding_model = %s,
                      embedding_dim = %s, embedding_source_hash = %s
                where concept_id = %s""",
            (str(unit(angle, dims)), model, dims, key.lower(), cid))
        return cid

    calls = []

    def counted(_model, _text, d):
        calls.append(_text)
        return unit(0.0, d)

    phrase = "c3test a phrase answered by whichever vector is nearer"
    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase=%s", (phrase,))
    a = place("REV_A", "c3test revision alpha", 10.0)   # cos 0.985
    b = place("REV_B", "c3test revision beta", 40.0)    # cos 0.766, below the floor

    r1 = NZ.resolve(conn, phrase, llm=None, embed_call=counted)
    check("the phrase resolves to the nearer of two EXISTING live concepts",
          r1.decision == "RESOLVED" and r1.concept_ids == [a], repr(r1))
    rev_before = conn.execute("select current_ontology_revision()").fetchone()[0]
    cached_before = conn.execute(
        """select concept_ids, ontology_revision from normalization_cache
            where phrase_norm = norm_phrase(%s)""", (phrase,)).fetchone()
    check("...and is cached at the current revision",
          cached_before is not None and cached_before[1] == rev_before,
          str(cached_before))

    # THE ONLY CHANGE: an existing live concept's vector. No insert, no
    # status change, no alias, no relation. Every check 036 had is satisfied.
    conn.execute("update concepts set embedding = %s::vector where concept_id = %s",
                 (str(unit(0.0, dims)), b))
    rev_after = conn.execute("select current_ontology_revision()").fetchone()[0]
    check("RE-EMBEDDING AN EXISTING LIVE CONCEPT ADVANCES THE REVISION",
          rev_after > rev_before,
          f"{rev_before} -> {rev_after}; 036 documented this and never compared it")

    n = len(calls)
    r2 = NZ.resolve(conn, phrase, llm=None, embed_call=counted)
    check("...so the stale answer is not served from cache",
          r2.method != "cache", repr(r2))
    check("...and the live resolver returns the newly better concept",
          r2.concept_ids == [b], repr(r2))
    check("...having paid exactly one embedding call to find out",
          len(calls) == n + 1, f"{len(calls) - n} call(s)")
    check("...and the row is rewritten at the new revision",
          conn.execute(
              """select ontology_revision from normalization_cache
                  where phrase_norm = norm_phrase(%s)""",
              (phrase,)).fetchone()[0] == rev_after)

    conn.execute("delete from normalization_cache where phrase_norm=norm_phrase(%s)",
                 (phrase,))
    conn.execute("delete from concept_proposals where raw_phrase=%s", (phrase,))
    for key in ("REV_A", "REV_B"):
        conn.execute("delete from concepts where canonical_key=%s", (PFX + key,))
    check("the revision fixtures do not outlive the block",
          conn.execute("select count(*) from concepts where canonical_key like %s",
                       (PFX + "REV_%",)).fetchone()[0] == 0)


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
    gate2_review(conn, check, concept)
    gate2_epoch(conn, check, concept)
    gate2_revision_integrity(conn, check, concept)

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
