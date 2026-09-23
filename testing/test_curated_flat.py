#!/usr/bin/env python3
"""The grammar must not depend on a heading level the author never wrote.

The canonical source states NO level: 0 Heading styles and 0 `w:outlineLvl`
across 13,763 paragraphs. The `##`/`###` in the converted fixtures were
assigned by a model. So recognition keys on registered LABELS and
containment is parser STATE (migration 048).

Three things are proven here:

  1. LEVEL INDEPENDENCE. Rewriting every heading marker in the committed
     fixtures to one uniform depth changes nothing that is recognised.
     Compared by TEXT, never by offsets -- changing the marker changes
     every offset, so an offset comparison across two renderings would be
     meaningless and would pass or fail for the wrong reason.

  2. BOLD IS NOT A HEADING. Adversarial synthetic documents where bold is
     used for emphasis, for a whole body sentence, and for a line that
     looks exactly like a label.

  3. AMBIGUITY FAILS CLOSED. Synthetic documents where a label cannot be
     placed -- no container open, a container kind that may not own it, a
     field the container already holds -- and must become REVIEW_REQUIRED
     rather than be attached. Since D58, ONLY registered structure moves
     ownership: an unregistered heading inside a container is absorbed as
     body of the current field, never a reason to close it.

EVERY DOCUMENT IN THIS SUITE IS SYNTHETIC AND WRITTEN HERE. The repository
is public; no practitioner text is copied in. The two committed fixtures
are READ for the equivalence proof in (1) and nothing is quoted from them.

Deterministic, no provider, every capability floor.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "testing"))

import psycopg

import curated_parser as CP

FAILS: list[str] = []
FIXTURES = REPO / "testing" / "fixtures" / "curated"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


MARKUP = re.compile(r"^#{1,6}(?=[ \t])", re.M)


def unmarked(text: str) -> str:
    """Remove line-start heading markers from a field's text. Nothing else.

    D58. A field keeps as body any unregistered heading inside it, verbatim --
    so WITH that rendering's own `#` run. That run is the model-assigned depth
    this suite proves meaningless, and it is the ONLY thing removed. Section
    4 bounds it: a field that absorbed no heading must match byte for byte.
    """
    return MARKUP.sub("", text)


def recognised(text: str, rules) -> dict:
    """What the parser recognises, keyed by identity and compared by TEXT."""
    _, cards, objs = CP.parse(text, rules)
    out: dict = {}
    for c in cards:
        out[("CARD", c.kind, c.name)] = {
            f.field_name: unmarked(text[f.source_start:f.source_end])
            for f in c.fields}
    for o in objs:
        out[("OBJ", o.disposition, o.name)] = {
            f.field_name: unmarked(text[f.source_start:f.source_end])
            for f in o.fields}
    return out


def full_shape(text: str, rules) -> dict:
    """The COMPLETE semantic shape: every block, card, object and field.

    D57. `recognised()` above compares fields by name and text and ignores
    heading_path -- so it proved level-independent RECOGNITION and said
    nothing about the structure that is persisted and retrieved. This
    compares ownership, heading paths, failure reasons, the open-container
    context and name provenance too. Offsets are left out on purpose:
    changing the marker length moves every offset, so they are not a
    property of the structure.
    """
    blocks, cards, objs = CP.parse(text, rules)
    head = {b.ordinal: b.raw_heading for b in blocks}
    fields = [(c.name, f) for c in cards for f in c.fields] \
        + [(o.name, f) for o in objs for f in o.fields]
    return {
        "blocks": [(b.ordinal, b.raw_heading, b.status,
                    b.rule.rule_id if b.rule else None,
                    head.get(b.parent_ordinal), b.heading_path,
                    b.failure_reason, b.context_kind,
                    head.get(b.absorbed_into), b.review_class) for b in blocks],
        "cards": [(c.kind, c.name, c.heading_path) for c in cards],
        "objects": [(o.disposition, o.name, o.heading_path) for o in objs],
        "fields": [(n, f.field_name, f.heading_path, f.name_source,
                    unmarked(text[f.source_start:f.source_end]))
                   for n, f in fields],
        # Raw, for the bound: which fields' bytes may differ by markup at all.
        "raw": [(n, f.field_name, text[f.source_start:f.source_end],
                 any(b.absorbed_into == f.block_ordinal for b in blocks))
                for n, f in fields],
    }


def reflatten(text: str, marker: str) -> str:
    """Every heading to the SAME depth: the level distinction removed."""
    return re.sub(r"^#{1,6}(?=[ \t])", marker, text, flags=re.M)


# ----------------------------------------------------------------------
# Synthetic adversarial documents. Invented here, deliberately dull.
# ----------------------------------------------------------------------
BOLD_BODY = """# Widget Maintenance — Update

## ADD — Rotor balancing

**This entire sentence is bold and it is an ordinary body sentence that the
author emphasised for effect, which is exactly the shape a naive reader
would mistake for a heading.**

Some following prose that is not bold at all.

**Short bold line**

**What the strategy means**

More prose. The bold line above LOOKS like a registered label and is still
just bold text inside the body.
"""

AMBIGUOUS = """# Widget Maintenance — Update

## Monitoring

This label appears before anything has opened a container.

## ADD — Rotor balancing

Opening statement for the object.

## Some Heading Nobody Registered

This block is not recognised. Under D58 it does NOT close the object: only
registered structure changes ownership, so it is body of the opening field.

## Monitoring

Registered, and the object is still open, so this IS the object's field.

## Monitoring

A second monitoring label in the same object. The object already holds that
field, so this changes no ownership and is kept as body of the first.

## Decision intelligence

Registered, but only for strategy and principle containers -- never for a
curated object (050) -- so it too is body, not a field.

## Strategy family — Rotating equipment

A registered boundary. It closes the object.

## When useful

Registered, but the boundary above closed everything, so it has no owner.
"""

NESTED_OK = """# Widget Maintenance — Update

## ADD — Rotor balancing

Opening statement for the object.

## Client decision logic

A registered label immediately inside an open object.

## ADD — Bearing inspection

A second object opens, which closes the first.

## Monitoring

A registered label inside the second object.
"""


# ONE LABEL, TWO MEANINGS, TWO KINDS OF CONTAINER. Synthetic. In the card
# it is selection logic; in the object it is a statement about how fast a
# response might come. Under the flat design the label is the only signal,
# so mapping both to one field by surface form would unify two things the
# author did not say were the same.
SAME_LABEL_TWO_MEANINGS = """# Widget Maintenance — Update

## Strategy 1 — Rotor balancing

Balance the rotor before anything else.

## Decision intelligence

Pick this option first when vibration is the dominant complaint, and choose
a different one when the housing is cracked.

## ADD — Faster recovery is possible

Some rotors settle within a week.

## Decision intelligence

A short settling time is more plausible when the rotor is new and the
bearings are recent. This says nothing about which option to choose.
"""


def main() -> int:
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    rules = CP.load_rules(conn)

    print("\nthe level dependency is GONE from the registry")
    lv = conn.execute(
        "select count(*) from curated_grammar_rules "
        " where active and heading_level is not null").fetchone()[0]
    check("no ACTIVE rule requires a heading level", lv == 0, str(lv))
    catchall = conn.execute(
        "select active from curated_grammar_rules "
        " where rule_id='SUB_AUTHORED_SUBHEAD'").fetchone()
    check("SUB_AUTHORED_SUBHEAD is retired, not renamed",
          catchall is not None and catchall[0] is False, str(catchall))
    pat = conn.execute(
        "select pattern from curated_grammar_rules "
        " where rule_id='SUB_AUTHORED_SUBHEAD'").fetchone()[0]
    check("...and it is the catch-all, which is why it had to go",
          pat == "^(?P<name>.+)$", pat)
    check("no ACTIVE rule is a catch-all",
          conn.execute(
              "select count(*) from curated_grammar_rules where active "
              "  and pattern in ('^(?P<name>.+)$', '^(.+)$', '^.*$')"
          ).fetchone()[0] == 0)

    # ==================================================================
    print("\n1. LEVEL INDEPENDENCE on the committed fixtures")
    for name in ("t2d_video1", "t2d_video14"):
        text = (FIXTURES / f"{name}.md").read_text(encoding="utf-8")
        base = recognised(text, rules)
        one = recognised(reflatten(text, "#"), rules)
        three = recognised(reflatten(text, "###"), rules)
        six = recognised(reflatten(text, "######"), rules)
        check(f"  {name}: all headings at '#' recognises the same knowledge",
              base == one, f"{len(base)} vs {len(one)} containers")
        check(f"  {name}: '###' too", one == three)
        check(f"  {name}: '######' too", three == six)
        check(f"  {name}: something was actually recognised",
              len(base) > 0 and sum(len(v) for v in base.values()) > 0,
              str(len(base)))

    # Video 1 is entirely registered-label driven, so flattening must be a
    # no-op for it. Asserted separately because it is the strongest claim.
    v1 = recognised((FIXTURES / "t2d_video1.md").read_text(encoding="utf-8"), rules)
    check("Video 1 keeps all 8 containers and all 24 fields",
          len(v1) == 8 and sum(len(v) for v in v1.values()) == 24,
          f"{len(v1)} containers, {sum(len(v) for v in v1.values())} fields")

    # ==================================================================
    print("\n2. BOLD IS NOT A HEADING")
    blocks, cards, objs = CP.parse(BOLD_BODY, rules)
    check("the object opens from its registered label", len(objs) == 1,
          str(len(objs)))
    fields = {f.field_name for o in objs for f in o.fields}
    check("the bold body text did NOT become a field",
          fields == {"opening_statement"}, str(sorted(fields)))
    body = objs[0].fields[0].text_value
    check("...it is kept INSIDE the opening statement, verbatim",
          "This entire sentence is bold" in body and "Short bold line" in body)
    check("a bold line SPELLING a registered label is still not a field",
          "what_it_means" not in fields, str(sorted(fields)))
    check("...and that text is still preserved in the body",
          "**What the strategy means**" in body)
    check("no block was created for a bold line",
          len(blocks) == 2, f"{[b.raw_heading for b in blocks]}")

    # ==================================================================
    print("\n3. AMBIGUITY FAILS CLOSED -- ONLY REGISTERED STRUCTURE MOVES OWNERSHIP")
    blocks, cards, objs = CP.parse(AMBIGUOUS, rules)
    # By ORDINAL, never by heading text. An earlier version indexed a dict
    # by raw_heading, so `by_head["Monitoring"]` was the LAST Monitoring and
    # the "no container open" check was examining the wrong block.
    by = {b.raw_heading: [x for x in blocks if x.raw_heading == b.raw_heading]
          for b in blocks}
    first_mon, owned_mon, dup_mon = by["Monitoring"]
    stray = by["Some Heading Nobody Registered"][0]
    di = by["Decision intelligence"][0]
    late = by["When useful"][0]
    obj = next(b for b in blocks if b.raw_heading.startswith("ADD"))
    check("a registered label with NO container open is REVIEW_REQUIRED",
          first_mon.status == "REVIEW_REQUIRED"
          and first_mon.review_class == "REGISTERED_NO_CONTAINER",
          f"{first_mon.status} {first_mon.review_class}")
    check("...and says the label is KNOWN and the container missing",
          "REGISTERED" in (first_mon.failure_reason or "")
          and "no container was open" in (first_mon.failure_reason or ""),
          str(first_mon.failure_reason))
    check("an unregistered heading is REVIEW_REQUIRED, reason NO_RULE",
          stray.status == "REVIEW_REQUIRED" and stray.review_class == "NO_RULE",
          f"{stray.status} {stray.review_class}")
    check("...and is ABSORBED into the field it sits in, not dropped",
          stray.absorbed_into == obj.ordinal, str(stray.absorbed_into))
    # D58 REVERSES what this section used to assert. `0df47bf` held that a
    # registered label after an unrecognised block had no owner, because the
    # unrecognised block closed the container. The canonical .docx refuted
    # that: its emphasised body sentences are bold paragraphs, so the old
    # rule orphaned every subsection after one. The label attaching here is
    # the fix, not a loosening.
    check("D58: a registered label AFTER an unrecognised block still attaches",
          owned_mon.status == "PARSED"
          and owned_mon.parent_ordinal == obj.ordinal,
          f"{owned_mon.status} parent={owned_mon.parent_ordinal}")
    check("a SECOND occurrence of a field is REVIEW_REQUIRED, never an overwrite",
          dup_mon.status == "REVIEW_REQUIRED"
          and dup_mon.review_class == "REGISTERED_DUPLICATE_FIELD"
          and dup_mon.absorbed_into == owned_mon.ordinal,
          f"{dup_mon.status} {dup_mon.review_class} into={dup_mon.absorbed_into}")
    check("a label the container kind may not own is REVIEW_REQUIRED",
          di.status == "REVIEW_REQUIRED"
          and di.review_class == "REGISTERED_NOT_OWNABLE",
          f"{di.status} {di.review_class}")
    check("a registered BOUNDARY closes the container; a label after it has "
          "no owner",
          late.status == "REVIEW_REQUIRED"
          and late.review_class == "REGISTERED_NO_CONTAINER"
          and late.absorbed_into is None,
          f"{late.status} {late.review_class} into={late.absorbed_into}")
    fields = {f.field_name: f for o in objs for f in o.fields}
    check("the object holds exactly one monitoring field and no decision field",
          sorted(fields) == ["monitoring", "opening_statement"], str(sorted(fields)))
    # .get, never []: with the old rule restored there is no monitoring field,
    # and a KeyError here stopped the suite before section 7 -- the real
    # .docx case -- could run. Red by crash hides which checks have teeth.
    mf, of = fields.get("monitoring"), fields.get("opening_statement")
    mon_text = AMBIGUOUS[mf.source_start:mf.source_end] if mf else ""
    check("...whose VERBATIM text runs through both absorbed labels",
          "A second monitoring label" in mon_text
          and "## Decision intelligence" in mon_text
          and "Strategy family" not in mon_text, repr(mon_text[-80:]))
    open_text = AMBIGUOUS[of.source_start:of.source_end] if of else ""
    check("...and the opening field keeps the unregistered heading as body",
          "## Some Heading Nobody Registered" in open_text
          and "Registered, and the object" not in open_text, repr(open_text[-80:]))

    # The positive control: the same labels DO attach when a container is
    # genuinely open. Without this the section above would pass on a parser
    # that recognised nothing at all.
    blocks, cards, objs = CP.parse(NESTED_OK, rules)
    check("POSITIVE CONTROL: two objects open", len(objs) == 2, str(len(objs)))
    f0 = {f.field_name for f in objs[0].fields}
    f1 = {f.field_name for f in objs[1].fields}
    check("...the first gets its registered label as a FIXED field",
          "client_decision_logic" in f0, str(sorted(f0)))
    check("...the second gets its own", "monitoring" in f1, str(sorted(f1)))
    check("...and neither stole the other's",
          "monitoring" not in f0 and "client_decision_logic" not in f1,
          f"{sorted(f0)} {sorted(f1)}")

    # ==================================================================
    # ==================================================================
    print("\n4. THE COMPLETE SHAPE, not just recognised fields (D57)")
    for name in ("t2d_video1", "t2d_video14"):
        text = (FIXTURES / f"{name}.md").read_text(encoding="utf-8")
        shapes = {m: full_shape(reflatten(text, m) if m else text, rules)
                  for m in ("", "#", "###", "######")}
        base = shapes[""]
        for m in ("#", "###", "######"):
            leaked = [r[:2] for r, r0 in zip(shapes[m]["raw"], base["raw"])
                      if r[2] != r0[2] and not r0[3]]
            check(f"  {name} {m!r:>8}: raw text differs ONLY where a field "
                  "absorbed a heading", leaked == [], str(leaked))
            for part in ("blocks", "cards", "objects", "fields"):
                check(f"  {name} {m!r:>8}: {part} identical — incl. heading_path"
                      " and ownership", shapes[m][part] == base[part],
                      f"{sum(1 for a, b in zip(shapes[m][part], base[part]) if a != b)} differ")
        depth = max(b[5].count(" > ") + 1 for b in base["blocks"])
        check(f"  {name}: no path is deeper than container > subsection",
              depth <= 2, str(depth))
        orphans = [b for b in base["blocks"]
                   if b[4] is None and " > " in b[5]]
        check(f"  {name}: an unowned block has NO inferred parent in its path",
              orphans == [], str(orphans[:2]))
        check(f"  {name}: no persisted failure reason mentions a markup depth",
              not any(b[6] and re.search(r"at level \d", b[6])
                      for b in base["blocks"]))

    # ==================================================================
    print("\n5. ONE LABEL, TWO MEANINGS — NOT SILENTLY UNIFIED")
    blocks, cards, objs = CP.parse(SAME_LABEL_TWO_MEANINGS, rules)
    di = [b for b in blocks if b.raw_heading == "Decision intelligence"]
    check("the label occurs twice, in two kinds of container",
          [b.context_kind for b in di] == ["STRATEGY", "CURATED_OBJECT"],
          str([b.context_kind for b in di]))
    check("inside the STRATEGY card it maps to client_decision_logic",
          cards and "client_decision_logic" in {f.field_name for f in cards[0].fields},
          str([f.field_name for c in cards for f in c.fields]))
    check("inside the CURATED OBJECT it is REVIEW_REQUIRED",
          di[1].status == "REVIEW_REQUIRED", di[1].status)
    check("...so the two meanings did NOT land in one field",
          all("client_decision_logic" not in {f.field_name for f in o.fields}
              for o in objs), str([f.field_name for o in objs for f in o.fields]))
    obj_rule = conn.execute(
        "select pattern, owner_kinds from curated_grammar_rules "
        " where rule_id='SUB_DECISION_LOGIC' and active").fetchone()
    check("SUB_DECISION_LOGIC exists for objects and does NOT match it",
          obj_rule is not None
          and not re.match(obj_rule[0], "Decision intelligence", re.I),
          str(obj_rule))
    sd = conn.execute("select owner_kinds from curated_grammar_rules "
                      " where rule_id='SUB_DECISION'").fetchone()[0]
    check("SUB_DECISION is card-only again", "CURATED_OBJECT" not in sd, str(sd))

    # ==================================================================
    print("\n6. A LEVEL CANNOT COME BACK THROUGH DATA")
    refused = False
    try:
        with conn.transaction():
            conn.execute(
                """insert into curated_grammar_rules
                     (rule_id, construct, pattern, heading_level, block_kind,
                      field_name, field_name_source, example_heading,
                      reusable_justification, expected_elsewhere, priority)
                   values ('FLAT_TEETH_L3','x','^Monitoring$',3,'SUBSECTION',
                           'monitoring','FIXED','Monitoring',
                           'a justification long enough for the length check',
                           'anywhere at all', 500)""")
    except psycopg.errors.CheckViolation as exc:
        refused = "ck_rule_no_heading_level" in str(exc)
    check("a rule with heading_level = 3 is REFUSED by the registry", refused)
    check("...and nothing was inserted",
          conn.execute("select count(*) from curated_grammar_rules "
                       " where rule_id='FLAT_TEETH_L3'").fetchone()[0] == 0)
    src = (REPO / "scripts" / "curated_parser.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    check("the parser no longer compares a rule level at all",
          "r.heading_level" not in code and "stack.pop()" not in code)

    print("\nspans and text survive all of it")
    for doc in (BOLD_BODY, AMBIGUOUS, NESTED_OK):
        _, cards, objs = CP.parse(doc, rules)
        flds = [f for o in objs for f in o.fields] + [f for c in cards for f in c.fields]
        check("  every field IS the slice its span names",
              all(doc[f.source_start:f.source_end] == f.text_value for f in flds))
        check("  verify() is clean", CP.verify(doc, flds) == [])
        check("  everything stored is VERBATIM_SOURCE",
              all(f.provenance == "VERBATIM_SOURCE" for f in flds))

    # ==================================================================
    print("\n7. THE CANONICAL SHAPE, IN A REAL .docx (D58)")
    # The failure independent review measured on the real document, rebuilt
    # SYNTHETICALLY: an emphasised body sentence is a bold paragraph exactly
    # like a label, and it sits between two registered subsections. Read
    # through the SAME path the survey uses -- the real .docx reader and the
    # production classify / attach -- not a Markdown stand-in, because the
    # Markdown renderings are what hid this in the first place.
    import curated_survey as SV
    dpath = FIXTURES.parent / "docx" / "bold_body_between_labels.docx"
    dblocks, dsig = SV.docx_candidates(dpath)
    CP.classify(dblocks, rules)
    CP.attach(dblocks)
    CP.derive_paths(dblocks)
    dby = {b.raw_heading: b for b in dblocks}
    s1 = dby.get("Strategy 1 — Rotor balancing")
    emph = next((b for b in dblocks if b.raw_heading.startswith("Vibration")), None)
    why = dby.get("Why this can be useful")
    cdl = dby.get("Client decision logic")
    what = dby.get("What the strategy means")
    check("the fixture is read as SIX bold candidates from a real package",
          len(dblocks) == 6 and dsig["heading_styled"] == 0
          and dsig["outline_levels"] == 0,
          f"{[b.raw_heading[:30] for b in dblocks]} {dsig}")
    if None in (s1, emph, why, cdl, what):
        check("every expected candidate is present", False, str(list(dby)))
    else:
        check("the emphasised body sentence matches no rule and is AUDITED",
              emph.status == "REVIEW_REQUIRED" and emph.review_class == "NO_RULE",
              f"{emph.status} {emph.review_class}")
        check("...and is absorbed into the field BEFORE it, not dropped",
              emph.absorbed_into == what.ordinal, str(emph.absorbed_into))
        check("the subsection AFTER it is still owned by its container",
              why.status == "PARSED" and why.parent_ordinal == s1.ordinal,
              f"{why.status} parent={why.parent_ordinal}")
        check("...and so is client_decision_logic, the field GATE 1 protects",
              cdl.status == "PARSED" and cdl.parent_ordinal == s1.ordinal
              and cdl.rule is not None
              and cdl.rule.field_name == "client_decision_logic",
              f"{cdl.status} parent={cdl.parent_ordinal}")
        check("...with the path of an owned subsection, not an orphan's",
              cdl.heading_path == f"{s1.raw_heading} > Client decision logic",
              cdl.heading_path)
        s2 = dby.get("Strategy 2 — Bearing inspection")
        check("the next registered container still opens its own",
              s2 is not None and s2.status == "PARSED" and s2.parent_ordinal is None)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_curated_flat: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
