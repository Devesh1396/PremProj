# PROGRESS

## Completed

### M0 — Foundations
- Repo scaffold per master specification
- `docker-compose.yml`: Postgres 16 + pgvector, n8n. Both persisted.
  Ports bound to `127.0.0.1` only (this database holds PHI).
  n8n stores its own state in the same Postgres, separate schema, so one
  backup covers everything. Success-execution payloads not retained.
- `.env.example` with model-role abstraction. No model name is hard-coded
  anywhere in the repo.
- `scripts/migrate.py`: ordered, once-only, per-migration transaction,
  checksum guard against edited history. **Verified rejecting an edit.**

### M1 — Schema `COMPLETE`
- `000_extensions.sql` — capability registry. Every extension optional.
  `gen_random_uuid()` is core PG13+, so pgcrypto is not a dependency.
  `norm_phrase()` deterministic normalizer.
- `001_ops.sql` — `cost_events`, `job_runs`, `dead_letter_jobs`,
  `v_cost_by_operation`. Cost instrumented from batch one.
- `002_concepts.sql` — the concept layer:
  `concepts`, `concept_aliases`, `concept_relations` (incl.
  `CONFUSABLE_DO_NOT_MERGE`, auto-mirrored), `concept_proposals`,
  `normalization_cache`, `normalization_tests`, plus
  `v_active_concepts`, `v_concept_escalation_queue`, `v_confusable_pairs`.
- `003_knowledge.sql` — the knowledge library: domains with 19 tracked
  coverage dimensions, source creators / sources / items / documents /
  chunks, claims, evidence, strategies, `strategy_concepts` (the retrieval
  spine joining strategies to the 002 ontology), implementation patterns,
  controversies, negative knowledge, foods, seasonality, supplements, gaps,
  `knowledge_updates`, `practice_strategy_outcomes`. Views:
  `v_domain_readiness`, `v_knowledge_floors`, `v_provenance_audit`,
  `v_quality_issues`.
- `004_client.sql` — clients, `client_case_versions` (Engine 6 canonical
  state, one current row enforced by partial unique index), `case_cycles`
  with routing-depth bound, measurements, labs, conditions, symptoms,
  medications, supplements, food logs, interventions, exposure, targets,
  follow-ups, `engine_runs` (prompt file + SHA-256 hash + model + params),
  `engine_outputs` (human / structured / control split), `case_flags`,
  `practitioner_reviews`, `client_communications`. Functions:
  `get_current_client_state()`, `get_client_timeline()`. Views:
  `v_review_queue`, `v_engine_run_health`.

### M2 — Engine execution layer `COMPLETE`
- `schemas/orchestration/control_contract.v1.json` — strict JSON Schema for
  the control-flow subset only. Typed enums for `ROUTING_RECOMMENDATION`,
  `CURRENT_DECISION`, `NEXT_ENGINE`, `PRIMARY_FAILURE_TYPE`, plus
  conditional rules: routing needs a reason, live research needs a prior
  insufficiency finding, a FAILED run needs an error state. Report
  formatting and deep extraction remain deferred.
- `scripts/run_engine.py` — the single engine execution path. Loads and
  hashes the prompt, builds the request, calls the provider, extracts and
  validates the control block, retries once with a repair prompt, dead-
  letters after bounded retries, records run + outputs + cost. Written
  once; no per-engine copy.
- Fixture provider mode so orchestration is fully testable with no API key,
  per the master specification's guidance on missing credentials. Live
  OpenAI-compatible provider selected automatically once `LLM_API_KEY` is
  set.

### Verification
Ran against live PostgreSQL 16, not inspected by eye.
`bash testing/run_all.sh` rebuilds and verifies everything.
- All 5 migrations apply cleanly from an empty database; re-run is a no-op
- **24/24** concept layer, **28/28** knowledge layer, **26/26** client
  layer, **27/27** RUN_ENGINE. All suites idempotent and re-runnable.
- State survives a full server stop/start
- Degradation path proven: applies on a build with **no pg_trgm and no
  btree_gin**, capability registry records the absence, trigram indexes
  skipped, schema still functional
- 54 tables, 10 views, 32 enums, 139 indexes, 25 check constraints,
  10 triggers

### The cross-condition test that matters
A vegetarian client with PCOS + MASLD + prediabetes + high triglycerides +
low muscle activity:
- **diagnosis-only retrieval → 1 strategy** (what a disease-folder library
  returns)
- **concept-based retrieval → 3 strategies**, including progressive
  resistance training, which is indicated only for PCOS in the data but is
  reached for the MASLD case through `SKELETAL_MUSCLE_GLUCOSE_DISPOSAL` and
  `INSULIN_SENSITIVITY`

That gap is the entire value of the concept layer, and it is now asserted
by a test rather than assumed.

## Bugs found and fixed during build
1. **`norm_phrase` trailing whitespace.** Trimming before punctuation
   stripping left a trailing space on any phrase ending in punctuation
   ("post-meal glucose excursion!!"), silently breaking exact-match alias
   lookup and pushing the phrase to LLM resolution. Reordered to strip →
   collapse → trim. Caught by test, not by reading.
2. **pgcrypto assumed unnecessarily.** `gen_random_uuid()` has been core
   since PG13. Dependency removed.
3. **Extensions hard-failed the migration.** Rewritten so each is
   attempted, recorded in `system_capabilities`, and branched on. This is
   what makes "must function without pgvector" true rather than aspirational.
4. **Enum arrays returned as unparsed strings.** `v_domain_readiness`
   returned `missing_dimensions` as a raw literal because drivers do not
   know custom enum types. n8n would have hit the same thing. Cast to
   `text[]` in the view.
5. **`cost_events.entity_id` type mismatch.** RUN_ENGINE passed a raw UUID
   into a deliberately polymorphic `text` column. Inserts succeeded via
   assignment cast, then every `entity_id = $1` comparison failed with
   "operator does not exist: text = uuid". Cost telemetry would have been
   written but unqueryable. Callers now stringify at the source.
10. **Tests were not re-runnable.** Synthetic fixtures collided on
   `uq_client_external` on second run. Suites now clear their own fixtures
   first, so verification works against a used database.

## The E1 two-pass rule is enforced, not documented
`trg_enforce_two_pass` rejects an insert where Pass A and Pass B in the
same cycle carry different prompt hashes:

```
E1 pass B uses prompt engine1_pass_b_lite.md (hash 4f2a...) but the other
pass in this cycle used engine1_prevention.md (hash 9c81...). Pass A and
Pass B must run the identical master Engine 1 specification.
```

A fork of Engine 1 is a failed insert, not a silent drift. RUN_ENGINE also
raises `PromptMissing` rather than falling back to a stub: an engine output
that cannot be traced to a specification is worse than no output.

## Enforced structurally, not by prompt
- A strategy past `AI_DISCOVERED_CANDIDATE` cannot exist without provenance
  (`ck_provenance_required`)
- `practice_strategy_outcomes` has **no** foreign key to `evidence_records`
  and no view joins them, so internal practice experience cannot be
  presented as trial evidence
- Practice aggregates below 5 clients are rejected (`ck_min_cohort`)
- A source must declare at least one role; `DISCOVERY` and `EVIDENCE` are
  distinct values, so a podcast cannot be queried as evidence
- Impossible publication years rejected; duplicate DOI, PMID, URL and
  content hash rejected
- Exactly one current case version per client (partial unique index), so
  history is retained on supersede rather than overwritten
- A start date on a `PROPOSED` intervention is rejected: proposed is not
  started. A `STOPPED` intervention may still carry an `IMPROVING` outcome:
  stopped is not failed.
- Client-facing release blocked while a HOLD flag is open
  (`trg_block_unapproved_communication`). Drafting is never blocked;
  internal analysis and practitioner view are never gated; NOTE flags do
  not block.
- An LLM-attributed actor cannot clear a `DETERMINISTIC` flag
  (`trg_protect_deterministic_flags`); it may only add flags
- Routing loop bound per cycle (`ck_loop_bound`)
- Malformed engine output never reaches `engine_outputs`; it dead-letters
  with the raw payload retained

## Working end to end today
On the synthetic vegetarian PCOS + MASLD + prediabetes client, with the
fixture provider:

```
E6 init -> case v1 -> E1 Pass A -> research questions + clinical phrases
        -> E7 case mode -> E1 Pass B -> both passes, one prompt hash
```

Repair retry and dead-lettering both verified: an invalid first response is
repaired on attempt 2; persistently invalid output dead-letters after 3
attempts with no `engine_outputs` row written.

## Next task
Both tracks now start in parallel.

**Case track — C1/C2 completion.** Replace the fixture provider on E6 and
E1 once `LLM_API_KEY` and the canonical prompts are in place. Then C3, the
normalization layer: `NORMALIZATION_PHRASES` from Pass A resolved through
deterministic alias -> structured -> trigram -> semantic -> LLM, writing
confirmed aliases back so a phrase never costs a second call.

**Knowledge track — K1, the ontology seed.** Seed the concept dictionary
across the core Wave-1 areas before large-scale extraction, expanded one
level into physiology, drivers, biomarkers and outcomes, with sibling-
derived `CONFUSABLE_DO_NOT_MERGE` pairs generated from structure.

## Deployment (decided)
Hostinger VPS, **India**. 2 vCPU, 8 GB RAM, 100 GB disk. n8n already
running in Docker; `docker-compose.yml` adds PostgreSQL to the same network
with **no published port**. Full procedure in `docs/OPERATIONS.md`.

- 2 vCPU is the binding constraint, not RAM. Keep
  `KNOWLEDGE_MAX_CONCURRENCY` at 2-3.
- Three DB roles: `phi_admin` (migrations), `phi_runtime` (n8n, RLS
  enforced, default deny), `phi_practitioner` (review, read-only).
- `scripts/backup.sh` written; **restore drill not yet performed**.
- Provider: Gemini first via OpenAI-compatible endpoint. Model roles make
  switching an `.env` edit. Claude rates for comparison: Haiku 4.5 $1/$5,
  Sonnet 5 $2/$10, Opus 5 $5/$25 per MTok; batch -50%, cache read 0.1x.
- **Data residency:** DB and VPS in India, model inference is not.
  `STRIP_IDENTITY_FROM_ENGINE_PAYLOADS=true` — engines get `client_id` and
  clinical facts, never names.

## Awaiting input
The seven canonical prompt files for `prompts/`. RUN_ENGINE refuses to run
without them by design. Test fixtures under `testing/fixtures/prompts/` are
clearly labelled as fixtures and exercise plumbing only.

## Known gaps
- n8n workflows not yet built (M2)
- n8n subworkflow JSON not yet exported; `scripts/run_engine.py` is the
  reference implementation and both must be validated by the same suite so
  behaviour cannot drift
- Canonical prompts not yet supplied (expected separately, verbatim)
- Deterministic flag rule set not yet written; `case_flags` and the gate
  work, but the SQL rules that populate HOLD/NOTE are still to come and
  must start narrow
- `EMBEDDING_DIM` is hard-coded to 1536 in `002_concepts.sql`; changing it
  needs a migration and a full re-embed
- `norm_phrase` backs STORED generated columns; changing it later requires
  a migration that also rewrites those columns and rebuilds their indexes
