# BUILD PLAN

Internal AI-assisted nutrition / functional-health operating system.
One practitioner. Self-hosted. n8n + PostgreSQL + configurable LLM.

Claude Code is the builder, not a runtime dependency. When the build is
finished the system must keep running on n8n + PostgreSQL + an LLM API
alone.

Governing rule for every design decision below:

> AUTOMATE → AUTO-RESOLVE HIGH CONFIDENCE → LOG LOW-IMPACT UNCERTAINTY
> → ESCALATE ONLY HIGH-IMPACT AMBIGUITY

The practitioner's time is the scarce resource. No milestone may create a
recurring manual knowledge-curation job.

---

## Two clocks

The system runs on two independent clocks that touch at exactly two points.

**Case clock** — event-driven, per client. Form submitted, follow-up
submitted, practitioner acts.

**Knowledge clock** — continuous, client-independent. Discovery, ingestion,
extraction, synthesis, freshness review. Never waits on a client; no client
waits on it.

They meet at:
1. E7 case retrieval (knowledge → case)
2. De-identified practice aggregation (case → knowledge, delayed, batched)

Collapsing the two clocks makes every client trigger expensive research.
Keeping them separate is what makes runtime cheap and the library rich.

---

## Milestones

### M0 — Foundations `COMPLETE`
Shared. Blocks everything.

- Repo scaffold
- docker-compose: Postgres (pgvector) + n8n, both persisted, loopback-only
- Migration runner with checksum guard
- `.env.example` with model-role abstraction
- Capability registry so optional extensions degrade rather than fail

**Acceptance:** containers start; migrations apply; migrations are
idempotent; an edited applied migration is rejected. ✅

---

### M1 — Schema
Four migrations. `002` is on the critical path.

| # | Migration | Status | Blocks |
|---|-----------|--------|--------|
| 000 | extensions + helpers | ✅ | all |
| 001 | ops: cost, jobs, dead letter | ✅ | all |
| 002 | concepts: ontology layer | ✅ | K1, C3 |
| 003 | knowledge: domains, sources, claims, strategies, evidence, foods | pending | K4+ |
| 004 | client + orchestration: cases, labs, engine runs, flags, review | pending | C1+ |

**Acceptance:** every migration applies on a build with *and* without
pgvector / pg_trgm; functional tests pass, not merely table existence.

---

### M2 — Engine execution layer

- `RUN_ENGINE` subworkflow: build request, call LLM, validate against
  schema, retry malformed output with repair prompt, dead-letter after
  bounded retries, persist run + raw + structured output, return normalized
  result. Written **once**, not copied seven times.
- Orchestration contract as strict JSON Schema — the ~17 control-flow
  fields only. Report formatting is explicitly deferred.
- Prompt files as versioned Markdown; content hash recorded on every run so
  an output can always be traced to the exact prompt that produced it.

**Acceptance:** a deliberately malformed model response is repaired on
retry and dead-lettered after the bound, never inserted.

After M2 the two tracks run concurrently.

---

## Case track

| Step | Work | Depends on |
|------|------|-----------|
| C1 | E6 initialize, case versioning, `GET_CURRENT_CLIENT_STATE()` | M2, 004 |
| C2 | E1 pass A on synthetic clients, no retrieval | C1 |
| C3 | Normalization layer: engine prose → canonical concepts | C2, K1 |
| C4 | E7 case retrieval + E1 pass B | C3, K8 |
| C5 | E2 behaviour, E3 nutrition with E7 handoffs | C4 |
| C6 | Practitioner review queue, deterministic holds, E5 | C5 |
| C7 | Follow-up: E6 update → E4 → routing → E5 | C6 |

C2 exists to prove the case spine — state, versioning, structured output,
validation, review — before any knowledge dependency is added.

### E1 two-pass: orchestration only

E1 runs **twice**. This is an orchestration method around knowledge
retrieval. It is **not** a redesign of Engine 1.

- **Pass A** — the full master Engine 1 specification, invoked without
  retrieved knowledge. Produces initial case understanding, driver
  identification, physiology / biomarker / outcome mapping, and the
  formulation of what Engine 7 should retrieve.
- **Pass B** — the full master Engine 1 specification, invoked again with
  the Engine 7 handoff present. Complete reasoning, prioritisation and
  intervention design against retrieved options.

Binding constraints for implementation:

1. **One prompt file.** `prompts/engine1_prevention.md` is loaded for both
   passes. There is no `engine1_pass_a.md`.
2. **No simplified variants.** Neither pass may be a trimmed, summarised or
   otherwise weakened Engine 1. The master specification is the governing
   reasoning contract for both.
3. **The difference is context and stopping point, not capability.** Pass A
   differs only in that the E7 handoff slot is empty and the run is asked
   to emit its research questions. Pass B differs only in that the slot is
   populated.
4. **Same prompt hash on both runs.** `engine_runs` records the identical
   content hash for Pass A and Pass B. A divergent hash means someone
   forked the specification and is a build error.

If Pass A appears to need a shorter prompt for cost or latency reasons,
that is a signal to revisit orchestration, not to fork Engine 1.

---

## Knowledge track

| Step | Work | Depends on |
|------|------|-----------|
| K1 | Ontology seed: core concepts, aliases, confusable pairs | 002 |
| K2 | K01 domain mapper | K1 |
| K3 | K02/K03/K04 discovery: PubMed, web, RSS | K2 |
| K4 | K07/K08 ingestion + content normalizer | K3, 003 |
| K5 | K09 claim extraction (proposes concepts, never creates) | K4, K1 |
| K6 | K10 evidence analysis | K5 |
| K7 | K11 strategy synthesis + deduplication | K6 |
| K8 | K14 embedding + hybrid retrieval | K7 |
| K9 | K12 controversy + negative-knowledge passes, per domain | K7 |
| K10 | K13 gap analysis + live research escalation | K8 |
| K11 | K04/K15/K16 continuous update, freshness, dead-letter retry | K8 |

**Critical path:** M0 → M1 → K1 → K4 → K5 → K7 → K8 → C4.

K9 runs **per domain once that domain reaches moderate coverage**, not at
the end of Wave 1. Negative knowledge and controversies do not fall out of
ingestion naturally; they need dedicated passes over accumulated evidence.

---

## Evaluation layers

Five layers. None requires the practitioner to author gold answers, because
Engine 7 exists to find knowledge the practitioner does not already have —
practitioner recall cannot define the ceiling on success.

**A. Automated retrieval tests.** Queries generated from seeded domain
structure, scored against concept families defined in that same seed. The
seed predates extraction, so this is a real constraint rather than the
model grading itself.

**B. Source-grounded tests.** Hold out a slice of ingested sources from
synthesis. Extract their strategies separately as the answer key. Query and
measure recovery. Self-grounding, no human authoring, scales with the
library. *Held-out is essential — testing against fully synthesised
material measures index integrity, not retrieval quality.*

**C. Cross-domain synthetic case tests.** The vegetarian PCOS + fatty liver
+ prediabetes case must retrieve across insulin sensitivity, hepatic fat,
triglyceride handling, body composition, muscle, appetite, sleep,
vegetarian implementation, exercise and behaviour — not three disease
folders. **Run from the first domain reaching moderate coverage**, so the
normalization layer is corrected while re-tagging is still cheap.

**D. Practitioner spot check.** A small periodic sample marked
expected/useful, unexpected/useful, irrelevant, important-item-missing.
Quality control, not a knowledge-authoring job.

**E. Discovery value.** `UNEXPECTED_USEFUL_STRATEGIES_FOUND`, tracked as a
**rate per spot-check sample**, not a raw count — raw counts rise with
library size regardless of quality. Expected to decline as the practitioner
absorbs what the system surfaces. A near-zero rate early is the warning
sign.

---

## Concept governance

Extraction proposes; it never creates concept IDs directly.

| Condition | Action | Human? |
|-----------|--------|--------|
| similarity ≥ `CONCEPT_AUTO_ALIAS_THRESHOLD` | attach as alias | no |
| similarity < `CONCEPT_AUTO_CREATE_THRESHOLD` | create new concept | no |
| between, low impact | log for later audit | no |
| between, high impact | escalate, impact-ranked | yes, capped |

`CONCEPT_ESCALATION_WEEKLY_CAP` bounds the queue. Items beyond the cap stay
queued and re-rank; they are never dropped. Escalation is ranked by
**impact**, not by uncertainty — an ambiguous concept touching forty
strategies matters, an ambiguous one-off does not.

Confusable pairs are generated from ontology structure (siblings under a
shared parent), not enumerated by hand. Practitioner spot-checks a sample.

---

## Wave 1 readiness

`WAVE1_FOUNDATION_READY` is an **operational readiness state**, computed
from telemetry the system already collects. Not a certification, not a
meeting, and explicitly not a claim of complete medical knowledge.

Statuses: `NOT_STARTED` → `DISCOVERY` → `EARLY_FOUNDATION` →
`MODERATE_FOUNDATION` → `FOUNDATION_READY` → `DEEP_COVERAGE` /
`REVIEW_DUE`. There is no `COMPLETE`.

Four simultaneous dimensions: domain coverage, knowledge depth, retrieval
quality, data quality / provenance. Counts are engineering floors and
progress instrumentation — never definitions of quality.

Core domains carry higher Wave-1 processing priority. This is a weight on
the K00 queue only. It never restricts what Engine 7 may discover;
autonomous domain expansion continues throughout.

---

## Deferred by decision

Client report formatting, WhatsApp output, practitioner deep-analysis view,
full extraction contracts beyond control-flow fields, multi-tenant
anything, mobile app, billing, client portal.

Prompt length is not output length. The engine specifications describe how
each engine reasons; they are not templates for 50-page reports. Do not
simplify reasoning to make output tidy — output design is a separate,
later task.
