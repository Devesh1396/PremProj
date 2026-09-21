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

### Why this is worth keeping

It is cheap, it is low-friction, and it has a plausible route to sleep onset.

### Dose reasoning

Ten to thirty minutes depending on cloud cover. This heading is NOT a
registered construct, so it is REVIEW_REQUIRED -- and it closes the object,
because without an authored level there is nothing that would say the next
heading still belongs inside.

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
        "select block_kind, field_name_source, owner_kinds, active, pattern "
        "  from curated_grammar_rules where rule_id='SUB_AUTHORED_SUBHEAD'"
    ).fetchone()
    check("SUB_AUTHORED_SUBHEAD is RETIRED (048), not renamed",
          row2 is not None and row2[3] is False, str(row2))
    check("...and it was the catch-all, which is why level was its only guard",
          row2 is not None and row2[4] == "^(?P<name>.+)$", str(row2))

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
    # `Dose reasoning` is NOT a registered construct, and since 048 there
    # is no catch-all to adopt it. It stays REVIEW_REQUIRED, which is the
    # whole point: an unregistered label is not silently turned into a
    # field just because it sits inside an object.
    check("an UNREGISTERED subheading does NOT become a field",
          "dose_reasoning" not in fields, str(sorted(fields)))
    closed = [b for b in blocks if b.raw_heading == "Dose reasoning"]
    check("...it is REVIEW_REQUIRED", closed and closed[0].status == "REVIEW_REQUIRED",
          str([(b.raw_heading, b.status) for b in closed]))
    # `Why this is worth keeping` matches SUB_WHY (a strategy-card rule)
    # AND the generic authored-subhead rule. SUB_WHY cannot be owned by a
    # curated object, so the chain hands over -- the block is kept, and it
    # is named by the AUTHOR rather than being declared to be a strategy
    # card's `why_useful`. Asserting `why_useful` here would be asserting
    # that the two are the same field, which is exactly the flattening
    # decision the parser is not entitled to make.
    # `Why this is worth keeping` matches SUB_WHY, a REGISTERED construct,
    # and 049 lets the 033 subsection rules be owned by a curated object --
    # so it is recognised under its registered field name rather than under
    # the author's wording. No label was invented to make that happen: the
    # pattern and the field name are both 033's own.
    check("a REGISTERED label inside an object is recognised (049)",
          "why_useful" in fields, str(sorted(fields)))
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
    check("the unknown heading is not silently adopted",
          len(unknown) == 1 and unknown[0].failure_reason is not None,
          str([(u.raw_heading, u.status) for u in unknown]))

    # ==================================================================
    print("\nNEGATIVE CONTROL: the generic rule cannot reach into a card")
    b2, c2, o2 = CP.parse(CARD_DOC, rules)
    check("the strategy card parses", len(c2) == 1 and len(o2) == 0)
    card_fields = {f.field_name for f in c2[0].fields}
    check("its known subsection is kept", "why_useful" in card_fields,
          str(sorted(card_fields)))
    check("an INVENTED heading inside a card is NOT adopted as a field",
          "invented_heading_the_grammar_does_not_know" not in card_fields
          and "invented_heading" not in card_fields, str(sorted(card_fields)))
    orphan = [b for b in b2 if b.raw_heading.startswith("Invented Heading")]
    check("...it is REVIEW_REQUIRED instead", len(orphan) == 1
          and orphan[0].status == "REVIEW_REQUIRED", str(orphan))
    # Since 048 retired the catch-all, an invented heading matches NO rule
    # at all, so it fails in classify() rather than in attach(). Either way
    # it is refused with a reason; the assertion names which.
    check("...and the reason says no registered rule matched it",
          orphan and orphan[0].failure_reason
          and "no rule in curated_grammar_rules matches" in orphan[0].failure_reason,
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

    # ==================================================================
    print("\nSEMANTIC ROLES MUST NOT CLAIM MORE THAN THE GRAMMAR SAYS")
    role = conn.execute(
        "select semantic_role from curated_field_roles "
        " where field_name='when_not_useful'").fetchone()
    print(f"        when_not_useful -> {role[0] if role else None}")
    check("`when_not_useful` has a registered role at all", role is not None)
    check("...and it is NOT a contraindication",
          role and "CONTRA" not in role[0].upper().replace("_", ""),
          str(role))
    check("...and it is NOT safety",
          role and "SAFETY" not in role[0].upper(), str(role))
    check("...it is the grammar's own word: negative indication",
          role and role[0] == "NEGATIVE_INDICATION", str(role))

    # The construct 033 actually describes, quoted from the registry rather
    # than from memory. A role stronger than this text is an over-claim.
    src = conn.execute(
        "select construct, reusable_justification from curated_grammar_rules "
        " where rule_id='SUB_WHEN_NOT_USEFUL'").fetchone()
    check("033 describes it as NEGATIVE INDICATION, never contraindication",
          src and "negative-indication" in src[0].lower()
          and "contraindicat" not in (src[0] + src[1]).lower(), str(src))

    # `safety_context` IS the safety construct and must keep that role --
    # this check would also pass if safety had simply been deleted, so it
    # is asserted positively.
    safety = conn.execute(
        "select semantic_role from curated_field_roles "
        " where field_name='safety_context'").fetchone()
    check("`safety_context` still carries SAFETY — the real one is untouched",
          safety and safety[0] == "SAFETY", str(safety))

    others = conn.execute(
        "select field_name, semantic_role from curated_field_roles "
        " where semantic_role ilike '%%contra%%'").fetchall()
    check("NO field anywhere is registered as a contraindication",
          others == [], str(others))

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
