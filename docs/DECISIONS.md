# DECISIONS

Architecture decisions with rationale, including what was rejected and why.

**Read this before proposing any structural change.** Several constraints
here look like overhead or like something to "clean up" if you don't know
what they protect against. Every one of them was argued and settled. If a
decision genuinely blocks implementation, raise it as a blocker rather than
routing around it.

Status key: **SETTLED** — do not revisit without explicit instruction.
**OPEN** — genuinely undecided. **DEFERRED** — decided to postpone.

---

## D1 — Seven-engine architecture over a single-prompt system
**SETTLED**

Two approaches were weighed. Approach A: seven specialist engines with
persistent state and a knowledge library. Approach B: one large system
prompt doing clinical analysis, behaviour and communication in a single
call, with a curated Notion library and RAG "later".

B was faster to ship and had sharper clinical texture. It was rejected on
three grounds:

1. **No memory.** Every run stateless. A returning client is a new client.
   Workable at 5 clients, impossible at 50.
2. **No response learning.** The commercial product is a 90-day programme
   that is entirely iteration. B designs month one and has nothing for
   months two and three.
3. **Conversion inside the reasoning engine.** B's single call both decides
   what the client needs and writes the upsell script. A reasoning engine
   with conversion in its objective will over-promise, and it will not be
   obvious when it does.

The upsell varies per client, which means the continuation decision must
come from actual response data. That is Engine 4's job and B cannot reach it.

**What was kept from B:** the 4-Week Energy Diet framing, rapid symptomatic
wins as the bridge into the longer programme, and the consultation script —
all relocated to **Engine 5 and the phase model**, not Engine 1. Its
clinical texture (meal sequencing, Indian flour swaps, therapeutic dosing
forms) belongs in **Engine 7's library and Engine 3**, as retrievable
versioned knowledge rather than frozen prompt strings.

---

## D2 — Concept normalization layer
**SETTLED**

Engine 1 emits prose: *"large post-meal glucose excursions associated with
refined evening carbohydrate intake and low muscle stimulus"*. The library
stores rows. Prose does not join to rows.

Without a canonical concept layer, hybrid retrieval degrades to vector
similarity alone — which is precisely the "huge library, bad retrieval"
failure mode identified as the first way Engine 7 fails. 10,000 strategies
with bad retrieval is worse than 200 with good retrieval.

Design constraints:
- Engines are **never** asked to speak in codes. Normalization sits between
  reasoning output and retrieval.
- One phrase → many concepts, and many phrases → one concept, both allowed.
- Resolution order cheapest-first: deterministic alias → structured mapping
  → trigram → semantic → LLM only when required.
- Confirmed results cached (`normalization_cache`) so a phrase never costs
  a second LLM call.

**Rejected:** forcing engines to emit canonical keys. It distorts clinical
reasoning to serve the database and produces worse analysis.

---

## D3 — `CONFUSABLE_DO_NOT_MERGE`
**SETTLED**

"Belly fat" and "central adiposity" are colloquial and clinical versions of
one thing. "Visceral fat" is a distinct compartment with different
metabolic risk. All three are semantically close; embedding similarity will
merge them.

So the concept graph carries an explicit do-not-merge relation, auto-
mirrored by trigger so a merge check cannot miss a pair by querying the
wrong direction. Negative test pairs are **generated from sibling structure**
(concepts under a shared parent), not hand-enumerated — that is where
dangerous merges actually occur.

---

## D4 — Engine 1 runs twice, with one specification
**SETTLED — enforced by `trg_enforce_two_pass`**

Phase 32 specifies `E1 analyze → E7 retrieve → E1 finalize`. That is E1
twice. Without the split you either give E1 no knowledge, or you retrieve
before understanding the client.

**Pass A and Pass B are the same master specification invoked twice.**

Binding rules:
1. One prompt file, `engine1_prevention.md`, loaded for both. There is no
   `engine1_pass_a.md`.
2. Neither pass may be trimmed, summarised or otherwise weakened.
3. The difference is context and stopping point, not capability. Pass A has
   an empty E7 slot and emits research questions; Pass B has it populated.
4. Both runs record the identical prompt hash. A divergent hash is a build
   error, not a variation.

If Pass A appears to need a shorter prompt for cost or latency, that is a
signal to revisit orchestration, **not** to fork Engine 1.

The database rejects a violation outright:
> E1 pass B uses prompt engine1_pass_b_lite.md (hash 4f2a…) but the other
> pass in this cycle used engine1_prevention.md (hash 9c81…). Pass A and
> Pass B must run the identical master Engine 1 specification.

---

## D5 — Prompt length is not output length
**SETTLED — an earlier proposal was withdrawn**

An early review proposed splitting Engine 1 into staged calls on the
grounds that a ~5,000-word prompt demanding a 19-part report would produce
degraded output. **That proposal was withdrawn.** It reasoned backward from
prompt size to a change in the reasoning architecture, before output
contracts were even defined.

The engine specifications describe *how each engine reasons*. They are not
templates for 50-page client reports. Output design — machine JSON,
practitioner quick view, deep-analysis view, client report, WhatsApp
format — is a separate later task.

**Do not simplify reasoning to make output tidy.**

The one legitimate concern is that context and output limits are a hard
constraint, not a preference. Handle it empirically: once the canonical
prompt and an API key are in place, measure actual token counts and output
quality across the full report. If later sections degrade, staging becomes
a mechanical fix at that point. Measure; do not pre-empt.

---

## D6 — Safety controls: narrow, deterministic, release-only
**SETTLED**

An early proposal listed antihypertensives, thyroid replacement and
diuretics as HOLD triggers. Against this client population that fires on
nearly every case, which makes the gate a rubber stamp providing less
protection than no gate while adding friction. **That proposal was
withdrawn as too broad.**

It was also aimed at the wrong artifact. In a single-prompt system where
analysis goes straight to output, broad gating is warranted. In the
seven-engine system, internal reasoning and client-facing output are
already separated by Engine 5 plus practitioner review. Internal breadth is
not delivered action.

**What survives — roughly five or six deterministic checks:**
- Configured critical lab thresholds
- Insulin or sulfonylurea combined with a glucose-lowering intervention
  (a plan that works creates hypoglycaemia risk within days)
- Warfarin where the intervention plausibly interacts
- Pregnancy, breastfeeding, minors
- Significant renal or hepatic impairment
- Engine 4 reporting a worsening marker

A client on metformin, a statin and an ACE inhibitor **passes clean**.

Structural rules:
- Deterministic rules are SQL over `client_labs` / `client_medications` /
  `client_conditions`. Not prompt instructions — a missed flag is the case
  you cannot afford.
- An LLM may **add** flags. It may not **clear** a deterministic one
  (`trg_protect_deterministic_flags`).
- Only **release** of client-facing output is gated
  (`trg_block_unapproved_communication`). Drafting, internal analysis and
  the practitioner view are never gated. NOTE flags never block.

**Separately and absolutely:** no engine instructs a client to stop, reduce
or change a prescribed medication. It may flag that prescriber reassessment
is warranted. That is a different thing.

---

## D7 — No practitioner-authored gold benchmark
**SETTLED — this corrected a logic error, not just a workload problem**

An early proposal asked the practitioner to author a frozen gold benchmark
of 50–100 queries with expected answers, plus 100–200 normalization cases.

This was wrong in kind. Engine 7 exists **because the practitioner cannot
personally author, read, classify and remember the full knowledge
universe**, and is supposed to surface strategies they do not already know.
A benchmark whose answers come from practitioner recall makes practitioner
recall the ceiling on measured success.

**Five evaluation layers instead:**

| | Layer | Human input |
|--|-------|-------------|
| A | Automated retrieval tests from seeded domain structure | none |
| B | Source-grounded recovery on **held-out** sources | none |
| C | Cross-domain synthetic case tests | none |
| D | Practitioner spot check | small QC sample |
| E | Discovery value as a **rate** | via D |

**Layer B is the strongest** and is self-grounding: hold out a slice of
ingested sources from synthesis, extract their strategies separately as an
answer key, then query. Testing against fully synthesised material measures
index integrity, not retrieval quality — hence `source_items.held_out`.

**Layer E** must be a rate per spot-check sample, never a raw count: raw
counts rise with library size regardless of quality. Expect it to decline
as the practitioner absorbs what the system surfaces. A near-zero rate
early is the warning sign.

---

## D8 — Automate first; escalate only high-impact ambiguity
**SETTLED — the governing rule for the whole build**

```
AUTOMATE → AUTO-RESOLVE HIGH CONFIDENCE → LOG LOW-IMPACT UNCERTAINTY
         → ESCALATE ONLY HIGH-IMPACT AMBIGUITY
```

Concept governance is the worked example:

| Condition | Action | Human? |
|-----------|--------|--------|
| similarity ≥ `CONCEPT_AUTO_ALIAS_THRESHOLD` | attach as alias | no |
| similarity < `CONCEPT_AUTO_CREATE_THRESHOLD` | create new concept | no |
| between, low impact | log for audit | no |
| between, high impact | escalate, impact-ranked | yes, capped |

Escalation is ranked by **impact, not uncertainty** — an ambiguous concept
touching forty strategies matters; an ambiguous one-off does not.
`CONCEPT_ESCALATION_WEEKLY_CAP` bounds the queue; items beyond the cap stay
queued and re-rank rather than being dropped.

**No milestone may create a recurring manual knowledge-curation job for the
practitioner.** The practitioner's time is the scarce resource; that is the
entire premise of the system.

---

## D9 — Practice experience never becomes evidence
**SETTLED — enforced structurally**

Aggregated case outcomes are genuinely valuable and are **not** published
causal evidence. Keeping the distinction depends on structure, not
discipline:

- `practice_strategy_outcomes` has **no foreign key** to `evidence_records`
  and no view joins them. A test asserts the FK count is zero.
- De-identified aggregates only, minimum cohort of 5 (`ck_min_cohort`).
- Always returned to engines as a separately labelled block.

"Learning" means new structured knowledge is added, evidence records are
updated, strategy cards evolve, practice observations are recorded and
retrieval improves. It does **not** mean an LLM rewriting its own clinical
rules. The master engine specifications remain controlled.

---

## D10 — Discovery source is not evidence source
**SETTLED**

A podcast can introduce an excellent intervention. That does not make the
podcast the evidence. A government guideline may be excellent for
diagnostic definitions and safety context without being the sole source of
intervention innovation. Popularity is never evidence quality.

`knowledge_sources.source_roles` is an array over
`DISCOVERY | EVIDENCE | IMPLEMENTATION | DEFINITIONAL | TRADITIONAL |
FOOD_DATA`. A source may hold several. A test asserts a podcast cannot be
queried as evidence.

Evidence standards differ by knowledge type by design: intervention
efficacy leans on human evidence; practical implementation may legitimately
come from experienced practitioners; food availability from food and
agricultural data; traditional use recorded as use, with modern evidence
recorded separately. **Source role is always labelled.**

---

## D11 — Provenance is a database constraint
**SETTLED**

`ck_provenance_required`: a strategy past `AI_DISCOVERED_CANDIDATE` cannot
exist without a provenance note. Unattributed model output cannot become
permanent authoritative library content.

`AI_DISCOVERED_CANDIDATE` must never silently become `VERIFIED`.

Correspondingly, `RUN_ENGINE` raises `PromptMissing` rather than falling
back to a stub prompt. An engine output that cannot be traced to a
specification is worse than no output.

---

## D12 — Two clocks
**SETTLED**

**Case clock** — event-driven, per client. **Knowledge clock** — continuous,
client-independent. They meet at exactly two points: E7 case retrieval
(knowledge → case), and de-identified practice aggregation (case →
knowledge, delayed and batched).

Collapsing them makes every client trigger expensive research, which is
what "research once, reuse many times" exists to prevent.

An earlier proposal to defer Engine 7 to month four was **withdrawn**: the
knowledge clock does not depend on having clients, so foundation building
starts immediately and in parallel. Do not hard-code a calendar duration.
Progress is coverage, quality and retrieval performance — not elapsed time.

---

## D13 — Wave 1 is operational readiness, not certification
**SETTLED**

`WAVE1_FOUNDATION_READY` means *enough to start using it*. It is computed
from telemetry the system already collects. It is not a claim of complete
medical knowledge, and there is no `COMPLETE` status — health knowledge is
never finished.

Never define readiness by card count alone: 1,000 poor cards are worse than
300 excellent connected ones. Four simultaneous dimensions — coverage,
depth, retrieval quality, provenance. The numeric floors are **engineering
minimums and progress instrumentation**, not definitions of quality, and
information must never be manufactured to satisfy a count. Missing areas
stay marked as gaps.

Core domains carry higher Wave-1 **processing priority only**. This is a
weight on the K00 queue. It never restricts what Engine 7 may discover;
autonomous domain expansion continues throughout.

---

## D14 — Control-flow fields are strict now; everything else is deferred
**SETTLED**

The full handoff blocks are prose-shaped templates, not schemas. Converting
all seven is real work and is **deferred** with output design.

But n8n must route on Engine 4's decision. `CASE_VERSION`,
`ENGINE_RUN_STATUS`, `ROUTING_RECOMMENDATION`, `CURRENT_DECISION`,
`NEXT_ENGINE`, `LOOP_COUNT` and the rest need types and enums from version
one. **n8n never parses prose to decide what runs next.**

Roughly 17 fields strict now; the remaining ~200 wait.

---

## D15 — Optional extensions are genuinely optional
**SETTLED**

Every extension is attempted at migration time and recorded in
`system_capabilities`; later migrations branch via `has_capability()`.
Verified by applying the full schema on a build with **no pg_trgm and no
btree_gin** — trigram indexes skipped, schema still functional.

`gen_random_uuid()` is core Postgres from v13, so **pgcrypto is not a
dependency**.

---

## D16 — Engine 7's client revision is merged, not swapped
**SETTLED**

The client supplied a full replacement Engine 7 master prompt (87 sections,
7,679 words). It is a rewrite, longer than the original, and richer on
philosophy, epistemics and acquisition architecture. It also drops runtime
detail the build already depends on.

`prompts/engine7_research_practice.md` is therefore a merge in four layers:
Addendum A (runtime), Part I §1–§87 (client text, verbatim), Part II
§R1–§R3 and Part III §R4–§R9 (retained original operating detail), and §88
(the control contract).

**Do not "simplify" this back to one document.** The five retained pieces
each carry weight the client's revision does not:

- **§R8/§R9 handoff blocks.** The client's §78–§82 describe handoff
  *content* in prose and contain **no XML tags**. `RUN_ENGINE` parses tags.
  Without these, nothing reaches Engines 1–4.
- **§R2 coverage test.** The source of `coverage_dimension`, which
  `domain_coverage` stores and `v_domain_readiness` computes readiness from.
- **§R1/§R3** foundation build and case retrieval process.
- **§R4/§R5** self-audits.

*Rejected:* shipping the client's file as-is. Every run would have
dead-lettered on the missing tags, and domain readiness would have become
uncomputable.

---

## D17 — 18 coverage dimensions; gap assessment is governance
**SETTLED**

The prompt once claimed 19 dimensions and listed 18. Checked against the
original OCR rather than reconciled by guess: **the source has 18
questions**, and `coverage_dimension` now carries exactly those 18.

`KNOWLEDGE_GAPS` was briefly kept as a nineteenth because it is
operationally useful. That was a misclassification. "Have we identified what
we still don't know?" is a **readiness and governance** question about the
library, not another domain of content. It now lives in
`domain_gap_assessments` and `knowledge_gaps.severity`.

Two names were also semantic shortcuts taken to force an 18-to-18 mapping,
and were corrected while the database still held foundation data:

- `MEASUREMENT` → **`EFFECT_MAGNITUDE`**. "How large might the effects be?"
  is magnitude — absolute change, relative change, responder proportion —
  not how something is measured.
- `NUTRITION_STRATEGIES` → **`ALTERNATIVE_STRATEGIES`**. "What alternatives
  exist?" spans food, exercise, supplement, behaviour, implementation, or a
  different intervention family entirely.

`foundation_ready` = sufficient coverage across the 18 **+** a gap
assessment actually performed **+** no unresolved CRITICAL gap.

**It does not require zero gaps, and zero currently identified critical gaps
never implies COMPLETE.** Open non-critical gaps are the normal state of a
living library. `foundation_status` has no `COMPLETE` value and §70 forbids
one. The earlier prompt sentence "recording zero gaps is a claim that the
domain is finished" was wrong and has been removed.

*Rejected:* keeping `KNOWLEDGE_GAPS` as a content dimension because it was
convenient; and keeping the two shortcut names to avoid a migration.

---

## D18 — `CASE_VERSION = 0` is the knowledge-clock value
**SETTLED**

The control contract requires `CASE_VERSION` on every run, but Engine 7
foundation, update and inbox runs have no case. The contract previously
declared `minimum: 1`, so **every knowledge-clock run would have failed
validation and dead-lettered** — the entire knowledge clock was unrunnable
through `RUN_ENGINE`.

Resolved as `minimum: 0`, with 0 reserved and documented as "not attached
to a client case". Four properties are asserted by test:

- `client_case_versions.case_version >= 1`, so 0 can never denote a stored
  case version
- `ck_run_clock_coherent` on `engine_runs` rejects a row carrying a case
  version or cycle without a client
- `v_engine_run_clock` reports `KNOWLEDGE` vs `CASE`, returning
  `case_version` **NULL** for knowledge runs — never 0, because 0 is a wire
  value and not a stored version
- the prompt instructs 0 on knowledge-clock runs and rejects it on case runs

*Rejected:* echoing `1` on knowledge runs. It asserts a case version that
does not exist and makes the run indistinguishable from a case run.

---

## D19 — Source kinds are a registry, not an enum
**SETTLED**

Engine 7 §47, §48 and §85 require that **a new source tomorrow is a data
operation, not a software-development event**, and forbid depending on the
coder having known a source type existed at build time.

`source_kinds` is therefore a reference table with 22 seeded rows. Adding
`SUBSTACK_POST` is an `INSERT`. `OTHER` is protected by trigger from
deletion and deactivation, because §48 makes it the landing state for
previously unseen kinds.

Enums are still used where the value set is genuinely stable and
safety-bearing: `rights_context`, `delta_classification`,
`envelope_status`, `drug_claim_support`.

*Rejected:* a `source_kind` enum. Correct-looking, and it would have made
every new source type a migration — precisely the outcome the
specification names as the failure.

---

## D20 — `006` is schema only
**SETTLED**

`006_knowledge_inbox.sql` adds the structural foundation for the Knowledge
Inbox, source envelope, rights context, delta analysis, reprocessing,
source→derived provenance and medication-context knowledge.

It deliberately builds **no UI, no ingestion pipeline and no acquisition
adapters**, and does not touch K1–K11. Same rationale as `005`: cheap now,
expensive as a retrofit once E7 ingestion is wired.

Two rules are enforced structurally rather than requested:
`ck_raw_before_derived` blocks an envelope reaching an extracted state
without its raw source preserved (§50), and `v_client_safe_sources` is the
single path that filters purchased and private material out of anything
client-facing (§52) — nothing else may assume that filtering.

---

## D21 — Provenance integrity without typed foreign keys
**SETTLED**

`envelope_derived_records` originally held `derived_id` as a bare UUID with
no target, to avoid one foreign key per derived kind. That preserved
extensibility and broke the guarantee the table exists for: an edge could
name a claim that did not exist, and Postgres accepted it.

Resolved with `knowledge_entities` — a registry every derived object joins
automatically by trigger, across all nine kinds today. The provenance edge
carries a **composite** foreign key on `(derived_id, derived_kind)`, so an
edge can neither point at a nonexistent object nor mislabel a real one's
kind. Deleting the object deregisters the entity and cascades the edge away.

Extensibility survives intact: **a new derived kind adds an enum value and a
registration trigger, not a foreign key here.** That is the same principle
as `source_kinds` in D19 — the integrity mechanism is generic, so growth
stays a data operation.

*Rejected:* nine typed foreign keys, which would have made every new
derived kind a schema change to the provenance table.

---

## D22 — Core Intake V1 is defined by what it does NOT ask
**SETTLED**

The exclusions were written before any field, and the fields were derived
from them. That order matters: a questionnaire designed by adding fields
until it feels complete becomes an interrogation, and every field added
"while we are asking anyway" is permanent client burden paid on every
single client, forever, in exchange for a marginal signal one engine might
use once.

The governing sentence: **do not ask clients for information merely because
an engine knows how to analyse it.**

### What Core Intake V1 deliberately does not ask, and why

**1. Anything the Real Health Test owns.** Sleep quality, pattern and
regularity; stress; recovery; fatigue and body signals; work and lifestyle
load; detailed sedentary/activity distribution; proprietary health and
body-load signals.

*Rejected:* "ask a few sleep questions anyway, they are cheap." They are not
cheap. RHT is a separate paid assessment; duplicating its questions dilutes
what the client is paying for, trains them to answer the same thing twice,
and — the real damage — creates two sources of truth for one signal with no
rule saying which wins when they disagree. Core Intake collects only the
minimal basics case reasoning cannot proceed without, and records
`RHT_STATUS` so the gap is visible rather than guessed.

**2. Calorie and macronutrient self-quantification.** The 3-day food log is
descriptive: what was eaten, roughly how much, when.

*Rejected:* asking clients to estimate grams or calories. Self-reported
quantification is unreliable in a way that looks precise, which is worse
than an honest description, and Engine 3 derives what it needs from the
description plus food composition data.

**3. Exhaustive disease-screening checklists.** Symptoms are collected where
relevant to nutritional, metabolic and functional reasoning.

*Rejected:* a 100-symptom checklist on the grounds that Engine 1 can reason
about many symptoms. High burden, low signal, and a long checklist actively
manufactures false positives: a client ticking 40 boxes has told you less
than one describing three things that actually bother them.

**4. Deep behavioural and psychometric profiling.** Previous attempts and
obvious adherence barriers only — lightweight.

*Rejected:* a behavioural battery at intake. Engine 2 does this reasoning
properly, and it does it far better against real response data from the
first four-week cycle than against a client's pre-programme self-assessment.

**5. Client-authored diagnostic hypotheses.** Clients are asked what they
want and what they experience, never what they think is causing it.

*Rejected:* "what do you think your root cause is?" It anchors the engines
on a lay hypothesis, and D1 already places conversion and framing outside
the reasoning path for the same reason.

**6. Family history beyond what changes reasoning.** First-degree relatives
and conditions in the metabolic, cardiovascular, endocrine and autoimmune
families.

*Rejected:* a full genealogy. Third-degree relatives do not change a
four-week intervention.

**7. Financial and household detail beyond a coarse constraint.** Budget is
a band; cooking access, who cooks, and equipment are captured because
Engine 3 cannot design an executable plan without them.

*Rejected:* itemised household income and spending. Engine 3 needs to know
whether a suggestion is affordable and cookable, not what the client earns.

**8. Fields no engine currently consumes.** If nothing reads it, it is not
collected.

*Rejected:* "collect it now in case we need it later." That is PHI acquired
without purpose, and it inverts the premise of the whole system: the
practitioner's and client's time is the scarce resource. When an engine
repeatedly reports a gap, `v_missing_data_recurrence` surfaces it and the
field is added **deliberately**, with a classification — never
automatically, per §57 and the policy in D8.

**9. Connected-device and wearable streams.** `event_source` already carries
`CONNECTED_SOURCE` so this can arrive later without a retrofit; V1 ingests
none of it.

**10. Exhaustive manual lab transcription.** Key values are entered
structurally; the report itself is referenced with its provenance.

*Rejected:* requiring every value on a panel to be typed by hand. It is the
single most reliable way to make a client abandon intake halfway, and it
introduces transcription error into the data the engines trust most.

### What follows from the exclusions

- **Absence is never normality.** A field not asked, or asked and not
  answered, is `UNKNOWN` / `NOT_ASSESSED`. It is never defaulted to a
  normal value, and `RHT_STATUS = NOT_ASSESSED` never means "RHT was fine".
  Asserted by test.
- **Intake never blocks a case.** Validation records gaps; it does not
  refuse. An incomplete intake still initializes a runnable Engine 6
  canonical state v1 and populates the high-priority missing-data set, which
  Engine 5 turns into follow-up questions. Asserted by test.
- **Conditional sections are data, not code.** `intake_field_catalog` holds
  the field registry with its classification and its condition, so adding or
  reclassifying a field in V2 is an `INSERT` or an `UPDATE` — the same
  principle as `source_kinds` in D19.
- **V1 is deliberately not final.** Real engine runs teach us what V2 needs.
- **Completeness and usability are different questions, and only the second
  one is new.** V1 shipped proving which applicable fields had no answer,
  and nothing checking whether a supplied answer could be used. That let
  `height_cm: "about 170"` kill extraction on a numeric column hundreds of
  lines from where intake accepted it, and — worse — let
  `rht_status: "probably fine"` reach Engine 6 as `RHT_STATUS
  "PROBABLY FINE"`, in the one field this decision makes load-bearing.
  Migration `011` adds `intake_submissions.validation_issues`, and the
  rule is three outcomes and never a fourth: **missing** is a gap as
  before; **valid** is accepted; **supplied but unreadable** becomes an
  issue and is treated as unknown or dropped. Never guessed at, never
  corrected, never accepted as given, and never a reason to refuse the
  submission.

  *Rejected:* validating every field. Only the shapes that bear safety or
  data integrity are checked — what step 15 writes into typed columns, and
  what an engine would read as clinical fact. A validate-everything layer
  would freeze the field registry that this decision deliberately keeps as
  data.

  *Rejected:* repairing values. "14/08/2026" is a different day in Mumbai
  and in New York and intake cannot know which was meant; a lab result
  dated today because its own date was unreadable is a false fact that
  outlives everyone who remembers why. Removing is allowed, defaulting is
  not.

  *Rejected:* letting an unrecognised RHT status through as itself, or
  silently rewriting it to `NOT_ASSESSED`. It becomes `NOT_ASSESSED` **with
  a `DISCREPANCY` note naming what was declared** — the same treatment
  `COMPLETED`-with-nothing-linked already gets. An unrecognised status is
  not evidence of anything, and hiding that someone answered the question
  badly is its own kind of dishonesty.

*Rejected outright:* building intake to cover everything Engine 1 §15–§37
can reason about. Engine 1 reasons about far more than any client should be
asked to type, and the gap between the two is exactly what Engine 7's
library and the practitioner's consultation are for.

---

## D23 — At runtime the prompts are served from PostgreSQL, not from a filesystem
**SETTLED — forced by step 11**

`CLAUDE.md` says the finished system must keep working on **n8n +
PostgreSQL + an LLM API alone**. Porting `RUN_ENGINE` to n8n is the first
thing that tests that sentence, and it fails immediately:
`scripts/run_engine.py` loads `prompts/engine1_prevention.md` off the
repository working tree, and n8n runs in a container that has never seen
this repository.

So the question is not "how does n8n read a file" but "what is the prompt
at runtime". Answer: a row.

`engine_prompts` is an append-only registry keyed by
`(prompt_file, prompt_hash)`, with exactly one `active` version per engine.
`scripts/load_prompts.py` is its only writer and reads `prompts/*.md`.
The files stay the authored form — reviewed, diffed and version-controlled
like everything else — and the database is the **runtime** form, exactly
the relationship `database/migrations/` already has with
`schema_migrations`.

What this buys, beyond making the port possible:

- **The hash is computed once, from one body of text.** Both Engine 1
  passes read the same row, so D4's identical-hash rule is satisfied by
  construction rather than by two implementations agreeing. A Python
  reference run and an n8n run of the same engine cannot record different
  hashes, because there is nothing for them to disagree about.
- **`PromptMissing` survives.** An engine with no active row raises, and
  no stub is substituted. Hard rule 7 is unchanged: an output that cannot
  be traced to a specification is worse than no output.
- **A prompt change is auditable after the fact.** `engine_runs` records
  a hash; until now that hash resolved to whatever the working tree
  happened to contain at the time. Now it resolves to a stored row with
  its own `loaded_at`, so a run from three months ago can be traced to the
  exact text that produced it.

*Rejected:* mounting `prompts/` into the n8n container read-only. It
works, and it makes n8n's behaviour depend on a bind mount that
`docs/OPERATIONS.md` would have to document, back up and restore
separately from the database. It also leaves two runtime sources of the
same text — the Python reference reading the tree, n8n reading the mount —
which is exactly the drift step 11 exists to prevent.

*Rejected:* embedding the prompt text in the n8n workflow JSON. A 5,000-word
specification pasted into a Code node is not reviewable, and editing a
prompt would mean editing a workflow.

*Rejected:* having `load_prompts.py` write the registry **and**
`run_engine.py` keep reading files, with a test asserting the two agree.
Two sources of truth plus a test is still two sources of truth; the test
tells you they diverged after they already have.

*Rejected:* making the registry mutable in place (`UPDATE` the content of
a row). `engine_runs` foreign-keys nothing to the prompt today, but the
hash is the provenance link, and rewriting a row's content under a
recorded hash is the same class of mistake migration 010 exists to
prevent. Superseding is an `INSERT` plus deactivating the old row, which
keeps the old text readable.

---

## D24 — The control block routes; the handoff is the reasoning. Never interchangeable
**SETTLED — found in review, before the n8n port**

Every prompt defines **two** machine-readable outputs, not one:

| | |
|---|---|
| `<..._HANDOFF>` | The substantive reasoning — strategies, evidence, effect magnitude, applicability, targets, implementation. What the next engine thinks with. |
| `<CONTROL_BLOCK>` | ~17 typed fields. What n8n routes and gates on (D14). |

`RUN_ENGINE` parsed only the second. `EngineResult.structured` was `None`
on every return path; `engine_outputs.structured` was written from
`req.structured_input.get("_echo", {})` — the **input's** `_echo` key,
which nothing has ever set, so it stored `{}` on every run since the engine
layer was built. `CLIENT_NEW` then passed control blocks downstream as
`E7_HANDOFF` and `E1_HANDOFF`, and built both case versions out of the
input it had handed Engine 6 rather than Engine 6's answer.

The pipeline executed correctly end to end and almost none of the reasoning
moved. Engine 1 Pass B — which exists solely to see Engine 7's retrieval
(D4) — was receiving eight routing booleans where the strategies and
evidence should have been.

**A valid control block is not evidence that an engine did its work.** That
is now structural: a response missing a required handoff joins the same
`errors` list as a contract violation, so it travels the repair retry and
dead-letters. It does not add a third failure path.

**The expected tags are a registry**, the third instance of the pattern
`010` gave the prompts and `012` gave the contract. `engine_handoffs` is
keyed `(engine, mode, tag)` with a `required` flag, modes are rows rather
than an enum (D19), and the loader **verifies every tag against the
registered prompt** before loading — a renamed tag fails the load instead
of registering a block no engine will ever emit. n8n reads the same rows.

**Modes exist because two engines emit different blocks.** E6 §A1: the full
`<CASE_MEMORY_HANDOFF>` establishes or rebuilds state, the
`<CASE_MEMORY_DELTA>` records an incremental change and is the normal path
on follow-up. E7 emits a CASE or a FOUNDATION handoff. **E6 and E7 have no
default mode** — guessing means expecting a delta where a state was needed,
or the reverse, and both write a case record that is quietly wrong.

**A delta is not a state.** `004` created two columns for this:
`canonical_state` is "Full canonical state (CASE_MEMORY_HANDOFF)", `delta`
is "Only what changed". `get_current_client_state()` returns the former, so
storing a delta there would hand every engine a description of a change as
though it were the case. `_new_case_version` refuses to write a version
without a full state.

**CLIENT_NEW's second Engine 6 call runs in `REBUILD`, not `UPDATE`.** This
is a deviation worth stating plainly. Version 2 needs a complete state
because `canonical_state` is `NOT NULL` and every engine reads it, and a
delta cannot be mechanically merged into a state — its fields
(`NEW_FACTS`, `UPDATED_FACTS`, `RESOLVED_ITEMS`) describe changes and do
not map onto the state's fields, so merging would mean inventing Engine 6's
semantics. §A1's own word for this is *rebuilding*: the case is still being
established, across one cycle. The delta is **optional** in `REBUILD` mode
and is kept in the `delta` column rather than discarded. `CLIENT_FOLLOWUP`
is where `UPDATE` and the delta path belong.

**Typed values come from typed places.** A handoff block is line-oriented
`KEY: text`, so every value in it is a **string** — Engine 6 writes
`CASE_VERSION: 1` and it parses as `"1"`, which the control contract
correctly rejects as not an integer. The fix is not per-field coercion: it
is that `client_case_versions.case_version` is an integer column assigned
by the insert, and D18 rests on stored versions starting at 1. Engine 6's
line is its claim; the row is the fact.

**The parser discards nothing.** A key is an ALL-CAPS identifier followed
by a colon **at column zero** — narrow on purpose, because `Note: take with
food`, an indented `IMPORTANT:` and a prefixed `- STRATEGY_A:` are all
values, not keys. `_raw` keeps the block verbatim so a mis-split value is
recoverable, text before the first key is kept as `_preamble`, a repeated
key keeps both values, and unknown keys are kept as they come: the registry
says which BLOCK is expected, never which fields are permitted inside it.

*Rejected:* treating the control block as the handoff when a handoff is
absent. It is the bug, written down as a policy.

*Rejected:* a dict in `run_engine.py` mapping engine to tag. This is the
third time the same question has come up — which specification, which
schema, which handoff — and a third bespoke mechanism would be the point at
which the pattern stopped being a pattern.

*Rejected:* asking Engine 6 for a full state on every update. §A1 says
plainly not to restate unchanged state as though it were new, and
`CLIENT_FOLLOWUP` will run many updates per case.

*Rejected:* requiring handoffs to be JSON. The prompts specify a
line-oriented format, they are authoritative (hard rule 1), and changing
seven master specifications to suit a parser is the wrong direction. The
parser was made lossless instead.

### D24a — the requested mode is transmitted, not merely resolved

`RUN_ENGINE` resolved `handoff_mode` and then never told the model. The
mode went into provider `params`, the fixture read it, and
`openai_compatible_provider` ignores `params` entirely — so `INIT` versus
`REBUILD`, the difference between Engine 6 emitting a full state and
emitting a delta, reached the wire as **nothing at all**.

E1 looked fine only because `client_new.py` hand-wrote `"MODE": "PASS_A"`
into its structured input. That is the accident, not the fix: a key a
caller must remember is a key a caller will forget, and E6 and E7 duly
did.

`RUN_ENGINE` now injects a `<RUNTIME_INVOCATION>` envelope ahead of the
payload — engine, mode, pass, the expected and required handoff blocks —
**once, generically, for every engine**. The hand-written `MODE` keys are
gone from `client_new.py`, `measure_engine1.py` and the suites, and a test
asserts no script outside `run_engine.py` writes one. The repair retry
rebuilds the same envelope, so attempt two is not a differently-shaped
request.

The envelope is runtime metadata, not engine specification: it says which
mode was requested, and the **prompt** says what that mode means. n8n
builds the identical string from the identical registry rows.

*Rejected:* a fixture-level test. The fixture reads the param the live
path throws away, which is exactly why this survived. The test intercepts
`urlopen` and asserts against the bytes
`openai_compatible_provider` would have sent.

### D24b — §R8/§R9 corrected, §R10 added

`RESEARCH_PRACTICE_FOUNDATION_HANDOFF`'s opening tag appeared only inside
its §R8 heading, and `RESEARCH_PRACTICE_CASE_HANDOFF`'s only in the §R3
example. A model following either field template literally would emit a
block the runtime cannot find.

**D16 draws the line and it falls on our side.** Part I §1–§87 is the
client's text, verbatim and untouchable; Parts II/III §R1–§R9 are
build-owned. So both were fixed to carry a standalone opening tag rather
than teaching the verifier to accept a formatting accident. The verifier
now requires a standalone **opening** line and keeps the closing-tag check
as a second assertion.

`ENGINE7_MODE` is `FOUNDATION | UPDATE | CASE | INBOX` (§3262) and only two
were registered. **UPDATE** shares the foundation contract — an update is a
smaller foundation pass, not a different output. **INBOX had no substantive
output contract at all**: §55 defines what Engine 7 must report from a
manually added source and describes it in prose, so an INBOX run could only
ever have produced a control block. Reusing that as the handoff would be
D24 again, so §R10 adds
`<RESEARCH_PRACTICE_INBOX_HANDOFF>` carrying §55's information-gain fields
verbatim plus §56's versioning, and states that a candidate strategy stays
a candidate.

Adding §R10 moved the composition header, the R-range assertions and the
prompt hash together — those assertions exist because a merge accident
once mis-stated the ranges, so they were updated, never relaxed.
`MANIFEST.json`'s E7 entry was already stale before this change; only
`sha256`, `chars` and `words` were refreshed. `sections_expected` is a
hand-declared invariant with a different counting rule and was left alone
rather than overwritten with a recount that would have changed all seven
entries.

---

## D25 — Engine runs set transaction-local client scope, and always have to
**SETTLED — found preparing the n8n port; a real blocker, not a tidy-up**

`set_client_scope()` appears nowhere in `scripts/`. Connecting as
`phi_runtime` and calling `run_engine()` fails on its **first statement**,
both ways:

```
client run       InsufficientPrivilege: new row violates row-level
knowledge clock  security policy for table "engine_runs"
```

Two independent causes, and the Python reference has never hit either
because `DATABASE_URL` connects as `phi_admin`, which is **SUPERUSER** and
so bypasses RLS entirely. **Every engine run this system has ever made went
around the policies rather than through them.** n8n connects as
`phi_runtime` (hard rule 8) and would have been the first thing to discover
that — in production, on a pooled connection.

**Cause 1: nothing set the scope.** Fixed in `run_engine.py`. Every write
now runs inside an explicit transaction that calls `set_client_scope()`
first, via one `client_scope()` context manager, and the n8n workflow
mirrors it: each Postgres node runs `SELECT set_client_scope($1)` and its
statement in one transaction.

The transaction wraps the **write**, never the model call. Scope is
transaction-local by design so a pooled connection cannot carry Client A's
context into a later Client B query — but holding one transaction across a
300-second provider call would leave a connection idle-in-transaction for
five minutes.

**Cause 2: a knowledge-clock run has no client.** Engine 7 in FOUNDATION,
UPDATE or INBOX mode carries `client_id` NULL and `CASE_VERSION` 0 (D18),
and the policy was `client_id = current_client_scope()`. `NULL = anything`
is never true, so those runs were unwritable as `phi_runtime` whatever
scope was set. Migration `014` widens the runtime policy on `engine_runs`
and `engine_outputs` to `client_id IS NULL OR client_id =
current_client_scope()` — **the same judgement and the same policy shape
005 already applied** to `chat_threads` and `chat_messages`: "carries no
client data, so it stays readable without a client context."

This does not widen access to client rows. A run **with** a client is still
visible only under that client's scope.

*The cost of tolerating NULL*, stated rather than glossed: a CASE run that
lost its client would now file quietly as a knowledge-clock run instead of
being rejected. `v_runs_without_client` is the check — only Engine 7 has
clock modes, so any other engine without a client lost it somewhere — and
the suite asserts it is empty.

**The test that matters is the pooled one.** Two clients run back to back
on **one** `phi_runtime` connection, and neither can see the other's rows
under its own scope, with no `client_id` filter in the query. That test is
close to meaningless in Python — one short-lived connection — and
essential in n8n, whose Postgres node pools.

*Rejected:* running n8n as `phi_admin` so the policies do not apply. It is
hard rule 8, and it would make the isolation guarantee decorative.

*Rejected:* giving knowledge-clock runs a synthetic client id. Inventing a
client so a policy passes is how a system loses the meaning of the word.

*Rejected:* one long transaction around the whole run. Correct for scope
and wrong for everything else: a five-minute idle-in-transaction
connection per engine call, on a 2 vCPU box.

---

## D26 — n8n parity is byte-identical, and the wording of a violation is ours
**SETTLED**

The n8n port mirrors `scripts/run_engine.py`. "Behaviourally equivalent" is
not the bar: **the prompt hash plus the request IS the call**, and two
serializers that mean the same thing produce different model behaviour with
nothing downstream to notice.

**One stored corpus, two implementations, identical output** — the third
use of the pattern the contract registry established, and the third time it
found something.

### The two ways Python and JavaScript actually disagreed

Measured over a corpus covering ASCII, non-ASCII, nesting, empty
containers, big integers and every JSON escape. Everything agreed except:

| | |
|---|---|
| non-ASCII | Python escaped to `\uXXXX` by default; JavaScript did not |
| integral floats | Python wrote `78.0`; JavaScript wrote `78` |

`canonical_json()` fixes both. `ensure_ascii=False` is an improvement on
its own merits — escaping "idli, sambar" or a rupee sign costs tokens and
hides the text from the model. Integral floats become ints because JSON has
one number type and JavaScript cannot tell `78.0` from `78` once parsed; a
weight of 78.0 kg and a weight of 78 kg are the same measurement, and
byte-identical requests are worth more than a trailing zero.

### The wording of a contract violation is defined here, not inherited

```
jsonschema  "'CASE_VERSION' is a required property"
ajv         "must have required property 'CASE_VERSION'"
```

That string is **not cosmetic**. It is persisted to
`engine_runs.error_detail`, and `repair_instruction()` sends it to the
model on attempt two. Two implementations disagreeing means n8n asks the
model to fix something in different words than the reference does, on the
one retry that matters.

So `format_violation(field, keyword, detail)` defines the wording, both
sides build it from their own library's **structured** error data, and the
parity suite proves they agree. Applicator keywords (`if`, `then`,
`allOf`, …) are skipped on both sides: they are containers, they name no
field, and their child errors carry the real blame.

### The JavaScript under test is extracted from the workflow

`testing/n8n_parse_response.js` reads the Code-node source out of
`workflows/run_engine.json` at run time. A copy would drift from the
workflow it claims to test, and parity would then be proving that two test
helpers agree.

### What the corpus covers

Valid execution; an invalid control block three ways; a missing substantive
handoff; a handoff block present but empty; **the wrong block for the
mode** (an `UPDATE` that returned only a state); a fenced control block; a
handoff whose value lines look like keys; an empty response; E6 INIT /
REBUILD / UPDATE; E7 CASE / FOUNDATION / UPDATE / INBOX; E1 Pass A and Pass
B; token and cost accounting.

*Rejected:* comparing verdicts and blamed fields only, as
`test_contract_registry.py` does for the schema. That is right for "is this
control block valid"; it is not enough once the message text reaches a
model and a database column.

*Rejected:* executing the whole workflow through a live provider to prove
parity. Deterministic comparison covers it, and paid calls prove nothing
extra.

---

## D27 — The mode is stored on the run, and coherence is checked before the insert
**SETTLED**

`v_runs_without_client` (migration 014) read
`client_id IS NULL AND engine <> 'E7'`. That is two rules where there are
four, and the exemption it grants is far too wide: it permits **every**
Engine 7 run without a client, including **E7 CASE**, which is client work
and cannot be a case with no case.

| | |
|---|---|
| E1–E6 | client **required** |
| E7 `CASE` | client **required** |
| E7 `FOUNDATION` / `UPDATE` / `INBOX` | client **must be NULL** |

### The real defect was that the mode was not on the run

The rule could not be checked correctly by any view, because the only place
a mode was recorded was `engine_outputs.handoff_mode` — a row that exists
only after a run **succeeds**. So the mode of a dead-lettered run, or an
in-flight one, was unknowable, and the mode of any run was inferable only
from the engine name plus a guess. A guard that can only evaluate
successful runs is not a guard.

`engine_runs.engine_mode` is written by `RUN_ENGINE` at the moment the run
opens, from the mode it already resolved for the `<RUNTIME_INVOCATION>`
envelope (D24a). One typed column, no inference anywhere.

### A trigger, not a CHECK constraint

The VPS is running `main` and has `engine_runs` rows from before this. A
CHECK would have to either reject that history or carry a permanent escape
hatch that new rows could use too. `trg_engine_run_coherent` is BEFORE
INSERT: history is grandfathered by construction and nothing new can skip
it. Pre-015 rows are not hidden — `v_engine_run_incoherent` lists them as
"mode not recorded".

*Note for anyone writing a test:* a BEFORE INSERT trigger fires **before**
CHECK constraints. `test_knowledge_inbox.py` had to start supplying a valid
`engine_mode` for `ck_run_clock_coherent` to remain the thing its assertion
was actually testing.

*Rejected:* deriving the mode from the engine name. E7 has four modes and
two of them route in opposite directions on the client question. There is
nothing to derive it from.

*Rejected:* keeping the view and fixing only its WHERE clause. A view
detects; it does not prevent. The brief asked for enforcement before the
insert, and after the insert is after the payload already exists.

---

## D28 — A failed engine response is client data, not telemetry
**SETTLED**

`dead_letter_jobs` has existed since `001_ops.sql` with **no `client_id`
and no row level security**, while `RUN_ENGINE` writes up to 8,000
characters of raw failed model output into `raw_payload`. For a case run
that raw output is the client's labs, conditions, medications and
symptoms — the clinical record in a different shape. Every one of those
rows was readable by `phi_runtime` under **any** client scope.

Hard rule 8 says client isolation is structural. It does not have an
exception for the failure path, and calling the payload "telemetry" would
be a relabelling, not a fix — the bytes are the same bytes.

**The payload is kept.** Debugging a dead letter without the response that
caused it is guesswork, and the point of the queue is that a malformed
output can be inspected rather than lost. It is kept **and scoped**:
`client_id` is nullable, RLS is `ENABLE` + `FORCE`, and the runtime policy
is `client_id IS NULL OR client_id = current_client_scope()`.

Nullable because dead letters that genuinely carry no client data are
real — knowledge-clock runs and source ingestion — and those stay readable
without a scope, exactly as 005 decided for `chat_threads` and 014 for
knowledge-clock runs. It is the same rule in both places: no client, no
scope needed; a client, scope enforced.

`v_dead_letter_triage` answers the first question anyone actually asks —
how many, since when, still happening — **without a `raw_payload`
column**. Reading someone's failed clinical text should take a deliberate
scoped query, not be the by-product of checking whether the queue is
backing up.

Forward migration, never a redefinition of `001` (hard rule 10): the
column is added, existing rows are backfilled from the run they belong to,
and rows whose client cannot be recovered stay NULL rather than being
guessed at.

*Rejected:* dropping `raw_payload`, or truncating it to a hash. That
trades a fixable isolation problem for a permanent debugging one.

*Rejected:* a separate `dead_letter_jobs_client` table. Two queues means
two things to check and one of them will be forgotten; the scoping key
belongs on the row.

---

## D29 — n8n retries the way the reference retries
**SETTLED**

The HTTP Request node was configured with **six retries at a fixed
2,000 ms**, under a note describing exponential backoff. `run_engine.py`
does exponential backoff, jittered, capped at 60 s, with `Retry-After`
honoured when the provider sends one, and retries **only** the statuses
that can succeed on a repeat.

The gap matters most exactly where it is least visible: Step 16's
Knowledge Factory, at `KNOWLEDGE_MAX_CONCURRENCY` 2–3, on a 2 vCPU box.
Fixed-interval retries from concurrent workers all come back at the same
instant and re-overload a provider that is already shedding load. Jitter is
the whole reason the reference has it.

n8n's own retry cannot express any of this, so **the call moved into the
Code node** and the semantics are the reference's:

| | |
|---|---|
| retryable | 408, 409, 425, 429, 500, 502, 503, 504, and network-level failures |
| permanent | everything else, 400 and 401 included — an unrecognised error is not retried |
| delay | `min(60, base ** attempt)`, then multiplied by `0.5 + random()` |
| `Retry-After` | delta-seconds honoured, capped at 60; unparseable falls back to backoff, never to zero |
| accounting | one `cost_events` row per **physical** attempt, failures included |

Tested deterministically against a local stub — 18 assertions, no paid
calls — including that a transport failure never consumes one of the two
**repair** attempts. Those are different budgets: a repair is a second
request with a violation message attached, and spending it on a 503 means
a malformed response gets one chance instead of two.

*Rejected:* documenting the fixed-interval node as an intentional
divergence. D26's bar is parity, the divergence had no upside, and its
first symptom would have been a Knowledge Factory batch failing under load
in a way nothing distinguishes from a provider outage.

---

## D30 — The rate card is rows too. The fourth registry
**SETTLED**

Prompts (`010`), the orchestration contract (`012`) and the handoff
registry (`013`) all moved from files to rows for one reason: **n8n cannot
read this repository.** `config/model_prices.json` was the last thing
`RUN_ENGINE` read from disk, and the consequence surfaced the moment the
n8n cost node was written — it had nowhere to get a rate.

The choice was to write `UNPRICED` for every n8n call, or to make the rate
card readable the same way everything else is. UNPRICED is not a small
divergence: **n8n is production and the Python path is the reference**, D5
was decided on cost numbers, and Step 16 will push thousands of Knowledge
Factory calls through the workflow. A production path that cannot price its
own calls makes the cost table describe the reference implementation
instead of the system.

So `model_prices` is a table, `scripts/load_prices.py` is the fourth
loader, and the SQL function `price_call()` reproduces
`pricing.price_call()`: env override, exact model name, longest matching
prefix, else UNPRICED with a **NULL** cost — never zero, which would read
as "this call was free". A fresh deployment now runs **four** loaders after
migrating.

Two implementations of one rule, compared over a corpus. That arrangement
has now found something four times out of four.

A model removed from the file is **deactivated, never deleted**: its rate
is the evidence for every `cost_events` row already priced with it.

---

## D31 — The workflow's SQL is executed by a test, because reading it is not enough
**SETTLED**

`test_n8n_parity.py` proved the two implementations build the same request
and read the same response. Nothing ever executed the third thing the
workflow does, which is **write** — and three defects were sitting in it
at once, all introduced in the same sitting as the migrations that made
them wrong:

* `Open run` did not send `engine_mode`, so **every** n8n run would have
  been rejected by the coherence trigger D27 had just added.
* `Dead letter` did not send `client_id`, so every n8n dead letter would
  have been exactly the unscoped cross-client payload D28 had just fixed.
* `Record attempts` inserted into `latency_ms`, a column that has never
  existed, and cast `error_class` to `failure_type` — an enum belonging to
  the case layer's intervention-failure vocabulary, which has nothing to do
  with engine errors and does not contain `SCHEMA_INVALID`.

### Two of them were not SQL mistakes at all

They were mistakes about how n8n turns a `queryReplacement` expression
into a parameter list. At Postgres node v2.5 that algorithm is surprising
in three separate ways, none of them documented:

1. **Literal text outside `{{ }}` is discarded.** `RUN_ENGINE_{{ engine }}`
   binds `E1`, not `RUN_ENGINE_E1` — so `job_type` and `workflow` were
   silently losing their prefix.
2. **`null` becomes the string `'null'`.** Against a `uuid` column that is
   an error; against `text` it is worse, because it succeeds.
3. **A resolved string that is not JSON is split on commas** into several
   parameters. One comma in an error message shifts every parameter after
   it.

**SUPERSEDED BY D32 ON THE FIX, NOT ON THE FINDING.** The three
behaviours above are real and still hold. The fix recorded here was the
**array form** — a single `{{ [a, b, c] }}`, which on 2.35.7 takes a
branch that has none of them. That branch **does not exist on 2.11.4**,
the version this system runs, where an array is stringified and bound as
one value. See D32 for the form actually in use: one resolvable per
parameter, each a JSON literal, unwrapped with `($n::jsonb #>> '{}')`.

Recorded rather than rewritten, because the lesson is the point: this fix
was verified thoroughly against the wrong version.

`testing/n8n_bind_params.js` is a faithful port of that algorithm, and
`test_n8n_sql.py` binds the workflow's **real** expressions through it and
executes the resulting SQL against the real database as **`phi_runtime`**.
It also compares the INSERT column lists of both implementations, which is
what makes a missing `engine_mode` a failure rather than a silent
difference.

Ported rather than imported: n8n is not a dependency of this repository and
must not become one for a test to run. Same reasoning as `scripts/trigram.py`.

*Rejected:* asserting on the SQL text. Two of the three defects were
invisible in the text and one of them was in the JSON around it.

---

## D32 — n8n is pinned to 2.11.4, the version the VPS runs. The VPS is not upgraded
**SETTLED 2026-09-10**

The VPS's n8n stack runs **three live business automations** (GFG T1 v2,
AiSensy, a detection PoC) that have nothing to do with this build. An
upgrade window is not free, and there was nothing to buy by taking one: the
binding quirks this workflow depends on knowing were read out of the
installed node's own source, not inherited from a newer release.

**The pin follows the VPS. It is never raised to keep current.** A future
session that "helpfully" bumps `N8N_VERSION` is reintroducing the problem
this decision closes.

### Re-pinning was not a one-line change, and that is the point

`n8n-nodes-base` **2.11.2** is what n8n 2.11.4 ships. Diffing its
`executeQuery.operation.js` against 2.35.7's turned up one difference, and
it was load-bearing:

```
2.35.7   an expression evaluating to an ARRAY pushes one value per
         element, preserving null and passing strings through whole
2.11.2   there is no such branch. An array is JSON.stringify'd like any
         other object and pushed as ONE value
```

Every `queryReplacement` in `workflows/run_engine.json` had been written as
a single `{{ [a, b, c] }}` to use that branch — the fix from D31, made
against the wrong version. On 2.11.4 that binds **one** parameter where the
statement wants twelve, and **every Postgres node in the workflow fails on
the first run**. Verified by driving the real 2.11.2 module: Open run
bound 1 of 12, Record attempts 1 of 9, Record success 1 of 12, Dead letter
1 of 10.

### The form that is exact on both

One resolvable per parameter, each evaluating to a **JSON literal**:

```
={{ JSON.stringify(a ?? null) }},{{ JSON.stringify(b ?? null) }}
```

`isJSON()` is then true for every one, so each is pushed whole on either
version — no branch that only one of them has. SQL unwraps with
`($n::jsonb #>> '{}')`, which turns JSON `null` into a real SQL NULL and
returns a comma-bearing string intact. `?? null` before `JSON.stringify` is
not decoration: `JSON.stringify(undefined)` returns `undefined`, not a
string, and `stringToArray('')` drops it — shifting every later parameter.

Verified against **both** real implementations over the workflow's own
expressions: identical values, identical count, and the count matches the
highest `$n` each statement uses. `test_n8n_sql.py` asserts that arity
match for every node on every run, and that no node uses the array form.

### What was checked before accepting the pin

| Node | Workflow uses | 2.11.2 supports |
|---|---|---|
| `postgres` | 2.5 | 2 … **2.5** … 2.6 |
| `code` | 2 | 1, **2** |
| `if` | 2.2 | 2, 2.1, **2.2**, 2.3 |
| `executeWorkflowTrigger` | 1.1 | 1, **1.1** |

*Rejected:* upgrading the VPS. It buys a workflow proven against the
version it runs on — which re-pinning also buys, at no risk to three live
automations.

*Rejected:* keeping the 2.35.7 pin and "testing on 2.11.4 later". Later is
after the first import fails.

---

## D33 — The Code node has no `fetch`, and a test that runs the code in plain Node cannot know that
**SETTLED 2026-09-10**

`workflows/run_engine.json`'s Call provider node was written with
`await fetch(url, …)`. **It could never have run.** n8n's Code node
executes inside `vm2`, and that sandbox does not provide `fetch` or `URL`.
Verified empirically against the installed vm2 — the same answer on 2.11.4
and 2.35.7, so this was never a version question:

```
setTimeout function   Promise function   Math object
JSON object           Date function      helpers object
fetch UNDEFINED       URL   UNDEFINED
```

Every retry assertion passed anyway, because `testing/n8n_retry.js`
extracted the node's source and ran it with `new Function(...)` **in plain
Node, where `fetch` is a global**. The harness was more capable than the
runtime it claimed to model, which is the same failure as bug 57 wearing
different clothes: a check that cannot see the condition it exists to
catch.

### Two fixes, and the second is the durable one

**The node** now calls `helpers.httpRequest`, which the Code node's context
does provide. Options read from n8n-core 2.11.1's implementation, not
guessed:

| | |
|---|---|
| `returnFullResponse: true` | returns `{ body, headers, statusCode, statusMessage }` |
| `ignoreHttpStatusErrors: true` | sets axios `validateStatus = () => true`, so a 4xx/5xx **returns** instead of throwing — which is what lets the retry loop see the status and decide |
| a network failure | still throws, and is retryable, as in Python |

Header names arrive **lowercased** (axios), so `Retry-After` is read
case-insensitively.

**The harness** now runs the extracted source in `node:vm` with a context
carrying exactly the host globals vm2 provides and nothing else. A fresh vm
context has the JS intrinsics and none of Node's additions, which is the
same shape — so a node reaching for `fetch` throws `ReferenceError` there
just as it would in n8n. `node:vm` is built in; **vm2 is not a dependency
of this repository and must not become one for a test to run** — the same
reasoning as `scripts/trigram.py` and `testing/n8n_bind_params.js`.

### The bug the fix uncovered

With `fetch` restored temporarily to prove the harness catches it, the
`ReferenceError` was **retried five times with exponential backoff** and
then dead-lettered as a transport failure. The node treated every thrown
error as a network error; Python retries `URLError`, `TimeoutError` and
`ConnectionError` and **nothing else**, so a `NameError` there fails on the
first attempt.

So thrown errors are now classified by network `code` (`ECONNREFUSED`,
`ETIMEDOUT`, `ENOTFOUND`, …) exactly as statuses are classified by number.
A programming error has no such code, fails once, and is reported as
itself. A bug in this node must be loud, not slow.

*Rejected:* requiring vm2 in the test suite to get a perfect sandbox.
`node:vm` reproduces the property under test — host globals absent — and
adding an n8n internal as a test dependency is how a suite starts testing
n8n instead of this build.

---

## D34 — Embeddings are 1536-dimensional, from `gemini-embedding-2`, and the database enforces both
**SETTLED 2026-09-10**

Every input to this was **measured**, not recalled — web search was
unavailable and Google's documentation was blocked by the egress proxy, so
the provider questions were answered by calling the API. Full evidence in
`docs/evidence/embedding_dimension_probe.md`.

| measured | |
|---|---|
| `gemini-embedding-001` truncated to 1536 | L2 norm **0.702** — not normalised |
| `gemini-embedding-2` at 3072 / 1536 / 768 | **1.000000** at every one |
| pgvector 0.6.0, `vector(3072)` + HNSW | `ERROR: column cannot have more than 2000 dimensions for hnsw index` |
| a genuine unit vector at 1536 dims | round-trips through float4 with error **1.49e-06** |
| already embedded, anywhere | **nothing** — 5 columns, 4 HNSW indexes, 0 rows |

### Why 1536 and not 3072

pgvector **refuses to index** above 2000 dimensions. 3072 stores and
computes, so the failure is not an error — it is every similarity query
silently becoming a sequential scan. Indexing 3072 needs pgvector ≥ 0.7 and
`halfvec`; the image here is 0.6.0 and the VPS's version has never been
checked. Against that, a probe comparing 3072 and 1536 rankings found the
top two identical and ranks 3/4 swapped between two documents 0.004 apart —
noise at a tie boundary. One probe is not a benchmark, and it is enough to
say the quality difference does not pay for the index it would cost.

Nothing was embedded when this was decided, so the answer cost no re-embed.
That was the cheap moment and it was used.

### Why `gemini-embedding-2`

Because it removes the hazard rather than managing it. With `-001`,
truncation to 1536 requires the caller to re-normalise, and a
re-normalisation step that is silently skippable will eventually be
skipped. `-2` returns unit vectors at every supported dimensionality, so
there is no step to skip.

### A correction to the premise, because it changes what to guard

`<=>` — cosine distance, which **all four HNSW indexes here use** — is
norm-invariant: measured 1.8e-08 between a vector and the same direction
scaled to 0.7. Cosine *ranking* therefore survives unnormalised vectors.
The hazard is real for `<->` and `<#>`, and for any column holding a mix of
normalised and unnormalised rows where magnitudes are compared — but it is
narrower than "cosine is quietly wrong", and worth stating precisely so the
guard is built for the actual failure.

### What the database now enforces (migration 018)

1. **Every vector carries its provenance.** `embedding_model` and
   `embedding_dim` on all five tables, required whenever `embedding` is not
   null. A vector cannot say what produced it.
2. **A non-unit-norm vector is refused on write**, with the norm it
   actually had in the message. Tolerance **1e-3**, chosen from the
   measurements above: ~670× the float4 noise floor, ~200× smaller than the
   failure it catches.
3. **A second model or dimensionality into one column is refused.**
   `embedding_provenance` pins each table on its first write. Changing it
   means clearing the column and calling
   `reset_embedding_provenance()`, which itself refuses while any vector
   remains — the friction is the point, because that clearing *is* the
   re-embed.

The norm is computed as `sqrt(-(v <#> v))`. `<#>` is the negative inner
product, so that is the dot product with itself — no helper function, so it
works on pgvector 0.6.0 where `l2_normalize` does not exist.

### The dimension had three copies and no check

`EMBEDDING_DIM` in `.env.example` (**read by no code at all**), plus a
`dim int := 1536` literal in `002_concepts.sql` and again in
`003_knowledge.sql`, each commented "must match" the other two.

The fix is not a fourth copy. pgvector stores a column's dimension in
`atttypmod`, so `embedding_dim()` reads it from the **catalog** and
everything derives from that. `018` additionally asserts all five columns
agree, and `test_embeddings.py` asserts `.env.example` agrees with the
database. There is nothing left to keep in sync.

`MODEL_EMBEDDING` is **named** in `.env.example` while the other four
roles are blank, and that is deliberate: the others are a per-deployment
choice, this one is a schema-level commitment wearing an env var.

### The rate is missing, and deliberately so

`config/model_prices.json` has no rate for `gemini-embedding-2`. It was not
guessed: search is unavailable here and the provider's pricing pages are
blocked, and **a fabricated rate is worse than none** — UNPRICED is
visibly missing, a wrong number silently corrupts every total built on it,
which is the whole point of D30.

So the gap is made loud instead. `load_prices.py` names every configured
model role with no rate on every run, and `v_unpriced_spend` (migration
019) counts calls already made without one — the embedding probe's own 14
calls are the first entry it would have shown. Adding the number is a
one-line edit and a loader run.

*Rejected:* 3072 with no index. Correct results, sequential scans, and the
first slow query would be blamed on the corpus rather than the schema.

*Rejected:* `-001` with normalisation in application code. It works, and it
is one skippable step away from the exact silent degradation this decision
exists to prevent.

*Rejected:* a `system_settings` row for the dimension. That is a fourth
copy with extra steps. The columns already know.

---

## D35 — The Claim Cards are their own handoff, and they are strict JSON
**SETTLED 2026-09-10**

K09 is "Engine 7 in claim-extraction mode. Strict JSON." Engine 7's INBOX
mode already had a registered handoff — `<RESEARCH_PRACTICE_INBOX_HANDOFF>`,
§R10 — and it deliberately carries **§55's information GAIN and not the
claims**: how many were identified, how many were already known, what
extended the library.

So an INBOX run could report *"7 claims identified"* and leave **nothing**
for K09 to normalize, retrieve evidence for, or synthesise from. The
substance was described and never emitted. That is D24's failure in a new
place: a summary is not the reasoning any more than a control block is.

`<RESEARCH_PRACTICE_CLAIMS>` (§R11) carries the Claim Cards themselves, and
both blocks are **required** on an INBOX run. `engine_handoffs` already
supported several tags per mode — E6 REBUILD has two — so registering it
was an INSERT, not a mechanism.

### Strict JSON without touching frozen step 11

Handoff blocks are line-oriented `KEY: value`; a Claim Card has eleven
fields and there may be dozens of cards. The obvious move was to teach
`RUN_ENGINE` and the workflow that a handoff body can be JSON — and that
is a change to **step 11, which is frozen**, and to both sides of D26's
byte parity and D31's SQL parity.

It was not needed. `parse_handoff_block` already handles **continuation
lines**: a line that is not `KEY:` is appended to the current field. So a
single `CLAIMS_JSON:` field followed by pretty-printed JSON round-trips
losslessly — verified against the real parser before the format was
chosen. A JSON line begins with a brace, a bracket, a quote or whitespace,
never with an ALL-CAPS key, so it cannot be mistaken for a new field.

**Zero changes to `run_engine.py`, the workflow, or either parity suite.**
The frozen thing stayed frozen because the constraint was checked first
rather than worked around.

### What K09 may not do

* **No evidence records.** `evidence_referenced_by_source` holds what the
  SOURCE cited. It is text, it stays text, and
  `envelope_derived_records.discovery_only` is `true`: this envelope
  surfaced the claim, it does not evidence it (D10). A video that gave us
  an idea has not proved it.
* **No strategies.** That is K11, after synthesis has actually compared the
  claim against the library.
* **No `POTENTIAL_NEW_STRATEGY` verdict.** §54's classification here is
  derived from what was *written*, not from the model's own counts, and
  only three outcomes are decidable at this stage: no claims →
  `LOW_INFORMATION_GAIN`; claims and no new concepts → `SUPPORTS_EXISTING`;
  claims and new concepts → `NEW_CLAIM_REQUIRES_RESEARCH`. `ALREADY_KNOWN`
  is withheld too — at this point "nothing new was proposed" has been
  established, which is not the same thing.
* **Nothing from a held-out source.** A3: those are the retrieval answer
  key. The envelope goes to `SKIPPED` with the reason recorded on the row.

### Extraction confidence is not authorisation

Hard rule 4, restated in §R11 because this is exactly where it would be
forgotten: `extraction_confidence` is confidence that **the source says
this**. Not that it is true, not an evidence grade, and not permission to
promote anything. §5 keeps claim strength and claim truth separate.

*Rejected:* a second, narrower extraction prompt. Hard rule 7 — an output
that cannot be traced to a specification is worse than no output — and
K09 says *Engine 7* in claim-extraction mode.

*Rejected:* parsing the claims out of the human-readable output. That is
prose parsing to route, wearing a different hat.

*Rejected:* making `<RESEARCH_PRACTICE_CLAIMS>` optional so a source with
nothing in it need not emit it. An empty array is an answer and an absent
block is a failed run, and those must not look the same.

---

## D36 — K10 and K11 get their own E7 modes, and the dedup is not the model's job
**SETTLED 2026-09-10**

Two new Engine 7 modes, `EVIDENCE` and `SYNTHESIS`, each with its own
required handoff (§R12, §R13). Adding them was **data**: `ENGINE7_MODE` is
not in `control_contract.v1.json`, so no contract version moved; §88 is
build-owned and its enum row grew; and migration `020` had already put the
client/clock rule in `engine_handoffs.client_required`, so registering a
knowledge-clock mode is an INSERT.

*Rejected:* running K10 and K11 inside `UPDATE`. §R8 calls an UPDATE "a
smaller foundation pass" and its handoff wants `DOMAIN`, `SUBDOMAINS`,
`PHYSIOLOGY_TARGETS` — required output for a single-claim research call
that has none of them. A mode is what an engine was asked to do, and these
are different questions.

### K10 — "do not deep-research trivial claims" is the design, not a caveat

Every researched claim is a model call. A library that researches every
mechanism aside a creator makes will spend its budget on the cheapest
claims in it. So the queue is triaged **deterministically, before anything
is called**, and the rule is written down where it can be argued with:
`SAFETY` and `INTERVENTION_EFFECT` are researched, everything else is not.
Impact, not uncertainty (hard rule 3) — a SAFETY claim is researched even
when it looks obvious, a `DEFINITIONAL` one is not even when it looks
interesting.

**The source's own citation is not the input.**
`evidence_referenced_by_source` is deliberately **not sent** to the
EVIDENCE run. What a creator cited is a fact about the creator (§12);
feeding it in as the starting point turns independent research into an
echo, and D10 is exactly the line it would cross. Evidence records never
link to the discovery envelope, and a study with no DOI, PMID or URL gets
**no `source_items` row at all** — inventing one would put an unverifiable
citation in the same table as retrievable sources, where nothing could tell
them apart.

**Finding nothing is a finding.** An empty `EVIDENCE_JSON` writes no
records and still records the conclusion on the claim, because a NULL there
would put the claim straight back on the queue and pay for it again.

### K11 — deterministic dedup before the call, and the veto after it

`BUILD_GUIDE` predicts the failure: *"If cost per new card climbs with
library size, deterministic dedup is not filtering enough before the LLM
call."* So candidates are found by concept overlap first — exact, cheap,
and works with no optional extension — then by `pg_trgm` name similarity
where it exists, and **only those candidates are sent**. Asking a model "is
this already in the library?" with the whole library attached is the cost
curve that warning describes.

**"Never silently duplicate" is enforced, not requested.** A model
returning `CREATE` is a proposal. Every `CREATE` is re-checked against the
live library immediately before insertion, and a collision is **converted
to an UPDATE** with the override written into the rationale. The model
proposes; `knowledge_synthesize.py` decides.

There are exactly four decisions. A fifth is a malformed run, not a
nuance — a run returning `PROMOTE` fails rather than being interpreted.

### What K11 may set, and the one thing it may not

Everything created lands at `AI_DISCOVERED_CANDIDATE`, which
`ck_provenance_required` lets exist without a provenance note. The only
status K11 may set beyond that is `DEPRECATED`, on the losing side of a
MERGE — and the constraint refuses that without a note, so **the merge
rationale becomes the provenance note**. A MERGE with no rationale fails in
this file, saying why, rather than at the constraint saying "check
constraint violated" (D11).

### A strategy nothing can retrieve is a gap, not a success

§R13: *a strategy with no concepts is a strategy nothing will ever
retrieve.* An unmatched phrase becomes a `PROPOSED` concept and the
normalizer returns **no id** for it, deliberately — `PROPOSED` is what
keeps a machine-invented concept out of retrieval until something promotes
it (D8). So a strategy built from all-new phrases is real and not yet
findable.

That is recorded as an **OPEN `HIGH` gap** naming the strategy and the
phrases that resolved to nothing, on the create path and the update path
alike. Hard rule 11: zero identified gaps never means finished, and a gap
the library cannot see is one nobody will ever close.

*Rejected:* linking the `PROPOSED` concepts into `strategy_concepts` so the
count looks right. That is the retrieval spine; putting unpromoted concepts
in it is precisely what D8 prevents, and it would trade a visible gap for
an invisible one.

---

## D37 — Discovery finds; it does not ingest. And the access policy is a registry row
**SETTLED 2026-09-10**

K02–K06 add five ways for something to arrive. They add **no** ways for
something to be processed: every adapter ends at
`knowledge_ingest.deliver_to_inbox()` and K07/K08 take it from there.

Two ingestion paths would be two normalizers, two dedup rules and two
places for rights handling to be forgotten — and the second one always
learns about §52 later than the first. "Discovery is another way things
arrive at the inbox" is not a simplification; it is the correct
description.

### The policy is data, checked at one chokepoint

Three sentences of the specification are policy:

| | |
|---|---|
| K03 | "Not indiscriminate scraping. Respect access restrictions." |
| K06 | "Do not build brittle unauthorized scraping as a core dependency." |
| §49 | acquisition is provider-independent and the adapter is replaceable |

A policy inside an adapter is one the next adapter reinterprets. It lives
in `acquisition_adapters` (migration `021`) — `allowed_hosts`,
`respect_robots`, `requires_authorization`, `min_interval_seconds`,
`repeat_after_hours` — and `acquisition.fetch()` is the only place a
request is made. Adding an adapter is an INSERT (hard rule 13); what it may
do is a column, not an argument someone remembered to pass.

**An unregistered adapter fetches nothing.** No row means no policy, and
this layer will not act on behalf of one.

### Refusing is an outcome, and it is recorded

`source_fetches` records every request **and every refusal, with the
reason**. "robots.txt disallowed this" and "no authorization is recorded"
are findings about our access. A discovery layer that logged them nowhere
would be indistinguishable from one that was quietly scraping.

A `robots.txt` that **errors or cannot be read is a refusal**. "Respect
access restrictions" cannot mean "respect them when they are conveniently
available". A 404 is the one honest "no restriction stated".

### K06 has no scraper to be brittle

`YOUTUBE` is registered with `requires_authorization = true` and no
authorization note, so the chokepoint refuses before anything is requested
— not even `robots.txt` — and the item is recorded `ACCESS_DENIED`. That
is a **true statement about our access**, not a failure. The day an
authorization exists it becomes a registry note and the same path fetches.

K05 is the same shape at a smaller scale: an episode with no published
transcript is recorded `FULL_TEXT_NOT_AVAILABLE`, so it is not
rediscovered every run and its content is not manufactured from a title and
a blurb.

### One item, whose status progresses

Discovery registers a `source_items` row when it *finds* something;
normalization used to insert another when it *read* it, and the two
collided on `uq_item_url`. They are one item at two stages —
`DISCOVERED` → `QUEUED` → `NORMALIZED` — so the normalizer now reconciles
by URL and then by content hash.

The same seam produced a second, worse bug: a monitored page keeps its URL
and changes its content, which hit `uq_envelope_url_version`. §56 says the
same raw source processed again is a **new version** and neither is lost,
so `open_envelope` now bumps `source_version` and the receipt says it did.
Both were reachable only once discovery existed, and neither was
hypothetical.

### What has NOT been verified, and it matters

**No adapter in this build has ever spoken to its real API.** The build
environment's egress proxy blocks `eutils.ncbi.nlm.nih.gov`,
`api.crossref.org` and `pubmed.ncbi.nlm.nih.gov` — all three answered
`000`. The suite drives the **real** adapters through the **real**
chokepoint with only `transport()` replaced, which proves the policy, the
query history, the cursor, the refusal paths, the parsing and the handoff.
It proves nothing about whether PubMed's JSON is shaped the way this code
reads it.

That is a weaker claim than anything else in this build and `PROGRESS.md`
labels it as such. The first live run of `PUBMED` should be treated as
unverified code, not as a regression if it fails.

*Rejected:* a feed library. A feed is a documented format and this reads
five fields from it; a dependency would be a larger surface than the
parsing it replaces.

*Rejected:* letting discovery normalize HTML itself, since it already has
the bytes. That is the second normalizer this decision exists to prevent.

---

## D38 — A rate belongs to a modality, and K14 embeds text only
**SETTLED 2026-09-10**

`gemini-embedding-2` text input is **$0.20 per 1M tokens**, paid tier —
supplied by the practitioner 2026-09-10, the one number D34 said it would
not guess. The gap `load_prices.py` had been naming on every run is closed
and `v_unpriced_spend` is empty for `MODEL_EMBEDDING`.

### The model is multimodal, and the modalities are priced 60x apart

| | per 1M tokens |
|---|---|
| TEXT | **$0.20** |
| IMAGE | $0.45 |
| AUDIO | $6.50 |
| VIDEO | $12.00 |

A registry keyed on model name alone has **one rate per model**. An audio
embedding priced at the text rate under-reports by **32x** and a video one
by **60x** — and the cost table would look fine while being wrong, which is
the failure D30 exists to prevent arriving through a different door. A
fabricated rate and a borrowed one corrupt the same totals.

So the key is `(model_name, modality)` in `model_prices`, `cost_events`
records which modality it paid for, and both halves of `price_call` —
SQL and Python — **refuse to guess**:

* a modality given with no rate → `UNPRICED`, **never another modality's rate**
* no modality given, model priced in **several** → `UNPRICED`
* no modality given, model priced in **one** → that one, unambiguously

The last case is what keeps every single-modality caller working unchanged,
including the frozen n8n workflow (D32), which passes no modality and does
not need to: an engine run is text and Claude models carry one rate.

### K14 embeds TEXT ONLY, and it is enforced in two places

Transcripts and extracted document text, never the source media. Embedding
a podcast's audio instead of its transcript is a **32x bill for a worse
retrieval index** — the audio carries no more meaning than the words and
far more tokens.

| where | what it refuses |
|---|---|
| `scripts/embedding.py` | media magic bytes (PNG, JPEG, Ogg, MP3, Matroska, PDF, FLAC), `data:` media URLs, media MIME types, non-UTF-8 bytes, non-strings, empty payloads — **before the provider is called** |
| `ck_embedding_text_only` | any `cost_events` row with `model_role = 'MODEL_EMBEDDING'` and a modality other than TEXT |

Two layers because either alone is a habit. The code refusal is what stops
the spend; the constraint is what stops a second code path from ever
appearing that does not refuse.

**This is a cost decision, not a capability limit.** If multimodal
embedding is ever actually wanted, drop the constraint in a migration that
says why and change `embedding.py` deliberately. The rates for the other
three modalities are already loaded, so that day is a policy change and not
a pricing one.

### One embedding boundary

`embedding.embed()` is the only path, for the same reason there is one
`RUN_ENGINE`. It also enforces D34 at the call rather than only at the
column: a vector that comes back non-unit-norm or wrong-dimensioned is
refused **before it is returned**, so the failure surfaces where it
happened instead of one layer later at the insert.

Token counts are an **estimate** — the embeddings endpoint returns no usage
block — and `estimate_tokens()` says so in its name and its docstring. The
measurement report must not quote them as measurements.

*Rejected:* one rate per model with the modality handled at the call site.
That is the arrangement being replaced: it puts the guarantee in whichever
caller remembered, and the registry stays capable of expressing something
false.

*Rejected:* defaulting an unstated modality to TEXT. It is the cheapest of
the four, so every mistake would round in the direction of under-reporting
— silently, and in the direction nobody checks.

---

## OPEN

**O1 — Intake form. `RESOLVED FOR V1` — see D22.** Core Intake V1 is built:
scope and exclusions in D22, schema in migration `009_intake.sql`. It emits
structured JSON, never prose; an incomplete intake runs anyway, populates
the high-priority missing-data set, and lets Engine 5 generate the follow-up
questions.

What remains open is **V2**, and deliberately so: which fields to add is a
question for `v_missing_data_recurrence` once real cases have run, not for a
design session. Also still open: the practitioner-facing capture surface —
V1 accepts a structured submission, and how a human fills it in (form, or
practitioner transcription during consultation) is O2's problem.

**O2 — Practitioner review surface.** `v_review_queue` exists; no UI.
Minimum: client list, review-required queue, engine results, approve / edit
/ rerun.

**O3 — PostgreSQL hosting.** Self-hosted on the VPS versus managed. Data
residency under India's DPDP Act is a deliberate decision, not a default.
Non-negotiable either way: loopback-bound port, nightly encrypted off-site
`pg_dump`, and **a restore actually tested once**. The restore drill was
performed 2026-09-10 against a local PostgreSQL and found that the backup
contained no roles; that is fixed. It has still never run on a VPS, under
cron, with GPG or an off-site target, so this clause is satisfied for the
script and not for the deployment.

**O4 — Deterministic flag rule set.** `case_flags` and the gate work; the
SQL rules that populate HOLD versus NOTE are unwritten. Start narrow
(see D6) and tune from real cases.

**O5 — Indian food composition data source.** Needed by Engine 3 for
seasonality and regional availability. The engine is instructed not to
invent availability.

---

## DEFERRED

**F1** Full engine-output JSON schemas beyond the control contract.
**F2** Client report formatting, WhatsApp output, practitioner deep view.
**F3** ~~Engine 1 call-size measurement~~ — **DONE 2026-09-09, see D5.**
Measured on a live provider, not estimated: the cycle is
81,258 in / 86,681 out, $0.386, 306s, and both Engine 1 passes produced
complete 19-part reports on one prompt hash. Re-run
`python3 scripts/measure_engine1.py` (~$0.39) after a model change, not to
re-confirm a settled result.
**F4** Multi-tenant anything, mobile app, billing, client portal. Explicitly
out of scope: this is internal single-practitioner software.

---

## D39 — Retrieval breadth is a mechanism, not a hope
**SETTLED 2026-09-10**

BUILD_GUIDE step 17's acceptance criterion is *"the cross-domain case
retrieves across insulin sensitivity, hepatic fat, triglycerides, muscle,
appetite, sleep, vegetarian implementation, exercise and behaviour — **not
three disease folders**."*

That is not a quality target that better embeddings eventually reach. It is
a statement about what the ranking must be built to do, because the two
things standing in its way are both structural.

### Why similarity alone always returns the folders

A case note about insulin resistance is lexically and semantically **close**
to insulin-resistance material and **far** from sleep material. That is not
a defect in the index; it is what similarity means. Retrieval that ranks by
text or vector similarity to the presenting complaint therefore returns the
presenting complaint's folder, and the better the embeddings the more
reliably it does so.

The sleep and behaviour material is relevant because **Engine 1 said it
was** — the case's normalized concepts include `SLEEP_QUALITY` and
`BEHAVIOUR_CHANGE` — not because the words resemble each other. So the
concept spine is a **retrieval channel** here, not a filter applied to one:
`strategy_concepts` is queried with the case's concepts and contributes its
own scored hits, alongside full text and vector. `by_concept()` is the
channel that can reach material no similarity score would.

### Why a fixed per-bucket cap would have been a knob, not a property

Even with the spine, an imbalanced library defeats breadth on volume alone.
Six insulin strategies and one sleep strategy means the top of any blended
ranking is insulin strategies. So each query concept may fill at most
`per_bucket_cap` slots in a first pass, and leftover capacity is filled from
what that pass deferred — the cap changes the **order** in which breadth and
depth are spent and costs no recall.

The cap is **derived, not a constant**: `limit // len(concepts)`. A fixed
cap of 3 satisfies the criterion at a page of 27 and fails it at a page of
12, where three folders take nine of the twelve slots. A build whose
acceptance test passes only because the test chose the cap has tested the
test. `derive_cap()` means the default satisfies the criterion, and the
suite asserts the cap it used was the derived one.

**Rejected:** a fixed cap (fails at small pages); returning N per concept
regardless of score (throws away ranking entirely and returns weak
material to fill quotas); reranking with a model (a per-query LLM call on
the hot path, for an ordering problem that is deterministic).

### Channel weights are renormalized over the channels that ran

`concept 0.40 / fts 0.30 / vector 0.30`, divided by the weight of whichever
channels actually produced hits. Without this, a database with no pgvector
(D15) scores every result 30% lower than the same database with it — the
same ordering wearing a different number, which reads as a quality drop
that has not happened. Recall genuinely degrades without vectors; ranking
does not, and the scores should say so.

Raw channel scores are normalized to `[0,1]` **per channel** first.
`ts_rank_cd` is unbounded and corpus-dependent, cosine similarity is a
bounded angle; blending them raw lets whichever is numerically larger
dominate for reasons unrelated to relevance.

### One row, every channel that found it

A strategy found by all three channels is **one result carrying three
channels**, not three results. The channel list is why a retrieval is
explainable afterwards — "why did this appear?" is answered by the row
rather than reconstructed.

### A3: held-out material is excluded by default

Chunks from a held-out `source_items` row are filtered in the metadata
step. Evaluation passes `include_held_out=True` deliberately. If production
retrieval could see the held-out set, the measurement it exists for would
be measuring itself.

### Freshness is a hash of the TEXT, not of the row

`embedding_source_hash` (migration 023) is the sha256 of the exact text
that was embedded, so "do not regenerate unchanged embeddings" is a
property rather than an intention: a second backfill pass makes **zero**
provider calls and an edit to one row costs exactly one. Hashing the row
would re-embed the library every time `retrieval_hits` moved — which
retrieval itself increments, so reading the library would have paid to
re-embed it.

The embeddable text expression **mirrors the full-text index** on the same
table. Two halves of one hybrid score computed over different text are not
comparable, and the rerank combines them.

`scripts/embed_library.py` chooses rows and text; it never calls a
provider, checks a norm or prices a call. Those live in `embedding.py`
(D38) because a second copy of a check is a second place for it to be
wrong.

---

## D40 — Evaluation is five layers, and its expectations are never authored
**SETTLED 2026-09-10** — implements D7; migration `024`

D7 settled *why* there is no practitioner-authored gold benchmark. This is
*how* the five layers are built, and what each one refuses to do.

### Every expectation is derived from something the system already held

| | the expectation comes from | human |
|---|---|---|
| A | the K1 ontology seed, which predates every extraction | none |
| B | a HELD-OUT source, extracted separately, kept out of the library | none |
| C | how many domains the library could possibly span | none |
| D | the practitioner marking a small sample | QC only |
| E | layer D's verdicts, as a rate | via D |

### The concept-domain edge is a row, not a sentence

Layer A scores against a domain's seeded concept family, and that family
existed only inside `concepts.origin_detail` — prose, of the form
`'... DOMAIN A (CONDITIONS & CLINICAL STATES); also DOMAIN B'`. Parsing it
to decide what a test expects is the same mistake as routing on prose
(hard rule 5). `concept_domains` is the edge; `seed_ontology.py` writes it,
and the migration reconciled the 269 already-seeded concepts once. Both
derivations produce **290 edges**, and the suite asserts they agree.

### Layer A splits the family so the query cannot contain the answer

Three of a domain's concepts become the query text; the **rest** are what
must come back. The sets are disjoint by construction, and `query_concepts`
is empty — handing the spine the family it is being asked to find is the
same failure wearing a different hat (V2).

The score is **recall@20**, and a family of 67 concepts is bounded above by
20/67 before retrieval is judged at all. The score is deliberately **not**
rescaled for that; the ceiling travels with the number in the result note
instead. Rescaling a measure after reading it is how a measure stops
meaning anything.

### Layer B must not teach the library the answer key

`knowledge_extract.py` already refuses to extract a held-out source into
`claims` (A3). But the answer key still has to be produced, and producing
it the ordinary way would have leaked it in a quieter place:
`normalize.resolve()` **creates PROPOSED concepts and attaches trigram
aliases**. The held-out vocabulary would have entered the ontology, and the
library would have learned from the material it was being measured against
— with nothing in the schema to notice.

Two mechanisms:

* `holdout_answer_keys` is the destination, and nothing in K10 or K11 reads
  it. No `claims` row, no strategy, no provenance edge.
* `normalize.resolve(..., read_only=True)` runs the SAME tiers and writes
  nothing — no cache row, no alias, no proposal, no escalation.

`read_only` is a parameter on the shared resolver rather than a second
matcher in `evaluate.py`, deliberately. An answer key built by a different
resolver would be in a different vocabulary from the library, and the
comparison would measure the two resolvers against each other (V2).

### Layer C measures breadth against an achievable ceiling

"Not three disease folders" is a claim about how many domains a page spans,
so layer C's metric is `DOMAIN_BREADTH` and the denominator is **how many
domains the library actually has strategies in** — computed, never assumed.
A library holding one domain cannot span two, and scoring it 0.3 for that
would be measuring the library's age.

A library spanning **no** domain is `UNSCORABLE`, recorded as such and
**excluded from the mean rather than counted as zero**. The metric is a
column on the test row (`evaluation_metric`), not a branch keyed off the
layer: A and B ask "did the expected material come back", C asks something
else, and a third question should be a value rather than an `if`.

### An empty expectation is not a perfect score

`ck_test_has_expectation` refuses a test with nothing to expect. Recall over
an empty set is undefined, not 1.0 — and a young library reporting a perfect
score for knowing nothing is the single most plausible way this whole layer
could have become decorative.

### Layer D is capped, and layer E is a rate

The sample is drawn automatically from a layer C case, so nobody authors a
query, and a **second sample is refused while one is unreviewed**. A queue
that grows whether or not anyone looks at it is the recurring manual job
hard rule 3 forbids, arriving quietly.

D7's fourth verdict — "an important item was missing" — is about the sample,
not about any row in it, so it lives on the sample and
`ck_missing_needs_note` refuses it without a note. "Something was missing"
that does not say what cannot become a knowledge gap or a query fix.

Layer E's denominator is what was **reviewed**, never what was presented: a
half-reviewed sample would otherwise report half the rate. `v_discovery_value`
gives the per-sample rate and `v_discovery_value_trend` pools items across
samples rather than averaging per-sample rates, so a three-item sample does
not weigh as much as a thirty-item one.

### A score is recorded with the configuration that produced it

`retrieval_test_runs` stores `vector_enabled`, `library_size` and the
`score_floor` the run judged against. Recall with pgvector and recall
without it are different numbers (D15) and must never be trended as one
line; a floor that moved between runs would make the history meaningless.

**Measured on the first real run** (`docs/evidence/layer_a_baseline.md`):
full text alone **0.1372**, full text + vector **0.3255**, same fourteen
tests, 269 concepts embedded in between. The floor was 0.30 before either
run — a threshold chosen to sit just under the number it judges is not a
threshold.
