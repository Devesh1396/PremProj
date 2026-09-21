# GATE 4 — reading structure from the canonical .docx

## The finding this is built around

Measured directly against `T2D_V_1.docx` (the private source is **not** in
this repository and must not be committed):

| | |
|---|---|
| paragraphs | **13,763** |
| Heading-styled paragraphs | **0** |
| explicit `w:outlineLvl` | **0** |
| paragraphs carrying `w:numPr` | **351** |
| bold-only paragraphs | **4,207** |
| longest bold-only paragraph | **838 characters** |

Every heading is a plain paragraph whose only formatting is bold, **identical
whether it is a section title, a subsection label or a full body sentence**.

**Bold is not even a reliable HEADING signal in this document.** At 838
characters the longest bold-only paragraph is a paragraph, not a title. A
reader that promoted bold to structure would promote body prose.

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

**The verdict wording was narrowed.** It used to say "no heading numbering",
which was never established: the reader counted `w:numPr` and had **never
opened `numbering.xml`**. It reported 351 numbered paragraphs and then drew a
conclusion about numbering it had not checked. `numbering.xml` is now parsed
and each `numId`'s declared format is reported; the verdict claims only what
is proven — **NO AUTHORED HEADING LEVELS**.

**Three more signal-reporting defects, found by auditing the reader against
its own claims:**

- `<w:b w:val="0"/>` and `w:val="false"` were counted as **bold**, because
  only the element's presence was tested. The real source contains none, so
  its 4,207 stands — but a document using them would have been miscounted.
- **Inherited bold was invisible.** Bold applied through a paragraph style
  rather than directly on the runs counted as not bold at all, so the reader
  was measuring one of the two ways Word expresses it. Direct and inherited
  are now counted and reported separately.
- **Font sizes were read from `pPr`**, where they are not declared, so every
  document reported "0 distinct font sizes" — a fact about where the reader
  looked. They are now read from the runs, and where nothing is declared the
  reader says the sizes are inherited and not resolved.
- **Conflicting signals are now reported rather than silently resolved.** A
  paragraph that is both Heading-styled and list-numbered, or Heading-styled
  with bold explicitly off, is telling two stories; choosing one quietly is
  how a reader starts inventing.

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
| `signals.docx` | bullet and decimal numbering, bold turned explicitly off, bold inherited from a style, two font sizes, and one paragraph that is both a heading and numbered — the signals the reader used to get wrong |

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

## FIXTURE PROVENANCE — ANSWERED

The practitioner confirms `t2d_video1.md` and `t2d_video14.md` were produced
**by a Claude model** from `T2D_V_1.docx`.

Their TEXT was independently verified against the docx:

- Video 1: **218 content lines, 0 genuine differences**
- Video 14: **245 content lines, 0 genuine differences**

after normalising only Markdown syntax — heading markers, bullet dashes,
emphasis asterisks, trailing backslash line breaks, `\<` escapes, `--` for en
dashes, curly versus straight quotes, and `[text](url)` hyperlinks.

So:

> **TEXT: practitioner-authored, verified verbatim.**
> **HIERARCHY: model-interpreted, not practitioner-authored.**

42 heading markers in Video 1 and 61 in Video 14, **none** corresponding to a
level stated in the docx. The hierarchy is not described as authored anywhere
in this repository.

## THE DECISION — OPTION 2, THE CORPUS IS FLAT

Taken by the practitioner. The grammar no longer depends on a converted
Markdown level; see `DECISIONS.md` D56 and migrations `048`/`049`. Options 1
and 3 were not chosen: no Heading styles are being applied to 524 pages, and
no converter rule is being recorded as a transformation.

## What was NOT done

No survey was run. The docx was not converted to markdown. No level was
inferred. No grammar rule was added or changed.
