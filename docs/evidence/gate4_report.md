# GATE 4 — report

One source. Video 14, frozen at `4b897e5`, sha256 `03b6577d…`, 20,364 bytes
(20,298 characters), 2,584 words.

Companion evidence, none of it rewritten after the fact:
`gate4_prediction.md` (committed before the baseline),
`gate4_baseline.md` (the 033-only measurement),
`gate4_first_run.md` (the first implemented run, a MISS, and what followed).

---

## A. PREDICTION VS BASELINE

Committed at `432d0c1`, before `039357b` measured anything.

| | predicted | actual |
|---|---|---|
| blocks detected | 61 | **61** |
| PARSED | 1 | **1** |
| REVIEW_REQUIRED | 60 | **60** |
| cards | 1 | **1** |
| fields | 1 | **1** |
| provider calls | 0 | **0** |

Every number matched, including the two subsections that match a rule and
are then refused by `attach()`, and `## Main Practitioner Principle`
near-missing `PRINCIPLE_NAMED` on the `^` anchor.

**Where I was wrong: nowhere, and the file said in advance why that is weak
evidence.** The prediction was derived by reading 61 headings against 17
regexes, not guessed, so matching says the rules mean what they say — not
that the corpus is understood. The prediction also recorded three
uncertainties; all three resolved as predicted.

**One thing the baseline found that the prediction did not anticipate at
all**: the spans are **character** offsets, not byte offsets. 20,364 bytes
vs 20,298 characters, because of `—`, `≠`, `→`, `−` and curly quotes. GATE 1
and GATE 3 call them byte ranges throughout, including in
`ck_link_span_is_phrase`. They verify correctly — the same convention writes
and re-reads them — but the documentation would mislead any consumer that
seeks by byte. Reported, not fixed: renaming reaches into GATE 1 and GATE 3.

---

## B. BASELINE

`docs/evidence/gate4_baseline.md`, verbatim and never replaced.
Reproducible: `testing/gate4_baseline.py` **pins itself to the rule ids
migration 033 seeds**, read out of the migration file, so adding rules
cannot quietly re-measure something else under the same heading.

1 of 61. The single parse is `### E7 principle`. Eleven curation-directive
headings — the document's organising unit — matched nothing, and
`Strategy N`, the grammar's primary unit, occurs **zero times**.

---

## C. GRAMMAR DELTA

**Two rules.** That number is the result, not an accident.

| rule | construct | why reusable |
|---|---|---|
| `CURATION_DIRECTIVE` | `ADD` / `ADD / UPGRADE` / `MERGE` / `REINFORCE` / `SKIP` / `PROVENANCE ONLY` followed by a dash and a title | It is the editing language the practitioner uses to tell Engine 7 what to DO with a block, and it is **self-describing**: the disposition is the literal word the author wrote, so recognising it needs no inference about meaning. The section's own closing roll-up uses the same six words as its headings, which is the author confirming it is a vocabulary rather than a phrasing. |
| `SUB_AUTHORED_SUBHEAD` | any level-3 heading **inside a curated object** | The construct is **authorial, not lexical**: "the author names their own subsection". A closed field list would either drop headings it does not know or rename them, which is the flattening GATE 1 exists to prevent arriving through the grammar. The field takes the author's own name, slugified; the heading and its span are preserved. |

**Counterexamples, tested in `testing/test_curated_objects.py` on synthetic
text that shares nothing with Video 14:**

- The generic rule **must not** reach inside a strategy card. Proven: an
  invented heading inside `Strategy 1 — Plate structure` stays
  REVIEW_REQUIRED, and the refusal names the owner kinds it needed. This is
  enforced by a registry **column** (`owner_kinds`), not a branch in the
  parser, so the scope travels with the rule.
- A `CURATED_OBJECT` rule that captures no `directive` group is refused
  rather than having its disposition guessed.
- The verification rule must not match `"The source checked the underlying
  report"`, `"I checked with the client"`, `"I checked the numbers against
  my own practice"`, `"We should check the underlying report"`. All four
  tested.

**Deliberately NOT given rules**, and reported instead: `Final E7 status`
and `Strategy tier` (two occurrences each, both inside this one fixture —
not evidence of reusability); `When potentially worth considering`, `When
not to prioritize` (Q1); `Berberine Safety / Gate`, `ACV Protocol
Guardrails` (Q3); every assessment, consultation, problem-solving and market
heading. **Note the correction in migration `043`**: `041`'s header claims
those four are left REVIEW_REQUIRED, and they are not — they get no rule of
their own, but the generic rule stores them as author-named fields. The
intent (no aliasing to `client_decision_logic` or `safety_context`) holds;
the header described an outcome the parser does not produce.

**A mechanism defect the synthetic suite found, not a rule gap.**
`classify()` selected the highest-priority matching rule and `attach()` then
refused it, with no fallback — so `Why this is worth keeping` inside a
curated object matched a strategy-card rule, failed ownership, and was lost
although a rule that *would* have applied also matched. **A block's fate was
decided by the order two rules were tried in.** Same shape as the trigram
tier ending the chain at a near-match and never reaching the semantic tier
(D51). Fixed the same way: keep the candidates, hand over.

### The 18-section estimate, and why the framing has to change first

**The corpus is not 18 uniformly-marked sections, so an 18-section estimate
would be arithmetic on a premise that is false.** The `Video N` heading
stops at Video 14. Roughly **77,000 words** follow it with no such heading —
about **30× the size of this fixture**, and the majority of the 524-page
parent by a wide margin. Nothing is known about its structure.

What the two samples do support:

| | Video 1 | Video 14 |
|---|---|---|
| grammar family | numbered strategy cards | curation directives |
| rules needed | 9 of 17 | 2 new |
| blocks | 42 | 61 |
| REVIEW_REQUIRED | 11 (26%) | 29 (48%) |

Working, and its limits:

1. Two sections produced **two** grammar families and **two** new rules for
   the second. Cost per new family so far: ~2 rules.
2. The 29 blocks still unmatched are **not 29 one-offs**. They cluster into
   about **eight** candidate constructs: assessment questions (7 + its
   container), problem-solving scenarios (7 + its container), consultation
   intelligence, market intelligence (2), the closing roll-up (4), the
   do-not-duplicate list, the do-not-store list, and the two closing
   principle/takeaway headings. So the reusable-to-one-off ratio inside
   the *recognised* part of the corpus looks favourable: **~8 constructs
   for 29 blocks**, not 29 bespoke rules.
3. **For the 13 remaining `Video N` sections**, if they divide between the
   two known families, the incremental cost is plausibly **0–8 rules** —
   mostly the eight constructs above, which Video 14 alone is not sufficient
   evidence to justify.
4. **For the 77,000 unmarked words, no estimate is defensible.** They could
   be a third family costing two rules, or unstructured prose for which a
   deterministic grammar is the wrong tool entirely and K09-for-raw is
   right. Two samples cannot distinguish those.

**Recommendation on the estimate: a structural survey of the post-Video-14
material is a prerequisite to any corpus-wide number.** That survey is
cheap — it needs heading extraction and frequency counting, not ingestion,
not a model, and not this gate's storage layer.

---

## D. STORAGE DECISION

**Could the existing curated schema represent Video 14? No.**

`curated_strategies` has no disposition. Writing an `ADD` block there
asserts it is a strategy, which for `SKIP — "Underground Vegetables Should
Be Restricted"` is not imprecision but the exact failure the gate exists to
catch: a rejected claim promoted to active knowledge.

**The smallest generalized representation, and what was reused rather than
rebuilt:**

- `curated_objects` — new. Explicit `disposition`, plus `directive_start/end`
  pointing at the characters the disposition was read from, so "this is a
  SKIP" is traceable rather than asserted. `ck_object_directive_span` keeps
  that pointer inside the object.
- `curated_disposition_is_active()` — a function, so "REINFORCE, SKIP and
  PROVENANCE_ONLY may never become active knowledge" is a database property
  and not a convention in the runner.
- `curated_fields` — **reused**, with a third owner. The per-field
  provenance contract is what GATE 1 proved; a parallel table would be a
  second place to enforce it differently.
- `curated_strategy_concepts` — **reused**, with a second owner, for the
  same reason.
- Inbox, envelope, rights, content hash, §57 dedup, K08's chunker, the
  concept resolver, `knowledge_entities` / `envelope_derived_records` — all
  unchanged (D37, hard rule 12).

**Video 1 was not migrated.** `curated_strategies` and `curated_principles`
are untouched and no view flattens one into the other. Proven, not assumed —
see F.

**The change was unavoidable** in the narrow sense that the alternative was
to store a refusal as a strategy. Everything beyond that was reuse.

---

## E. KNOWLEDGE-STATE AUDIT

| state | count | examples |
|---|---|---|
| **A — practitioner intelligence** | 1 principle + 8 active objects | `E7 principle`: *"Use rapid responders as evidence of possibility, not as a deadline imposed on every client."* Stored and usable; not recorded as evidence and not sent for re-research. |
| **B — practitioner-verified evidence** | **1** | *"I checked the underlying published report."* at `[539:581]`, `PRACTITIONER` / `PRACTITIONER_VERIFIED`, attached to the Rapid Improvement object. |
| **C — source/market claim** | 1 object (`Market / Client Expectation Intelligence`, 7 fields) | Holds `Example:` → *"Reverse insulin resistance in 90 days."* and the source's own `Important separation` block. Disposition ADD; it is market intelligence the practice must know, and it is not evidence and not a recommendation. |
| **D — uncertain evidence-supported adjunct** | 2 | Berberine: 6 fields (`final_e7_status`, `strategy_tier`, `when_potentially_worth_considering`, `when_not_to_prioritize`, `berberine_safety_gate`, `opening_statement`). ACV: 6 fields (`final_e7_status`, `strategy_tier`, `best_use`, `acv_does_not_replace_meal_structure`, `acv_protocol_guardrails`, `opening_statement`). **Not flattened into "works / does not work".** |
| **E — merge / reinforce** | MERGE 4, REINFORCE 1, ADD_UPGRADE 1 | Carbohydrate spectrum, natural fat, exercise selection, exercise snack; earlier energy distribution; ACV upgraded from candidate. |
| **F — rejected / skip** | SKIP 2 | `"Underground Vegetables Should Be Restricted"`, `Mechanism Overload Around ACV`. Full text preserved, `curated_disposition_is_active()` false. |
| **provenance-only** | 0 objects | The `PROVENANCE ONLY` roll-up heading is level-3 inside the closing delta and is REVIEW_REQUIRED, not an object. See the caveat below. |
| **REVIEW_REQUIRED** | **29 of 61** | Every one keeps its heading, its full raw text, its span and a reason. |

Totals: **11 objects** (ADD 3, ADD_UPGRADE 1, MERGE 4, REINFORCE 1, SKIP 2),
1 principle, **31 fields** (31 verbatim, **0 transformed**), 1 verification,
0 unattached verifications, **0 provider calls**.

**A caveat I am not going to paper over.** `PROVENANCE ONLY` is one of the
six dispositions in the enum and Video 14 never uses it as a block heading —
only as a level-3 roll-up label listing four items. So that disposition is
**implemented and unexercised by real data**. The synthetic suite exercises
it; this source does not.

---

## F. PRESERVATION AUDIT

- Object fields whose stored text is not exactly their claimed slice: **0**.
- `TRANSFORMED` fields: **0**. Everything is `VERBATIM_SOURCE`.
- Invented `mechanism` fields: **0** (asserted, given D49).
- Blocks stored with empty raw text: **0**.
- Verification statements whose span does not contain the statement: **0**,
  checked in the importer *and* by `ck_verification_span_is_statement`.
- Authored text silently discarded: **none**. Every character is either
  inside a stored field or inside a REVIEW_REQUIRED block that carries its
  heading, text, span and failure reason.

**Video 1 byte-identity: PASS, compared row by row.** The acceptance suite
imports Video 1 first, captures `(ordinal, name, span, content_hash,
field_name, text_value, field span, provenance)` for every strategy field,
runs GATE 4, and re-reads. Identical. Separately, parsing Video 1 under
033-only vs 033+041 yields identical block statuses, rule ids, parent
ordinals, card spans, name spans, content hashes and field text — so the
guarantee holds at the parse level as well as in the stored rows. Video 1
produced **0** curated objects.

---

## G. CONCEPT AUDIT

Run on a clean K1 seed (269 concepts), `read_only=True`, semantic tier
inert (`LLM_API_KEY` unset — a named degradation, V3).

| | |
|---|---|
| candidate units | **11** |
| refused as statements, not names | **27** |
| resolved | **0** |
| concepts created | **0** (`read_only`) |

Units, all `UNRESOLVED` at tier `none`: `Market / Client Expectation
Intelligence`, `Do Not Fear Naturally Occurring Fat Automatically`, `Earlier
Energy Distribution / Late Eating`, `Exercise Selection Must Balance
Biological Value with Execution`, `Berberine as a Practitioner-Gated
Supplement Adjunct`, `Vinegar / ACV as a Meal-Targeted Food Adjunct`,
`Mechanism Overload Around ACV` (CARD_NAME); `\<30 g/day for 90 days`,
`\<30 g carbohydrate/day`, `HIGH-POTENTIAL ADJUNCT / MODERATE EVIDENCE
CONFIDENCE`, `PRACTICE-INFORMED / EVIDENCE-SUPPORTED SECONDARY ADJUNCT`
(BOLD_LABEL).

**0 resolved is a library state, not a parser failure.** The K1 seed holds
no concept for berberine, vinegar or market intelligence, and `read_only`
created none (D8). `SEMANTIC_THRESHOLD` 0.82 was not touched, no alias was
added and no concept was created to improve this number.

**Two findings here, both mine, both fixed before this measurement:**

1. **The concept bridge did not see curated objects at all.** The first
   complete run reported `units 0` — not because nothing resolved, but
   because `attach_concepts()` iterates `curated_strategies`. A new
   knowledge object nothing can reach by concept is D52a again.
2. **And once wired, it was wired wrong.** `card_units` exempts the card
   NAME from the grammatical phrase test, which is right for `Breakfast
   restructuring` and wrong for `ADD — Rapid Improvement Is Possible, but
   Timeline ≠ Biological Guarantee`. Sending that to the resolver is the
   mechanism mistake in a new costume (D51). The exemption is withdrawn for
   objects: 7 of 11 headings pass the ordinary test, **4 are refused and say
   so** rather than being dropped.

**Stated, not left to be discovered: retrieval does not surface curated
objects.** `by_concept()` and `by_fts()` read `curated_strategies`.
Widening them is GATE 3 work this gate was scoped out of, so the links are
stored, traceable and **unused**, and the column comment says exactly that.

---

## H. THE THREE QUESTIONS — reported, not solved

### Q1. One field under three names, or three fields?

**Not decided, and deliberately not decidable by accident**: none of the
three was aliased, and none was given a rule that would map it onto
`client_decision_logic`. All three are preserved as their own fields with
their own spans, so either answer remains available and reversible.

**`Decision intelligence`** `[1318:1809]` — *(subsection of `ADD — Rapid
Improvement`)*

> A short timeline may be more plausible when:
> diabetes is relatively recent; there is substantial modifiable
> adiposity/metabolic load; intervention intensity and adherence are high;
> glucose begins responding quickly; sufficient beta-cell capacity remains.
> […] A client with long-duration diabetes, substantial beta-cell
> dysfunction, complex medication use, lower intervention adherence, or
> different underlying drivers may follow a very different trajectory.

**`When potentially worth considering`** `[9204:9476]` — *(subsection of
`ADD — Berberine`)*

> Especially when:
> major lifestyle drivers are already being addressed; client specifically
> wants a supplement adjunct; glucose control remains suboptimal;
> cost/burden is acceptable; medication/safety context has been reviewed.

**`When not to prioritize`** `[9476:9771]` — *(subsection of `ADD —
Berberine`)*

> If the client still has obvious major untreated bottlenecks such as:
> high refined-carbohydrate exposure; major excess energy intake; very low
> activity; poor adherence to foundational plan.
> Do not let supplement optimization replace major-driver optimization.

**What the text suggests, offered as observation and not as a decision.**
`Decision intelligence` is about a *prognosis* — when a fast timeline is
plausible for this client — and it has no negative counterpart in its block.
The berberine pair is about *intervention selection*, and it is explicitly a
pair: positive indication and contra-indication, in the shape `033` already
calls `When useful` / `When not useful`. So they may be two different things
(prognosis vs selection) that both differ from Video 1's
`Client decision logic`, which does both at once. **Your call.**

### Q2. Where does SKIP material live?

It currently lives in `curated_objects` with `disposition = SKIP`, full text
preserved, `curated_disposition_is_active()` false. The options the existing
schema offers, **none chosen**:

- **`negative_knowledge`** — has `why_investigated`, `evidence_examined`,
  `revisit_trigger`, and exists for a question **examined and found wanting**
  (D41). Video 14's SKIPs are not that. Prem is refusing *the source's
  simplification* — "carrot ≠ potato ≠ beet ≠ sweet potato… cannot be
  meaningfully classified only by botanical location" — not reporting a
  failed investigation. And there is no revisit condition in the text, so
  the NOT NULL columns could only be filled by inventing one, which D41 says
  is a `COMPLETE` status by another name.
- **`knowledge_gaps`** — "nobody has looked". False: somebody did.
- **`curated_blocks` REVIEW_REQUIRED** — preserves text and span, but asserts
  the *parser* did not understand, which is also false.
- **`curated_objects` with SKIP** — what is implemented. Says what the
  document says, and nothing more.

**The distinction that matters for your decision:** a SKIP here is a
*curation* verdict on a source's claim; `negative_knowledge` is a *research*
verdict on a question. If you want SKIPs to stop the same claim being
re-researched later, they need a bridge to `negative_knowledge` with a
revisit trigger a human supplies — which is a decision, not a parse.

### Q3. Is there a non-flattening home for safety?

**It is a GAP. Reported, not closed.**

`Berberine Safety / Gate` `[9771:10389]` and `ACV Protocol Guardrails`
`[11943:12741]` are preserved verbatim as their own author-named fields with
their own spans. **They are not reachable as safety.**

- `033` has `SUB_SAFETY → safety_context`, but it matches only the bare
  heading `Safety` and it is a **strategy-card** subsection. Neither applies.
- The deterministic safety layer — `safety_rules`,
  `safety_match_patterns`, `critical_lab_thresholds` — is a
  practitioner-curated registry, and D42 makes adding a rule an INSERT a
  human performs. **A curated import writing into it would be an ingestion
  path authoring clinical gates**, which is a larger decision than this gate.

So the content is preserved and inert. Video 14 contains a routable rule in
so many words — *"berberine + active medication use → interaction/safety
check before implementation"* — and there is currently no path from that
sentence to `safety_rules` that does not involve a machine authoring a gate.

---

## I. FIRST IMPLEMENTED RUN

**MISS.** `docs/evidence/gate4_first_run.md`, kept above the fold.

The run aborted on `envelope_derived_records / fk_derived_entity`: migration
`040` added `CURATED_OBJECT` to the `derived_kind` enum and **did not add
the registration trigger hard rule 12 requires**. `040`'s own header cites
that rule and then does half of it.

The constraint caught it at the first attempt to store a real object — D12
working as designed. `042` adds the triggers, append-only; `040` is not
edited.

Two further defects, both in my own tests, both found by running:

- The acceptance suite cleared its fixtures at the **start** and not at the
  end, so Video 14's text stayed in the library and `test_curated`'s D49
  negative control found `GLUT4` and `beta-cell` — which really are in Video
  14 — and reported a fabrication that never happened. Visible only on the
  **second** consecutive `run_all`.
- A Python tuple comma in SQL: `field_name in ('mechanism',)`.

And one correct guard I tripped: `test_optional_deps` refuses the literal
`SKIP` inside a `print()`, because a hand-rolled skip is never exercised by
its registry. My Q2 prose set it off. The guard is right and cannot tell
prose from a hand-rolled skip, so the disposition's name is held in a
variable rather than the guard being weakened.

---

## J. ONE COMPLETE TRACE

```
fixture   testing/fixtures/curated/t2d_video14.md  sha256 03b6577d…
  ↓ heading  "## ADD — Berberine as a Practitioner-Gated Supplement Adjunct"
object    curated_objects  disposition=ADD  span [7931:10389]
          directive span [7934:7937] → the characters "ADD"
          name span [7940:7992] → "Berberine as a Practitioner-Gated Supplement Adjunct"
  ↓ subsection "### Berberine Safety / Gate"
field     curated_fields.field_name = 'berberine_safety_gate'
          span [9800:10387]   provenance VERBATIM_SOURCE
          text  "Common adverse effects include:\n\nnausea\\\ndiarrhea\\\n
                 constipation\\\nbloating/abdominal symptoms.\n\nIt can
                 interact with medications, and NCCIH advises against its
                 use in pregnancy/breastfeeding and infants. …"
  ↓ mechanical check
          source[9800:10387] == stored text          → TRUE
  ↓ knowledge state
          D — evidence-supported but uncertain adjunct; safety kept as its
          own field, not folded into a description
  ↓ concept
          name unit "Berberine as a Practitioner-Gated Supplement Adjunct"
          → UNRESOLVED, tier none. The K1 seed has no berberine concept and
            read_only created none.
  ↓ retrieval-visible
          NO — retrieval reads curated_strategies. Stated in G, not implied.
```

## K. ONE REJECTED TRACE

```
source    "## SKIP — \"Underground Vegetables Should Be Restricted\""
  ↓
object    curated_objects  disposition=SKIP  span [4888:5349]
          full text preserved, including
            "carrot ≠ potato ≠ beet ≠ sweet potato"
            "Existing E7 intelligence is better: amount + preparation +
             food matrix + meal context + individual response."
  ↓ provenance retained
          knowledge_entities: CURATED_OBJECT   (registered)
          envelope_derived_records → the source envelope
  ↓ proof it is NOT active practitioner knowledge
          curated_disposition_is_active('SKIP')  → FALSE   (database property)
          curated_strategies rows from this envelope        → 0
          concept links from SKIP objects                   → 0
          ix_curated_objects_active excludes it by predicate
```

Rejection did not become deletion of provenance, and it did not become
knowledge.

---

## VERIFY — exit codes captured and read, never behind a pipe

| | |
|---|---|
| `testing/test_curated_objects.py` (synthetic grammar) | `0` |
| `testing/test_gate4_acceptance.py` (frozen fixture) | `0` |
| `testing/test_curated.py` (GATE 1) | `0`, inside `run_all` |
| `testing/test_gate3_bridge.py` (GATE 3) | `0`, inside `run_all` |
| `bash testing/run_all.sh` | `0` — ALL SUITES PASSED |
| `bash testing/run_all.sh` (re-run, idempotent) | `0` — ALL SUITES PASSED |
| `bash testing/run_bare.sh` (no optional extension) | `0` — ALL SUITES PASSED |

**Named skips**, not passes: the semantic tier is inert without
`MODEL_EMBEDDING` / `LLM_API_KEY` / pgvector, so `semantic_recomputation_
authoritative()` is false and says why; `test_gate3_acceptance` skips inside
`run_all` as it always has.

**One red run, explained rather than dismissed.** During verification
`run_all` failed once with `test_normalization` raising an unhandled
`HTTPError: 429 Too Many Requests` from the embedding provider. That suite
was last touched in GATE 2 (`d3c0efb`), is untouched by this branch, and
guards on capability and env but **not** on the provider rate-limiting.
Reproduced deliberately, then confirmed green on four subsequent runs once
quota recovered. **It is a V3-shaped hole — a live dependency that crashes
instead of degrading to a named skip — and it is pre-existing. Reported, not
fixed here.** It also means a green `run_all` in this environment is partly
a statement about provider quota.

---

## STOP CONDITION

**No import of the full source has begun, and none should.**

**Recommendation: B — another materially different grammar family should be
tested before the corpus, and before that, the unmarked material needs a
structural survey.**

Not A. Video 14 shows the architecture can host a second construct family
without flattening — the disposition is explicit, Video 1 is byte-identical,
nothing was aliased, 0 fields were transformed, and unknown structure stayed
loud at 48%. But **two samples that both came from the `Video N` region
cannot support a claim about a corpus that is ~30× larger outside it.**

Not C. Nothing in this gate suggests the architecture is wrong. The three
defects found were a missing trigger, a chain that ended early, and a bridge
that was not connected — all mechanism, all caught by constraints and tests
that already existed for exactly that purpose.

**What I would do next, in order:**

1. **Survey the 77,000 unmarked words structurally** — heading extraction and
   frequency counts, no ingestion, no model. Until that exists, every
   corpus-wide number is arithmetic on a guess.
2. **Then one section from the least-structured part of that material**, as
   the third preservation test. GATE 1 already said the next test should be
   one of the least structured sections; Video 14 was materially different
   but still heavily headed.
3. **Decide Q1, Q2 and Q3.** All three are open by design and all three
   become UPDATEs to registry rows, not re-imports.
4. **Close the safety gap (Q3) before importing a section whose safety
   content must be routable**, and close the `verification_actor` /
   `verification_status` gap on `evidence_records` if evidence records are
   ever to carry what `curated_verifications` now carries.

**Still closed, and untouched by this gate:** K10, the 20-video pilot, K09 on
curated content, `SEMANTIC_THRESHOLD` 0.82, the GATE 3 answer key `b5b2477`,
retrieval weights.
