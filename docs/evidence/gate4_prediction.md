# GATE 4 — prediction, written and committed BEFORE the baseline ran

Fixture: `testing/fixtures/curated/t2d_video14.md`,
sha256 `03b6577d6190dfa53f1f13ea35b0957581fed2fc5dd5764a54841948fffd6bfd`,
20,364 bytes, frozen at `4b897e5`.

Grammar under test: the 17 rules seeded by migration `033`, unchanged.

**Method, stated so the prediction can be weighed properly.** This is not a
guess. I read the fixture's 61 headings and the 17 rule patterns and worked
out which match. So a hit is weak evidence — it mostly says I can read a
regex. **A miss is the valuable outcome**, because it would mean the parser
does something the rules do not say it does, and that is worth more than the
baseline itself.

---

## The numbers I am committing to

| | predicted |
|---|---|
| structural blocks detected (headings) | **61** |
| PARSED | **1** |
| REVIEW_REQUIRED | **60** |
| cards produced | **1** (a PRINCIPLE) |
| stored fields | **1** |
| provider / model calls | **0** |

## Which constructs I expect to parse

Exactly one: `### E7 principle` (line 46), via `PRINCIPLE_NAMED`. Its body
becomes a single `opening_statement` field — *"Use rapid responders as
evidence of possibility, not as a deadline imposed on every client."*

## Which constructs I expect to match a rule and then be REFUSED

Two, both by `attach()` rather than by `classify()`:

- `### Decision intelligence` (line 30) matches `SUB_DECISION`.
- `### Why it attracts clients` (line 68) matches `SUB_WHY`.

Both are subsections of a `## ADD — …` block, which no rule matches, so
neither has a strategy or principle to belong to. `attach()` will flip them
back to REVIEW_REQUIRED rather than inventing an owner. **This is the
behaviour I most want to see confirmed** — a subsection rule firing inside an
unrecognised parent is exactly where a lazier parser would attach the field
to whatever came before it.

## Which constructs I expect to fail, and why that is correct

- **All 11 curation-directive headings** — `ADD`, `ADD / UPGRADE`, `MERGE`,
  `REINFORCE`, `SKIP`. The grammar has no concept of a curation directive at
  all; its primary unit is `Strategy N — Name`, which occurs **zero times**
  in this document.
- **Both safety blocks** — `Berberine Safety / Gate`, `ACV Protocol
  Guardrails`. `SUB_SAFETY` is `^Safety(?:\s+context)?$` and matches neither.
- **Both decision-adjacent blocks** — `When potentially worth considering`,
  `When not to prioritize`. `SUB_WHEN_USEFUL` / `SUB_WHEN_NOT_USEFUL` are the
  exact strings `When useful` / `When not useful`.
- **`## Main Practitioner Principle`** (line 676) — near-miss on
  `PRINCIPLE_NAMED`, which anchors at `^` and so does not match a heading
  beginning `Main`. The document's single most important sentence will land
  in REVIEW_REQUIRED, and I predict that rather than hoping otherwise.
- Every roll-up, assessment, consultation, problem-solving and market block.

## What I am claiming this means

A high REVIEW_REQUIRED count here is the parser working. 1 of 61 says the
Video 1 grammar does not generalise to this section **at all** — not that it
is broken. The gate's question is whether the unknown is reported loudly and
completely, and whether the architecture can host a second construct family
without flattening Prem's reasoning into the first one.

## Where I expect to be wrong

The honest uncertainties, recorded now:

1. **Block count.** 61 is a count of `^#{1,6} ` lines. If the parser's
   `HEADING` regex disagrees with `grep` on any line, the count moves.
2. **`### Claim structure:` and `### Example:`** (lines 60, 64) are
   colon-terminated headings. I predict no rule matches them, but they are the
   clearest instance of the inline-label ambiguity the brief asks about.
3. **The `E7 principle` card's extent.** I predict its body stops at the next
   heading and it owns no subsections. If `attach()` gives it something, my
   model of ownership is wrong.
