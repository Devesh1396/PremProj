#!/usr/bin/env python3
"""C3 — the normalization layer. BUILD_GUIDE step 13, DECISIONS.md D2.

Engine 1 emits prose: "large post-meal glucose excursions associated with
refined evening carbohydrate intake and low muscle stimulus". The library
stores rows. Prose does not join to rows. This is the join.

Resolution runs CHEAPEST FIRST and stops at the first tier that answers:

    1 alias        exact match on a confirmed alias or canonical name
    2 structured   an identifier the phrase carries (HBA1C, LDL_C, ...)
    3 trigram      pg_trgm similarity, if the extension is present
    4 semantic     vector similarity, if pgvector and embeddings are present
    5 LLM          only when the cheap tiers cannot answer

Two rules that are not negotiable:

  * **Extraction proposes; it never silently creates a canonical concept.**
    A new concept enters as `status='PROPOSED'` with a `concept_proposals`
    row recording how it got there. Nothing becomes SEEDED or ACTIVE
    without a deliberate act.
  * **CONFUSABLE_DO_NOT_MERGE is checked before any answer is returned.**
    "Belly fat", "central adiposity" and "visceral fat" are all close in
    embedding space and the third is a different compartment with different
    risk (D3). A resolution that would collapse a confusable pair is
    downgraded to an escalation rather than returned.
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg

import concept_key
import embedding

ALIAS_THRESHOLD = float(os.environ.get("CONCEPT_AUTO_ALIAS_THRESHOLD", "0.92"))
CREATE_THRESHOLD = float(os.environ.get("CONCEPT_AUTO_CREATE_THRESHOLD", "0.72"))
WEEKLY_CAP = int(os.environ.get("CONCEPT_ESCALATION_WEEKLY_CAP", "15"))

# ---------------------------------------------------------------------
# Per-tier thresholds. ONE CONSTANT PER TIER, never one shared (D51).
# ---------------------------------------------------------------------
# 0.92 is a TRIGRAM number: for pg_trgm it means near-identity. Cosine over
# a domain-coherent corpus has a much higher floor -- the measured minimum
# across 56 phrases x 269 concepts was 0.613, for `1-deoxynojirimycin`
# against `HbA1c`, which share nothing at all. Applying 0.92 to cosine
# admits 1 of 56. The two scales are not comparable and a single constant
# applied to whichever tier answered was a latent bug, not a simplification.
#
# SEMANTIC_THRESHOLD is PROVISIONAL. 0.82 is the knee measured in
# docs/evidence/normalization_diagnosis.md over a FAILURE-SELECTED sample:
# 23 admitted, 16 right, 6 partial, 1 wrong, with wrong merges tripling
# below 0.80. What would falsify it is written down in D51 -- chiefly a
# phrase set that is not failure-selected, and a second seeded domain whose
# vocabulary is less internally coherent than metabolic health.
SEMANTIC_THRESHOLD = float(os.environ.get("CONCEPT_SEMANTIC_THRESHOLD", "0.82"))

# Below this the semantic tier says NOTHING, so the phrase is free to reach
# AUTO_CREATE. The band between FLOOR and THRESHOLD is escalate-or-log, and
# it is deliberately narrow: a wide band converts "a genuinely new concept"
# into "LOGGED, and no concept created", which is how a library loses the
# vocabulary it should have been learning. The diagnosis's sweep is what
# sets the width -- at 0.78 five of 32 admitted are wrong, at 0.82 one of 23.
SEMANTIC_FLOOR = float(os.environ.get("CONCEPT_SEMANTIC_FLOOR", "0.78"))

# Top-K, not top-1. `confusable_with()` fires only on a SPAN, so a tier that
# hands back one answer removes the guard's ability to object -- and the one
# wrong merge the diagnosis admitted at 0.80 has BOTH halves of a
# do-not-merge pair in its top-3.
SEMANTIC_CANDIDATES = int(os.environ.get("CONCEPT_SEMANTIC_CANDIDATES", "3"))

# The threshold each tier's own confidence is judged against. `None` means
# the tier is EXACT rather than a similarity judgement -- an alias hit is an
# identity statement and there is nothing to be confident about.
TIER_THRESHOLD: dict[str, float | None] = {
    "alias": None,
    "structured": None,
    "trigram": ALIAS_THRESHOLD,
    "semantic": SEMANTIC_THRESHOLD,
    "llm": ALIAS_THRESHOLD,
}

# ---------------------------------------------------------------------
# What a caller may STRUCTURALLY know a phrase to be
# ---------------------------------------------------------------------
# These are read off the Claim Card specification (§R11), never off the
# phrase. §R11 defines `target` as "the measured or claimed outcome" and
# `intervention` as "what is being done or taken" -- so a caller reading
# those fields knows which kind of thing it is holding without inspecting a
# single word of it. That is the only sort of type a guard may use: a type
# inferred from wording would be the resolver deciding what it wants the
# answer to be and then checking against its own decision.
#
# Where no caller knows, the answer is None -- UNKNOWN, not a guess. A type
# guard with an untrustworthy source type is not a guard.
# DRIVER is in TARGET_TYPES on the merits, not because something failed
# without it: the enum's own grouping puts CONDITION, PHYSIOLOGY, DRIVER,
# BIOMARKER, SYMPTOM and OUTCOME together as things a body IS or DOES, and
# INTERVENTION, NUTRIENT, FOOD, EXERCISE and BEHAVIOUR as things done TO it.
# A claim can measure a driver -- "X reduces inflammation" -- so a driver is
# a legitimate `target`. Recorded because the K1 seed contains no DRIVER
# concept at all, so only a fixture exercises this arm today.
TARGET_TYPES = frozenset({
    "OUTCOME", "BIOMARKER", "PHYSIOLOGY", "DRIVER", "CONDITION", "SYMPTOM"})
INTERVENTION_TYPES = frozenset({
    "INTERVENTION", "EXERCISE", "BEHAVIOUR", "NUTRIENT", "FOOD",
    "MEDICATION_CONTEXT"})

# Identifiers a clinical phrase may carry verbatim. Structured mapping is
# tier 2 because a phrase containing "HbA1c" is not a similarity question.
STRUCTURED_IDENTIFIERS = {
    "hba1c": "HBA1C", "a1c": "HBA1C", "glycated haemoglobin": "HBA1C",
    "ldl": "LDL_C", "ldl-c": "LDL_C", "hdl": "HDL_C", "hdl-c": "HDL_C",
    "tg": "TRIGLYCERIDES", "alt": "ALT", "sgpt": "ALT", "ast": "AST",
    "tsh": "TSH", "homa-ir": "HOMA_IR", "crp": "HS_CRP", "hs-crp": "HS_CRP",
}


# The schema types every method column as resolution_method. The tier names
# used internally are lowercase and readable; this is the single place they
# become the enum, so a new tier cannot reach the database as free text.
DB_METHOD = {
    "alias": "DETERMINISTIC",
    "structured": "STRUCTURED",
    "trigram": "TRIGRAM",
    "semantic": "SEMANTIC",
    "llm": "LLM",
    "cache": "DETERMINISTIC",
    "none": "DETERMINISTIC",
}


def db_method(method: str) -> str:
    return DB_METHOD.get(method, "DETERMINISTIC")


class Candidate:
    """One concept a tier CONSIDERED, with the score that made it a candidate."""

    __slots__ = ("concept_id", "name", "concept_type", "score")

    def __init__(self, concept_id: str, name: str, concept_type: str | None,
                 score: float):
        self.concept_id = str(concept_id)
        self.name = name
        self.concept_type = concept_type
        self.score = float(score)

    def __repr__(self) -> str:
        return f"<{self.name!r} {self.concept_type} {self.score:.3f}>"


class TierResult:
    """What a tier considered, and what -- if anything -- it SELECTED.

    These are two different things and the old contract was one list used
    for both. `_tier_*` returned `(ids, confidence)` and `resolve()` cached,
    aliased and returned exactly those ids, so widening what a tier LOOKED
    AT would have widened what it RESOLVED TO. A semantic tier returning its
    top three would have produced three-concept resolutions the moment no
    confusable pair happened to object -- a phrase silently meaning three
    things, which is the failure `confusable_with()` exists to prevent,
    arriving through the mechanism meant to prevent it.

    So:

      candidates  everything the tier thought worth looking at. The input to
                  the SAFETY checks, and never an answer.
      selected    the concept(s) the tier will stand behind. The only thing
                  that may be cached, aliased or returned.
      confidence  the selection's score.
      rejected    candidates a guard removed, kept so a refusal can be
                  reported rather than merely happening.
    """

    __slots__ = ("selected", "candidates", "confidence", "note", "rejected")

    def __init__(self, selected: list[str] | None = None,
                 candidates: list[Candidate] | None = None,
                 confidence: float = 0.0, note: str = "",
                 rejected: list[tuple[Candidate, str]] | None = None):
        self.selected = list(selected or [])
        self.candidates = list(candidates or [])
        self.confidence = float(confidence)
        self.note = note
        self.rejected = list(rejected or [])

    @property
    def candidate_ids(self) -> list[str]:
        return [c.concept_id for c in self.candidates]

    @classmethod
    def empty(cls, note: str = "") -> "TierResult":
        return cls(note=note)

    @classmethod
    def exact(cls, candidates: list[Candidate], confidence: float) -> "TierResult":
        """An EXACT tier: everything it found is also what it selected.

        Preserved deliberately for alias, structured and trigram so this
        refactor changes no tier's behaviour except the one being built.
        """
        return cls(selected=[c.concept_id for c in candidates],
                   candidates=candidates, confidence=confidence)

    def __repr__(self) -> str:
        return (f"<TierResult selected={len(self.selected)} "
                f"candidates={len(self.candidates)} conf={self.confidence:.3f}>")


def _candidates_from(conn, ids: list[str], score: float) -> list[Candidate]:
    """Attach name and concept_type to ids a tier matched by other means."""
    if not ids:
        return []
    rows = conn.execute(
        """select concept_id::text, canonical_name, concept_type::text
             from concepts where concept_id = any(%s::uuid[])""", (ids,)).fetchall()
    found = {r[0]: (r[1], r[2]) for r in rows}
    return [Candidate(i, *found.get(i, (None, None)), score) for i in ids
            if i in found]


class Resolution:
    """One phrase's outcome. `concept_ids` may be empty; that is an answer."""

    def __init__(self, phrase: str, concept_ids: list[str], method: str,
                 confidence: float, decision: str, note: str = ""):
        self.phrase = phrase
        self.concept_ids = concept_ids
        self.method = method
        self.confidence = confidence
        self.decision = decision      # RESOLVED / AUTO_ALIAS / AUTO_CREATE / LOGGED / ESCALATED
        self.note = note

    def __repr__(self) -> str:
        return (f"<{self.decision} {self.method} conf={self.confidence:.2f} "
                f"n={len(self.concept_ids)} {self.phrase!r}>")


def norm(conn, phrase: str) -> str:
    """The deterministic normalizer the STORED generated columns use."""
    return conn.execute("select norm_phrase(%s)", (phrase,)).fetchone()[0]


def _capability(conn, name: str) -> bool:
    row = conn.execute(
        "select enabled from system_capabilities where capability=%s", (name,)).fetchone()
    return bool(row and row[0])


# ---------------------------------------------------------------------
# Confusable guard
# ---------------------------------------------------------------------

def confusable_with(conn, concept_ids: list[str]) -> list[tuple[str, str]]:
    """Pairs within this answer that are explicitly marked do-not-merge.

    Returning two concepts that the ontology says must never be merged is
    not a richer answer, it is a wrong one: it hands the retrieval layer a
    phrase that means both "central adiposity" and "visceral fat".
    """
    if len(concept_ids) < 2:
        return []
    rows = conn.execute(
        """select c1.canonical_key, c2.canonical_key
             from concept_relations r
             join concepts c1 on c1.concept_id = r.from_concept
             join concepts c2 on c2.concept_id = r.to_concept
            where r.relation_type = 'CONFUSABLE_DO_NOT_MERGE'
              and r.from_concept = any(%s::uuid[])
              and r.to_concept   = any(%s::uuid[])""",
        (concept_ids, concept_ids)).fetchall()
    return [(a, b) for a, b in rows]


# ---------------------------------------------------------------------
# Tier 1-4
# ---------------------------------------------------------------------

def _tier_alias(conn, phrase_norm: str, **_) -> TierResult:
    rows = conn.execute(
        """select a.concept_id from concept_aliases a
             join concepts c on c.concept_id = a.concept_id
            where a.alias_norm = %s and a.confirmed
              and c.status in ('SEEDED','ACTIVE')""", (phrase_norm,)).fetchall()
    if rows:
        return TierResult.exact(
            _candidates_from(conn, [str(r[0]) for r in rows], 1.0), 1.0)
    rows = conn.execute(
        """select concept_id from concepts
            where norm_phrase(canonical_name) = %s
              and status in ('SEEDED','ACTIVE')""", (phrase_norm,)).fetchall()
    if not rows:
        return TierResult.empty()
    return TierResult.exact(
        _candidates_from(conn, [str(r[0]) for r in rows], 1.0), 1.0)


def _tier_structured(conn, phrase_norm: str, **_) -> TierResult:
    key = None
    for token, canonical in STRUCTURED_IDENTIFIERS.items():
        if token == phrase_norm or f" {token} " in f" {phrase_norm} ":
            key = canonical
            break
    if key is None:
        return TierResult.empty()
    rows = conn.execute(
        """select concept_id from concepts
            where canonical_key = %s and status in ('SEEDED','ACTIVE')""", (key,)).fetchall()
    if not rows:
        return TierResult.empty()
    return TierResult.exact(
        _candidates_from(conn, [str(r[0]) for r in rows], 0.99), 0.99)


def _tier_trigram(conn, phrase_norm: str, **_) -> TierResult:
    if not _capability(conn, "pg_trgm"):
        return TierResult.empty("pg_trgm absent (D15)")
    rows = conn.execute(
        """select c.concept_id::text, c.canonical_name, c.concept_type::text,
                  greatest(similarity(norm_phrase(c.canonical_name), %s),
                           coalesce(max(similarity(a.alias_norm, %s)), 0)) as sim
             from concepts c
             left join concept_aliases a on a.concept_id = c.concept_id
            where c.status in ('SEEDED','ACTIVE')
            group by c.concept_id, c.canonical_name, c.concept_type
           having greatest(similarity(norm_phrase(c.canonical_name), %s),
                           coalesce(max(similarity(a.alias_norm, %s)), 0)) >= %s
            order by sim desc limit 5""",
        (phrase_norm, phrase_norm, phrase_norm, phrase_norm, CREATE_THRESHOLD)).fetchall()
    if not rows:
        return TierResult.empty()
    best = float(rows[0][3])
    # Only tie-level matches join the answer; a clear winner stays alone.
    # This tier's candidate set is deliberately still its selection: widening
    # what trigram LOOKS AT changes what it already does, and the measurement
    # that justifies the wider set was made on cosine, not on pg_trgm.
    tied = [Candidate(r[0], r[1], r[2], float(r[3]))
            for r in rows if float(r[3]) >= best - 0.01]
    return TierResult.exact(tied, best)


def _tier_semantic(conn, phrase_norm: str, *, phrase: str | None = None,
                   embed_call=None, **_) -> TierResult:
    """Cosine similarity over the embedded concepts. The synonym tier.

    This is the ONLY tier that can cross a vocabulary boundary.
    `postprandial walking` is twenty characters and trigram's best match is
    `postprandial glucose` at 0.448 -- it matched the wrong word of the two,
    because `postprandial` shares trigrams and `walking` cannot reach
    `post-meal movement` by any amount of character overlap. Cosine puts
    `post-meal movement` first at 0.833. It is synonymy, not length, and no
    trigram threshold reaches it (D51).

    The RAW phrase is embedded, not `phrase_norm`: concepts are embedded
    from `search_text`, which is raw `canonical_name || definition`, and
    comparing a punctuation-stripped query against unstripped documents
    would measure the normalizer as much as the meaning.

    Three degradations, all NAMED rather than raised (V3). The VPS runs with
    MODEL_EMBEDDING deliberately unset, so "this tier is inert in
    production today" is a supported state and must say so -- a resolver
    that raised there would take down every caller.
    """
    if not _capability(conn, "vector"):
        return TierResult.empty("pgvector absent (D15): the semantic tier cannot run")
    if not os.environ.get("MODEL_EMBEDDING", "").strip():
        return TierResult.empty(
            "MODEL_EMBEDDING is not set: the phrase cannot be embedded, so the "
            "semantic tier is skipped (alias, structured and trigram only)")
    if embed_call is None and not os.environ.get("LLM_API_KEY", "").strip():
        # No credential, no call. `run_engine` already treats an empty
        # LLM_API_KEY as "use the fixture provider, spend nothing", and the
        # VPS runs with it empty on purpose; without this the tier reached
        # for the live endpoint anyway and every suite that resolves a
        # phrase started paying -- or, with no key, getting a 404 from
        # inside the resolver, which is a worse way to learn the same thing.
        # An injected `embed_call` is its own transport and needs no key.
        return TierResult.empty(
            "LLM_API_KEY is not set: no provider call may be made, so the "
            "semantic tier is skipped (alias, structured and trigram only)")
    embedded = conn.execute(
        "select count(*) from concepts where embedding is not null "
        "and status in ('SEEDED','ACTIVE')").fetchone()[0]
    if not embedded:
        return TierResult.empty(
            "no concept is embedded yet: run scripts/embed_library.py --table concepts")

    # embedding.embed() is the ONE embedding boundary (D38): it pins the
    # model, refuses non-text, checks the dimension and the unit norm, and
    # prices the call. A second client here would be a second place for a
    # 0.702-norm vector to get in.
    vector, _model, _dims = embedding.embed(
        conn, phrase if phrase is not None else phrase_norm,
        entity_type="normalization_query", call=embed_call)
    q = str(vector)

    rows = conn.execute(
        """select concept_id::text, canonical_name, concept_type::text,
                  (1 - (embedding <=> %s::vector))::float as score
             from concepts
            where status in ('SEEDED','ACTIVE') and embedding is not null
            order by embedding <=> %s::vector
            limit %s""", (q, q, SEMANTIC_CANDIDATES)).fetchall()
    if not rows:
        return TierResult.empty()

    candidates = [Candidate(r[0], r[1], r[2], max(0.0, float(r[3]))) for r in rows]
    best = candidates[0].score
    if best < SEMANTIC_FLOOR:
        # Below the floor the tier says NOTHING, deliberately: the phrase
        # must stay free to reach AUTO_CREATE. `1-deoxynojirimycin` scores
        # 0.613 against `HbA1c` and is a genuinely new concept -- a tier
        # that reported that as a near-match would convert it into a LOGGED
        # proposal with no concept created, and the library would never
        # learn the word.
        return TierResult.empty(
            f"best cosine {best:.3f} is below the semantic floor {SEMANTIC_FLOOR}")

    # SELECTION IS THE TOP-1, AND ONLY THE TOP-1. The rest stay candidates:
    # they are what the confusable guard reads, and they are not the answer.
    #
    # Trigram's tie rule (everything within 0.01 of the best joins the
    # answer) does NOT transfer, and applying it here was the first thing
    # this tier got wrong. Cosine scores are dense where trigram's are
    # coarse: `postprandial walking` gives `post-meal movement` 0.833 and
    # `postprandial glucose` 0.828, five thousandths apart and an
    # INTERVENTION and a PHYSIOLOGY -- a tie rule would have resolved the
    # phrase to both and quietly created exactly the multi-meaning concept
    # this file exists to prevent. Two near-equal cosine scores mean the
    # query sits BETWEEN two concepts, which is an ambiguity, not a
    # statement that they are the same thing.
    return TierResult(selected=[candidates[0].concept_id],
                      candidates=candidates, confidence=best)


def type_rejection(conn, tier: TierResult,
                   allowed_types: frozenset[str] | set[str] | None
                   ) -> tuple[Candidate, str] | None:
    """Refuse a selection whose concept_type the caller did not allow.

    Most of the wrong merges the diagnosis found are CATEGORY CROSSINGS, not
    near-misses: a TIME WINDOW, a DRUG CLASS, a MOLECULE and a MECHANISM all
    mapping to a BIOMARKER at scores a threshold would happily admit.
    `concepts.concept_type` already tells these apart and the resolver never
    consulted it.

    It REFUSES; it never shops. If the top candidate is the wrong kind of
    thing, the tier answers nothing -- it does not walk down the list for
    something type-compatible, because picking the second-best BECAUSE it
    matches the expected type is manufacturing the answer the caller asked
    for. The cost is a real one and is measured: a right answer whose seeded
    type disagrees with the caller is refused too.

    `allowed_types is None` means the caller does not structurally know, and
    then there is nothing to check. That is a genuine answer, not a gap to
    fill with a guess.
    """
    if not allowed_types or not tier.selected:
        return None
    by_id = {c.concept_id: c for c in tier.candidates}
    for concept_id in tier.selected:
        candidate = by_id.get(concept_id)
        if candidate is None or candidate.concept_type is None:
            continue
        if candidate.concept_type not in allowed_types:
            return (candidate,
                    f"{candidate.name!r} is {candidate.concept_type}; the caller "
                    f"allows {sorted(allowed_types)}")
    return None


# ---------------------------------------------------------------------
# Escalation, ranked by impact
# ---------------------------------------------------------------------

def impact_score(conn, phrase_norm: str) -> int:
    """How much rides on getting this phrase right.

    D8: escalation ranks by IMPACT, not uncertainty. An ambiguous concept
    touching forty strategies matters; an ambiguous one-off does not.
    """
    return int(conn.execute(
        """select coalesce(count(*), 0) from strategy_concepts sc
             join concepts c on c.concept_id = sc.concept_id
            where similarity(norm_phrase(c.canonical_name), %s) > 0.5""",
        (phrase_norm,)).fetchone()[0]) if _capability(conn, "pg_trgm") else 0


def escalations_this_week(conn) -> int:
    return int(conn.execute(
        """select count(*) from concept_proposals
            where decision='ESCALATED' and created_at > now() - interval '7 days'"""
    ).fetchone()[0])


# ---------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------

def resolve(conn, phrase: str, context: str | None = None,
            llm=None, use_cache: bool = True,
            read_only: bool = False,
            allowed_types: frozenset[str] | set[str] | None = None,
            embed_call=None) -> Resolution:
    """Resolve one clinical phrase to canonical concepts.

    `llm` is an optional callable(phrase, candidates) -> dict, used ONLY
    when the deterministic tiers cannot answer. It is injected rather than
    imported so the suite can prove the cheap tiers do not call it.

    `allowed_types` is the set of `concept_type` values the CALLER
    structurally knows this phrase may be -- `TARGET_TYPES` when it came
    from a Claim Card `target`, `INTERVENTION_TYPES` from an `intervention`
    (§R11 defines both). `None` means unknown, and unknown imposes no
    constraint: a type inferred from the phrase's own wording would be the
    resolver marking its own homework.

    `embed_call` replaces the provider transport for the semantic tier, the
    way `retrieval.by_vector` already does, so a suite can drive the real
    tier without paying for a call (V2).

    `read_only=True` runs the SAME tiers and writes NOTHING: no cache row,
    no alias, no proposal, no escalation. It exists for layer B of the
    evaluation (D7, migration 024). A held-out source is the answer key,
    and the ordinary path would quietly write its vocabulary into the
    ontology as PROPOSED concepts and trigram aliases -- so the library
    being measured would have learned from the material it is being
    measured against. The tiers are unchanged deliberately: a second
    matcher written for evaluation would be measuring a different resolver
    than production uses.
    """
    phrase_norm = norm(conn, phrase)

    # A cache HIT bumps hit_count, which is a write -- small, but it would
    # make the cache look hotter than the runtime made it, and read_only
    # means read_only. The tiers produce what the cache stored anyway.
    if use_cache and not read_only:
        cached = conn.execute(
            """select concept_ids, method, confidence from normalization_cache
                where phrase_norm=%s""", (phrase_norm,)).fetchone()
        if cached:
            conn.execute(
                """update normalization_cache
                      set hit_count = hit_count + 1, last_used = now()
                    where phrase_norm=%s""", (phrase_norm,))
            return Resolution(phrase, [str(c) for c in cached[0]], "cache",
                              float(cached[2] or 1.0), "RESOLVED",
                              f"cached from {cached[1]}")

    # A tier that answers WEAKLY no longer ends the chain. It used to: a
    # trigram near-match at 0.778 returned LOGGED and the semantic tier was
    # never reached, so `Postprandial glucose spike` -- which cosine places
    # on `postprandial glucose` at 0.955 -- was logged as an ambiguity by a
    # tier that had matched the wrong word. The near-match is REMEMBERED
    # instead, and becomes the outcome only if nothing later can do better.
    near: tuple[str, TierResult] | None = None
    refused: str | None = None

    for method, fn in (("alias", _tier_alias), ("structured", _tier_structured),
                       ("trigram", _tier_trigram), ("semantic", _tier_semantic)):
        tier = fn(conn, phrase_norm, phrase=phrase, embed_call=embed_call)
        if not tier.candidates:
            continue

        # SAFETY FIRST, and over the whole candidate set -- before any type
        # filtering. A do-not-merge pair objects whatever the caller expected
        # the type to be: the ontology recorded that these two must not be
        # collapsed, and a caller's type hint is not authority to overrule it.
        clash = confusable_with(conn, tier.candidate_ids)
        if clash:
            if read_only:
                return Resolution(phrase, [], method, tier.confidence, "UNRESOLVED",
                                  f"read-only: candidates span CONFUSABLE_DO_NOT_MERGE {clash}")
            return _escalate(conn, phrase, phrase_norm, tier.selected or tier.candidate_ids,
                             tier.confidence, method,
                             f"candidates span CONFUSABLE_DO_NOT_MERGE pair(s): {clash}")

        # THE TYPE GUARD APPLIES TO THE SIMILARITY TIERS ONLY.
        #
        # alias and structured are EXACT: the phrase is literally the
        # concept's confirmed alias or canonical name, or it carries the
        # identifier. That is an identity, not a guess, and a caller's
        # expectation is not authority to overrule it -- the first version
        # applied the guard everywhere and refused `postprandial glucose`
        # against the concept named `postprandial glucose`, because the
        # ontology had typed it something the caller had not listed. An
        # exact match to a concept of an unexpected type is a fact about how
        # that concept is TYPED, and the place to fix it is the concept.
        rejection = (type_rejection(conn, tier, allowed_types)
                     if method in ("trigram", "semantic") else None)
        if rejection is not None:
            candidate, why = rejection
            tier.rejected.append(rejection)
            note = f"refused on concept_type: {why}"
            refused = note
            # A category crossing is not an ambiguity to escalate and not a
            # near-match to log against: the candidate is the wrong KIND of
            # thing, so the phrase carries on as if this tier had not spoken.
            #
            # read_only takes the SAME branch, deliberately. An earlier
            # version returned here while the ordinary path continued, so
            # `evaluate.py`'s layer B answer key and `curated_import` would
            # have reported an outcome production never produces -- a
            # read-only mode that resolves differently from the mode it
            # exists to observe is the harness/production gap V2 is about.
            if not read_only:
                _proposal(conn, phrase, phrase_norm, context, candidate.concept_id,
                          tier.confidence, method, "LOGGED", note)
            continue

        threshold = TIER_THRESHOLD[method]
        if tier.selected and (threshold is None or tier.confidence >= threshold):
            if read_only:
                return Resolution(phrase, tier.selected, method, tier.confidence,
                                  "RESOLVED", "read-only")
            _cache(conn, phrase_norm, tier.selected, method, tier.confidence)
            if method == "trigram":
                _attach_alias(conn, tier.selected[0], phrase, phrase_norm,
                              method, tier.confidence, threshold)
            # THE SEMANTIC TIER ATTACHES NO ALIAS, and that is deliberate.
            #
            # A confirmed alias is read by the alias tier at confidence 1.0
            # forever: an IDENTITY rule that bypasses the confusable guard,
            # the type guard and every later tier for that phrase,
            # permanently, on the strength of one cosine score. Trigram at
            # 0.92 is near-identity and may say that; cosine at 0.82 is
            # "these mean similar things" and may not. The first version of
            # this tier confirmed an alias at 0.8211 -- one thousandth over
            # the threshold -- onto a SEEDED concept, where it outlived the
            # suite that created it.
            #
            # Writing it UNCONFIRMED does not fix it, which is the part worth
            # knowing: `_tier_trigram` takes max(similarity(a.alias_norm,...))
            # over concept_aliases WITHOUT filtering on `confirmed`, so an
            # unconfirmed row still returns 1.0 there. An "inert record" is
            # not inert when another tier reads the table without the flag.
            # (That missing filter is pre-existing and is reported, not
            # changed here -- it also governs aliases the LLM tier writes.)
            #
            # Nothing is lost by refusing. `_cache` above is what stops a
            # repeat phrase costing a second provider call, which is what D2
            # actually asks for; the alias table was never load-bearing for
            # that.
            return Resolution(phrase, tier.selected, method, tier.confidence,
                              "RESOLVED")

        # Real but not certain. Remember the best one seen and keep going.
        if near is None or tier.confidence > near[1].confidence:
            near = (method, tier)

    if near is not None:
        method, tier = near
        ids = tier.selected or tier.candidate_ids
        if read_only:
            # The ordinary path escalates or logs; both write, and neither
            # is an answer.
            return Resolution(phrase, [], method, tier.confidence, "UNRESOLVED",
                              "read-only: below the tier's own threshold")
        impact = impact_score(conn, phrase_norm)
        if impact > 0 and escalations_this_week(conn) < WEEKLY_CAP:
            return _escalate(conn, phrase, phrase_norm, ids, tier.confidence, method,
                             f"ambiguous, impact={impact}")
        return _log(conn, phrase, phrase_norm, ids, tier.confidence, method,
                    f"low-impact ambiguity, impact={impact}")

    # Nothing deterministic answered. This is where, and only where, an LLM
    # is worth paying for.
    if read_only:
        # No LLM tier either: it is the most expensive way to reach the
        # same place, and its successful branch attaches an alias.
        return Resolution(phrase, [], "none", 0.0, "UNRESOLVED",
                          f"read-only: {refused}" if refused
                          else "read-only: nothing deterministic matched")

    if llm is not None:
        candidates = conn.execute(
            """select concept_id, canonical_key, canonical_name from concepts
                where status in ('SEEDED','ACTIVE') limit 40""").fetchall()
        verdict = llm(phrase, [{"concept_id": str(c), "key": k, "name": n}
                               for c, k, n in candidates]) or {}
        ids = [str(i) for i in verdict.get("concept_ids", [])]
        confidence = float(verdict.get("confidence", 0.0))
        if ids and confidence >= ALIAS_THRESHOLD and not confusable_with(conn, ids):
            _cache(conn, phrase_norm, ids, "llm", confidence)
            _attach_alias(conn, ids[0], phrase, phrase_norm, "llm", confidence)
            return Resolution(phrase, ids, "llm", confidence, "RESOLVED")
        if confidence < CREATE_THRESHOLD:
            return _propose_new(conn, phrase, phrase_norm, context, confidence,
                                verdict.get("concept_type", "PHYSIOLOGY"))
        return _escalate(conn, phrase, phrase_norm, ids, confidence, "llm",
                         "LLM was not confident enough to alias or to create")

    return _propose_new(conn, phrase, phrase_norm, context, 0.0, "PHYSIOLOGY")


# ---------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------

def _cache(conn, phrase_norm: str, ids: list[str], method: str, confidence: float) -> None:
    """A confirmed result is cached so a phrase never costs a second call (D2)."""
    conn.execute(
        """insert into normalization_cache (phrase_norm, concept_ids, method, confidence)
           values (%s,%s::uuid[],%s,%s)
           on conflict (phrase_norm) do update
             set concept_ids = excluded.concept_ids,
                 method = excluded.method,
                 confidence = excluded.confidence,
                 hit_count = normalization_cache.hit_count + 1,
                 last_used = now()""",
        (phrase_norm, ids, db_method(method), confidence))


def _attach_alias(conn, concept_id: str, phrase: str, phrase_norm: str,
                  method: str, confidence: float,
                  threshold: float | None = None,
                  confirmed: bool | None = None) -> None:
    """Learn the phrase so it never costs a second similarity query (D2).

    `confirmed` is judged against the THRESHOLD OF THE TIER THAT ANSWERED,
    not against the trigram constant. A cosine 0.84 is a confident semantic
    answer and an impossible trigram one; scoring it against 0.92 would file
    every semantic resolution as an unconfirmed alias, which the alias tier
    then refuses to read -- the resolution would be learned into a row
    nothing looks at.
    """
    if threshold is None:
        threshold = ALIAS_THRESHOLD
    conn.execute(
        """insert into concept_aliases
             (concept_id, alias_text, method, confidence, confirmed)
           values (%s,%s,%s,%s,%s)
           on conflict do nothing""",
        (concept_id, phrase, db_method(method), confidence,
         (confidence >= threshold) if confirmed is None else confirmed))


def _proposal(conn, phrase: str, phrase_norm: str, context: str | None,
              candidate: str | None, similarity: float, method: str,
              decision: str, note: str, impact: int = 0) -> str:
    return str(conn.execute(
        """insert into concept_proposals
             (raw_phrase, context, candidate_concept, similarity, method,
              impact_score, decision, decision_note)
           values (%s,%s,%s,%s,%s,%s,%s,%s) returning proposal_id""",
        (phrase, context, candidate, similarity, db_method(method), impact,
         decision, note)
    ).fetchone()[0])


def _escalate(conn, phrase, phrase_norm, ids, confidence, method, note) -> Resolution:
    _proposal(conn, phrase, phrase_norm, None, ids[0] if ids else None,
              confidence, method, "ESCALATED", note, impact_score(conn, phrase_norm))
    return Resolution(phrase, [], method, confidence, "ESCALATED", note)


def _log(conn, phrase, phrase_norm, ids, confidence, method, note) -> Resolution:
    _proposal(conn, phrase, phrase_norm, None, ids[0] if ids else None,
              confidence, method, "LOGGED", note)
    return Resolution(phrase, [], method, confidence, "LOGGED", note)


def _propose_new(conn, phrase: str, phrase_norm: str, context: str | None,
                 confidence: float, concept_type: str) -> Resolution:
    """A phrase nothing matched becomes a PROPOSED concept, never a canonical one.

    D8 allows this to happen without a human -- the practitioner's time is
    the scarce resource -- but `status='PROPOSED'` is what keeps it out of
    retrieval until something deliberate promotes it. Automatic is not the
    same as canonical.
    """
    # ck_canonical_key_shape is ^[A-Z][A-Z0-9_]{2,79}$, and the old rule
    # here (upper + spaces to underscores) produced
    # LARGE_POST-MEAL_GLUCOSE_EXCURSIONS, which the database rejected
    # outright. That phrase is D2's own example of what normalization is
    # for; this suite never hit it because its fixtures have no
    # punctuation, and the first CLIENT_NEW run did. One rule now, shared
    # with the seeder (scripts/concept_key.py).
    key = concept_key.key_for(phrase_norm)
    existing = conn.execute(
        "select concept_id, norm_phrase(canonical_name) from concepts "
        "where canonical_key=%s", (key,)).fetchone()
    if existing and existing[1] == phrase_norm:
        # Same phrase modulo punctuation -- one concept, not two.
        concept_id = str(existing[0])
    elif existing:
        # Different phrase, same key: 80-character truncation can collide
        # two unrelated long phrases, and reusing a concept because its KEY
        # matched is a silent merge (D3). Suffix rather than merge.
        key = concept_key.disambiguate(key, phrase_norm)
        concept_id = str(conn.execute(
            """insert into concepts
                 (canonical_key, canonical_name, concept_type, status,
                  origin_method, origin_detail)
               values (%s,%s,%s,'PROPOSED','DETERMINISTIC',%s)
               on conflict (canonical_key) do update set canonical_key = excluded.canonical_key
               returning concept_id""",
            (key, phrase, concept_type,
             "C3_NORMALIZATION: proposed from an unmatched phrase whose key "
             f"collided with an existing concept; context: {context or 'none'}")
        ).fetchone()[0])
    else:
        concept_id = str(conn.execute(
            """insert into concepts
                 (canonical_key, canonical_name, concept_type, status,
                  origin_method, origin_detail)
               values (%s,%s,%s,'PROPOSED','DETERMINISTIC',%s)
               returning concept_id""",
            (key, phrase, concept_type,
             "C3_NORMALIZATION: proposed from an unmatched phrase; "
             f"context: {context or 'none'}")
        ).fetchone()[0])
    _proposal(conn, phrase, phrase_norm, context, concept_id, confidence,
              "none", "AUTO_CREATE", "no deterministic tier matched")
    # NOT cached: a proposal is not a confirmed mapping.
    return Resolution(phrase, [], "none", confidence, "AUTO_CREATE",
                      f"proposed new concept {key} with status PROPOSED")


def resolve_all(conn, phrases: list[str], context: str | None = None,
                llm=None, allowed_types: frozenset[str] | set[str] | None = None,
                embed_call=None) -> list[Resolution]:
    """NORMALIZATION_PHRASES from an Engine 1 Pass A control block.

    `allowed_types` defaults to None for this caller and should stay there:
    Pass A emits one flat list of phrases with no field structure, so
    nothing here knows which of them is a biomarker and which an
    intervention. Unknown is the correct answer (D51).
    """
    return [resolve(conn, p, context=context, llm=llm,
                    allowed_types=allowed_types, embed_call=embed_call)
            for p in phrases]
