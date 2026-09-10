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
| `docs/DECISIONS.md` | **Before proposing any structural change.** 21 settled decisions with rationale and rejected alternatives. |
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
and §88. It is not redundant. See `DECISIONS.md` D16 before consolidating
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

- Run `bash testing/run_all.sh` before every commit. All suites must pass.
- Commit after each working milestone. Update `PROGRESS.md` with what
  genuinely works, tests passed, bugs fixed, and the next exact task.
- **Never declare completion because files exist.** Verify execution.
- Tests assert behaviour, not table existence. A test that only checks a
  table exists is not a test.
- Tests must be idempotent — clear their own fixtures and re-run cleanly
  against a used database.
- Where something is ambiguous but a reasonable default exists, choose the
  simplest low-cost internal implementation and document the assumption
  rather than stopping.

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

## State as of 2026-09-10

**Complete and verified** — M0 foundations, M1 schema (15 migrations), M2
engine execution layer, all seven canonical prompts installed, and build
steps **10b, 12, 13, 14, 15** and step 11's registry half.

77 tables, 23 views, 51 enums, 202 indexes, 64 check constraints,
44 triggers, 29 RLS tables, 58 policies. **Sixteen test suites**, passing
from an empty database three consecutive times, idempotent, and verified in
three capability configurations: full, **no pgvector**, and **no optional
extension at all**.

Working end to end **on a live provider**, not only on the fixture:
```
E6 init → case v1 → E1 Pass A → research questions
        → E7 → E1 Pass B → both passes, one prompt hash
```
Measured 2026-09-09: 81,258 in / 86,681 out, **$0.386** per 4-call cycle,
306s, both passes producing complete 19-part reports. **D5 is answered —
do not stage Engine 1.** The free provider tier is not viable; billing is a
prerequisite.

**Nothing is blocked on input.** `LLM_API_KEY` and the base URL are set.

**Three runtime registries, all rows (D23, D24).** `prompts/*.md` and
`schemas/orchestration/*.json` stay the authored forms; `engine_prompts`
(`010`), `orchestration_contracts` (`012`) and `engine_handoffs` (`013`)
are what `RUN_ENGINE` reads. A fresh deployment must run **all three**
loaders after migrating — `load_prompts.py`, `load_contracts.py`,
`load_handoffs.py` — or every engine raises `PromptMissing`,
`ContractMissing` or `HandoffMissing`. Migrating alone is not enough.

**The control block routes; the handoff is the reasoning (D24).** Every
engine emits both, and they are never interchangeable. `<CONTROL_BLOCK>`
is ~17 typed fields for routing and gating; `<..._HANDOFF>` is what the
next engine thinks with. A run missing its required handoff repairs and
then dead-letters — a valid control block is not evidence that an engine
did its work. **A delta is never stored as `canonical_state`.**

**Mode is passed, never hand-written (D24a).** `RUN_ENGINE` injects a
`<RUNTIME_INVOCATION>` envelope — engine, mode, pass, expected handoff
blocks — ahead of the payload, once, for every engine. **Never put a
`"MODE"` key in `structured_input`**; a test walks `scripts/` and fails if
anything outside `run_engine.py` does. **E6 and E7 have no default mode**
and `mode=` must be passed: E6 `INIT`/`REBUILD` emit a full state and
`UPDATE` a delta; E7 has four modes — `FOUNDATION` and `UPDATE` share the
foundation handoff, `CASE` and `INBOX` have their own.

**The case track runs end to end.** `scripts/client_new.py` takes a
submitted intake to the practitioner's review queue: E6 → E1 Pass A →
normalization → E7 → E1 Pass B → E2 → E3 → E6, on one prompt hash. It
stops at the queue by design — Engine 5 is gated on a practitioner
decision, and an open HOLD never stops the analysis (hard rule 9).

**`workflows/run_engine.json` is built and proven byte-identical to the
Python reference (D26).** One golden corpus, two implementations: 15
requests identical to the byte, 15 responses identical field for field.
The JavaScript under test is extracted from the workflow at run time, so a
copy cannot drift from it.

**Engine runs set transaction-local client scope (D25).** `RUN_ENGINE`
could not run as `phi_runtime` at all before this — every run went around
the policies because `DATABASE_URL` connects as a superuser. Every write is
now inside a transaction that calls `set_client_scope()` first, and the
workflow mirrors it per Postgres node.

**Next:** step 16, the Knowledge Factory (K02–K11). Until it runs, Engine 7
retrieves from an empty library and Pass B reasons from an empty retrieval
set — that is expected, not a bug, and `PROGRESS.md` says so before the
first full case is run.

**Before deploying:** `scripts/local_n8n.sh` pins n8n **2.35.7**. What the
VPS runs is **unknown and unrecorded**, and workflow JSON is
version-sensitive. See `docs/OPERATIONS.md` "n8n version".

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
