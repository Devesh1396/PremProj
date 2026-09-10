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
`pg_dump`, and **a restore actually tested once**.

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
**F3** Engine 1 call-size measurement — pending canonical prompt and API key
(see D5).
**F4** Multi-tenant anything, mobile app, billing, client portal. Explicitly
out of scope: this is internal single-practitioner software.
