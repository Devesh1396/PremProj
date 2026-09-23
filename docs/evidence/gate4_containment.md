# GATE 4 — only registered structure changes ownership (D58)

Independent review ran `scripts/curated_survey.py` against the canonical
`T2D_V_1.docx` (outside the repository, never committed) and measured what
the Markdown fixtures had hidden. **Those figures are the review's, not this
build's. The canonical file was NOT available in this session**, so the
canonical survey was **not re-run** here, and the review's run stands as
the only canonical measurement:

| canonical .docx, measured by independent review at `1cfdde8` | |
|---|---|
| paragraphs | 13,763 |
| authored heading levels | 0 |
| bold-only candidates | 4,207 |
| recognised | 278 |
| STRATEGY_NUMBERED containers | 28 |
| STRATEGY containers attaching nothing | 21 |
| STRATEGY containers attaching only SUB_WHAT_MEANS | 8 |
| STRATEGY containers keeping `client_decision_logic` | **0** |
| `Decision logic` reported UNRECOGNISED | 14x |
| labels flagged across container kinds | 0 — **a false negative** |

## The mechanism

`0df47bf` closed the open container on ANY unrecognised block. In the
canonical document an emphasised body sentence is a bold paragraph exactly
like a label, so the first one after `What the strategy means` closed the
strategy and every registered subsection after it was orphaned. The
Markdown fixtures were produced by a model that rendered those sentences as
inline bold inside a paragraph, so the rule held on them and nowhere else.

`Decision logic` was reported unrecognised because the survey printed
every REVIEW_REQUIRED block as one list: a registered label whose container
had been closed looked exactly like text matching no rule. The
cross-container list was a false zero for the same reason — nothing
attached, so nothing could appear in two kinds.

## The rule now

* a registered CONTAINER opens one (closing any previous);
* a registered SUBSECTION ownable by the open container kind attaches;
* a registered boundary that is neither (`Strategy family — …`) closes it;
* **everything else inside an open container is ABSORBED as body of the
  current field** — characters and span unchanged, the block kept
  REVIEW_REQUIRED with `absorbed_into_ordinal` and a `review_class`
  (`052`), listed by `v_curated_absorbed_body`.

A registered label the container may not own, or a second copy of a field it
already holds, is absorbed the same way and never attached. Nothing tells a
label from emphasis by length, punctuation, a trailing colon or
capitalisation, and no grammar rule was added.

## Synthetic regression, a real .docx

`testing/fixtures/docx/bold_body_between_labels.docx` — invented text,
bold paragraphs `Strategy 1 — Rotor balancing`, `What the strategy means`,
an emphasised bold body sentence, `Why this can be useful`,
`Client decision logic`, `Strategy 2 — Bearing inspection`. Read through
the real .docx reader and the production `classify` / `attach`
(`test_curated_flat.py` §7):

| | `1cfdde8` rule restored | D58 |
|---|---|---|
| emphasised sentence | NO_RULE, closes Strategy 1 | NO_RULE, absorbed into `What the strategy means` |
| `Why this can be useful` | REVIEW_REQUIRED, no owner | owned by Strategy 1 |
| `Client decision logic` | REVIEW_REQUIRED, no owner | owned by Strategy 1, `client_decision_logic` |

**Teeth:** restoring "unknown closes the container" turns
`test_curated_flat` (§3 five checks, §7 four checks), `test_curated_survey`
(3) and `test_gate4_atomicity` (1) red — as assertions, with no crash.
`test_gate4_renderings` stays green under the restored rule, correctly:
it proves level independence, and the old rule was level-independent too.

## Committed fixtures, `1cfdde8` → D58

Produced by running both parsers over the same fixture and registry:

```
== t2d_video1
  containers              8 -> 8
  fields                 24 -> 24
  REVIEW_REQUIRED        11 -> 11 of 42
  by reason (D58)      {'NO_RULE': 9, 'REGISTERED_NO_CONTAINER': 2}
  absorbed blocks      4
  fields added         []
  fields removed       []
  text identical       23 of 24
  GREW  'Preserve agency and reduce unnecessary deprivati' :: client_decision_logic  1191 -> 4456 chars, prefix identical=True, absorbed 4:
          - Adherence philosophy
          - Assessment & Consultation Intelligence
          - How this changes the consultation
          - Final Engine 7 intelligence from Video 1
== t2d_video14
  containers             12 -> 12
  fields                 12 -> 13
  REVIEW_REQUIRED        49 -> 48 of 61
  by reason (D58)      {'NO_RULE': 47, 'REGISTERED_NOT_OWNABLE': 1}
  absorbed blocks      46
  fields added         [('Market / Client Expectation Intelligence', 'why_useful')]
  fields removed       []
  text identical       5 of 12
  GREW  'Rapid Improvement Is Possible, but Timeline ≠ Bi' :: opening_statement  905 -> 1396 chars, prefix identical=True, absorbed 1:
          - Decision intelligence
  GREW  'Market / Client Expectation Intelligence' :: opening_statement  223 -> 391 chars, prefix identical=True, absorbed 3:
          - Market claim observed
          - Claim structure:
          - Example:
  GREW  'Carbohydrate Reduction Is a Strategy Spectrum, N' :: opening_statement  688 -> 1011 chars, prefix identical=True, absorbed 1:
          - Escalation logic
  GREW  'Exercise Selection Must Balance Biological Value' :: opening_statement  205 -> 797 chars, prefix identical=True, absorbed 1:
          - E7 reasoning
  GREW  'Berberine as a Practitioner-Gated Supplement Adj' :: opening_statement  938 -> 2393 chars, prefix identical=True, absorbed 5:
          - Final E7 status
          - Strategy tier
          - When potentially worth considering
          - When not to prioritize
          - Berberine Safety / Gate
  GREW  'Vinegar / ACV as a Meal-Targeted Food Adjunct' :: opening_statement  632 -> 2284 chars, prefix identical=True, absorbed 5:
          - Final E7 status
          - Strategy tier
          - Best use
          - ACV Does Not Replace Meal Structure
          - ACV Protocol Guardrails
  GREW  'Mechanism Overload Around ACV' :: opening_statement  468 -> 7515 chars, prefix identical=True, absorbed 27:
          - Assessment Intelligence Added
          - Time horizon
          - Intervention intensity
          - Eating distribution
          - Activity execution
          - Post-meal opportunity
          - Adjunct opportunity
          - Market expectation
          - Consultation Intelligence
          - Problem-Solving Intelligence
          - Client asks for the fastest possible result
          - Client cannot follow an "optimal" exercise program
          - Client already exercises but remains sedentary after major meals
          - Client wants berberine instead of fixing diet
          - Client wants ACV
          - Client is improving faster than expected
          - Client is not improved by 90 days
          - Market Intelligence Added
          - Larger market principle
          - Existing Knowledge Reinforced — Do Not Duplicate
          - Claims NOT to Store as Clinical Truth
          - Final Engine 7 Delta — Video 14
          - ADD
          - MERGE
          - PROVENANCE ONLY
          - Main Practitioner Principle
          - One-Sentence Engine 7 Takeaway
```

## What this costs, stated rather than hidden

**Video 1 is NOT text-invariant any more.** 8 containers and 24 fields are
unchanged, and 23 of the 24 texts are byte-identical. The 24th is
**Strategy 6's `client_decision_logic`** — the field GATE 1 recovered and
GATE 3 retrieves — which grew from the frozen span `[9452:10643]` (1,191
chars) to 4,456 chars by absorbing the document's closing sections:
`Adherence philosophy`, `Assessment & Consultation Intelligence`,
`How this changes the consultation` and `Final Engine 7 intelligence
from Video 1`, up to the registered `Core principle`. That material is
not Strategy 6's decision logic. `test_curated.py` §D used a substring
check that could not see the field grow; it now asserts the field starts
exactly at the frozen span with the frozen bytes and that every byte past
it belongs to one of those four audited absorbed blocks.

**GATE 3's within-band ranking moved, with no retrieval code changed.**
Same clean seed, same query, measured with each parser:

| | curated cards by rank |
|---|---|
| `1cfdde8` | (4, 0.9774), (1, 0.4286), (6, 0.3910), (2, 0.2632), (5, 0.1880), (3, 0.0977) |
| D58 | (4, 0.7898), (6, 0.4286), (1, 0.2305), (2, 0.1415), (5, 0.1011), (3, 0.0526) |

`1cfdde8` reproduces the recorded GATE 3 result exactly. Full text ranks a
card as one document, so Strategy 6's absorbed closing material now matches
the query. The answer key's bands still hold — PRIMARY {1, 4, 6} in the top
three, {2, 5} next, Strategy 3 last — and `test_gate3_acceptance` passes. The
order within the PRIMARY band is not in the key and was not asserted; no
assertion was added now, because one written after seeing the number would
be fitted to it.

**Video 14's SKIP object swallows the document's tail.** `SKIP —
Mechanism Overload Around ACV` absorbs 27 blocks (468 → 7,515 chars),
including `Claims NOT to Store as Clinical Truth`, `Final Engine 7 Delta —
Video 14`, `Main Practitioner Principle` and `One-Sentence Engine 7
Takeaway`. Curated objects are not retrieval-exposed, so nothing reaches an
engine today. It matters the moment they are: a retrieval layer that
excludes SKIP would never return the main practitioner principle.

**One new registered role.** `Why it attracts clients` (SUB_WHY) is now
owned by the Market object as `why_useful`, role RATIONALE — previously
orphaned by `Market claim observed`. Whether that label means "rationale"
in a market-expectation object is the same kind of question as Q1, and the
survey's new rule-level list flags SUB_WHY for it. `test_gate4_acceptance`
asserts exactly this one role and still asserts that no field is
PRIORITISATION.

**The cure for all four is registering boundary labels, and that is a
coverage decision for the practitioner**, not something this build may
make: `Final Engine 7 intelligence`, `Main Practitioner Principle`,
`Claims NOT to Store as Clinical Truth` and the rest are the practitioner's
own section names, and whether each one opens, closes or belongs to a
container is theirs to say.

## Assertions that changed, and why

| suite | was | now | why |
|---|---|---|---|
| `test_curated_flat` §3 | a registered label after an unrecognised block is REVIEW_REQUIRED | it attaches | that assertion WAS the refuted rule; the fixture text said so. Fail-closed cases kept: no container, not ownable, duplicate field, after a registered boundary |
| `test_curated_flat` §3 | `by_head["Monitoring"]` | by ordinal | a dict keyed by heading held the SECOND Monitoring, so "no container open" examined the wrong block |
| `test_curated_flat` §1/§4, `test_gate4_renderings` | field text byte-equal across renderings | equal with line-start `#` markers removed, AND raw-equal for every field that absorbed nothing | absorbed headings keep the rendering's own `#` run (VERBATIM_SOURCE); those markers are the model depth the suites prove meaningless. Measured: all differences vanish with markers removed, in all 12 comparisons |
| `test_curated_survey` | split on "MORE THAN ONE KIND OF CONTAINER" | bounded section | the new rule-level section shares the phrase |
| `test_gate4_atomicity` | 11 object fields | 12 | the Market object's `why_useful` |
| `test_gate4_acceptance` | REVIEW_REQUIRED 49; no registered role | 48; exactly one, RATIONALE, none PRIORITISATION | the same block |
| `test_curated` §D | CONTAINS the frozen span | starts exactly at it; the rest is audited absorption | CONTAINS could not see the field grow |
