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
- `006_knowledge_inbox.sql` — Engine 7 §44–§57 and §25–§26 foundations:
  `source_kinds` (a **registry table, not an enum**, so a new source type is
  an INSERT rather than a migration), `source_envelopes`,
  `source_delta_analyses`, `envelope_derived_records`,
  `medication_knowledge`, `medication_aliases`, `drug_nutrient_claims`.
  Views: `v_ingestion_status` (the practitioner's ingestion receipt),
  `v_client_safe_sources`, `v_engine_run_clock`. Adds
  `ck_run_clock_coherent` to `engine_runs`.
- `007_coverage_and_provenance.sql` — three corrections made while the
  library still holds foundation data. `coverage_dimension` now carries
  exactly the **18** questions recovered from Engine 7 §35, with
  `MEASUREMENT` → `EFFECT_MAGNITUDE` and `NUTRITION_STRATEGIES` →
  `ALTERNATIVE_STRATEGIES`, and `KNOWLEDGE_GAPS` removed. Gap governance
  modelled separately: `gap_severity`, `knowledge_gaps.severity`,
  `domain_gap_assessments`. `v_domain_readiness` rebuilt. Provenance edges
  bound to a new `knowledge_entities` registry.
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
- All 8 migrations apply cleanly from an empty database; re-run is a no-op
- Seven suites pass: concept layer, knowledge layer, client layer,
  RUN_ENGINE, case events, **59/59** knowledge inbox, **78/78** prompt
  contracts. Verified passing **three consecutive times** from empty, and
  again after a full server stop/start.
- All suites idempotent and re-runnable against a used database.
- State survives a full server stop/start
- Degradation path proven: applies on a build with **no pg_trgm and no
  btree_gin**, capability registry records the absence, trigram indexes
  skipped, schema still functional
- 70 tables, 15 views, 48 enums, 183 indexes, 44 check constraints,
  38 triggers, 26 RLS-protected tables, 52 policies

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
11. **U+0002 control character standing in for a hyphen** in 7 places
    across 5 recovered prompts (`food-related`, `CLIENT-SPECIFIC`,
    `DIAGNOSIS-ONLY`, `health-education`, `nutrient-delivery`). Found by an
    automated scan of all seven sources, mapped at the cleaning stage.
12. **Engines 2-7 control sections omitted the literal `<CONTROL_BLOCK>`
    tag.** They described the fields but never showed the tag RUN_ENGINE
    parses — every run would have dead-lettered. Caught by an assembly check.
13. **`test_run_engine` asserted `prompts/` was empty.** Correct while the
    prompts were missing, wrong the moment they landed. Rewritten to test
    the refusal-to-stub behaviour against a temp directory, plus a new check
    that all seven canonical prompts load, hash distinctly, and specify the
    control block tag.
14. **Tests were not re-runnable.** Synthetic fixtures collided on
   `uq_client_external` on second run. Suites now clear their own fixtures
   first, so verification works against a used database.
15. **§70A swallowed into a retained section during the Engine 7 merge.**
    The section-extraction regex `^## (\d+)\. ` does not match `## 70A.`,
    so the older control-block specification was carried inside the §67
    block and the prompt shipped with **two** control contracts. Found by
    the client reading the file, which is the wrong way to find it.
    `test_prompt_contracts.py` now asserts exactly one control-block
    specification and one tag pair per prompt, for all seven.
16. **Prompt claimed 19 coverage dimensions while listing 18.** *(Partly
    superseded by 19 and 20 below — the first fix kept KNOWLEDGE_GAPS as a
    dimension, which was itself wrong.)* Checked
    against the original OCR (`knowledge.pdf` p.44-45) rather than guessed:
    **the source has 18 questions.** The 19th, `KNOWLEDGE_GAPS`, was added
    by the build. §R2a now maps all 18 recovered questions to enum values
    and names `KNOWLEDGE_GAPS` as build-added; two mappings are marked
    build-assigned rather than recovered. A test binds prompt to enum in
    both directions.
17. **`v_ingestion_status` picked a non-deterministic "latest" delta.**
    `now()` is transaction-scoped in Postgres, so two reprocessing rows
    written in one transaction share `analysed_at` and ordering was
    arbitrary. Added `analysis_seq bigserial`. Caught by test.
18. **`test_case_events.py` connected as the wrong role, in two places.**
    It built the runtime and practitioner DSNs by string-replacing
    `postgresql://postgres`. Per `docs/OPERATIONS.md` the admin role is
    `phi_admin`, so on the real VPS that replacement does nothing and both
    connections silently fall back to **admin** - meaning "practitioner
    role is read-only" and "practitioner sees across clients" were passing
    against a superuser. Replaced with a `_with_user()` helper verified
    across four DSN forms. This would have hidden a genuine RLS regression
    in production.
19. **`KNOWLEDGE_GAPS` was misclassified as a coverage dimension.** It is
    useful, but it asks a readiness question about the library rather than
    a question about a domain's content — and the prompt drew the wrong
    conclusion from it: *"recording zero gaps is a claim that the domain is
    finished."* A domain can honestly report no critical gaps currently
    identified while science keeps moving. Gap governance now lives in
    `domain_gap_assessments` and `knowledge_gaps.severity`, and
    `foundation_ready` requires a gap assessment **performed** with no open
    CRITICAL gap — never zero gaps.
20. **Two coverage mappings were semantic shortcuts.** `MEASUREMENT` was
    carrying "how large might the effects be", which is effect magnitude,
    not measurement; `NUTRITION_STRATEGIES` was carrying "what alternatives
    exist", which spans food, exercise, supplement, behaviour and
    implementation. Renamed to `EFFECT_MAGNITUDE` and
    `ALTERNATIVE_STRATEGIES` while the database still held foundation data
    rather than years of records. The `†` build-assigned markers are gone
    because nothing is build-assigned any more.
21. **Provenance edges could point at nothing.** `envelope_derived_records`
    took a bare UUID with no target, so an edge could name a claim that did
    not exist and Postgres would accept it — in the one table whose entire
    purpose is provenance. Fixed with a `knowledge_entities` registry
    maintained by trigger across all nine derived kinds, and a **composite**
    FK on `(derived_id, derived_kind)` so an edge also cannot mislabel an
    entity's kind. Extensibility is intact: a new derived kind adds an enum
    value and a registration trigger, not a foreign key.

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
Both tracks run in parallel. The prompts and `006` are done, so nothing
below is blocked on schema.

**Case track — C1/C2 completion.** Replace the fixture provider on E6 and
E1 once `LLM_API_KEY` is set. Then C3, the normalization layer:
`NORMALIZATION_PHRASES` from Pass A resolved through deterministic alias ->
structured -> trigram -> semantic -> LLM, writing confirmed aliases back so
a phrase never costs a second call.

**Knowledge track — K1, the ontology seed.** Seed the concept dictionary
across the core Wave-1 areas before large-scale extraction, expanded one
level into physiology, drivers, biomarkers and outcomes, with sibling-
derived `CONFUSABLE_DO_NOT_MERGE` pairs generated from structure. **K1 now
loads `knowledge/seed/foundation_domains.md`** as its curriculum input -
26 domains, A to Z, recovered verbatim.

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

## Canonical prompts installed
All seven in `prompts/`, ~44,800 words total. Each is: **original recovered
specification unchanged** + **Addendum A** (runtime architecture, clearly
marked) + **engine-specific control block contract**.

| file | words | tokens~ | sha256 |
|---|---|---|---|
| engine1_prevention.md | 6,839 | 9,118 | `33d857c2dd6f` |
| engine2_behaviour.md | 5,765 | 7,686 | `44d08f2fbfee` |
| engine3_nutrition.md | 5,019 | 6,692 | `25b1b063e076` |
| engine4_progress.md | 5,629 | 7,505 | `0a708a8ebc49` |
| engine5_communication.md | 4,503 | 6,004 | `2acc29e0c5fe` |
| engine6_memory.md | 5,570 | 7,426 | `bcc6bbb65a09` |
| engine7_research_practice.md | 11,481 | 15,304 | `c1276c136368` |

Verified: every original section present, original handoff blocks intact
(E1 retains all 57 fields), exactly one control block specification per
file, zero non-printing characters, seven distinct hashes. Two-pass hash
identity confirmed with the real E1 prompt.

### Engine 7 revision — client's Final Master Prompt merged
The client supplied a **full replacement** master prompt (87 sections,
7,679 words) - a rewrite, not an addition, and longer than the original.
It expands philosophy and acquisition architecture; it drops runtime detail
the build depends on. Merged rather than swapped:

- **Addendum A** (A1-A8) - runtime architecture, including the
  `CASE_VERSION = 0` knowledge-clock rule.
- **Part I §1-§87** - the client's specification, verbatim. Asserted: every
  non-heading line present unaltered.
- **Part II §R1-§R3** - retained operating detail (foundation build
  process, coverage test, case retrieval process).
- **Part III §R4-§R9 + §88** - self-audits, human-readable outputs, both
  machine handoff blocks, and the single authoritative control contract.
  The client's §78-§82 describe handoff *content* in prose but carry **no
  XML tags**; without §R8/§R9 nothing would reach Engines 1-4.
- **Appendix D** - pointer only. The A-Z curriculum moved verbatim to
  `knowledge/seed/foundation_domains.md` (body sha256 `eba68ddadf9a`),
  loaded for K1 seeding, domain mapping and foundation research, not on
  CASE, INBOX or routine UPDATE runs. Cut E7 from ~26.7k to ~22.7k tokens
  with nothing deleted; the seed file's hash is asserted by test.

New capability the client's revision adds, now backed by `006`: the
permanent Knowledge Inbox (§44-§55), the generic source envelope (§46),
extensible source kinds (§48), acquisition adapters (§49, §75),
delta/newness analysis (§54), medication intelligence (§25-§26), rights and
access context (§52), and reprocessing/versioning (§56).

**Cost (prompt side, 8-call new-client cycle = 68,437 tokens):**
Sonnet 5 $0.137 uncached / $0.014 cached. Caching matters: E1 and E6 each
load twice per cycle.

## Awaiting input
`LLM_API_KEY` and provider base URL. Everything around the integration is
built and tested against the fixture provider.

Two Engine 7 items for the practitioner, neither blocking:
- Proofread clinical passages carrying a number, dose, threshold or marker
  name. E1 §20, §26, §27 and §42 are the highest-value checks. The OCR is
  structurally clean; that does not make a value correct.
- The two previously build-assigned coverage mappings are **resolved**:
  `EFFECT_MAGNITUDE` and `ALTERNATIVE_STRATEGIES` now say what the recovered
  questions ask. Nothing in the mapping is build-invented any more.

## Known gaps
- n8n workflows not yet built (M2)
- n8n subworkflow JSON not yet exported; `scripts/run_engine.py` is the
  reference implementation and both must be validated by the same suite so
  behaviour cannot drift
- Deterministic flag rule set not yet written; `case_flags` and the gate
  work, but the SQL rules that populate HOLD/NOTE are still to come and
  must start narrow
- `006` is schema only. No inbox UI, no ingestion pipeline, no acquisition
  adapters. It exists so those can be built without a retrofit.
- **Restore drill still not performed.** Single most likely way to lose
  this project; about ten minutes.
- `EMBEDDING_DIM` is hard-coded to 1536 in `002_concepts.sql`; changing it
  needs a migration and a full re-embed
- `norm_phrase` backs STORED generated columns; changing it later requires
  a migration that also rewrites those columns and rebuilds their indexes
