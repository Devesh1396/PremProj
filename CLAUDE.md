# CLAUDE.md

Read this first, every session. It is the operating contract for this repo.

---

## What this is

An internal AI-assisted nutrition and functional-health operating system
for **one** Certified Functional Nutritionist. Seven specialist reasoning
engines, a longitudinal client record, and a continuously growing knowledge
library, orchestrated by n8n over PostgreSQL.

It is **not** a diet-plan generator, not a consumer chatbot, and not
multi-tenant SaaS.

The practitioner remains the professional decision-maker. The software
removes **repetitive cognitive labour**, not professional judgment.

You are the builder. You are not part of the runtime. When this is
finished it must keep working on n8n + PostgreSQL + an LLM API alone.

---

## Read these before you build

| File | When |
|---|---|
| `docs/DECISIONS.md` | **Before proposing any structural change.** 36 settled decisions with rationale and rejected alternatives. |
| `docs/MASTER_SPEC.md` | The 40-phase build specification plus amendments. |
| `BUILD_PLAN.md` | Milestones, dependencies, acceptance criteria. |
| `PROGRESS.md` | What actually works, tests passed, bugs fixed, next exact task. |
| `docs/OPERATIONS.md` | VPS deployment, roles, backup, restore. |
| `prompts/*.md` | The seven engine specifications. Authoritative domain logic. |
| `knowledge/seed/foundation_domains.md` | Engine 7's A–Z foundation curriculum, verbatim. Load for K1 seeding, domain mapping and foundation research — not on CASE, INBOX or routine UPDATE runs. |

Several constraints in this repo look like overhead if you don't know what
they protect against. `DECISIONS.md` explains each one. **If a decision
genuinely blocks implementation, raise it as a blocker. Do not route around
it.**

---

## The seven engines

| | Role |
|---|---|
| E1 | Decide what matters clinically and nutritionally |
| E2 | Make behaviour executable |
| E3 | Make nutrition executable |
| E4 | Learn from response |
| E5 | Communicate to the client |
| E6 | Remember the complete evolving case |
| E7 | Know far more interventions and evidence than the practitioner could personally read |

They are **specialist skills of one agent**, not seven chatbots.

Primary path:
```
E6 → E1 Pass A → normalization → E7 → E1 Pass B → E2 → E3
   → E6 update → practitioner review → E5 → follow-up/E4
```

---

## Hard rules

### 1. Engine prompts are authoritative
Never shorten, summarise, rewrite or "optimise" a file in `prompts/`.
They are master reasoning specifications. Technical formatting fixes only.

Engine 7 is a **four-layer merge** — Addendum A, Part I §1–§87 (the client's
text, verbatim), Parts II/III §R1–§R9 (retained original operating detail),
and §88. It is not redundant. **§R10–§R13 are build-added output
contracts** on top of that merge — the INBOX information gain, the Claim
Cards, the evidence analysis and the synthesis decisions — each because a
stage of the Knowledge Factory had a count to report and no block to carry
the substance (D35, D36). See `DECISIONS.md` D16 before consolidating
anything: the client's revision carries no handoff XML tags, so §R8/§R9 are
what let output reach Engines 1–4 at all.

**Prompt length is not output length.** A 5,000-word specification
describes how an engine reasons; it is not a template for a 50-page report.
Do not simplify reasoning to make output tidy. Output design is a separate,
later task.

### 2. E1 runs twice with ONE specification
Pass A and Pass B both load `prompts/engine1_prevention.md`. There is no
`engine1_pass_a.md`. Neither pass may be a trimmed or simplified Engine 1.
The difference is context and stopping point, not capability.

Both runs record the **identical prompt hash**. `trg_enforce_two_pass`
rejects a mismatch at insert. That rejection is a build error, not a
variation to work around.

### 3. Automate first
```
AUTOMATE → AUTO-RESOLVE HIGH CONFIDENCE → LOG LOW-IMPACT UNCERTAINTY
         → ESCALATE ONLY HIGH-IMPACT AMBIGUITY
```
**No milestone may create a recurring manual job for the practitioner.**
Their time is the scarce resource. That is the premise of the whole system.

Escalation ranks by **impact, not uncertainty**, and is capped.

### 4. Confidence is not authorization
For ontology aliases, high similarity may auto-resolve.
For **client facts, it may not.** High extraction confidence means the
model heard correctly, not that the fact is true or that anyone authorised
recording it. Chat-derived facts need practitioner approval, an explicit
"save this" instruction, or trusted structured ingestion.

### 5. n8n never parses prose to route
Routing reads typed fields from
`schemas/orchestration/control_contract.v1.json`. Roughly 17 strict fields.
The remaining handoff content stays prose for now, by decision.

**Exactly one control-block specification per prompt file.** A second one is
a merge accident, not a variant — it happened once already. `CASE_VERSION`
is required on every run: echo the real version on case runs, emit **0** on
Engine 7 knowledge-clock runs (FOUNDATION / UPDATE / INBOX). Stored case
versions always start at 1, so 0 can never denote a real case.

### 6. Practice experience is never evidence
`practice_strategy_outcomes` has no foreign key to `evidence_records` and
no view joins them. Do not add one. De-identified aggregates only, minimum
cohort 5.

### 7. Provenance is enforced, not requested
A strategy past `AI_DISCOVERED_CANDIDATE` cannot exist without a provenance
note. `RUN_ENGINE` raises `PromptMissing` rather than falling back to a
stub. An output that cannot be traced to a specification is worse than no
output.

### 8. Client isolation is structural
n8n connects as `phi_runtime` — `NOSUPERUSER`, `NOBYPASSRLS`. Never as
`phi_admin`. Client scope is transaction-local. With no scope set,
client-scoped tables return **zero rows**, not all rows.

### 9. Safety gates release, not analysis
Internal analysis, drafting and the practitioner view are **never** gated.
Only delivery of client-facing output is. NOTE flags never block. The gate
must not fire on ordinary medicated metabolic clients — a gate that fires
constantly is a rubber stamp.

No engine ever instructs a client to stop, reduce or change a prescribed
medication. It may flag that prescriber reassessment is warranted.

### 10. Migrations are append-only
Never edit an applied migration. `scripts/migrate.py` rejects it by
checksum. Add a new one.

`norm_phrase()` backs STORED generated columns; changing it requires a
migration that also rewrites those columns and rebuilds their indexes.

### 11. Readiness is not completion
`coverage_dimension` holds exactly the **18** questions recovered from
Engine 7 §35 — no build-invented dimensions. Gap assessment is governance,
tracked in `domain_gap_assessments`, not a coverage dimension.

`foundation_ready` needs coverage **+** a gap assessment performed **+** no
open CRITICAL gap. It never requires zero gaps, and zero identified gaps
never means finished. There is no `COMPLETE` status anywhere and §70 forbids
adding one.

### 12. Provenance edges cannot dangle
Every derived knowledge object registers in `knowledge_entities` by trigger.
`envelope_derived_records` foreign-keys `(derived_id, derived_kind)` to it.
A new derived kind adds an enum value and a registration trigger — never a
new foreign key on the provenance table.

### 13. A new source type is data, not code
`source_kinds` is a registry table. Adding a source kind is an `INSERT`, not
a migration and not an enum edit. `OTHER` is protected and always available
as the landing state for unseen kinds. Never hard-code a creator or a
source type into ingestion logic (Engine 7 §47); route on format, content
type, source role and access level.

---

## Working method

```
EXPLORE → PLAN → IMPLEMENT → TEST → FIX → DOCUMENT
```

- Run `bash testing/run_all.sh` before every commit. All suites must pass —
  and **read the exit code**, which is not the same thing. See **V1**.
- Commit after each working milestone. Update `PROGRESS.md` with what
  genuinely works, tests passed, bugs fixed, and the next exact task.
- **Never declare completion because files exist.** Verify execution.
- Tests assert behaviour, not table existence. A test that only checks a
  table exists is not a test — and neither is one that compares two things
  you wrote yourself. See **V2**.
- Tests must be idempotent — clear their own fixtures and re-run cleanly
  against a used database.
- Where something is ambiguous but a reasonable default exists, choose the
  simplest low-cost internal implementation and document the assumption
  rather than stopping.

### V1. READ THE EXIT CODE. Never chain verification behind another command

**Twice now.** Both times the suites ran, both times the result was not
read, and both times a commit landed on a red tree.

```bash
# WRONG -- grep's exit code is what `&&` sees, and grep succeeded
bash testing/run_all.sh 2>&1 | grep -E "ALL SUITES|FAILURES" && git commit ...

# WRONG -- the pipe discards run_all.sh's status entirely
bash testing/run_all.sh | tail -3 && git commit ...

# RIGHT -- capture, check the status explicitly, then commit
out=$(bash testing/run_all.sh 2>&1) || { echo "$out" | tail -40; exit 1; }
echo "$out" | grep -q "ALL SUITES PASSED" || { echo "RED"; exit 1; }
git commit ...
```

A pipeline's exit status is its LAST command's. `| tail`, `| grep`,
`| head` all succeed cheerfully on the output of a failing suite. Running
the suites and not reading the result is the same failure as not running
them, with an extra step and more confidence.

### V2. A test must not construct both halves of a comparison

**Four times now** — bugs 49, 57, 59, 61. Every instance had the same
shape: **the harness differed from production, so it proved nothing about
production.**

| | what was compared | what it proved |
|---|---|---|
| 49 | a path that meant one thing locally and another in CI | nothing, until CI went red |
| 57 | a suite that could not see the condition it existed to catch | nothing, and it crashed instead of skipping |
| 59 | the workflow's own code run in plain Node, where `fetch` is global | nothing — the node could never have run in `vm2` |
| 61 | a hand-written "n8n row" against a hand-written "reference row" | nothing — both halves were invented, so they agreed |

The rules that follow from it:

- **The reference side comes from calling the real implementation.** Never
  from a second hand-written copy of what you believe it does. If the
  comparison is against `run_engine.py`, *call* `run_engine()`.
- **Run the code the way production runs it.** Inside n8n's sandbox
  restrictions, as the role the runtime connects as, at the version the VPS
  installs. `testing/n8n_retry.js` uses `node:vm` with only the globals
  `vm2` provides for exactly this reason.
- **When you port an algorithm, drive the real module** and diff the output
  over a corpus. Porting `n8n`'s parameter binder and never running the
  original is how the array-branch bug survived a full review (D32).
- **Use the inputs a real caller produces.** `MODE: "PASS_A"` is not a mode
  and no caller emits it; inventing it let the suite construct a matching
  reference and report parity that did not exist.
- **A check that cannot run must SKIP loudly**, never pass quietly. A green
  suite that silently skipped its only real assertion is worse than a red
  one.

---

## Environment

Hostinger VPS, India. 2 vCPU, 8 GB RAM, 100 GB disk.
n8n already running in Docker; this repo adds PostgreSQL to the same
network with **no published port**.

**2 vCPU is the binding constraint.** Most work is API-wait, not compute,
so this matters for concurrency: keep `KNOWLEDGE_MAX_CONCURRENCY` at 2–3.

Never hard-code a model name. Use the five roles: `MODEL_ANALYSIS`,
`MODEL_EXTRACTION`, `MODEL_RESEARCH`, `MODEL_EMBEDDING`, `MODEL_FAST`.

Database is in India; model inference is not. Engine payloads carry
`client_id` and clinical facts, **not names**
(`STRIP_IDENTITY_FROM_ENGINE_PAYLOADS=true`).

---

## State as of 2026-09-10 — running on real infrastructure

**Container-verified and infrastructure-verified are different claims.**
Container-verified means it ran on a database this build controls, usually
with trust auth and a superuser DSN. Infrastructure-verified means it ran
on the Hostinger VPS with real roles and scram passwords over TCP. The
second is much stronger, and the reason to keep them apart is that
everything was container-green for weeks while `RUN_ENGINE` could not have
run as `phi_runtime` at all (D25). See `PROGRESS.md` *Deployed to the VPS*.

**Complete and verified** — M0 foundations, M1 schema, M2 engine execution
layer, all seven canonical prompts installed, and build steps **10b and
11–15**. Step 11 is **frozen**: changes to it are bug fixes only.

21 migrations, 80 tables, 28 views, 51 enums, 211 indexes, 66 check
constraints, 45 triggers, 30 RLS tables, 60 policies. **Nineteen test
suites**, passing from an empty database, idempotent on a re-run, and
verified in three capability configurations: full, **no pgvector**, and
**no optional extension at all**.

Working end to end **on a live provider**, not only on the fixture:
```
E6 init → case v1 → E1 Pass A → research questions
        → E7 → E1 Pass B → both passes, one prompt hash
```
Measured 2026-09-09: 81,258 in / 86,681 out, **$0.386** per 4-call cycle,
306s, both passes producing complete 19-part reports. **D5 is answered —
do not stage Engine 1.** The free provider tier is not viable; billing is a
prerequisite.

**Nothing is blocked on input.** `LLM_API_KEY` and the base URL are set
locally. On the VPS it is deliberately empty — nothing there makes a paid
call yet.

**Four runtime registries, all rows (D23, D24, D30).** `prompts/*.md`,
`schemas/orchestration/*.json` and `config/model_prices.json` stay the
authored forms; `engine_prompts` (`010`), `orchestration_contracts`
(`012`), `engine_handoffs` (`013`) and `model_prices` (`016`) are what the
runtime reads. A fresh deployment must run **all four** loaders after
migrating — `load_prompts.py`, `load_contracts.py`, `load_handoffs.py`,
`load_prices.py` — or every engine raises `PromptMissing`,
`ContractMissing` or `HandoffMissing`, and every call the workflow prices
records UNPRICED. Migrating alone is not enough.

**The control block routes; the handoff is the reasoning (D24).** Every
engine emits both, and they are never interchangeable. `<CONTROL_BLOCK>`
is ~17 typed fields for routing and gating; `<..._HANDOFF>` is what the
next engine thinks with. A run missing its required handoff repairs and
then dead-letters — a valid control block is not evidence that an engine
did its work. **A delta is never stored as `canonical_state`.**

**Mode is passed, never hand-written (D24a), and now stored (D27).**
`RUN_ENGINE` injects a `<RUNTIME_INVOCATION>` envelope — engine, mode,
pass, expected handoff blocks — ahead of the payload, once, for every
engine. **Never put a `"MODE"` key in `structured_input`**; a test walks
`scripts/` and fails if anything outside `run_engine.py` does. **E6 and E7
have no default mode** and `mode=` must be passed: E6 `INIT`/`REBUILD`
emit a full state and `UPDATE` a delta; E7 has four modes — `FOUNDATION`
and `UPDATE` share the foundation handoff, `CASE` and `INBOX` have their
own. The mode is written to `engine_runs.engine_mode` when the run opens,
and `trg_engine_run_coherent` rejects an incoherent client/mode
combination **before** the insert: E1–E6 and E7 `CASE` require a client;
E7 `FOUNDATION`/`UPDATE`/`INBOX` must have none.

**A failed engine response is client data (D28).** `dead_letter_jobs`
carries `client_id` and is RLS-forced. `raw_payload` holds up to 8,000
characters of the failed response, which for a case run is the clinical
record in a different shape. Do not relabel it telemetry, and do not read
it to triage — `v_dead_letter_triage` answers how-many-since-when without
it.

**`workflows/run_engine.json` is built and proven byte-identical to the
Python reference (D26).** One golden corpus, two implementations: 15
requests identical to the byte, 15 responses identical field for field.
The JavaScript under test is extracted from the workflow at run time, so a
copy cannot drift from it. **Its SQL is executed too (D31)** —
`test_n8n_sql.py` binds the workflow's real expressions through a faithful
port of n8n's own parameter algorithm and runs the result against the
database as `phi_runtime`. Every `queryReplacement` is **one resolvable
per parameter, each a JSON literal** (`{{ JSON.stringify(x ?? null) }}`),
unwrapped in SQL with `($n::jsonb #>> '{}')`. Do not "simplify" one back:
a bare expression discards literal text outside `{{ }}`, turns `null` into
the string `'null'`, comma-splits any resolved value that is not JSON, and
drops an empty string entirely — and the array form that avoids all four
**does not exist on 2.11.4** (D32).

**Engine runs set transaction-local client scope (D25).** `RUN_ENGINE`
could not run as `phi_runtime` at all before this — every run went around
the policies because `DATABASE_URL` connects as a superuser. Every write is
now inside a transaction that calls `set_client_scope()` first, and the
workflow mirrors it per Postgres node.

**Embeddings are settled and enforced (D34).** 1536 dimensions from
`gemini-embedding-2`, and the database refuses anything else: every vector
carries `embedding_model` and `embedding_dim`, a **non-unit-norm vector is
rejected on write**, and a second model into one column is refused
outright. `gemini-embedding-001` truncated to 1536 returns a norm of 0.702
and would otherwise have degraded retrieval silently. The dimension has one
source — `embedding_dim()` reads it from the catalog; do not add a second.
Not 3072: pgvector refuses an HNSW index above 2000 dimensions.

**`gemini-embedding-2` has no rate configured** and it was not guessed —
a fabricated price corrupts every total built on it. `load_prices.py` names
the gap on every run and `v_unpriced_spend` counts what has been spent
without one.

**Step 16: K07–K11 are built. Discovery (K02–K06) is next.** One source
now runs the whole loop: `knowledge_ingest.py` (inbox → heading-located
chunks, deterministic, no model call) → `knowledge_extract.py` (E7 INBOX →
Claim Cards + concept normalization + §54 delta) → `knowledge_research.py`
(E7 EVIDENCE → independent evidence + the claim's reading) →
`knowledge_synthesize.py` (E7 SYNTHESIS → CREATE / UPDATE / MERGE /
NO_CHANGE).

**E7 now has six modes** — `CASE` is client work; `FOUNDATION`, `UPDATE`,
`INBOX`, `EVIDENCE` and `SYNTHESIS` are knowledge-clock work with no client
and `CASE_VERSION` 0. The client/clock rule lives in
`engine_handoffs.client_required`, so **adding a mode is an INSERT** — do
not put a mode list in a trigger again (migration `020` removed the one
`015` had).

**K10: the source's own citation is never the input (D36).**
`evidence_referenced_by_source` is deliberately not sent to an EVIDENCE
run — what a creator cited is a fact about the creator (§12), and feeding
it in turns independent research into an echo. Evidence never links to the
discovery envelope, and a study with no DOI/PMID/URL gets **no
`source_items` row** rather than an invented one. Triage is deterministic
and written down: `SAFETY` and `INTERVENTION_EFFECT` are researched, the
rest are not.

**K11: dedup is deterministic and happens BEFORE the call.** Candidates
come from concept overlap, then `pg_trgm` name similarity; only those are
sent. **A model returning `CREATE` is a proposal, not authority** — every
CREATE is re-checked against the live library and a collision becomes an
UPDATE. Four decisions, never a fifth. Everything created is
`AI_DISCOVERED_CANDIDATE`; the only status K11 may set beyond that is
`DEPRECATED` on a MERGE, where the rationale becomes the provenance note
`ck_provenance_required` demands. A strategy with no canonical concepts is
recorded as an OPEN gap, never linked to `PROPOSED` concepts to make the
count look right (D8).

**K09 may not create an evidence record or a strategy (D35).**
`evidence_referenced_by_source` is what the SOURCE cited — text, and it
stays text; the provenance edge is `discovery_only` because a video that
surfaced an idea has not evidenced it (D10). The §54 classification is
derived from what was written, never echoed from the model's counts, and
`POTENTIAL_NEW_STRATEGY` is K11's verdict, not K09's. A held-out source is
`SKIPPED`, never extracted (A3).

**`<RESEARCH_PRACTICE_CLAIMS>` is strict JSON in one `CLAIMS_JSON` field**,
because `parse_handoff_block` already handles continuation lines — so K09
needed **no change to frozen step 11**, to `run_engine.py`, or to either
parity suite. Check the constraint before working around it.

Until real sources are ingested the library is nearly empty, so Engine 7
retrieves little and Pass B reasons from a thin retrieval set — that is
expected, not a bug. **Do not begin mass ingestion**: one source through
the complete loop first, then the 20-video pilot.

**n8n is pinned to 2.11.4, the version the VPS runs (D32).** The pin
follows the VPS; it is **never** raised to keep current. Re-pinning found
two things that would have failed on first run and are now covered by
tests: the Postgres node's `queryReplacement` **array branch does not exist
in 2.11.2**, and the Code node's `vm2` sandbox has **no `fetch` and no
`URL`** (D33). Every binding is now one resolvable per parameter, each a
JSON literal, unwrapped in SQL with `($n::jsonb #>> '{}')` — a form
verified exact against both real implementations. The provider call goes
through `helpers.httpRequest`, and the retry harness runs the node's source
in `node:vm` with only the globals vm2 provides, so a node reaching for a
host global fails in the test as it would in n8n.

The VPS's n8n stack runs three live business automations; **never touch
that stack, its volume `n8n-sdc9_n8n_data`, or its `docker-compose.yml`.**

## Do NOT build

Chat UI. Chat intent router. RHT scoring engine. WhatsApp integration.
General-chat interface. Learning dashboards. Client portal. Mobile app.
Billing. Multi-tenant anything.

Schema hooks for chat, assessments and case events exist in migration 005,
and for the Knowledge Inbox, source envelope, delta analysis and medication
knowledge in migration 006, **so these can be added later without a
rewrite**. That is not permission to build them now. `006` is schema only:
no inbox UI, no ingestion pipeline, no acquisition adapters.

---

## Deferred by decision, not forgotten

Full engine-output JSON schemas beyond the control contract. Client report
formatting, WhatsApp output, practitioner deep view.

*(Engine 1 call-size measurement is no longer deferred — it was measured
live on 2026-09-09 and settled D5. See above.)*

## Genuinely open

Intake form **V2** — V1 is built (D22, migration `009`); which fields V2
adds is a question for `v_missing_data_recurrence` after real cases, not
for a design session. The practitioner-facing capture surface: V1 accepts a
structured submission and how a human fills it in is still open.
Practitioner review UI. Deterministic flag rule set (start narrow).
Indian food composition data source. See `docs/DECISIONS.md` OPEN section.
