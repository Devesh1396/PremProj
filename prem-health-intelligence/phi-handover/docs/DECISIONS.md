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

## OPEN

**O1 — Intake form.** The largest unstarted piece on the case track, and it
gates everything. Must capture what Engine 1 and Engine 3 need — identity,
history, measurements, labs, medications, supplements, food log, sleep,
movement, pain and function, behaviour history, location, region, budget,
cooking access, family structure, culture, festivals, travel — and emit
structured JSON, not prose. Policy on incomplete intake: **run anyway**,
populate `HIGH_PRIORITY_MISSING_DATA`, and have Engine 5 generate the
follow-up question list. Do not block.

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
