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

## Step 10b — Wire the provider and measure Engine 1 *(DONE — measured live)*

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

**Registry half BUILT.** The port's two blockers are gone: the seven
specifications are rows (`010`) and the control contract is a row (`012`),
so a Code node reads both out of PostgreSQL with no copy of this
repository. `jsonschema` and `ajv` — the validator n8n ships — are proven
to agree on the stored document over 26 control blocks, verdict **and**
blamed field, in `test_contract_registry.py`, and CI installs `ajv@8` so
it is a real gate.

**BUILT AND FROZEN.** `workflows/run_engine.json`, **14 nodes**. Parity is
**byte-identical** (D26): 15 requests identical to the byte and 15
responses identical field for field, against one golden corpus, with the
JavaScript extracted from the workflow at run time so a copy cannot drift
from it. The workflow's **SQL is executed** by `test_n8n_sql.py` against a
real database as `phi_runtime`, with its parameters bound by a faithful
port of n8n's own algorithm (D31) — that is what caught a missing
`engine_mode`, a missing `client_id` on the dead letter, and an INSERT into
a column that has never existed. Transport retry matches the reference
exactly (D29): exponential, jittered, capped, `Retry-After` honoured, every
physical attempt in `cost_events`, and a thrown error classified by network
code so a bug in the node fails once instead of being retried six times.

**Written for the sandbox it runs in (D33).** The Code node has no `fetch`
and no `URL` — it is `vm2` — so the provider call goes through
`helpers.httpRequest`, and the retry harness runs the node's own source in
`node:vm` with only the globals vm2 provides. Every Postgres parameter is
one resolvable evaluating to a JSON literal, unwrapped with
`($n::jsonb #>> '{}')`: the form that is exact on 2.11.2 **and** 2.35.7,
because 2.11.2 has no array branch (D32).

No further step-11 work is to be started. Changes to it are bug fixes only.

**No n8n credentials are required.** `scripts/local_n8n.sh` installs n8n
from npm at a **pinned** version (the container registries are blocked in
some environments), seeds a `phi_runtime` credential from `.env.local`,
imports a workflow and runs it headlessly. **Pinned to 2.11.4, matching
the VPS** (D32) — the pin follows the VPS and is never raised to keep
current.

**The port must mirror the reference on all three outputs, not two.** D24:
a run produces human output, a substantive handoff, and a control block.
`engine_handoffs` (`013`) says which handoff tag to expect per engine and
mode; the workflow reads those rows rather than carrying a map of its own,
and a response missing a required handoff dead-letters exactly as an
invalid control block does.

## Step 12 — K1 ontology seed *(BUILT 2026-09-10)*

Seed the concept dictionary **before** large-scale extraction. Expand the
core Wave-1 areas one level into physiology, drivers, biomarkers and
outcomes. Generate `CONFUSABLE_DO_NOT_MERGE` pairs from sibling structure —
do not enumerate by hand.

**Acceptance:** seeded concepts across all core domains; auto-generated normalization tests with roughly half negative pairs; `v_confusable_pairs` populated.

**Built.** `scripts/seed_ontology.py`: 26 domains, 269 concepts, 12
aliases, 6 structure-derived confusable pairs, from a hash-verified
curriculum. Idempotent. `test_ontology_seed.py` also asserts the seed is
**not complete** (D13) — a seeded ontology is a starting position, not a
finished dictionary.

## Step 13 — C3 normalization layer *(BUILT 2026-09-10)*

`NORMALIZATION_PHRASES` from E1 Pass A → canonical concepts.

Resolution order, cheapest first:
deterministic alias → structured mapping → trigram → semantic → **LLM only
when required**. Write confirmed results to `normalization_cache` so a
phrase never costs a second call.

New concepts are **proposed**, never created directly. Auto-resolve high
confidence, log low-impact uncertainty, escalate only high-impact
ambiguity, capped weekly.

**Acceptance:** "large post-meal glucose excursions … low muscle stimulus" resolves to the expected concept family; cache hit avoids a second LLM call; normalization tests pass including negative pairs.

**Built.** `scripts/normalize.py`. The suite installs an LLM callable that
**raises if it is reached**, so "cheapest tier first" is proven rather than
asserted. Proposals are written `status='PROPOSED'` and deliberately not
cached, so a guess cannot harden into a fact by reuse. The
`CONFUSABLE_DO_NOT_MERGE` check runs at the exit, on every tier's answer
including the LLM's.

## Step 14 — Intake form V1 *(Core Intake V1 BUILT 2026-09-10)*

Was the largest unstarted piece on the case track and gated everything.
**Step 15 `CLIENT_NEW` is now the gating piece**: `scripts/intake.py`
already produces the E6 canonical-state v1 input, so what remains is
orchestration rather than new reasoning.

Scope and, more importantly, the exclusions are settled in `DECISIONS.md`
**D22** — written before any field, with the fields derived from them.
Schema in `009_intake.sql`; RLS enabled and forced on all three
client-scoped tables from that first migration.

The requirements below are the original brief, all of them now met, and
they stay here because step 15 has to keep meeting them.

Migration `011` adds the second half of validation: `009` proved
**completeness**, `011` proves **usability**. A supplied answer that cannot
be read becomes an issue in `intake_submissions.validation_issues` and is
treated as unknown or dropped — never guessed at, never accepted as given,
and never a reason to refuse the submission.

**Acceptance:** `test_intake.py` — a submission full of malformed values is
accepted, extraction survives every one of them, only the usable lab values
and named medications are stored, an unrecognised RHT status becomes
`NOT_ASSESSED` with a `DISCREPANCY` note rather than reaching an engine,
and a field whose only answer was unusable reads as **missing** so Engine 5
asks again.

Keep it **practical**. Do not recreate RHT — that is a separate paid
assessment and duplicating it dilutes it. Emit structured JSON, not prose.

Incomplete intake: **run anyway**, populate `HIGH_PRIORITY_MISSING_DATA`,
let E5 generate the follow-up questions. Do not block.

Engines record gaps to `missing_data_reports`. Reporting a gap **never**
adds a question to intake — aggregate via `v_missing_data_recurrence`, then
classify deliberately.

## Step 15 — `CLIENT_NEW` workflow *(BUILT 2026-09-10)*

```
intake → validate → create client → E6 v1
      → E1 Pass A → normalization → E7 → E1 Pass B
      → E2 → E3 → E6 v2 → review queue → E5 → save
```

E4 is not required before response data exists.

**Built.** `scripts/client_new.py`, and it stops at the review queue —
Engine 5 is not part of it. Hard rule 9: gates release, not analysis, so
an open HOLD does not stop the pipeline and nothing client-facing is
drafted. It is a fixed sequence rather than a routing loop (phase 5 is the
one that routes), so `NEXT_ENGINE` gates but never chooses; a new client
always needs E1, E2 and E3.

**Acceptance:** `test_client_new.py` — the phase 4 sequence in order on one
prompt hash; E4 and E5 never run and no communication row is written; an
open HOLD does not stop the analysis; a failed engine stops the pipeline
before anything downstream and queues no review; history is appended, never
overwritten; a sparse intake still reaches the queue; the same submission
cannot initialize a second case; one routing hop is spent, not one per
engine.

## Step 16 — Knowledge Factory K02–K11 *(K07 + K08 BUILT 2026-09-10)*

Discovery (PubMed, RSS, web), ingestion, normalizer, claim extraction,
evidence analysis, strategy synthesis with dedup.

**Build the pipe before the taps.** K07 (inbox) and K08 (normalizer) come
first because they are the one path into the library that depends on no
external service, no API key and no scraping — the practitioner hands over
a file. Discovery (K02–K06) adds more input to the same pipe; it does not
change its shape, and building it first would mean building the taps over a
drain that had never been tested.

**K07 + K08 BUILT.** `scripts/knowledge_ingest.py`, and **no model is
called** — both stages are deterministic, so the whole ingest path is
testable with no provider, no key and no cost, and a failure in it is a bug
in that file rather than something a model said.

```
knowledge/inbox/                     the drop zone
knowledge/raw/<hh>/<sha256>.<ext>    the untouched original, content-addressed
knowledge/processed/<name>.receipt.json
knowledge/failed/<name>.receipt.json
```

Originals are **moved, never deleted**: into a content-addressed immutable
store, with an A9 receipt saying what happened — received, hashed,
duplicate or new, normalized or failed. Duplicate content is DEDUPED
against its first envelope and nothing is extracted twice (§57). Rights are
carried through to `excerpt_only` and the item's access note (§52). Chunks
carry the **heading path**, so a claim extracted later can be pointed back
at a place in its source (§16, §42).

A `.pdf`, `.docx` or `.epub` is stored, preserved and marked **FAILED with
the extractor it needs named** — never guessed at. That is what §K05/§K06
say about transcripts, applied to documents: mark the status rather than
inventing content.

Routing is registry-driven end to end (D19, §47, hard rule 13): an
unregistered `source_kind` lands in the protected `OTHER` and the receipt
says so, and registering it afterwards is a single `INSERT` with no code
change — proven by a test that does exactly that. Migration `017` moved the
kind→`source_type` mapping onto `source_kinds` for the same reason: the
first draft of the normalizer worked it out with a CASE expression, which
would have made adding a kind an INSERT *and* a code change.

**Embeddings settled before anything embeddable was written (D34).** 1536
from `gemini-embedding-2`, enforced by migration `018`: provenance columns
on all five vector tables, a unit-norm check on write, and one model pinned
per column. `EMBEDDING_DIM`'s three unchecked copies are gone —
`embedding_dim()` reads the catalog.

**K09 BUILT.** `scripts/knowledge_extract.py` runs E7 in INBOX mode over a
normalized envelope's chunks and writes §39 Claim Cards, then normalizes
the concepts those claims mention through the same tiers as any other
phrase, then records a §54 delta analysis derived from what was **written**
rather than from the model's own counts (D35).

The claims arrive as strict JSON in a single `CLAIMS_JSON` field of
`<RESEARCH_PRACTICE_CLAIMS>` (§R11, added by the build because §R10 carries
the information *gain* and deliberately not the claims). That format was
chosen because `parse_handoff_block` already handles continuation lines, so
K09 required **no change to frozen step 11** and none to either parity
suite.

Boundaries, all asserted: no evidence record, no strategy, no
`POTENTIAL_NEW_STRATEGY` verdict, `discovery_only` provenance (D10), and a
held-out source is `SKIPPED` rather than extracted (A3).

**K10 BUILT.** `scripts/knowledge_research.py`, E7 in the new `EVIDENCE`
mode (§R12). Triage is deterministic and written down — `SAFETY` and
`INTERVENTION_EFFECT` only — because "do not deep-research trivial claims"
is a budget decision that must be visible rather than left to a model's
sense of importance. The source's own citation is **not** the input (D10,
D36), evidence never links to the discovery envelope, and a study with no
retrievable identifier gets no `source_items` row rather than an invented
one. Finding nothing is recorded as a finding, so a claim cannot loop.

**K11 BUILT.** `scripts/knowledge_synthesize.py`, E7 in the new `SYNTHESIS`
mode (§R13). Candidates are found **deterministically before the call** —
concept overlap, then `pg_trgm` name similarity — which is the cost curve
this step's note warns about. `CREATE` from the model is a proposal:
every one is re-checked against the live library and a collision is
converted to an `UPDATE`. Four decisions, never a fifth. Everything created
is `AI_DISCOVERED_CANDIDATE`; a `MERGE`'s rationale becomes the provenance
note `ck_provenance_required` demands. A strategy with no canonical
concepts becomes an OPEN gap rather than being linked to `PROPOSED`
concepts (D8).

**Next in this step:** discovery — K02 PubMed, K03 web, K04 RSS, K05/K06
transcripts. They add input to the pipe that now exists end to end. **Do
not begin mass ingestion** until one real source has run the whole loop.

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

## Step 24 — Backup drill *(drill performed 2026-09-10)*

`scripts/backup.sh` on cron, then **restore into a scratch database and
verify**. An untested backup is not a backup.

Performed 2026-09-10 and it earned itself immediately: the dump contained
no roles, so restoring onto a fresh machine produced a database with all
the data and none of the access controls (52 policies and 246 grants
failed). `backup.sh` now dumps roles alongside the database, and the
restore procedure in `docs/OPERATIONS.md` applies them first.

Verification is the suite, not row counts: **every suite** must pass
against the restored database (eleven at the time of writing; run
`testing/run_all.sh` rather than counting). Encoding must match UTF8 — `migrate.py`
refuses otherwise.

**Still unproven:** the script has never run on the VPS under cron with
GPG encryption and an off-site target configured.

---

## Order summary

```
1–9   done: VPS, migrations 000–005, contract, RUN_ENGINE
9b    done: 006 knowledge inbox schema
9c    done: 007 coverage dimensions, gap governance, provenance registry
10    done: seven canonical prompts + foundation domain seed
10b   DONE: measured live. 19/19 parts both passes, no degradation,
      $0.386/cycle. D5 stands — do not stage Engine 1.
11    n8n RUN_ENGINE subworkflow         <- BUILT 2026-09-10, byte-identical
                                         parity proven (D26)
12/13 K1 ontology seed  ||  C3 normalization layer
                                         <- BOTH BUILT 2026-09-10
14    Core Intake V1                     <- BUILT (009, 011, D22)
15    CLIENT_NEW workflow                <- BUILT 2026-09-10
16    Knowledge Factory K02–K11
17    K14 embedding and hybrid retrieval
18    evaluation layers A–E
19    K12/K13 controversy, negative knowledge, gaps
20    E2, E3, review queue, E5
21    CLIENT_FOLLOWUP and E4
22    Wave-1 foundation build
23    practice intelligence
24    backup restore drill               <- DONE 2026-09-10 (roles gap found)
```

`bash testing/run_all.sh` must pass before every commit. Sixteen suites.

**This layer is frozen.** Do not reopen D16–D21 without instruction.
