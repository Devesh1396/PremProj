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


def card_units(conn, rules: list[Rule], card) -> tuple[list[Unit], list[dict]]:
    """Every unit of one `curated_parser.ParsedCard`.

    The card NAME is a unit by construction -- the heading grammar already
    isolated it from the numbering and stored it as a verbatim slice with
    its span -- so it needs no pattern, only a rule saying it is one.
    """
    found: list[Unit] = []
    refused: list[dict] = []

    name_rule = next((r for r in rules if r.unit_kind == "CARD_NAME"), None)
    if name_rule is not None and card.name_start is not None:
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


def store_units(conn, curated_id: str, source_text: str,
                resolved: list[dict]) -> int:
    """Replace this card's links with the ones that RESOLVED.

    Verification happens BEFORE the delete, so a source whose spans have
    drifted leaves the previous links intact rather than wiping them and
    writing nothing.
    """
    keep = [r for r in resolved if r["concept_id"]]
    problems = verify(source_text, [r["unit"] for r in keep])
    if problems:
        raise RuntimeError(
            "concept unit(s) do not match the source span they claim, so "
            "nothing was stored:\n  " + "\n  ".join(problems))

    conn.execute("delete from curated_strategy_concepts where curated_id=%s",
                 (curated_id,))
    written = 0
    for r in keep:
        u = r["unit"]
        conn.execute(
            """insert into curated_strategy_concepts
                 (curated_id, concept_id, rule_id, field_name, source_phrase,
                  source_start, source_end, resolution_tier, resolution_score)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (curated_id, concept_id, source_start, source_end)
               do nothing""",
            (curated_id, r["concept_id"], u.rule_id, u.field_name, u.phrase,
             u.source_start, u.source_end, r["tier"], r["score"]))
        written += 1
    return written
