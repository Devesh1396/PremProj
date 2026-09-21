# GATE 4 — structural survey

## THE MATERIAL TO BE SURVEYED IS NOT IN THIS REPOSITORY

The task asks for a mechanical survey of the corpus **after** the recognised
`Video N` region — roughly 77,000 words. **That text is not present here, so
the survey of it has not been performed and no findings about it are
reported below.** Inventing them is the one thing that would make this
document worse than useless.

What the repository actually contains, measured:

```
testing/fixtures/curated/t2d_video1.md      2,215 words   16,568 bytes
testing/fixtures/curated/t2d_video14.md     2,584 words   20,364 bytes
                                            -----------
                                            4,799 words
knowledge/raw/87/87a893…f3b41.md          Video 1's preserved raw copy
```

A repo-wide search for `*.docx`, for `T2D_V*`, and of `knowledge/` finds no
parent document. `T2D_V_1.docx` — the 524-page source both extracts were cut
from — has never been in the repository. The "~77,000 words" figure in the
GATE 4 report came from **your** description of the parent, not from anything
this build has read.

So question by question:

| | answer |
|---|---|
| 1. How many major structural families exist? | **Unknown for the unseen region.** Two are known from the two extracts. |
| 2. Which are covered by Video 1 / Video 14 grammar? | Both known families are. Coverage beyond them is unknown. |
| 3. Which repeated constructs look promising? | **Cannot say** — no repeated construct from that region has been observed. |
| 4. Which areas are genuinely unstructured? | **Cannot say.** |
| 5. Several large families, or hundreds of one-offs? | **Cannot say.** This is the question the survey exists to answer and it needs the text. |
| 6. What portion is describable structurally? | **Cannot say.** |

**No corpus-wide parser-rule estimate is offered**, which is also what the
task instructs: do not estimate before seeing the survey. There is no survey
of that material to see.

## What HAS been delivered: the surveyor, calibrated

`scripts/curated_survey.py`. Deterministic, read-only, no model call, and it
writes nothing anywhere — no envelope, no block, no field, no concept, no
grammar rule. Its only database access is an optional read of
`curated_grammar_rules`; with no `DATABASE_URL` that one section degrades to
a named skip and the rest still runs.

```
python3 scripts/curated_survey.py <file.md>
python3 scripts/curated_survey.py <file.md> --after "Video 14"
```

`--after` is there precisely for this job: point it at the exported parent
and it surveys only the region past the last recognised section.

It reports heading levels, nesting shapes, repeated prefix tokens,
**syntactic shape families** (a heading reduced to `W N — W W`, so identical
constructs collapse and different ones do not), exact repeated heading text,
repeated child-heading templates, the body-length distribution and
prose-only regions, and what the current grammar would match.

It reports **structure only**. It does not group headings by topic, does not
say what a section is about, and does not propose rules.

## Calibration on the two extracts

```
### Video 1
```
======================================================================
STRUCTURAL SURVEY — t2d_video1.md
======================================================================
  characters    16516
  words          2241
  headings         42
  words per heading (mean)     53.4

-- heading LEVELS ---------------------------------------------------
  L1      1
  L2     11
  L3     30
```

### Video 14
```
======================================================================
STRUCTURAL SURVEY — t2d_video14.md
======================================================================
  characters    20298
  words          2614
  headings         61
  words per heading (mean)     42.9

-- heading LEVELS ---------------------------------------------------
  L1      1
  L2     21
  L3     39
```

| | Video 1 | Video 14 |
|---|---|---|
| words | 2,215 | 2,584 |
| headings | 42 | 61 |
| distinct syntactic shapes | 16 | 24 |
| headings inside a REPEATED shape | 33 (79%) | 40 (66%) |
| repeated child-heading templates | 2 | **0** |
| bodies ≥ 1,200 chars | 0 | 0 |
| matched by some rule PATTERN | 37 (88%) | 50 (82%) |
| actually stored as a card/object field | — | 32 of 61 blocks |

**The last two rows are the calibration that matters, and they disagree on
purpose.** Pattern coverage reads 82% for Video 14 while 29 of 61 blocks are
REVIEW_REQUIRED. A pattern match is not ownership: `SUB_AUTHORED_SUBHEAD`
matches four headings inside Video 1's strategy cards and applies to none of
them, because `owner_kinds` confines it to curated objects. The tool prints
that caveat under the figure rather than letting an 88% be read as
comprehension.

**Two structural families, confirmed mechanically.** Video 1's dominant
repeated shape is `W N — W W W W W W` at L2 (the numbered strategy card);
Video 14 has no such shape at all and its L2 mass is the directive prefix,
counted separately as `ADD` ×3, `MERGE` ×4, `SKIP` ×2, `REINFORCE` ×1,
`ADD / UPGRADE` ×1. Video 14 also has **zero** repeated child-heading
templates against Video 1's two — the measured form of "the author names
their own subsections", which is why `SUB_AUTHORED_SUBHEAD` exists.

Neither extract contains a prose-only region: every body is under 1,200
characters. **That is a property of two heavily-headed sections and is
exactly the kind of thing that cannot be extrapolated** — a region with no
headings is the case a heading grammar cannot serve at all, and whether the
unseen 77,000 words contain such regions is the single most consequential
open question for the ingestion approach.

## To complete this survey

Put the parent document (or the post-Video-14 region) somewhere readable and
run the two commands above. Nothing else is needed: no schema change, no
ingestion, no provider, no library mutation. The survey is minutes of work
once the text exists.

**Until then, stop condition G is NOT met**, and it is recorded as unmet
rather than answered from the two sections that happen to be on disk.
