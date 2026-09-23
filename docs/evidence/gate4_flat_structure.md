# GATE 4 — level independence of STORED and RETRIEVED structure (D57)

`0df47bf` made recognition level-independent and left the structure it
persisted depending on Markdown depth. `segment()` still built
`heading_path` with a stack on `#` count; that path was written into blocks,
strategies, principles, objects and fields and returned by `curated_trace()`
and `curated_expansion()`. The comparison added in that commit compared fields
by name and text and ignored `heading_path`, so it proved level-independent
RECOGNITION and said nothing about level-independent STRUCTURE.

The depth those paths encoded was assigned by a Claude model. The canonical
source states no level.

## Heading paths, before and after

### t2d_video1

| | before (depth stack) | after (parser state) |
|---|---|---|
| blocks | 42 | 42 |
| paths changed when every marker is rewritten to `#` | **41 of 42** | **0 of 42** |
| deepest path (segments) | 3 | 2 |
| paths of the form `container > subsection` | — | 20 |
| paths that are a block's own heading only | — | 22 |

Samples:

```
before  T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Video 1 distilled knowledge
after   Video 1 distilled knowledge

before  T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 1 — Breakfast restructuring
after   Strategy 1 — Breakfast restructuring

before  T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 1 — Breakfast restructuring > Why this can be useful
after   Strategy 1 — Breakfast restructuring > Why this can be useful

```

### t2d_video14

| | before (depth stack) | after (parser state) |
|---|---|---|
| blocks | 61 | 61 |
| paths changed when every marker is rewritten to `#` | **60 of 61** | **0 of 61** |
| deepest path (segments) | 3 | 1 |
| paths of the form `container > subsection` | — | 0 |
| paths that are a block's own heading only | — | 61 |

Samples:

```
before  T2D / Insulin Resistance — Engine 7 Update > Video 14: *Insulin Expert: Stop Eating THIS to Fix Blood Sugar in 90 Days*
after   Video 14: *Insulin Expert: Stop Eating THIS to Fix Blood Sugar in 90 Days*

before  T2D / Insulin Resistance — Engine 7 Update > ADD — Rapid Improvement Is Possible, but Timeline ≠ Biological Guarantee > Decision intelligence
after   Decision intelligence

before  T2D / Insulin Resistance — Engine 7 Update > ADD — Market / Client Expectation Intelligence
after   ADD — Market / Client Expectation Intelligence

```

**What "after" means.** A recognised container's path is its own heading. A
subsection it owns is `container > subsection`. Anything else is its own
heading with **no inferred parent**. The document-title ancestor every
"before" path began with existed only because the converter put a `#` above
everything; it is not in the source and is gone.

**Video 14 has zero `container > subsection` paths**, and that is correct: all
of its subsections are REVIEW_REQUIRED since `048`/`050`, so none is owned.

## Persisted rows and retrieved expansion, across renderings

`testing/test_gate4_renderings.py` imports each fixture four times through the
real inbox and importer — as committed, and with every heading marker
rewritten to `#`, `###` and `######` — and compares, per rendering:

- `curated_blocks`: ordinal, heading, status, rule, **heading_path**,
  **structural_provenance**, failure reason
- `curated_strategies`, `curated_principles`, `curated_objects`: name,
  **heading_path**
- `curated_fields`: owner, field name, **heading_path**, name provenance, text
  provenance, **text**, and the owning block's structural provenance
- `curated_expansion()` for every strategy card

**All identical across all four renderings, for both fixtures**, apart from
raw offsets, source titles and file locations — which differ by construction,
since each rendering is a different file with different byte positions.

## Structural provenance now travels with structure

`curated_trace()` and `curated_expansion()` return `structural_provenance` on
the card and on every field. For every source ingested today it is
`GRAMMAR_DERIVED_CLASSIFICATION` or `NO_HIERARCHY_AVAILABLE`, **never
`AUTHORED_STRUCTURAL_SIGNAL`**, and the suite asserts that.

## The markup depth is kept, and named as markup

It is persisted as `curated_blocks.source_markup_depth` (renamed from
`heading_level` in `051`, because that name read as an authored level). It is
kept for forensic audit, reaches no retrieval, and the suite asserts no
expansion carries it under either name. `curated_grammar_rules.heading_level`
now carries `CHECK (heading_level IS NULL)`, so a level cannot come back
through a registry INSERT.

## One label, two meanings

The flat survey (`scripts/curated_survey.py`, rebuilt for `D57`) lists labels
whose surface form recurs in more than one kind of container. Run across both
fixtures it flags exactly one:

```
'Decision intelligence'
      1x  inside CURATED_OBJECT
      1x  inside NONE
      1x  inside STRATEGY
```

In Video 1's Strategy 6 it is selection logic. In Video 14's ADD object it is
prognosis. `050` stops the object occurrence being stored as
`client_decision_logic`; Video 1 is unchanged.

## A test that was red for the wrong reason

Reverting the column rename made `test_gate4_renderings` go red — by
**crashing** on a query that selected `source_markup_depth`, before it reached
the assertion written for exactly that regression. The column-name check now
runs first, and the revert fails on it by name.
