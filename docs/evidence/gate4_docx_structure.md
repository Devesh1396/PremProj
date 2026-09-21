# GATE 4 — reading structure from the canonical .docx

## The finding this is built around

Verified directly against `T2D_V_1.docx`:

- **0** paragraphs use a Heading style
- **0** outline levels (`w:outlineLvl`) anywhere
- no list numbering on headings
- every heading is a plain paragraph whose only formatting is bold
  (`<w:pPr><w:rPr><w:b/><w:bCs/></w:rPr></w:pPr>`), **byte-identical whether
  it is a section or a subsection**
- **3,979** short bold paragraphs, with nothing distinguishing their level

**Consequence, and it reaches backwards into GATES 1 and 4.** The `##` and
`###` levels in `t2d_video1.md` and `t2d_video14.md` **do not exist in the
source**. They appeared when the docx was converted. `SUB_AUTHORED_SUBHEAD`
is specified as "a level-3 heading inside a curated object" and therefore
keys on a level the author never wrote. So do `SUB_WHY`, `SUB_DECISION` and
every other level-3 rule in migration `033`.

Nothing about the preserved text is affected — spans, verbatim guarantees and
provenance are all intact. What is affected is the claim that the grammar
reads *authored* structure. On these two fixtures it reads *converted*
structure.

## What was built

`scripts/docx_structure.py`. Stdlib only (`zipfile`, `xml.etree`), read-only,
no model, writes nothing anywhere.

It **reports the structural signals a document actually carries** and their
counts: Heading styles, explicit `w:outlineLvl`, heading numbering,
bold-only paragraphs with their length distribution, declared font sizes and
empty paragraphs.

**It assigns a level only where the document states one** — a Heading style
or an explicit outline level. Where the document states none it prints

```
NO HEADING HIERARCHY.
This document states no level anywhere: no Heading style, no
w:outlineLvl, no heading numbering. NO LEVEL HAS BEEN ASSIGNED, and
none will be inferred from bold, length, capitalisation, font size or
spacing.
```

and lists the bold paragraphs **as a signal, not a level**. For the real
source that output is correct and complete, not a failure to try harder.

**A length threshold was removed during review.** An earlier draft bucketed
"short" bold paragraphs at ≤120 characters and the suite's own
no-inference guard caught it. A length threshold is a number that can be
moved until a fixture passes; the raw distribution carries the same
information and decides nothing.

## The fixtures, and why the second one is the one that matters

| | |
|---|---|
| `headed.docx` | real authored hierarchy — proves the reader **uses** it |
| `flat_bold.docx` | mirrors the real source: bold-only paragraphs, no styles, no outline levels — proves the reader **reports the absence** rather than inventing one |

Without the second, the tool would be tested only on a document shape the
real corpus does not have: a harness that differs from production, built on
purpose (V2). A reader validated only against `headed.docx` passes there and
finds **nothing at all** in `T2D_V_1.docx`.

**`headed.docx` exercises the two recognition paths separately.** Levels 1
and 2 are declared by `w:outlineLvl` on the style; level 3 is recognisable
**only** by the style name `heading 3`. The first version of the fixture put
`outlineLvl` on all three, and sabotaging the style-name regex changed
nothing — the test had no teeth on that half. Both halves are now proven by
breaking each independently.

## How the corpus gets a hierarchy — three options, none chosen

This is the practitioner's decision, not the tool's.

1. **Prem applies Heading styles in Word.** The structure becomes authored in
   the canonical source, the reader finds it, and every level-keyed grammar
   rule is reading something a human wrote. Cost: manual work across 524
   pages.
2. **The corpus is treated as flat**, and the grammar stops depending on
   level. Cost: `SUB_AUTHORED_SUBHEAD` and every level-3 rule in `033` need
   rethinking, since level is their discriminator.
3. **A converter with an explicitly stated rule**, recorded as a
   transformation. Cost: the levels are then *derived*, and GATE 1's
   provenance model already has the vocabulary for that —
   `TRANSFORMED` with the rule named, never `VERBATIM_SOURCE`.

## OPEN QUESTION FOR THE PRACTITIONER

**How were `t2d_video1.md` and `t2d_video14.md` produced — by hand, by a
script, or by a model?**

This matters and is not answerable from the repository. If a model produced
them, then the heading hierarchy GATES 1 and 4 parse was **interpreted rather
than authored**, and every structural result on those fixtures rests on that
interpretation. The GATE 1 and GATE 4 preservation guarantees still hold for
the *text* — spans were verified against the file that exists — but "the
practitioner wrote this structure" would not be a statement the build can
make.

Recorded in `PROGRESS.md` as an open question, unanswered.

## What was NOT done

No survey was run. The docx was not converted to markdown. No level was
inferred. No grammar rule was added or changed.
