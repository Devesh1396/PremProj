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

ALIAS_THRESHOLD = float(os.environ.get("CONCEPT_AUTO_ALIAS_THRESHOLD", "0.92"))
CREATE_THRESHOLD = float(os.environ.get("CONCEPT_AUTO_CREATE_THRESHOLD", "0.72"))
WEEKLY_CAP = int(os.environ.get("CONCEPT_ESCALATION_WEEKLY_CAP", "15"))

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

def _tier_alias(conn, phrase_norm: str) -> tuple[list[str], float]:
    rows = conn.execute(
        """select a.concept_id from concept_aliases a
             join concepts c on c.concept_id = a.concept_id
            where a.alias_norm = %s and a.confirmed
              and c.status in ('SEEDED','ACTIVE')""", (phrase_norm,)).fetchall()
    if rows:
        return [str(r[0]) for r in rows], 1.0
    rows = conn.execute(
        """select concept_id from concepts
            where norm_phrase(canonical_name) = %s
              and status in ('SEEDED','ACTIVE')""", (phrase_norm,)).fetchall()
    return ([str(r[0]) for r in rows], 1.0) if rows else ([], 0.0)


def _tier_structured(conn, phrase_norm: str) -> tuple[list[str], float]:
    key = None
    for token, canonical in STRUCTURED_IDENTIFIERS.items():
        if token == phrase_norm or f" {token} " in f" {phrase_norm} ":
            key = canonical
            break
    if key is None:
        return [], 0.0
    rows = conn.execute(
        """select concept_id from concepts
            where canonical_key = %s and status in ('SEEDED','ACTIVE')""", (key,)).fetchall()
    return ([str(r[0]) for r in rows], 0.99) if rows else ([], 0.0)


def _tier_trigram(conn, phrase_norm: str) -> tuple[list[str], float]:
    if not _capability(conn, "pg_trgm"):
        return [], 0.0
    rows = conn.execute(
        """select c.concept_id,
                  greatest(similarity(norm_phrase(c.canonical_name), %s),
                           coalesce(max(similarity(a.alias_norm, %s)), 0)) as sim
             from concepts c
             left join concept_aliases a on a.concept_id = c.concept_id
            where c.status in ('SEEDED','ACTIVE')
            group by c.concept_id, c.canonical_name
           having greatest(similarity(norm_phrase(c.canonical_name), %s),
                           coalesce(max(similarity(a.alias_norm, %s)), 0)) >= %s
            order by sim desc limit 5""",
        (phrase_norm, phrase_norm, phrase_norm, phrase_norm, CREATE_THRESHOLD)).fetchall()
    if not rows:
        return [], 0.0
    best = float(rows[0][1])
    # Only tie-level matches join the answer; a clear winner stays alone.
    return [str(r[0]) for r in rows if float(r[1]) >= best - 0.01], best


def _tier_semantic(conn, phrase_norm: str) -> tuple[list[str], float]:
    # Requires pgvector AND embeddings actually written. Neither is true
    # until K14, so this tier reports "cannot answer" rather than pretending.
    if not _capability(conn, "vector"):
        return [], 0.0
    embedded = conn.execute(
        "select count(*) from concepts where embedding is not null").fetchone()[0]
    if embedded == 0:
        return [], 0.0
    return [], 0.0


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
            llm=None, use_cache: bool = True) -> Resolution:
    """Resolve one clinical phrase to canonical concepts.

    `llm` is an optional callable(phrase, candidates) -> dict, used ONLY
    when the deterministic tiers cannot answer. It is injected rather than
    imported so the suite can prove the cheap tiers do not call it.
    """
    phrase_norm = norm(conn, phrase)

    if use_cache:
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

    for method, fn in (("alias", _tier_alias), ("structured", _tier_structured),
                       ("trigram", _tier_trigram), ("semantic", _tier_semantic)):
        ids, confidence = fn(conn, phrase_norm)
        if not ids:
            continue

        clash = confusable_with(conn, ids)
        if clash:
            # Never return an answer that merges a do-not-merge pair.
            return _escalate(conn, phrase, phrase_norm, ids, confidence, method,
                             f"resolution spans CONFUSABLE_DO_NOT_MERGE pair(s): {clash}")

        if method in ("alias", "structured") or confidence >= ALIAS_THRESHOLD:
            _cache(conn, phrase_norm, ids, method, confidence)
            if method == "trigram":
                _attach_alias(conn, ids[0], phrase, phrase_norm, method, confidence)
            return Resolution(phrase, ids, method, confidence, "RESOLVED")

        # Between the thresholds: real but not certain.
        impact = impact_score(conn, phrase_norm)
        if impact > 0 and escalations_this_week(conn) < WEEKLY_CAP:
            return _escalate(conn, phrase, phrase_norm, ids, confidence, method,
                             f"ambiguous, impact={impact}")
        return _log(conn, phrase, phrase_norm, ids, confidence, method,
                    f"low-impact ambiguity, impact={impact}")

    # Nothing deterministic answered. This is where, and only where, an LLM
    # is worth paying for.
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
                  method: str, confidence: float) -> None:
    conn.execute(
        """insert into concept_aliases
             (concept_id, alias_text, method, confidence, confirmed)
           values (%s,%s,%s,%s,%s)
           on conflict do nothing""",
        (concept_id, phrase, db_method(method), confidence,
         confidence >= ALIAS_THRESHOLD))


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
    key = phrase_norm.upper().replace(" ", "_")[:80]
    existing = conn.execute(
        "select concept_id from concepts where canonical_key=%s", (key,)).fetchone()
    if existing:
        concept_id = str(existing[0])
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
                llm=None) -> list[Resolution]:
    """NORMALIZATION_PHRASES from an Engine 1 Pass A control block."""
    return [resolve(conn, p, context=context, llm=llm) for p in phrases]
