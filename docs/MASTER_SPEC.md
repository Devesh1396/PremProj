# MASTER SPECIFICATION — REFERENCE

**Provenance note.** This document is reconstructed from the OCR text layer
of the original master build specification (`mast_engine.pdf`, a ZIP
archive of page screenshots). It is faithful in structure and substance,
but it is a *reconstruction*. If a clean canonical text of the master
specification exists, replace this file with it and keep the AMENDMENTS
section below, since those decisions post-date the original.

Where this document and the original disagree, the original wins on intent.
Where this document and `docs/DECISIONS.md` disagree, DECISIONS wins — it
records deliberate, later amendments.

---

## Project objective

A self-hosted, low-cost internal system for one Certified Functional
Nutritionist. It automates new-client analysis, clinical and nutrition
reasoning, behaviour design, food and recipe implementation, progress
interpretation, client communication, longitudinal case memory, deep
research and knowledge-library construction, continuous knowledge updating,
and client-specific knowledge retrieval.

The seven engine prompts are **authoritative domain logic**. They are not
rewritten or shortened except where technical formatting requires it.

### Primary design goal

The practitioner spends time on reviewing high-level findings, approving or
modifying important decisions, client interaction, exceptional cases, and
growing the business. The software handles repetitive analysis, research,
documentation, plan construction, tracking and knowledge retrieval.

---

## Stack constraints

- **n8n Community Edition**, self-hosted, for orchestration
- **PostgreSQL**, self-hosted, for client data and knowledge
- **pgvector** where practical. The system MUST still function without it
  using structured metadata, full-text search and relational filtering.
  Design so it can be enabled later without database redesign.
- **OpenAI-compatible LLM API** via environment variables and provider
  abstraction

**No model name is hard-coded anywhere.** Configurable model roles only:

```
MODEL_ANALYSIS  MODEL_EXTRACTION  MODEL_RESEARCH  MODEL_EMBEDDING  MODEL_FAST
```

Not required, and must not become mandatory: Dify, paid vector databases,
paid dashboards, paid scraping platforms, a mobile app, a client portal.

### Interface

No fancy interface. n8n plus a minimal internal review mechanism. The
practitioner must be able to see clients requiring review, inspect summary
results, inspect full engine output on demand, approve, reject, request
rerun, and optionally edit notes. No development time on visual polish.

### Security

This system handles personal health information.

Secrets via environment variables. No API keys in git. `.env.example`
maintained. Database credentials protected. Access limited to local or
private deployment. Sensible log hygiene; avoid client data in debug logs.
Backups documented. **Knowledge-library research data kept logically
separate from identifiable client data.** Practice-based knowledge derived
from client outcomes uses de-identified aggregates.

---

## Working method

1. Read all seven prompt files
2. Read the specification completely
3. Maintain `BUILD_PLAN.md` with phases and acceptance criteria
4. Maintain `PROGRESS.md`
5. Use git from the beginning; commit after each working milestone
6. Run tests after each phase
7. **Do not declare completion because files exist. Verify workflows
   actually execute.**

For complex decisions: EXPLORE → PLAN → IMPLEMENT → TEST → FIX → DOCUMENT.

Where something is ambiguous but a reasonable default exists, choose the
simplest low-cost internal implementation and document the assumption
rather than stopping.

---

## The 40 phases

### Client system
| # | Phase |
|---|-------|
| 1 | Local infrastructure — PostgreSQL, n8n, optional pgvector |
| 2 | Core client database |
| 3 | Engine execution layer — `RUN_ENGINE` |
| 4 | New client workflow — `CLIENT_NEW` |
| 5 | Follow-up workflow — `CLIENT_FOLLOWUP` |
| 6 | Case memory system — Engine 6 |

**PHASE 3 — RUN_ENGINE.** A single reusable subworkflow. Inputs:
`ENGINE_ID`, `SYSTEM_PROMPT`, `STRUCTURED_INPUT`, `OUTPUT_SCHEMA`,
`CLIENT_ID`, `CASE_VERSION`, `RUN_CONTEXT`. Responsibilities: construct the
model request, execute, validate structured response, retry malformed
output, save run metadata, save raw/human output, save structured output,
return a normalized result. **Do not copy identical LLM-call logic seven
times.**

**PHASE 4 — CLIENT_NEW.**
```
intake → validate → create client → E6 initial state
      → E1 → E2 → E3 → E6 update
      → practitioner review queue → after approval
      → E5 client communication → save
```
Engine 4 is not required before response data exists.

**PHASE 5 — CLIENT_FOLLOWUP.**
```
follow-up data → save raw/structured → E6 update → E4 progress analysis
              → inspect routing recommendation
              → E1 (clinical/hypothesis) | E2 (behaviour/adherence)
                | E3 (nutrition implementation) | MULTIPLE
              → E6 update → review if needed → E5 → save
```
Prevent infinite routing loops. Maximum routing depth configurable.

**PHASE 6 — Case memory.** Canonical current state plus historical
versioning. Never overwrite history without retaining the previous version.
Provide `GET_CURRENT_CLIENT_STATE(client_id)`, `GET_CLIENT_TIMELINE()`, and
`GET_RELEVANT_CLIENT_HISTORY(client_id, context)` where practical.

### Knowledge system
| # | Phase |
|---|-------|
| 7 | Knowledge database |
| 8 | Semantic retrieval (hybrid) |
| 9 | Knowledge Factory workflows (K00–K16) |
| 10 | Research data sources |
| 11 | Source discovery |
| 12 | Book workflow |
| 13 | Podcast / video workflow |
| 14 | Duplication control |
| 15 | Knowledge versioning |
| 16 | Client knowledge retrieval |
| 17 | Live research escalation |
| 18 | Engine connections |
| 19 | Local / seasonal food |
| 20 | Practice-based learning |
| 21 | Knowledge coverage |

**PHASE 7.** Knowledge must NOT be a folder of disease articles. Build a
multidimensional relational/semantic system. Minimum entities:
`knowledge_domains`, `source_creators`, `knowledge_sources`, `source_items`,
documents, chunks, claims, strategies, evidence, implementation patterns,
controversies, negative knowledge, foods, seasonality, supplements, gaps.
**Popularity is never assigned as evidence quality.**

**PHASE 8 — Hybrid retrieval.** Do not rely only on embeddings. Sequence:
structured metadata filters → full-text search → vector similarity where
enabled → deduplication → LLM/contextual reranking.

Target query shape:
```
condition = PCOS, physiology = insulin sensitivity, diet = vegetarian,
outcome = postprandial glucose, population = women, location = India
```

**PHASE 9 — Knowledge Factory workflows.**

| ID | Purpose |
|----|---------|
| K00_FOUNDATION_CONTROLLER | Wave-1 build. domain map → subdomains → research questions → source discovery → ingestion → claim extraction → evidence analysis → strategy synthesis → gap assessment → repeat. Bounded breadth/depth. |
| K01_DOMAIN_MAPPER | Expand a domain into physiology, biomarkers, symptoms, outcomes, intervention families, populations, nutrients, exercise, behaviour, supplements |
| K02_RESEARCH_DISCOVERY | Legitimate biomedical APIs, prefer structured over scraping. Store query history so expensive searches are not repeated. |
| K03_WEB_SOURCE_DISCOVERY | Researcher and practitioner sites, blogs, newsletters. Not indiscriminate scraping. Respect access restrictions. |
| K04_RSS_MONITOR | Track last processed item; do not reprocess old content |
| K05_PODCAST_INGEST | Transcript where legitimately accessible. If none, mark status rather than inventing content. |
| K06_VIDEO_INGEST | Transcripts only when legitimately accessible. **Do not build brittle unauthorized scraping as a core dependency.** Store timestamps. |
| K07_MANUAL_DOCUMENT_INGEST | Watch `/knowledge/inbox`. Books processed chapter-by-chapter. Move to `/processed` or `/failed`. Never delete originals. |
| K08_CONTENT_NORMALIZER | Normalize to structured text preserving source, author, date, chapter/page/timestamp |
| K09_CLAIM_EXTRACTOR | Engine 7 in claim-extraction mode. Strict JSON. |
| K10_EVIDENCE_ANALYZER | Human research for high-value claims. Do not deep-research trivial claims. |
| K11_STRATEGY_SYNTHESIZER | CREATE / UPDATE / MERGE / NO CHANGE. **Never silently duplicate.** |
| K12_CONTROVERSY_ANALYZER | Create/update controversy records on conflict |
| K13_KNOWLEDGE_GAP_ANALYZER | Prioritized research questions for uncovered areas |
| K14_EMBED_INDEX | Embeddings; do not regenerate unchanged |
| K15_KNOWLEDGE_REVIEW | Freshness and quality: stale cards, contradictory evidence, gaps, duplicates |
| K16_DEAD_LETTER_RETRY | Bounded retries. **Do not silently lose failures.** |

### Wave 1 and quality
| # | Phase |
|---|-------|
| 22 | Wave-1 foundation controller |
| 23 | Wave-1 batching |
| 24 | Knowledge cost control |
| 25 | Source-content access rules |
| 26 | Structured output validation |
| 27 | Provenance |
| 28 | Quality control |

### Testing and operations
| # | Phase |
|---|-------|
| 29 | Test fixtures |
| 30 | Engine-7 tests |
| 31 | Foundation quality test |
| 32 | End-to-end acceptance test |
| 33 | Manual review / approval |
| 34 | Logging |
| 35 | Backups |
| 36 | Exportability |
| 37 | Documentation |
| 38 | Do not overbuild |
| 39 | Final deliverables |
| 40 | Completion standard |

**PHASE 32 — end-to-end acceptance.** A synthetic client runs
`E6 → E1 analyze → E7 retrieve → E1 finalize → E2 → E3 → review → E5`,
then a follow-up runs `E6 → E4 → routing → E5`.

---

# AMENDMENTS

These post-date the original specification and were agreed during design
review. Full rationale in `docs/DECISIONS.md`.

### A1 — Concept normalization layer (new, underneath Phase 8)
Hybrid retrieval as specified cannot work on free-text engine output alone:
engines emit prose, the library stores rows, and prose does not join to
rows. A canonical concept layer sits between them — concepts, aliases,
parent/child, related, and `CONFUSABLE_DO_NOT_MERGE`. Resolution order:
deterministic alias → structured mapping → trigram → semantic → LLM only
when required, with confirmed results cached so a phrase never costs a
second call. Engines are never asked to emit codes.

### A2 — Engine 1 two-pass orchestration (clarifies Phase 32)
`E1 analyze → E7 retrieve → E1 finalize` means E1 runs twice. Both passes
load the **same** prompt file and record the **same** prompt hash. Pass A
differs only in that the E7 handoff slot is empty; Pass B differs only in
that it is populated. This is orchestration, not a redesign, and **neither
pass may be a simplified Engine 1**. Enforced by `trg_enforce_two_pass`.

### A3 — Two clocks
The case clock (event-driven, per client) and knowledge clock (continuous,
client-independent) run concurrently and meet at exactly two points: E7
case retrieval, and de-identified practice aggregation. Wave 1 does not
block the case build.

### A4 — Wave 1 acceptance (extends Phases 21, 22, 31)
Four simultaneous dimensions: domain coverage, knowledge depth, retrieval
quality, provenance. 19 depth dimensions per domain, ~14 required for
`FOUNDATION_READY`. Counts are engineering floors and instrumentation, not
definitions of quality. No `COMPLETE` status exists.

### A5 — Five-layer evaluation (extends Phase 30)
(A) automated retrieval tests from seeded domain structure, (B)
source-grounded tests on **held-out** sources, (C) cross-domain synthetic
case tests run early per domain, (D) practitioner spot check as QC sample,
(E) `UNEXPECTED_USEFUL_STRATEGIES_FOUND` tracked as a **rate**.

No practitioner-authored gold benchmark: Engine 7 exists to find what the
practitioner does not already know, so practitioner recall cannot define
the ceiling on success.

### A6 — Deterministic safety controls (extends Phase 33)
Narrow deterministic HOLD rules in SQL over labs, medications and
conditions, plus additive LLM flags. An LLM may add a flag; it may not
clear a deterministic one. Client-facing **release** is gated; internal
analysis, drafting and the practitioner view never are. NOTE flags do not
block. The gate must not fire on ordinary medicated metabolic clients — a
gate that fires constantly is a rubber stamp.

### A7 — Orchestration control contract (extends Phase 26)
A small strict JSON Schema covering only the fields n8n routes on. Report
formatting and deep extraction contracts remain deferred. **n8n never
parses prose to decide what runs next.**

### A8 — Optional extensions are genuinely optional
Every extension is attempted at migration time and recorded in
`system_capabilities`. Later migrations branch on capability rather than
assuming. Verified by applying the full schema on a build with no pg_trgm
and no btree_gin.

### A9 — Ingestion acknowledgement (extends Phase 12, K07)
The practitioner supplying a document receives an immediate receipt —
received, hashed, duplicate or new, queued — and a later completion or
failure notice. Supplying knowledge must not feel like a void.

### A10 — Deployment target
n8n runs on an existing VPS rather than local Docker. PostgreSQL hosting
per `docs/OPERATIONS.md`. The n8n instance's own database stays separate
from the PHI database.
