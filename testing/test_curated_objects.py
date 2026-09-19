#!/usr/bin/env python3
"""GATE 4 — the curated-object grammar, tested WITHOUT the Video 14 fixture.

Every document in this suite is synthetic and written here. That is the
point: a rule justified as "reusable authored vocabulary" should recognise
its construct in text it has never seen, and a rule that only works on the
fixture that prompted it is a rule fitted to that fixture.

The fixture-based acceptance run lives in `test_gate4_acceptance.py` and
reads the frozen answer key. This suite reads neither.

Deterministic, no provider, every capability floor.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import curated_parser as CP

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


# ----------------------------------------------------------------------
# A synthetic directive-organised section. Nothing in it appears in Video
# 14: different domain, different wording, different subheadings.
# ----------------------------------------------------------------------
SYNTHETIC = """# Sleep / Circadian — Engine 7 Update

## Section 3: *A podcast about light exposure*

## ADD — Morning Outdoor Light as a Circadian Anchor

The source argues for outdoor light within an hour of waking.

I checked the underlying published trial.

### Dose reasoning

Ten to thirty minutes depending on cloud cover.

### Why this is worth keeping

It is cheap, it is low-friction, and it has a plausible route to sleep onset.

## MERGE — Evening Light Restriction Already Exists

We already hold evening light reduction. This adds device-level detail only.

## SKIP — "Blue-Blocking Glasses Fix Everything"

The source overclaims. Do not create this as active E7 logic.

## REINFORCE — Consistent Wake Time

Already represented. **No new strategy object.**

## ADD / UPGRADE — Post-Lunch Daylight Break

Previously a candidate. Enough evidence now to raise it.

## PROVENANCE ONLY — Caffeine Half-Life

Mentioned in passing; nothing new.

## Something The Grammar Has Never Heard Of

This heading is not a construct anyone registered.
"""

# A strategy-card section, to prove the generic subsection rule cannot
# reach inside one.
CARD_DOC = """# Nutrition — Engine 7 Update

## Strategy 1 — Plate structure

The first half of the plate is non-starchy vegetables.

### Why this can be useful

It displaces energy density without a rule about amounts.

### Invented Heading The Grammar Does Not Know

This is inside a STRATEGY card, not a curated object.
"""


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    rules = CP.load_rules(conn)

    print("\nthe two new rules are REGISTRY ROWS, with their justification")
    row = conn.execute(
        "select block_kind, field_name_source, owner_kinds, "
        "       length(btrim(reusable_justification)) "
        "  from curated_grammar_rules where rule_id='CURATION_DIRECTIVE'"
    ).fetchone()
    check("CURATION_DIRECTIVE is a CURATED_OBJECT block rule", row[0] == "CURATED_OBJECT")
    check("it states a substantial reusability justification", row[3] >= 200, str(row[3]))
    row2 = conn.execute(
        "select block_kind, field_name_source, owner_kinds "
        "  from curated_grammar_rules where rule_id='SUB_AUTHORED_SUBHEAD'"
    ).fetchone()
    check("SUB_AUTHORED_SUBHEAD names its field from the HEADING",
          row2[1] == "HEADING")
    check("...and is confined to CURATED_OBJECT owners by a COLUMN",
          row2[2] == ["CURATED_OBJECT"], str(row2[2]))

    # ==================================================================
    print("\nPOSITIVE: the directive construct is recognised in unseen text")
    blocks, cards, objects = CP.parse(SYNTHETIC, rules)
    by_disp = {}
    for o in objects:
        by_disp.setdefault(o.disposition, []).append(o)

    check("six objects, one per directive", len(objects) == 6,
          f"{len(objects)}: {[o.disposition for o in objects]}")
    for want in ("ADD", "ADD_UPGRADE", "MERGE", "REINFORCE", "SKIP",
                 "PROVENANCE_ONLY"):
        check(f"  {want} is read as its own disposition", want in by_disp,
              str(sorted(by_disp)))

    check("ADD and ADD_UPGRADE are NOT collapsed",
          by_disp.get("ADD") and by_disp.get("ADD_UPGRADE")
          and by_disp["ADD"][0].name != by_disp["ADD_UPGRADE"][0].name)

    # The disposition must be traceable to characters, not asserted.
    ok_spans = all(
        CP.normalize_disposition(SYNTHETIC[o.directive_start:o.directive_end])
        == o.disposition for o in objects)
    check("every disposition is re-derivable from its own directive span",
          ok_spans)
    ok_names = all(SYNTHETIC[o.name_start:o.name_end] == o.name for o in objects)
    check("every object name IS the slice its span names", ok_names)

    add = by_disp["ADD"][0]
    fields = {f.field_name for f in add.fields}
    check("an authored subheading becomes a field named by the AUTHOR",
          "dose_reasoning" in fields, str(sorted(fields)))
    # `Why this is worth keeping` matches SUB_WHY (a strategy-card rule)
    # AND the generic authored-subhead rule. SUB_WHY cannot be owned by a
    # curated object, so the chain hands over -- the block is kept, and it
    # is named by the AUTHOR rather than being declared to be a strategy
    # card's `why_useful`. Asserting `why_useful` here would be asserting
    # that the two are the same field, which is exactly the flattening
    # decision the parser is not entitled to make.
    check("a higher-priority rule that cannot be owned HANDS OVER",
          "why_this_is_worth_keeping" in fields, str(sorted(fields)))
    check("...and does not silently become a strategy-card field",
          "why_useful" not in fields, str(sorted(fields)))
    check("the object's own body is kept as opening_statement",
          "opening_statement" in fields, str(sorted(fields)))
    ok_field_spans = all(SYNTHETIC[f.source_start:f.source_end] == f.text_value
                         for o in objects for f in o.fields)
    check("every field IS the slice its span names", ok_field_spans)
    check("verify() is clean on synthetic text",
          CP.verify(SYNTHETIC, [f for o in objects for f in o.fields]) == [])

    print("\nan unregistered heading is still REVIEW_REQUIRED")
    unknown = [b for b in blocks if b.status == "REVIEW_REQUIRED"
               and b.raw_heading == "Something The Grammar Has Never Heard Of"]
    check("the unknown level-2 heading is not silently adopted",
          len(unknown) == 1 and unknown[0].failure_reason is not None)

    # ==================================================================
    print("\nNEGATIVE CONTROL: the generic rule cannot reach into a card")
    b2, c2, o2 = CP.parse(CARD_DOC, rules)
    check("the strategy card parses", len(c2) == 1 and len(o2) == 0)
    card_fields = {f.field_name for f in c2[0].fields}
    check("its known subsection is kept", "why_useful" in card_fields,
          str(sorted(card_fields)))
    check("an INVENTED heading inside a card is NOT adopted as a field",
          "invented_heading_the_grammar_does_not_know" not in card_fields,
          str(sorted(card_fields)))
    orphan = [b for b in b2 if b.raw_heading.startswith("Invented Heading")]
    check("...it is REVIEW_REQUIRED instead", len(orphan) == 1
          and orphan[0].status == "REVIEW_REQUIRED", str(orphan))
    check("...and the reason names the owner kinds it needed",
          orphan and orphan[0].failure_reason
          and "CURATED_OBJECT" in orphan[0].failure_reason,
          str(orphan[0].failure_reason if orphan else None))

    # ==================================================================
    print("\nthe verification construct: one positive, four counterexamples")
    vrules = [tuple(r) for r in conn.execute(
        "select rule_id, pattern, verification_actor::text, "
        "       verification_status::text from curated_verification_rules "
        " where active").fetchall()]
    vs = CP.find_verifications(SYNTHETIC, vrules)
    check("the practitioner's first-person check is found in unseen text",
          len(vs) == 1, str([v.statement_text for v in vs]))
    check("...as PRACTITIONER / PRACTITIONER_VERIFIED",
          vs and vs[0].verification_actor == "PRACTITIONER"
          and vs[0].verification_status == "PRACTITIONER_VERIFIED")
    check("...and its span IS the statement",
          vs and SYNTHETIC[vs[0].source_start:vs[0].source_end]
          == vs[0].statement_text)

    counterexamples = [
        "The source checked the underlying report before publishing.",
        "I checked with the client about adherence.",
        "I checked the numbers against my own practice data.",
        "We should check the underlying report at some point.",
    ]
    for c in counterexamples:
        got = CP.find_verifications(c, vrules)
        check(f"  NOT a practitioner verification: {c[:44]!r}", got == [],
              str([g.statement_text for g in got]))

    # ==================================================================
    print("\nthe disposition vocabulary is a DATABASE property")
    active = {r[0] for r in conn.execute(
        "select d::text from unnest(enum_range(null::curated_disposition)) d "
        " where curated_disposition_is_active(d)").fetchall()}
    check("ADD / ADD_UPGRADE / MERGE may become active knowledge",
          active == {"ADD", "ADD_UPGRADE", "MERGE"}, str(sorted(active)))
    inactive = {r[0] for r in conn.execute(
        "select d::text from unnest(enum_range(null::curated_disposition)) d "
        " where not curated_disposition_is_active(d)").fetchall()}
    check("REINFORCE / SKIP / PROVENANCE_ONLY may NOT",
          inactive == {"REINFORCE", "SKIP", "PROVENANCE_ONLY"},
          str(sorted(inactive)))

    print("\n" + ("=" * 60))
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_curated_objects: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
