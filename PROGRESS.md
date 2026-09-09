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

### Step 10b — synthetic client and call measurement `COMPLETE (fixture)`
Everything in step 10b that does not need credentials.

- `docker-compose.local.yml` + `.env.local.example` +
  `scripts/local_db_setup.sh` / `.ps1` — a throwaway local PostgreSQL 16 +
  pgvector for development and testing. A **separate stack**, not an
  override: `docker-compose.yml` is untouched and the VPS deployment is
  still exactly what `docs/OPERATIONS.md` describes. Rationale and the
  full comparison in `docs/LOCAL_DEV.md`.
- `testing/fixtures/synthetic_client.py` — a synthetic vegetarian Gujarati
  woman, 42, with PCOS + MASLD (grade 2) + prediabetes + atherogenic
  dyslipidaemia + subclinical hypothyroidism. 31 labs, 13 measurements,
  12 symptoms, 9 conditions, 4 medications, 2 supplements, 3 days of food
  log written the way a client reports it, plus imaging, weight history,
  sleep, movement, pain, stress, behaviour, household constraints and
  medical-coordination context. `PART_INPUTS` maps each of the **19 parts
  of Engine 1 §62** to the intake keys it reads; the suite asserts the map
  rather than assuming coverage. The medication set — metformin,
  atorvastatin, telmisartan, levothyroxine — is deliberately the ordinary
  medicated metabolic client **D6 requires to pass the gate clean**.
- `scripts/measure_engine1.py` — runs E6 → E1 Pass A → E7 → E1 Pass B and
  reports, per call, prompt tokens, completion tokens, cost, latency,
  retries and control-block parse success, read out of `cost_events`. It
  names no provider and no model: `select_provider()` already switches on
  `LLM_API_KEY`, and the runner just uses it. `--report-only` and `--json`
  as well.
- `008_call_measurement.sql` — `cost_events.run_id` (attribution),
  `cost_events.price_source` with `ck_cost_priced`, and
  `v_engine_call_measurement`.
- `config/model_prices.json` + `scripts/pricing.py` — a price **registry**,
  keyed by model name, matched exactly then by longest prefix so a dated
  snapshot resolves to its family. Adding a model's rate is a data edit.

Proven end to end on the fixture provider:

```
E6 → E1 Pass A → E7 → E1 Pass B     4 calls, 0 retries, 0 dead letters
both E1 passes on one prompt hash   33d857c2dd6f, engine1_prevention.md
control block parsed                on every call
```

**Token counts under the fixture provider are character estimates and the
report says so on every run.** Latency, attempt counts, retries and parse
success are real. D5 asked for a measurement of the Engine 1 call; only a
live provider can supply one.

### Verification
Ran against live PostgreSQL 16, not inspected by eye.
`bash testing/run_all.sh` rebuilds and verifies everything.

`.github/workflows/tests.yml` runs it on every pull request and every push
to `main`, in two jobs: **`suites`** on `pgvector/pgvector:pg16` (the
deployment image, every extension expected present) and **`degraded`** on
plain `postgres:16` (pgvector absent, and asserted absent so the job cannot
quietly stop testing the D15 path). Both set the role passwords through
`scripts/set_role_passwords.py` and run the full suite; `suites` also
re-runs it against the used database, asserts the migration re-run is a
no-op, and runs the measurement. No API key in CI, so `run_engine.py` stays
on the fixture provider: nothing spends and nothing depends on a provider
being up.

The runtime role password in CI deliberately contains a quote and a
semicolon, so a regression to interpolating it into a shell `psql -c` fails
the run.
- All 9 migrations apply cleanly from an empty database; re-run is a no-op
- **Eight** suites pass: concept layer, knowledge layer, client layer,
  RUN_ENGINE, case events, **59/59** knowledge inbox, **78/78** prompt
  contracts, and step 10b measurement. Verified passing **three
  consecutive times** from empty, each followed by a re-run against the
  used database, and again after a full server stop/start.
- All suites idempotent and re-runnable against a used database.
- State survives a full server stop/start
- Degradation path proven: applies on a build with **no pg_trgm and no
  btree_gin**, capability registry records the absence, trigram indexes
  skipped, schema still functional
- 70 tables, 16 views, 49 enums, 26 RLS-protected tables, 52 policies
- Verified with the three roles **password-authenticated**, not on trust:
  `phi_runtime` and `phi_practitioner` connect as themselves, and each
  connection asserts its own `current_user`

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

22. **The RLS suite could not authenticate as the roles it tests.**
    `test_case_events.py` builds the `phi_runtime` and `phi_practitioner`
    DSNs from `DATABASE_URL` with `_with_user()`, which correctly drops the
    admin password and then supplied none. On any server that asks for a
    password — which is every server configured the way
    `docs/OPERATIONS.md` describes — the suite died with
    `fe_sendauth: no password supplied` before reaching a single isolation
    assertion. Fix 18 corrected the role *name* in these DSNs and left the
    credential gap, which is invisible on a trust/peer development setup
    and fatal on the VPS. Roles are created without a password by migration
    005 and given one by `ALTER ROLE` afterwards, so the password is not in
    `DATABASE_URL`: `_with_user()` now takes it from
    `POSTGRES_RUNTIME_PASSWORD` / `POSTGRES_PRACTITIONER_PASSWORD`,
    percent-encoded, and never falls back to the admin password. Found the
    first time the suites ran against a password-authenticated database.
23. **Nothing asserted which role the isolation tests ran as.** The suite
    checked `rolsuper` and `rolbypassrls` in `pg_roles` but never
    `current_user` on the connection, so a regression in DSN rewriting
    would have been diagnosed as an RLS failure rather than a connection
    failure. Both connections now assert their own identity, and
    `_with_user()` is asserted directly across four DSN forms including a
    password containing `@ : / #`.
24. **Cost events could not be attributed to a run.** `cost_events`
    carried `entity_id = client_id`, so the two Engine 1 calls in a cycle —
    Pass A and Pass B, which share a client, a cycle *and* a prompt hash —
    were indistinguishable in the cost table. Those are exactly the two
    calls D5 asks to measure, so step 10b could not have reported them.
    Fixed by `cost_events.run_id` in migration 008, added alongside
    `entity_id` rather than replacing it: repurposing `entity_id` would
    have traded the client attribution for the run attribution.
25. **`cost_events.cost_usd` had never been written and had no provenance
    rule.** Once something writes to it, an unknown price must not become
    a zero — a zero reads as "this call was free" and silently corrupts
    every total built on top of it. Added `price_source` with
    `ck_cost_priced`, which rejects `UNPRICED` paired with a cost, and a
    price *registry* so adding a model's rate is a data edit.
26. **`engine_runs.input_tokens`, `output_tokens` and `duration_ms` were
    never populated.** They have existed since 004; RUN_ENGINE recorded
    per-attempt cost events and left the per-run totals NULL. Now written
    on both terminal paths, success and dead-letter.
27. **The fixture provider's token estimate ignored the client payload.**
    It returned `len(system_prompt) // 4`, counting the prompt file and
    none of the structured input — the half that varies per case, and the
    half the D5 call-size question is actually about. Now covers the whole
    request. Still an estimate, and the measurement report says so.
28. **A new view would have been an RLS bypass.** Migration 005 sets
    `security_invoker = true` on every view precisely so a view cannot
    become one; `v_engine_call_measurement` joins `engine_runs` and
    `engine_outputs`, both row-level secured, and is owned by `phi_admin`.
    Caught before 008 was committed, and now asserted by test so the next
    view cannot repeat it.

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

`python3 scripts/measure_engine1.py` reports the whole cycle out of
`cost_events` — per call: prompt tokens, completion tokens, cost, latency,
retries, control-block parse success, and the prompt hash of each E1 pass.
A repair retry shows as two provider attempts and one retry, with the
failed attempt's tokens included in the run total.

## Next task

**Immediately, and it needs nothing from the build: the live measurement
run.** Put `LLM_BASE_URL`, `LLM_API_KEY` and the five `MODEL_*` roles in
`.env`, add the provider's rates to `config/model_prices.json`, then

```
python3 scripts/measure_engine1.py
```

`run_engine.py` switches provider on its own. That produces the real token
counts D5 deferred — and it is the only way to answer whether Engine 1's
later sections degrade across a 19-part report. Do not restructure Engine 1
before that number exists.

Both build tracks run in parallel. The prompts and `006` are done, so
nothing below is blocked on schema.

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

## Live measurement attempt — 2026-09-09 `BLOCKED (provider quota)`

First run of `scripts/measure_engine1.py` against a real provider
(OpenAI-compatible Gemini endpoint). **The measurement did not complete.**
Engine 1 Pass A never returned, so D5 is still open: there is no live
Engine 1 call size on record and nothing here should be quoted as one.

What the provider actually returned, live, on the synthetic client:

| call | model | prompt | completion | latency | cost |
|---|---|---|---|---|---|
| E6 | gemini-3.8-flash | 18,912 | 11,132 | 38.5 s | $0.055929 |
| E6 | gemini-3.7-flash | 18,911 | 10,254 | 35.2 s | unpriced |
| E1 prompt alone, no payload | gemini-3.8-flash | 12,136 | — | 2.4 s | — |

E6 is a real measurement and is close to E1 in prompt size (39,903 vs
49,144 chars), so the order of magnitude for an engine call is now known:
**~19k prompt tokens, ~10k completion, ~35 s**. That is a bound, not the
D5 number.

**Why it is blocked.** The key is on the Gemini **free tier**: 20 requests
per day per project per model
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Large requests are
also refused during demand spikes with a 503 — *"This model is currently
experiencing high demand"* — which is provider capacity, not payload size:
a 40 KB request succeeded in 4 s minutes earlier, and the full Engine 1
prompt alone returned fine. A 14.5-minute run with a 12-attempt backoff
budget still could not land Pass A, on either `gemini-3.8-flash` or
`gemini-3.7-flash`. Completing this needs a billed key, or a quiet quota
window; nothing in the repo is at fault.

Also observed, and correct: `gemini-3.7-flash` has no rate in
`config/model_prices.json`, so its cost reported `unpriced` rather than 0.
`ck_cost_priced` did its job.

### Fixed while running it
- **`run_engine.py` had no backoff and one shared attempt budget.** A
  transport failure fell through the same `MAX_ATTEMPTS` loop as an invalid
  control block and retried instantly, so three attempts burned in ~26 s
  and a live run died on a transient that seconds of waiting would clear.
  Transport failures now have their own budget
  (`LLM_TRANSPORT_MAX_ATTEMPTS`, default 6) with capped, jittered
  exponential backoff and `Retry-After` honoured, and they no longer
  consume the repair retries that exist for schema violations. Retryable is
  an explicit status set; a 400 or 401 is never retried, because a retry
  loop that fires on unknown errors is how a bad request becomes a bill.
  Every **physical** attempt is still costed in `cost_events` — a retry
  invisible in the cost table understates what a call costs.
- **A provider failure was dead-lettered as `SCHEMA_INVALID`.** A 503 is
  not a malformed control block. It now records `PROVIDER_ERROR`.
- **`measure_engine1.py` reported a one-pass run as `FORK DETECTED`.** A
  fork is two passes with different hashes, which is what D4 and
  `trg_enforce_two_pass` exist to catch. A run where Pass B never happened
  is incomplete, and calling it a fork sends the reader hunting an
  architectural violation that is not there. It now says `INCOMPLETE`.

Seven new checks in `testing/test_run_engine.py` cover the retry split:
a transient is waited out, a transient does not spend a repair attempt, a
400 is never retried, transport retries stay bounded, a provider failure is
not recorded as a schema violation, and every failed physical attempt is
costed.

## Awaiting input
`LLM_API_KEY` and the base URL are now **supplied and working** — the live
provider path is proven end to end, and E6 has completed against it. What
is still needed to finish D5 is a key **with quota for more than a handful
of large calls**: the free tier allows 20 requests per day per model and
sheds large requests during demand spikes, which is what stopped the run
above. `MODEL_ANALYSIS` and `MODEL_RESEARCH` are set; the other three roles
are still unassigned and are needed as their engines come online.

Until a rate is configured the cost column reports `unpriced`, not zero.

Two Engine 7 items for the practitioner, neither blocking:
- Proofread clinical passages carrying a number, dose, threshold or marker
  name. E1 §20, §26, §27 and §42 are the highest-value checks. The OCR is
  structurally clean; that does not make a value correct.
- The two previously build-assigned coverage mappings are **resolved**:
  `EFFECT_MAGNITUDE` and `ALTERNATIVE_STRATEGIES` now say what the recovered
  questions ask. Nothing in the mapping is build-invented any more.

## Known gaps
- **`STRIP_IDENTITY_FROM_ENGINE_PAYLOADS` is documented and not enforced.**
  Nothing in `run_engine.py` reads it; the payload is whatever the caller
  passes. The synthetic client builds an identity-free payload and asserts
  it, so the step 10b path is clean, but the intake pipeline (step 14) must
  either strip at the source or RUN_ENGINE must enforce it. Given the
  data-residency position in `docs/OPERATIONS.md`, enforcement in
  RUN_ENGINE is the safer place.
- Fixture-mode token counts are character estimates, not measurements. The
  report says so on every run; do not quote them as call sizes.
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
