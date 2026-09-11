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
| `docs/DECISIONS.md` | **Before proposing any structural change.** 44 settled decisions with rationale and rejected alternatives. |
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

### V2. A test must not construct both halves of a comparison — or neither

**Five times now** — bugs 49, 57, 59, 61, 62. Every instance had the same
shape: **the harness differed from production, so it proved nothing about
production.**

| | what was compared | what it proved |
|---|---|---|
| 49 | a path that meant one thing locally and another in CI | nothing, until CI went red |
| 57 | a suite that could not see the condition it existed to catch | nothing, and it crashed instead of skipping |
| 59 | the workflow's own code run in plain Node, where `fetch` is global | nothing — the node could never have run in `vm2` |
| 61 | a hand-written "n8n row" against a hand-written "reference row" | nothing — both halves were invented, so they agreed |
| 62 | a retrieval fixture where every row scored identically | nothing — the page was decided by UUID tie-break, and a coin flip is green most of the time |

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
- **The fixture must be able to tell the right answer from the wrong one.**
  If every row scores the same, the assertion is measuring the tie-break.
  Before trusting a ranking test, ask what it would return if the mechanism
  under test were deleted — and if the honest answer is "the same thing,
  sometimes", the fixture has no signal in it. Sharpen the claim too:
  "fewer" passes on a tie where "only these three" does not.
- **Repeat-run anything whose fixture generates identifiers.** Bug 62 was
  green four consecutive times. Ten runs on each capability floor is cheap
  and is what actually distinguishes deterministic from lucky.

### V3. An optional dependency degrades to a NAMED skip, never an exception

**Three times now** — `pg_trgm`, `ajv`, `MODEL_EMBEDDING` (bug 64). Same
shape every time: a suite only passed where an optional dependency happened
to be configured, and CI was green throughout **because CI configures it**.

| | what was missing | what the suite did |
|---|---|---|
| `pg_trgm` | the extension | called `similarity()` and died |
| `ajv` | the node module | indexed `'valid'` on an error dict |
| `MODEL_EMBEDDING` | the env var | raised `BadVector` halfway through |

Each was fixed where it was found and the next formed elsewhere, because
"remember to guard optional dependencies" is not a mechanism.

- **`testing/preflight.py` is the mechanism.** `have_env`,
  `have_capability`, `have` — one skip format, one registry of what is
  optional and what its absence costs. Never write a bare `print("SKIP ...")`.
- **Named, not just skipped.** `SKIP` alone tells a reader something was
  not tested and not *what*, so nobody can tell a supported configuration
  from a suite that quietly stopped asserting anything.
- **`testing/test_optional_deps.py` is the assertion**, and it runs in
  `run_all.sh` so it holds on every floor. It removes each registered
  variable, finds the suites that reach it — walking the import graph, not
  reading a list that goes stale — and runs each **twice**: the degraded
  run must exit 0, and every skip it prints that the baseline did not must
  name the removed dependency.
- **Production code degrades too, not just tests.** `retrieval.by_vector`
  returns `"MODEL_EMBEDDING is not set: ..."` rather than raising; the VPS
  runs with it unset on purpose. `embedding.embed()` still refuses, and
  should: asking it to embed with no model pinned IS an error (D34) — a
  query is not asking it to.
- **Extensions are `run_bare.sh`'s floor**, env vars are
  `test_optional_deps`'s. Neither pretends to cover the other.

**A precondition gets the same treatment.** A suite needing the K1 seed, or
a library with strategies in it, must say what is missing and skip — failing
there claims the code is wrong when the database is merely unseeded.

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

31 migrations, 97 tables, 41 views, 55 enums, 255 indexes, 103 check
constraints, 54 triggers, 31 RLS tables, 62 policies — measured
2026-09-10, with the counting queries recorded in `PROGRESS.md`; earlier
figures used a different method and do not reconcile, so re-measure rather
than adjust. **Twenty-eight test suites**, passing from an empty database,
idempotent on a re-run, and verified in four configurations: full, **no
pgvector**, **no optional extension at all**, and **`MODEL_EMBEDDING`
unset with pgvector present** — the last is what the VPS actually runs,
and it is enforced by `testing/test_optional_deps.py` rather than
remembered (V3).

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

**A rate belongs to a MODALITY, and is never borrowed (D38).**
`gemini-embedding-2` is priced $0.20/1M for text, $0.45 image, $6.50 audio,
$12.00 video — 60x apart. `model_prices` is keyed `(model_name, modality)`,
`cost_events` records which modality it paid for, and **both** halves of
`price_call` refuse to guess: an unpriced modality is UNPRICED and a
multimodal model with no modality stated is UNPRICED. Never TEXT, which is
the cheapest and would round every mistake toward under-reporting. A
single-modality model still prices with no modality given, which is why the
frozen workflow needs no change.

**K14 embeds TEXT ONLY, enforced twice (D38).** Transcripts and extracted
document text, never the source media — audio is a 32x bill for a worse
index. `scripts/embedding.py` is the ONE embedding boundary and refuses
media magic bytes, `data:` media URLs, media MIME types, non-UTF-8 bytes
and empty payloads **before the provider is called**;
`ck_embedding_text_only` refuses the cost row. It also enforces D34's
unit-norm and dimension checks at the call, so a bad vector fails where it
happened. **A cost decision, not a capability limit** — the other three
rates are already loaded, so enabling multimodal embedding is a migration
that drops the constraint and says why, not a pricing exercise.

**Step 16: K02–K11 are ALL built.** One source runs the whole loop: `knowledge_ingest.py` (inbox → heading-located
chunks, deterministic, no model call) → `knowledge_extract.py` (E7 INBOX →
Claim Cards + concept normalization + §54 delta) → `knowledge_research.py`
(E7 EVIDENCE → independent evidence + the claim's reading) →
`knowledge_synthesize.py` (E7 SYNTHESIS → CREATE / UPDATE / MERGE /
NO_CHANGE). `knowledge_discover.py` adds five ways for something to
**arrive**, and no way for anything to be processed.

**Discovery finds; it does not ingest (D37).** Every adapter ends at
`deliver_to_inbox()` and K07/K08 take it from there — a second ingestion
path would be a second normalizer, a second dedup rule and a second place
to forget §52. The access policy lives in `acquisition_adapters` and is
checked at ONE chokepoint, `acquisition.fetch()`: `allowed_hosts`,
`respect_robots`, `requires_authorization`, intervals and repeat windows.
**An unregistered adapter fetches nothing.** Every request *and every
refusal* is recorded in `source_fetches` with its reason — a layer that
logged refusals nowhere would look exactly like one that was quietly
scraping. A `robots.txt` that errors or cannot be read is a **refusal**; a
404 is the one honest "no restriction stated".

**`YOUTUBE` still has no scraper, and now has an authorization (K06,
D46).** The transcript comes from Apify's documented API under the
practitioner's own token — **an authorization WITH APIFY, not a permission
from YouTube**, which is why `allowed_hosts` is `api.apify.com` alone and a
youtube.com URL is refused by the same adapter. Clearing the registry note
or unsetting `APIFY_TOKEN` returns it to refusing; both are the same
finding, so a missing token is **recorded as a refusal** and the item is
`ACCESS_DENIED`, never a crash. K05 is unchanged: no published transcript
means `FULL_TEXT_NOT_AVAILABLE`, never content invented from a title and a
blurb.

**The actor was RUN before code was written against it, and the first guess
was wrong** — the input field is `urls`, not `videoUrls`. Four things the
real output showed:

**THERE IS NO FLAT TRANSCRIPT FIELD, AND THE SEGMENTS OVERLAP.** Segment 1
runs 0 → 2.16 and segment 2 *starts* at 1.04 — YouTube's rolling-caption
format. Naive concatenation duplicates words throughout, and downstream it
does not look like a joining bug: it looks like a rambling source, so claim
extraction blames the speaker. `dedupe_segments()` gates the trim on the
**timings**, never on the text — two segments that do not overlap in time
are two different things being said, and a speaker who repeats themselves
must survive intact.

**`isAutoGenerated` is ASR provenance and must reach the derived
knowledge.** It rides on the envelope, reaches every chunk's metadata, and
`v_asr_derived_claims` answers which conclusions rest on machine
transcription. **NULL means "not a transcript", never "human".** That view
joins through `envelope_derived_records` — the obvious join via
`source_items.source_id` looks right and silently returns nothing, because
the envelope's source is the one the normalizer upserts, not the channel.

**Identity is `videoId`, never `videoUrl`** (the live URL carried playlist
and timestamp parameters), and **`channelId` is the creator, never
`channelName`** — a rename must not start a second §40 profile.
`creator_type` is `OTHER`: a channel id says who published, never what they
are, and §12 weighs claims on that.

**Timestamps survive through the normalizer we already have.** The
transcript is markdown whose block headings ARE timestamps, and `segment()`
already turns a heading path into the chunk `location` (§16, §42). A claim
citing minute 14 is provenance — no second ingestion path, no change to the
chunker (D37). `fetch()` gained `method`/`body`/`extra_headers` for the
same reason: the adapter does not get its own socket.

**The no-captions payload IS captured (2026-09-11), and it is the nastier
shape.** A video with no transcript returns **HTTP 200 and a complete,
healthy-looking item** — real title, channel, description, 9.2M views, 515
seconds, 26 keywords. Five fields differ: `segments` `[]`, `segmentCount`
0, the three language fields blank, `isAutoGenerated` **false**, and a
free-text `error`.

**`isAutoGenerated: false` here is NOT "a human wrote it"** — it is false
because there is no transcript at all. **Never read that field without
first confirming segments exist**, or a failed fetch records itself as the
highest-quality transcript type there is and its claims stay off
`v_asr_derived_claims`. `auto_generated_flag()` is the ONE place it is
read; `None` (no transcript), `False` (human) and `True` (ASR) are three
distinct answers.

**Key the refusal on `error` present OR segments empty — never either
alone**, because a future actor version may drop one signal, and segments
arriving *with* an error is a partial transcript, which is worse than none
(nothing downstream can tell it was truncated). Keep the **actor's own
wording** in the note. The item is registered so it is not rediscovered
(K05's treatment of a podcast with no transcript) and **nothing reaches
the inbox, not even a sidecar** — an empty body must never become a source;
it would pass through extraction as a source that taught us nothing and
§54 would agree with it.

**Still uncaptured: a bad or removed video ID**, which may be an empty
dataset rather than an item with an `error`. Do not guess it.

**No adapter has ever spoken to its real API.** The build environment's
proxy blocks `eutils.ncbi.nlm.nih.gov`, `api.crossref.org` and
`pubmed.ncbi.nlm.nih.gov` — all answered `000`. The suite drives the real
adapters through the real chokepoint with only the transport replaced, so
the policy, cursor, history, refusals and handoff are proven and the wire
format is **not**. Treat the first live `PUBMED` run as unverified code.

**E7 now has EIGHT modes** — `CASE` is client work; `FOUNDATION`,
`UPDATE`, `INBOX`, `EVIDENCE`, `SYNTHESIS`, `CONTROVERSY` and `GAP` are
knowledge-clock work with no client and `CASE_VERSION` 0. The client/clock
rule lives in `engine_handoffs.client_required`, so **adding a mode is an
INSERT** — do not put a mode list in a trigger again (migration `020`
removed the one `015` had).

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

**Step 17: K14 is built — retrieval breadth is a MECHANISM (D39).**
`metadata → full text → vector → dedupe → rerank`, and the case's
normalized concepts are a **fourth channel**, not a filter. Similarity
alone returns the presenting complaint's folder however good the
embeddings are; the sleep material is relevant because Engine 1 said so,
not because the words resemble each other. `per_bucket_cap` is **derived**
(`limit // len(concepts)`) — a fixed 3 fails the step 17 acceptance
criterion at a page of 12, and an acceptance test that passes because the
test chose the cap has tested the test. Channel weights renormalize over
the channels that ran, so no-pgvector changes recall and not the scale of
the scores. **Held-out material (A3) is excluded by default**; only
evaluation asks for it.

**The embedding endpoint is live-verified (2026-09-10).**
`gemini-embedding-2` through `embedding.embed()` returns **1536 dims at L2
norm 1.000000028** — D34 Option A confirmed on the provider, not only in
the probe. One call, $0.000001. That verifies the WIRE FORMAT and nothing
about throughput or cost at corpus scale; no corpus has been embedded for
real.

**Embedding freshness is a hash of the TEXT, never of the row.**
`embedding_source_hash` (migration `023`) makes "do not regenerate
unchanged embeddings" a property: a second backfill pass makes **zero**
provider calls. A row hash would re-embed on every read, because retrieval
increments `retrieval_hits`. `embed_library.py` chooses rows and text and
nothing else — the provider, the norm check and the price stay in
`embedding.py` (D38).

**Step 18: the five evaluation layers are built (D40), and layer A found a
real defect on its first run.** Every expectation is derived from something
the system already held — the K1 seed (A), a held-out source (B), the
domains the library actually spans (C) — never authored by the
practitioner (D7). Three refusals are what keep the layers from becoming
decorative: `ck_test_has_expectation` (recall over an empty expected set is
undefined, **not 1.0**), `normalize.resolve(..., read_only=True)` (the
ordinary resolver creates PROPOSED concepts and trigram aliases, so
building the layer B answer key the ordinary way would teach the library
the vocabulary it is being measured against), and `UNSCORABLE` (a library
spanning no domain has not failed retrieval, and is excluded from the mean
rather than counted zero). Layer D is capped — a second spot-check sample
is refused while one is unreviewed, because a queue that grows whether or
not anyone looks at it is the recurring manual job hard rule 3 forbids.
Layer E's denominator is items **reviewed**, never items presented.

**Step 19: K12 and K13 are built — the two passes nothing else produces
(D41).** `controversies`, `controversy_positions` and `negative_knowledge`
existed since `003` with nothing ever writing to them, because K09 reads
ONE source and no single source says "these two bodies of evidence
disagree" or "this was examined and does not work". Both are statements
about what has accumulated, so both are dedicated per-domain passes, run
**from moderate coverage rather than at the end**.

Four refusals make a written row mean something. **A controversy with one
position is refused at COMMIT** — it is a consensus statement or a gap, and
stored here it is retrieved as a live disagreement (a deferred CONSTRAINT
TRIGGER, because positions are written after the parent). **Negative
knowledge needs `why_investigated`, `evidence_examined` and
`revisit_trigger`** — its only job is to stop the same question being
researched twice, and a verdict with no revisit condition is a `COMPLETE`
status by another name (§70). **`knowledge_gaps.status` is a closed set**;
it was free text and `foundation_ready` turns on `status = 'OPEN'`, so
`'open'` would have hidden a CRITICAL gap and marked a domain ready.
**`domain_controversy_assessments` separates "nobody looked" from "nothing
found"**, the way `domain_gap_assessments` already did for gaps — without
it both are an absent row and the second is the dangerous one.

**Absence of evidence is not evidence of absence.** Unstudied is a GAP;
examined-and-found-wanting is NEGATIVE KNOWLEDGE. Swapping them either
tells the library it has an answer when it has a hole, or sends the next
pass to re-research something already refuted.

**`RESEARCHING` means a gap was taken up, not researched.** Escalation is
capped and ranks by impact (hard rule 3); wiring a gap into a live E7 run
is step 21, because a gap question is not a claim and
`knowledge_research.py` researches claims.

**Step 20: the safety gate finally has something to gate (D42).**
`trg_block_unapproved_communication` and `case_flags` existed since `004`
and **nothing ever evaluated a rule**, so no HOLD could open. Six
deterministic rules now do, in SQL over labs, medications, conditions and
interventions.

**The acceptance case is a NEGATIVE and `test_safety.py` asserts it
first**: metformin + statin + ACE inhibitor + thyroid + amlodipine, with
abnormal-but-not-critical labs and a carbohydrate reduction proposed,
produces **zero flags**. A gate that fires constantly is a rubber stamp
(D6), so the thing worth testing is that it stays shut up. Two rules need
**both halves** — insulin *and* a glucose-lowering intervention, warfarin
*and* an interacting one — and either alone is an ordinary client.
`WORSENING_MARKER` is a **NOTE**, never a HOLD (hard rule 9).

**A PLAN THAT LEAVES NO ROW CANNOT BE CHECKED.** Every rule that matters
matches on an intervention's NAME, and `client_interventions` had existed
since `004` with nothing writing to it — so the rules would have passed
every client clean **having inspected nothing**. E2 and E3 emit
`<BEHAVIOUR_PLAN_ITEMS>` (§60B) and `<NUTRITION_PLAN_ITEMS>` (§70B), the
seventh and eighth build-added output contracts. Everything they write is
`PROPOSED`; Engine 4 reads the same rows later.

**Drug names, intervention names and lab thresholds are ROWS** —
`safety_rules`, `critical_lab_thresholds`, `safety_match_patterns`. Adding
a sulfonylurea is an INSERT (hard rule 13), and the suite proves the
difference. `trg_flag_rule_registered` refuses a deterministic flag whose
rule_key is not in the catalogue. Evaluating and writing are separate,
`apply_safety_rules` is idempotent, and **a rule that stops firing is never
auto-closed** — clearing a deterministic flag is a practitioner act.

**Release is three conditions and none substitutes for another.** Approval,
drafting, release. **Drafting is never gated** (hard rule 9): the
practitioner may need to see what would be said before deciding whether the
HOLD matters. The approval check lives in `client_release.py` and the HOLD
check in a trigger, deliberately — a workflow can be edited or bypassed, a
trigger cannot be forgotten.

**Step 21: CLIENT_FOLLOWUP is a DIFFERENT pipeline, not CLIENT_NEW with a
flag (D43).** Engine 4 is the routing authority:
`ROUTING_RECOMMENDATION` — a **typed** control-block field, never prose —
decides which of E1/E2/E3 run, and a value the route map does not know
**stops** the pipeline rather than routing nowhere. The contract also
refuses a recommendation with no `ROUTING_REASON`. E6 runs in `UPDATE` mode
here (§A1's normal path), and the delta still never becomes
`canonical_state`.

**`client_interventions.outcome` had NEVER been written**, so
`WORSENING_MARKER` read an empty column and could not fire for any client —
the same shape as D42, one layer later. E4 emits §64B `<PROGRESS_OUTCOMES>`,
one entry per live intervention, and the live list is **passed in** because
an engine cannot be held to "one per intervention" if it was never told
what the list was.

**`TOO_EARLY` and `NOT_TRACKED` are real answers.** An unreadable outcome
lands at `NOT_TRACKED`, **never `STABLE`** — `STABLE` claims a measurement
that was never made, and the next cycle would read the intervention as
tried and neutral. `v_intervention_response.never_assessed` separates
"nobody looked" from "looked and found nothing".

**An outcome that changes leaves what it changed from.**
`record_intervention_outcome()` writes `intervention_outcome_history`
BEFORE the column, `STOPPED` requires a reason, and **adherence is stored
beside the outcome, never folded into it** — an intervention nobody carried
out has not failed, it has not been tested. A follow-up is processed once
(`processed_at`) and spends one routing hop.

**Step 22: K00_FOUNDATION_CONTROLLER, and the budget that was a name
(D44).** `KNOWLEDGE_DAILY_TOKEN_BUDGET` had been in `.env.example` since
the beginning with **nothing ever reading it** — harmless while every stage
ran on fixtures under a human who could see the bill, and the entire risk
once a loop across 26 domains exists. The cap is measured from
`cost_events`, never from a counter the controller keeps; client work is
excluded **in both directions**; and **unset means UNBOUNDED and says so**,
because inventing a default would be a spending decision that is not the
builder's to make.

**K00 does not execute by default.** `--plan` is the default, `--execute`
an explicit act — a controller whose safe mode is the one you have to
remember to ask for is not safe. `DISCOVER` and `INGEST` are **not
executable stages**: reported as MANUAL with the reason, never quietly
omitted, because the standing instruction is one source through the
complete loop first.

**Library stages are not per-domain.** A claim belongs to a SOURCE, so
running K09/K10/K11 once per domain had every domain claim the same item.
`Stage.scope` is `LIBRARY` or `DOMAIN`; only `CONTROVERSY` and `GAP` are
genuinely per-domain (D41). The cursor is a ROW (`foundation_progress`) so
a restart resumes, and a domain failing repeatedly is **paused with its
reason** rather than retried until the budget is gone.

**Priority orders the queue and nothing else** — core first, then
`wave1_priority`. It never restricts what Engine 7 may discover.
**`WAVE1_FOUNDATION_READY` is a VIEW, never stored**: a saved READY
outlives the library it described. `foundation_stage` has no `COMPLETE`
(§70) and `IDLE` stays in the queue.

**Step 23: practice intelligence — the FIFTH name with nothing behind it
(D45).** `practice_strategy_outcomes` has carried `ck_min_cohort` since
`003` and **had never held a row**, so the constraint was passing every
insert it never saw. Step 21 is what changed: started interventions with
recorded outcomes, and `intervention_outcome_history` holding what each
replaced.

**The cohort counts PEOPLE, once each.** `n_clients` is distinct clients
with a recorded outcome, taking each client's latest — five intervention
rows from two clients is a cohort of two, and one client's three attempts
is one observation.
`ck_practice_outcomes_account_for_cohort` refuses a distribution that does
not sum to it, so the rule is a database property and not a convention in
the runner. **A proposal nobody started is not experience.**

**The denominator travels with the numerator.** Five of five assessed,
where thirty started and twenty-five were never looked at, is a selection
effect with a number in front of it. `ck_practice_generated_complete`
refuses a generated aggregate that cannot say out of how many, over what
window, with what distribution; `v_practice_cohort_candidates` separates
"nobody ran the aggregator" from "the cohort is three" from "eleven
started it and NOBODY HAS ASSESSED ONE".

**Counts, never copied client text.** No stop reason, adherence note or
outcome evidence leaves the client layer — at a cohort of five one verbatim
sentence is quasi-identifying. `trg_practice_deidentified` is the
**backstop**, not the plan: it refuses a UUID, an email, a display name or
an external ref, and it is `SECURITY DEFINER` because `clients` is
RLS-forced and a check running with the caller's visibility would compare
against the one client in scope and pass. **The runtime reads aggregates
and cannot create one** — aggregation is a cross-client read and
`phi_runtime` is single-client-scoped, so `029` revokes its DML.

**Adherence never folds into outcome, at cohort scale too (D43).** Where
adherence is unrecorded for the majority the summary says a neutral result
there is *untested, not ineffective*. **The label is a column, not a
caption**: `basis` and `evidence_status` are fields on every row, and the
block reaches E7 and E1 Pass B as a TOP-LEVEL key — never inside
`E7_HANDOFF` — and E4 on the follow-up path.

**FULL-TEXT SEARCH ORS ITS TERMS. Never `websearch_to_tsquery`,
`plainto_tsquery` or `phraseto_tsquery` here — they AND (bug 63).** A
clinical query is a paragraph; ANDing seven lexemes matched nothing, so the
full-text channel returned `[]` for every realistic query from step 17
until layer A scored fourteen domains at exactly 0.00. `ts_rank_cd`
separates a document matching six terms from one matching one; ANDing is
not a relevance strategy, it is a filter that removes everything.

**Layer A baseline, measured on the live provider 2026-09-10:** full text
alone **0.1372**, full text + vector **0.3255**, 269 concepts embedded for
$0.000234. `docs/evidence/layer_a_baseline.md`. The score is recall@20 and
a 67-concept family is bounded by 20/67 before retrieval is judged — the
ceiling travels in the result note and the score is deliberately **not**
rescaled for it.

Until real sources are ingested the library is nearly empty, so Engine 7
retrieves little and Pass B reasons from a thin retrieval set — that is
expected, not a bug. Layers B and C have nothing to report yet, and
`v_evaluation_state` shows `tests_defined = 0` rather than a passing
score. **Do not begin mass ingestion**: one source through
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
