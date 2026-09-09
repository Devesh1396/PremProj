# BUILD GUIDE

Step 1 to the end. Steps 1–9 are **done and verified**; they are documented
so you can re-run and confirm rather than rebuild. Step 10 onward is the
remaining work.

Run `bash testing/run_all.sh` at any point. Everything must pass.
It needs a database: see `docs/LOCAL_DEV.md` for a local one.
CI runs the same suite on every pull request, with and without pgvector.

---

# PART A — COMPLETE

## Step 1 — VPS deployment

Hostinger VPS, India. n8n already in Docker. PostgreSQL joins the same
network with no published port.

```bash
docker inspect <n8n-container> -f '{{json .NetworkSettings.Networks}}'
cp .env.example .env      # set N8N_NETWORK + three role passwords
docker compose up -d && docker compose ps
```

Full procedure, tuning and role setup: `docs/OPERATIONS.md`.

**Acceptance:** container healthy; `docker compose exec postgres psql -U phi_admin -d phi` connects; no port published.

## Step 2 — Migration runner

`scripts/migrate.py`. Ordered, once-only, one transaction per migration,
checksum-guarded. Editing an applied migration is a hard error.

**Acceptance:** `python3 scripts/migrate.py --status`; re-run is a no-op; an edited applied file is rejected.

## Step 3 — `000_extensions` + `001_ops`

Capability registry (every extension optional, `has_capability()` branches
on it), `norm_phrase()`, then `cost_events`, `job_runs`,
`dead_letter_jobs`.

Cost is instrumented from batch one, not retrofitted.

**Acceptance:** applies with and without pgvector/pg_trgm/btree_gin.

## Step 4 — `002_concepts` — the retrieval spine

Canonical concepts, aliases, relations including
`CONFUSABLE_DO_NOT_MERGE` (auto-mirrored), proposals, normalization cache,
auto-generated normalization tests.

Engines emit prose; the library stores rows; this is the join.

**Acceptance:** `test_concept_layer.py` — 24 checks.

## Step 5 — `003_knowledge` — the library

Domains with 19 tracked coverage dimensions, sources with roles, claims,
evidence, strategies, `strategy_concepts`, implementation patterns,
controversies, negative knowledge, foods, seasonality, practice outcomes.

**Acceptance:** `test_knowledge_layer.py` — 28 checks. The one that matters: a
vegetarian PCOS + MASLD + prediabetes case retrieves **1 strategy by
diagnosis, 3 by concept**.

## Step 6 — `004_client` — case state and orchestration

Clients, versioned case state (one current row, index-enforced), routing
depth bound, clinical tables, `engine_runs` with prompt hash, outputs,
flags, reviews, communications.

**Acceptance:** `test_client_layer.py` — 26 checks, including two-pass fork rejection and the HOLD gate.

## Step 7 — Orchestration contract

`schemas/orchestration/control_contract.v1.json`. ~17 strict fields with
typed enums and conditional rules. n8n never parses prose to route.

## Step 8 — `RUN_ENGINE`

`scripts/run_engine.py`. Loads and hashes the prompt, calls the provider,
extracts and validates the control block, retries once with a repair
prompt, dead-letters after bounded retries, records run + outputs + cost.
Written once, not seven times.

Fixture provider mode makes all of this testable with no API key.

**Acceptance:** `test_run_engine.py` — 27 checks. E6 → E1 Pass A → E7 → E1 Pass B runs end to end; invalid output repairs then dead-letters.

## Step 9 — `005_case_events` — future-proofing hooks

RLS with three roles and default deny; versioned assessment envelope (RHT);
`case_events` spine; chat scoping; candidate facts requiring
authorization; `missing_data_reports`; draft vs delivery.

**Acceptance:** `test_case_events.py` — 34 checks. A query under Client A's scope with **no `client_id` filter** returns only Client A.

---

# PART B — REMAINING

## Step 9b — `006_knowledge_inbox` — Engine 7 ingestion foundations

Schema only. `source_kinds` as an extensible **registry table** (not an
enum), `source_envelopes`, `source_delta_analyses`,
`envelope_derived_records`, `medication_knowledge`, `medication_aliases`,
`drug_nutrient_claims`. Views `v_ingestion_status`, `v_client_safe_sources`,
`v_engine_run_clock`. Adds `ck_run_clock_coherent` to `engine_runs`.

**Acceptance:** `test_knowledge_inbox.py` — 38 checks. Adding a new source
kind is a plain `INSERT`; `OTHER` cannot be deleted or deactivated; an
envelope cannot reach an extracted state without its raw source preserved;
purchased material is excluded from `v_client_safe_sources` while staying
available internally.

---

## Step 9c — `007_coverage_and_provenance` — corrections before freeze

18 recovered coverage dimensions (`EFFECT_MAGNITUDE`,
`ALTERNATIVE_STRATEGIES`; no `KNOWLEDGE_GAPS`). Gap governance in
`domain_gap_assessments` + `knowledge_gaps.severity`. `v_domain_readiness`
rebuilt so readiness = coverage + gap assessment performed + no open
CRITICAL gap. `knowledge_entities` registry binds provenance edges.

**Acceptance:** covered by `test_knowledge_inbox.py` (59 checks) and
`test_prompt_contracts.py` (78 checks). A provenance edge to a nonexistent
entity is rejected; an open non-critical gap does not block readiness; an
open CRITICAL gap does.

---

## Step 10 — Canonical prompts *(done)*

All seven are installed in `prompts/`, ~44,550 words, seven distinct
hashes, zero non-printing characters, exactly one control-block
specification each. Engine 7 is the four-layer merge described in
`DECISIONS.md` D16.

`knowledge/seed/foundation_domains.md` holds Engine 7's A–Z foundation
curriculum verbatim, referenced from the prompt by path and hash. Load it
for K1 seeding, domain mapping and foundation research — not on CASE,
INBOX or routine UPDATE runs.

**Acceptance:** `test_prompt_contracts.py` — 55 checks binding prompt ↔
`coverage_dimension` enum ↔ `v_domain_readiness`, plus control-block
uniqueness across all seven prompts and the seed file's content hash.

**Step 10b is built. The live measurement run is the first task once
`LLM_API_KEY` and `LLM_BASE_URL` are set.**

---

## Step 10b — Wire the provider and measure Engine 1 *(built; awaiting the key)*

Everything that does not need credentials is done and proven on the fixture
provider. What remains is setting `LLM_API_KEY` and `LLM_BASE_URL`;
`run_engine.py` switches by itself and nothing else changes.

- `testing/fixtures/synthetic_client.py` — a vegetarian Gujarati woman with
  PCOS, MASLD, prediabetes and atherogenic dyslipidaemia. 31 labs, 12
  symptoms, 9 conditions, 4 medications, 3 days of food log written as the
  client would report them, plus sleep, movement, pain, stress, behaviour
  and household constraints. `PART_INPUTS` maps each of the 19 parts of
  §62 to the intake keys it reads, and the suite asserts the map. The
  medication set is deliberately the one D6 requires to **pass clean**.
  Synthetic throughout; no engine payload carries a name.
- `scripts/measure_engine1.py` — runs E6 → E1 Pass A → E7 → E1 Pass B and
  reports prompt tokens, completion tokens, cost, latency, retries and
  control-block parse success per call, out of `cost_events`. It names no
  provider and no model.
- `database/migrations/008_call_measurement.sql` — `cost_events.run_id`,
  `price_source`, and `v_engine_call_measurement`. Without run attribution
  Pass A and Pass B are indistinguishable in the cost table, which are
  exactly the two calls D5 asks about.
- `config/model_prices.json` — a price registry. A model with no rate is
  UNPRICED with a NULL cost, never 0.

**Acceptance:** `test_measurement.py`. Proven end to end on the fixture
provider: four calls, both E1 passes on one prompt hash, control block
parsed on every call, zero dead letters, a repair retry counted as two
provider calls.

Token counts under the fixture provider are **character estimates and the
report says so on every run**. The D5 question — whether a ~5,000-word
specification demanding a 19-part report degrades in its later sections —
is answerable only against a live provider. Measure, do not pre-empt.

---

## Step 11 — n8n `RUN_ENGINE` subworkflow

Port `scripts/run_engine.py` to n8n. Both must be validated by the same
suite so behaviour cannot drift.

Inputs: `ENGINE_ID`, `STRUCTURED_INPUT`, `CLIENT_ID`, `CASE_VERSION`,
`PASS`, `RUN_CONTEXT`.

n8n connects as **`phi_runtime`** and opens every client-scoped operation
with `SELECT set_client_scope($client_id)` inside the transaction.

**Acceptance:** identical results to the Python reference on the same fixtures; malformed output dead-letters; cost recorded.

## Step 12 — K1 ontology seed *(parallel with 13)*

Seed the concept dictionary **before** large-scale extraction. Expand the
core Wave-1 areas one level into physiology, drivers, biomarkers and
outcomes. Generate `CONFUSABLE_DO_NOT_MERGE` pairs from sibling structure —
do not enumerate by hand.

**Acceptance:** seeded concepts across all core domains; auto-generated normalization tests with roughly half negative pairs; `v_confusable_pairs` populated.

## Step 13 — C3 normalization layer *(parallel with 12)*

`NORMALIZATION_PHRASES` from E1 Pass A → canonical concepts.

Resolution order, cheapest first:
deterministic alias → structured mapping → trigram → semantic → **LLM only
when required**. Write confirmed results to `normalization_cache` so a
phrase never costs a second call.

New concepts are **proposed**, never created directly. Auto-resolve high
confidence, log low-impact uncertainty, escalate only high-impact
ambiguity, capped weekly.

**Acceptance:** "large post-meal glucose excursions … low muscle stimulus" resolves to the expected concept family; cache hit avoids a second LLM call; normalization tests pass including negative pairs.

## Step 14 — Intake form V1

The largest unstarted piece on the case track. It gates everything.

Keep it **practical**. Do not recreate RHT — that is a separate paid
assessment and duplicating it dilutes it. Emit structured JSON, not prose.

Incomplete intake: **run anyway**, populate `HIGH_PRIORITY_MISSING_DATA`,
let E5 generate the follow-up questions. Do not block.

Engines record gaps to `missing_data_reports`. Reporting a gap **never**
adds a question to intake — aggregate via `v_missing_data_recurrence`, then
classify deliberately.

## Step 15 — `CLIENT_NEW` workflow

```
intake → validate → create client → E6 v1
      → E1 Pass A → normalization → E7 → E1 Pass B
      → E2 → E3 → E6 v2 → review queue → E5 → save
```

E4 is not required before response data exists.

## Step 16 — Knowledge Factory K02–K11

Discovery (PubMed, RSS, web), ingestion, normalizer, claim extraction,
evidence analysis, strategy synthesis with dedup.

`MODEL_EXTRACTION` on the cheapest capable model — highest volume.
Use the **Batch API** where the provider offers it: the knowledge clock is
asynchronous and nothing waits on it.

Watch `MERGE_DECISION` in `v_cost_by_operation`. If cost per new card
climbs with library size, deterministic dedup is not filtering enough
before the LLM call.

Concurrency 2–3 on this VPS.

## Step 17 — K14 embedding and hybrid retrieval

Metadata filter → full-text → vector → dedupe → rerank.
Do not regenerate unchanged embeddings.

**Acceptance:** the cross-domain case retrieves across insulin sensitivity, hepatic fat, triglycerides, muscle, appetite, sleep, vegetarian implementation, exercise and behaviour — not three disease folders.

## Step 18 — Evaluation layers A–E

- **A** automated retrieval tests from seeded domain structure
- **B** source-grounded recovery on **held-out** sources (`source_items.held_out`)
- **C** cross-domain synthetic cases — **run per domain from moderate coverage, not at the end**
- **D** practitioner spot check, small sample
- **E** `UNEXPECTED_USEFUL_STRATEGIES_FOUND` as a **rate**

No practitioner-authored gold benchmark. See D7.

## Step 19 — K12/K13 controversy, negative knowledge, gaps

Dedicated per-domain passes once evidence has accumulated. Neither falls
out of ingestion naturally — negative knowledge and controversies are the
floors most likely to be missed at the end.

## Step 20 — E2, E3, review queue, E5

Then the deterministic flag rule set. **Start narrow** (D6). A client on
metformin, a statin and an ACE inhibitor must pass clean.

## Step 21 — `CLIENT_FOLLOWUP` and E4

```
follow-up → E6 update → E4 → routing → E1/E2/E3 → E6 → review → E5
```
Respect `case_cycles.max_loops`.

## Step 22 — Wave-1 foundation build

`K00_FOUNDATION_CONTROLLER`. Long-running, resumable, batched, cost-capped.
Core domains carry higher **processing priority only** — never a limit on
what E7 may discover.

`WAVE1_FOUNDATION_READY` is a **computed operational state**, not a
certification and not a meeting. No `COMPLETE` status exists.

## Step 23 — Practice intelligence

De-identified aggregation into `practice_strategy_outcomes`. Minimum cohort
5. Never merged with evidence.

## Step 24 — Backup drill

`scripts/backup.sh` on cron, then **restore into a scratch database and
verify**. Record the drill date in `PROGRESS.md`. An untested backup is not
a backup.

---

## Order summary

```
1–9   done: VPS, migrations 000–005, contract, RUN_ENGINE
9b    done: 006 knowledge inbox schema
9c    done: 007 coverage dimensions, gap governance, provenance registry
10    done: seven canonical prompts + foundation domain seed
10b   built: synthetic client, measurement runner, 008. Live run
      needs LLM_API_KEY + LLM_BASE_URL
11    n8n RUN_ENGINE subworkflow
12/13 K1 ontology seed  ||  C3 normalization layer
14    intake form V1                     <- gates the case track
15    CLIENT_NEW workflow
16    Knowledge Factory K02–K11
17    K14 embedding and hybrid retrieval
18    evaluation layers A–E
19    K12/K13 controversy, negative knowledge, gaps
20    E2, E3, review queue, E5
21    CLIENT_FOLLOWUP and E4
22    Wave-1 foundation build
23    practice intelligence
24    backup restore drill               <- do this early, not last
```

`bash testing/run_all.sh` must pass before every commit. Eight suites.

**This layer is frozen.** Do not reopen D16–D21 without instruction.
