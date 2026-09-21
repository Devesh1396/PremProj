#!/usr/bin/env python3
"""GATE 3 — concept units from a curated card, deterministically.

D52; migrations `038`/`039`. NO MODEL CALL FOR EXTRACTION. The only
provider call anywhere in this file is inside `normalize.resolve()`, which
is the ONE embedding boundary (D38) and is asked to MATCH a phrase, never
to invent one.

### What this is allowed to do

Take spans of the practitioner's own characters and offer them to the
concept resolver. That is all. It may not:

* summarise a paragraph into a concept phrase;
* ask a model for a shorter phrase;
* send a prose block to `normalize.resolve()` -- that is the `mechanism`
  mistake of D51 in a new costume;
* create a concept, of any status, for anything (`read_only=True`).

A field that carries real knowledge and contains no unit any registered
rule recognises stays UNLINKED, and `extract()` reports it. GATE 1 bought
provenance; guessing here would spend it.

### Which units, and why those

`curated_concept_rules` (039). The registry states, per construct, why it
is reusable across sections -- the same anti-overfitting control the
heading grammar carries. The rules are NOT in this file, and the phrase
test that separates a name from a sentence is described in `039`'s header
where a reviewer reads it beside the rules it governs.

### Every unit keeps its byte range, and the range is CHECKED

D48: a stored location that looks right and does not contain the text is
the shape that passes review. `verify()` re-reads the preserved raw source
and asserts `source[start:end] == phrase` for every unit, and `store()`
refuses to write anything at all if one fails -- exactly as
`curated_parser.verify()` already does for fields.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import embed_library as EL
import normalize as NZ

CARD_NAME_FIELD = "strategy_name"

# A unit is a NAME, not a sentence. See `039`'s header: the discriminator
# is grammatical and there is no character count in it, so there is no
# number here to move until a fixture passes.
SENTENCE_MARKS = ('.', '?', '!', ',', '"', '“', '”', '→')


@dataclass(frozen=True)
class Unit:
    rule_id: str
    unit_kind: str
    field_name: str
    phrase: str
    source_start: int
    source_end: int


@dataclass
class Rule:
    rule_id: str
    unit_kind: str
    pattern: str | None
    applies_to: list[str] | None
    priority: int

    @property
    def regex(self) -> re.Pattern | None:
        if not self.pattern:
            return None
        return re.compile(self.pattern, re.M)


def load_rules(conn) -> list[Rule]:
    rows = conn.execute(
        """select rule_id, unit_kind, pattern, applies_to, priority
             from curated_concept_rules where active order by priority, rule_id"""
    ).fetchall()
    return [Rule(*r) for r in rows]


def is_name_shaped(conn, phrase: str) -> tuple[bool, str]:
    """Is this run of characters a NAME, or a statement? (`039` header.)

    Returns (verdict, reason) so a refusal can be REPORTED rather than
    silently dropping the practitioner's text. `to_tsvector` is the
    lexeme test: it is PostgreSQL's own English dictionary, so "a run of
    stopwords names nothing" needs no stopword list invented here.
    """
    s = phrase.strip()
    if not s:
        return False, "empty"
    if s.endswith(':'):
        return False, "colon-terminated: a lead-in, not a name"
    for mark in SENTENCE_MARKS:
        if mark in s:
            return False, f"contains {mark!r}: a statement, not a name"
    lexemes = conn.execute(
        "select count(*) from unnest(to_tsvector('english', %s))", (s,)
    ).fetchone()[0]
    if not lexemes:
        return False, "no lexemes: stopwords only"
    return True, "phrase"


def units_from(conn, rules: list[Rule], field_name: str, text: str,
               offset: int) -> tuple[list[Unit], list[dict]]:
    """Units found in one field's text. `offset` is the field's own
    `source_start`, so every span returned is an offset into the ORIGINAL
    document and not into this fragment.

    Also returns the units a rule MATCHED and the phrase test REFUSED,
    with the reason. A refusal is reported, never invisible: "this bold
    run was a sentence" is how a reader tells a rule that is working from
    one that never fires.
    """
    found: list[Unit] = []
    refused: list[dict] = []
    for rule in rules:
        rx = rule.regex
        if rx is None:
            continue
        if rule.applies_to and field_name not in rule.applies_to:
            continue
        for m in rx.finditer(text):
            inner = m.group("unit")
            at = m.start("unit")
            # The span is tightened onto the characters the phrase
            # actually occupies, so `source[start:end] == phrase` holds
            # with no normalization anywhere.
            lead = len(inner) - len(inner.lstrip())
            phrase = inner.strip()
            if not phrase:
                continue
            start = offset + at + lead
            end = start + len(phrase)
            ok, why = is_name_shaped(conn, phrase)
            if not ok:
                refused.append({"rule_id": rule.rule_id, "field": field_name,
                                "phrase": phrase, "source_start": start,
                                "source_end": end, "reason": why})
                continue
            found.append(Unit(rule.rule_id, rule.unit_kind, field_name,
                              phrase, start, end))
    return found, refused


def card_units(conn, rules: list[Rule], card, *,
               name_is_a_name: bool = True) -> tuple[list[Unit], list[dict]]:
    """Every unit of one `curated_parser.ParsedCard`.

    The card NAME is a unit by construction -- the heading grammar already
    isolated it from the numbering and stored it as a verbatim slice with
    its span -- so it needs no pattern, only a rule saying it is one.
    """
    found: list[Unit] = []
    refused: list[dict] = []

    name_rule = next((r for r in rules if r.unit_kind == "CARD_NAME"), None)
    if name_rule is not None and card.name_start is not None \
            and not name_is_a_name:
        # GATE 4. A CURATED OBJECT'S HEADING IS A TITLE, NOT A NAME.
        #
        # `Strategy 1 — Breakfast restructuring` gives a name. `ADD —
        # Rapid Improvement Is Possible, but Timeline ≠ Biological
        # Guarantee` gives a sentence, and sending it to the resolver is
        # the mechanism mistake in a new costume (D51): a long clause
        # cannot resolve, and any score it did earn would be noise. So the
        # exemption below is withdrawn for objects and the ordinary
        # grammatical test decides. Four of Video 14's eleven headings are
        # refused by it, and refused LOUDLY -- they appear in `refused`
        # with the reason, not dropped.
        ok, why = is_name_shaped(conn, card.name)
        if not ok:
            refused.append({"kind": "CARD_NAME", "field": CARD_NAME_FIELD,
                            "phrase": card.name, "reason": why,
                            "source_start": card.name_start,
                            "source_end": card.name_end})
        else:
            found.append(Unit(name_rule.rule_id, "CARD_NAME", CARD_NAME_FIELD,
                              card.name, card.name_start, card.name_end))
    elif name_rule is not None and card.name_start is not None:
        # The span comes from the PARSER, which cut the name out of the
        # heading. It is never re-derived by searching the document for
        # the string: a name that occurs twice would point the trace at
        # the wrong occurrence, and a range that resolves cleanly to the
        # wrong place is precisely the D48 failure shape.
        #
        # The card name is NOT put through the phrase test. It is a name
        # by construction -- the practitioner wrote it as the title of the
        # unit -- and refusing one because it happens to contain a comma
        # would drop the single unit every curated card is guaranteed to
        # have.
        found.append(Unit(name_rule.rule_id, "CARD_NAME", CARD_NAME_FIELD,
                          card.name, card.name_start, card.name_end))

    for f in card.fields:
        u, r = units_from(conn, rules, f.field_name, f.text_value, f.source_start)
        found += u
        refused += r
    return found, refused


def verify(source_text: str, units: list[Unit]) -> list[str]:
    """Mechanical check: every unit IS its claimed slice of the source.

    D48. A location field being populated is not provenance; the range
    containing the text being attributed to it is. No normalization is
    applied and a mismatch is returned, never repaired.
    """
    problems: list[str] = []
    for u in units:
        actual = source_text[u.source_start:u.source_end]
        if actual != u.phrase:
            problems.append(
                f"{u.field_name} :: {u.rule_id} unit {u.phrase!r} does not "
                f"match source[{u.source_start}:{u.source_end}] = {actual!r}")
    return problems


# ---------------------------------------------------------------------
# Resolution and storage
# ---------------------------------------------------------------------

def resolve_units(conn, units: list[Unit], embed_call=None) -> list[dict]:
    """Run each unit through the GATE 2 resolver, READ-ONLY.

    `allowed_types=None` throughout, and that is a measured decision, not
    laziness. GATE 2 (D51) established that only a caller which
    STRUCTURALLY knows a phrase's kind may supply a type -- and a curated
    card does not: `Breakfast restructuring` is an intervention,
    `Preserve agency and reduce unnecessary deprivation` is a principle,
    and both arrive through the same rule. Assuming the 43
    unknown-provenance D47 phrases were interventions refused 12, ELEVEN
    of which were correct resolutions it would have destroyed. A type
    guard without a trustworthy source of type is not a guard.

    `read_only=True` means the tiers run exactly as production runs them
    and NOTHING is written: no cache row, no alias, no PROPOSED concept.
    Creating concepts here would pollute the ontology to make a retrieval
    test look better, and a PROPOSED concept is not a retrieval anchor
    anyway (D8) -- so the link it bought would be dead weight and the
    ontology damage would be real.
    """
    out = []
    for u in units:
        res = NZ.resolve(conn, u.phrase, context="CURATED_CONCEPT",
                         llm=None, read_only=True, allowed_types=None,
                         embed_call=embed_call)
        concept_id = res.concept_ids[0] if res.concept_ids else None
        key = None
        if concept_id:
            row = conn.execute(
                "select canonical_key from concepts where concept_id=%s",
                (concept_id,)).fetchone()
            key = row[0] if row else None
        out.append({"unit": u, "concept_id": concept_id, "canonical_key": key,
                    "tier": res.method, "score": res.confidence,
                    "decision": res.decision, "note": res.note})
    return out


# ---------------------------------------------------------------------
# RECOMPUTATION IS TRI-STATE, AND ONLY ONE STATE MAY DELETE
# ---------------------------------------------------------------------
#
# The first version deleted every link for a card and rewrote whatever
# this run resolved. That is safe only if every run is equally capable,
# and this build's runs are NOT: the semantic tier is the only tier that
# answers a curated phrase, and it is inert without pgvector, without
# MODEL_EMBEDDING, without a credential or with nothing embedded -- which
# is exactly the configuration the VPS runs on purpose.
#
# So a re-import on a less capable machine would have turned a verified
# link set into zero links and reported it as a successful import. A
# MISSING OPTIONAL CAPABILITY MUST NEVER DEGRADE KNOWLEDGE THAT WAS
# ALREADY ESTABLISHED.
#
#   RECOMPUTED       the resolver could reach every tier, so what it did
#                    not resolve genuinely does not resolve. Authoritative:
#                    the old link set is replaced, and a link that no
#                    longer resolves is correctly removed.
#   FIRST_ATTACHMENT no prior links exist, so nothing can be lost. What
#                    this run found is written even degraded, and a later
#                    authoritative run replaces it.
#   NOT_RECOMPUTED   prior links exist and the resolver could not reach
#                    the tier that produced them. Nothing is touched and
#                    the reason is reported.
#   FAILED_CLOSED    prior links exist, cannot be authoritatively
#                    recomputed, AND no longer sit on the text they name.
#                    Retaining them would keep a span pointing at moved
#                    characters, which is the D48 shape exactly, so they
#                    are DELETED rather than kept. Failing closed loses a
#                    link; retaining would fabricate provenance.
#
# The staleness test is the containment check itself, applied to what is
# already stored -- not a content hash kept in step somewhere. If every
# prior link still IS its claimed slice of the source, the text has not
# moved under it.

RECOMPUTED = "RECOMPUTED"
FIRST_ATTACHMENT = "FIRST_ATTACHMENT"
NOT_RECOMPUTED = "NOT_RECOMPUTED"
FAILED_CLOSED = "FAILED_CLOSED"


# AVAILABILITY IS NOT AUTHORITY, AND THE TWO MUST NOT SHARE A NAME.
#
#   normalize.semantic_tier_available()   CAN the tier execute a query?
#   semantic_recomputation_authoritative() is this run COMPLETE enough
#                                          that its SILENCE may delete
#                                          yesterday's link?
#
# The first is satisfied by ONE embedded concept. The second is not, and
# the gap between them is a live data-integrity bug in this repo, because
# partial embedding coverage is an ORDINARY SUPPORTED STATE here:
# `embed_library.py` defaults to batches of 25 rows and reports
# `still_stale` precisely so a partial pass is a normal intermediate.
#
#     yesterday   269/269 embedded, "Meal-linked postprandial movement"
#                 resolves to POST_MEAL_MOVEMENT, link stored
#     today       25/269 fresh; the tier still RUNS, and the one concept
#                 the phrase needed is not searchable
#     result      phrase unresolved -> authoritative -> valid link deleted
#
# That is the same failure class the tri-state was written to stop, one
# level narrower: a capability check that is true for the wrong reason.
#
# **GATE 2's behaviour is deliberately NOT changed.** `_tier_semantic`
# still searches whatever vectors exist and reports what it finds, which
# is the right operational answer for a resolver. Only the authority to
# DESTROY is made stricter.

def semantic_recomputation_authoritative(conn, embed_call=None) -> tuple[bool, str]:
    """May this run REPLACE an existing link set? Two conditions.

    1. The tier can execute at all -- `normalize.semantic_tier_available()`,
       the same predicate `_tier_semantic` itself acts on, never a second
       copy of its conditions (V2).
    2. Every live concept the semantic search is eligible to see carries a
       CURRENT embedding for its CURRENT text, and the column's pinned
       model is the one this run would query with.

    Freshness is `embed_library.stale_count()`, the ONE definition of
    "needs embedding" this repo already has -- embedding null, hash null,
    or hash not matching `search_text` (migration `023`). A second
    freshness formula written here would drift from the loader that
    actually maintains the vectors, which is the harness/production gap V2
    is about.
    """
    ok, why = NZ.semantic_tier_available(conn, embed_call=embed_call)
    if not ok:
        return False, why

    stale = EL.stale_count(conn, "concepts")
    if stale:
        total = conn.execute(
            "select count(*) from concepts where status in ('SEEDED','ACTIVE')"
        ).fetchone()[0]
        return False, (
            f"embedding coverage is PARTIAL: {stale} of {total} live concepts "
            "have no current vector for their current search_text. The tier "
            "can still run and Gate 2 still resolves on what exists, but a "
            "phrase failing to resolve here may mean the concept was simply "
            "not searchable -- which is not authority to delete a link an "
            "earlier, complete run established.")

    # D34/D38: one model per column, pinned at first write. If the runtime
    # is configured to a DIFFERENT model than the column holds, the query
    # vector and the stored vectors are not in the same space, so a low
    # score says nothing about meaning. `trg_embedding_coherent` refuses to
    # WRITE a second model; it cannot stop a caller QUERYING with one.
    row = conn.execute(
        "select embedding_model, embedding_dim from embedding_provenance "
        " where table_name='concepts'").fetchone()
    configured = os.environ.get("MODEL_EMBEDDING", "").strip()
    if row and configured and row[0] != configured:
        return False, (
            f"the concepts column is pinned to {row[0]} and MODEL_EMBEDDING "
            f"is {configured}: the query vector and the stored vectors are "
            "from different models (D34), so a non-match measures the model "
            "gap and not the phrase.")
    return True, ""


# The two owner columns a link may hang off. GATE 4 added the second; the
# callers name which one they are, so neither is inferred from the id.
OWNER_COLUMNS = ("curated_id", "object_id")

# ON CONFLICT has to name an inferable constraint, and the two owners do
# not have the same kind. `curated_id`'s is a plain UNIQUE CONSTRAINT;
# `object_id`'s is a PARTIAL unique index (`... WHERE object_id IS NOT
# NULL`, migration 044), and PostgreSQL will only infer a partial index if
# the statement repeats its predicate.
#
# This was dead code until a synthetic source with a resolvable name ran
# through it: Video 14 resolves nothing against the K1 seed, so the insert
# was never reached and the omission could not show up. The link-writing
# path for curated objects had never once executed.
CONFLICT_TARGET = {
    "curated_id": "(curated_id, concept_id, source_start, source_end)",
    "object_id": ("(object_id, concept_id, source_start, source_end) "
                  "where object_id is not null"),
}


def prior_links(conn, curated_id: str, owner_col: str = "curated_id") -> list[dict]:
    if owner_col not in OWNER_COLUMNS:
        raise ValueError(f"unknown owner column {owner_col!r}")
    rows = conn.execute(
        f"""select link_id::text, concept_id::text, source_phrase,
                  source_start, source_end, field_name, rule_id
             from curated_strategy_concepts where {owner_col}=%s
            order by source_start""", (curated_id,)).fetchall()
    keys = ("link_id", "concept_id", "source_phrase", "source_start",
            "source_end", "field_name", "rule_id")
    return [dict(zip(keys, r)) for r in rows]


def store_units(conn, curated_id: str, source_text: str,
                resolved: list[dict], *, authoritative: bool,
                authority_reason: str = "",
                owner_col: str = "curated_id") -> dict:
    """Write this card's links, or refuse to and say why.

    Verification happens BEFORE anything is deleted, so a source whose
    spans have drifted leaves the previous links intact rather than wiping
    them and writing nothing.

    Returns the tri-state report. The caller reports it; it is never
    reduced to a count, because "2 links" after a degraded re-import and
    "2 links" after an authoritative one are different facts.
    """
    keep = [r for r in resolved if r["concept_id"]]
    problems = verify(source_text, [r["unit"] for r in keep])
    if problems:
        raise RuntimeError(
            "concept unit(s) do not match the source span they claim, so "
            "nothing was stored:\n  " + "\n  ".join(problems))

    if owner_col not in OWNER_COLUMNS:
        raise ValueError(f"unknown owner column {owner_col!r}")
    existing = prior_links(conn, curated_id, owner_col)

    if not authoritative and existing:
        stale = [l for l in existing
                 if source_text[l["source_start"]:l["source_end"]]
                 != l["source_phrase"]]
        if stale:
            conn.execute(
                f"delete from curated_strategy_concepts where {owner_col}=%s",
                (curated_id,))
            return {"status": FAILED_CLOSED, "written": 0,
                    "retained": 0, "removed": len(existing),
                    "reason": (
                        f"{len(stale)} of {len(existing)} existing link(s) no "
                        "longer sit on the text they name, and this run "
                        f"cannot authoritatively recompute them ({authority_reason}). "
                        "Stale spans are deleted rather than retained: a range "
                        "that resolves cleanly to the wrong characters is worse "
                        "than a missing link (D48).")}
        return {"status": NOT_RECOMPUTED, "written": 0,
                "retained": len(existing), "removed": 0,
                "reason": (
                    f"{authority_reason} -- the tier that produced these links "
                    "could not run, so this run's failure to resolve them is "
                    "not evidence that they no longer resolve. "
                    f"{len(existing)} existing link(s) preserved unchanged.")}

    conn.execute(
        f"delete from curated_strategy_concepts where {owner_col}=%s",
        (curated_id,))
    written = 0
    for r in keep:
        u = r["unit"]
        conn.execute(
            f"""insert into curated_strategy_concepts
                 ({owner_col}, concept_id, rule_id, field_name, source_phrase,
                  source_start, source_end, resolution_tier, resolution_score)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict {CONFLICT_TARGET[owner_col]}
               do nothing""",
            (curated_id, r["concept_id"], u.rule_id, u.field_name, u.phrase,
             u.source_start, u.source_end, r["tier"], r["score"]))
        written += 1
    return {"status": RECOMPUTED if authoritative else FIRST_ATTACHMENT,
            "written": written, "retained": 0, "removed": len(existing),
            "reason": "" if authoritative else (
                f"{authority_reason} -- written anyway because this card had "
                "no prior links, so nothing established could be lost. A "
                "later authoritative run replaces this.")}
