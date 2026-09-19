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
| `docs/DECISIONS.md` | **Before proposing any structural change.** 51 settled decisions with rationale and rejected alternatives. |
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

32 migrations, 97 tables, 42 views, 55 enums, 255 indexes, 103 check
constraints, 54 triggers, 31 RLS tables, 62 policies — measured
2026-09-10, with the counting queries recorded in `PROGRESS.md`; earlier
figures used a different method and do not reconcile, so re-measure rather
than adjust. **Migrations, views and enums were re-counted on 2026-09-11
after migration `031`** (32 / 42 / 55); the rest of the line is still the
2026-09-10 measurement and was NOT re-counted, because a count taken with
a different query is not a correction. **Twenty-eight test suites**, passing from an empty database,
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

**The branch is `segments`, and only `segments`.** Whether a transcript
exists is a structural fact about the payload; `error` is free text a third
party writes. An actor version that started setting it for something
non-fatal — "some segments may be incomplete", "retried after a rate limit"
— would, if it were the condition, make this refuse perfectly usable
transcripts. **Quietly losing good sources is the worse failure**, because
nothing reports it.

**The actor's wording is carried on BOTH paths and branched on by neither.**
"No transcript available for this video" says which of several things went
wrong, in the vocabulary of the system that knows, where "nothing readable"
does not — and a transcript that arrives WITH a warning is ingested and
keeps the warning, rather than having it dropped on the floor. The item is registered so it is not rediscovered
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
score.

**One source HAS now been through the complete loop, live — 2026-09-11
(D47).** One YouTube video fetched from the real Apify API: envelope →
13 chunks → 7 claims → concepts → §54 delta → 16 evidence records → 6
strategy cards → retrievable by a case query, then re-run and correctly
recognised as already known. **$0.4959** in 14 LLM calls, 0 UNPRICED.
Every row is in `docs/evidence/first_source_loop.md`; do not summarise it
away, it is the only record of what the output actually looks like.

## ⛔ K10 IS BROKEN. DO NOT RUN IT. (audited 2026-09-18, D48)

A practising nutritionist audited that run against the raw transcript and
the literature. **Of 15 evidence records: 0 VERIFIED, 12 WRONG IN DETAIL,
3 CANNOT VERIFY.** Unresolvable citations; real papers with fabricated
authors, titles, `n` and effect sizes; effect sizes transplanted from a
different meta-analysis; an identifier pointing at an unrelated
chronic-pancreatitis paper; an invented negative finding; and walking
studies marked `SUPPORTS` for seated calf raises and vacuuming.

**`knowledge_research.py` writes `'Identified by K10 from a citation, not
fetched.'`** K10 asks Engine 7 and persists what the model RECALLS. The
`PUBMED`, `CLINICAL_TRIALS` and Crossref adapters have never executed
once. A model asked for citations returns citation-shaped text, and
nothing downstream tells that from a retrieved record.

- **The 16 evidence rows are INVALIDATED. Do not patch them.**
- **Do not run K10 until retrieval is fail-closed AND independently
  audited** — an evidence record must be unwritable without a fetch that
  succeeded, and the repaired layer must be checked by someone other than
  the thing that wrote it. Fail-closed alone only guarantees a fetch
  happened, not that the record matches what was fetched.
- **The 20-video pilot stays closed.**
- **Practitioner-verified evidence is never sent back through K10** (D49).

**Fixing retrieval is NOT sufficient.** `evidence_records` stores
DIRECTION and has **no DIRECTNESS field**, so a correctly retrieved
walking trial still has nowhere to say it is not about seated calf raises.
Indirect evidence is laundered as `SUPPORTS`, with real citations.

**Provenance failed the same audit.** Stored timestamp ranges do not
contain the statements they cite — **six of seven wrong**, claim 1 stored
at `[05:24]` for a statement at 06:06–06:20. The chain resolves cleanly to
the wrong second, which passes inspection. Any claim elsewhere in this
file that "full provenance closes" is false.

**Three judgements are computed and discarded, never stored**: K10's
triage verdict, K10's `evidence_confidence`, K11's verdict. A judgement
thrown away cannot be audited later.

**PRESENCE OF A SOURCE LOCATION IS NOT PROVENANCE.** Every stored range
looked right and six of seven did not contain the statement. So provenance
must be **mechanically validated** from now on:

```
stored object -> stored source range -> ACTUAL source text
```

and the check is that the range **contains the text being attributed to
it**. That is a test the machine can run on every write; "a location field
is populated" is not, and populated-but-wrong is the shape that passes
review.

**What survived the audit:** the Knowledge Inbox and source-envelope
model, chunking, heading-path provenance for structured documents, the
strategy-card architecture, claim extraction **for RAW sources**, source
roles and types, implementation patterns, and the rights / registry /
dedup concepts. Six of seven claims from the transcript were legitimate
checkable assertions and one correctly qualified the source.

**BUT "K09 is not implicated" WAS TOO BROAD — see the next block.** It
held for a raw transcript, which is what the audit examined. It does not
hold for curated input, and it does not hold for the `mechanism` field on
either.

## ⛔ K09 IS THE WRONG EXTRACTOR FOR CURATED KNOWLEDGE (measured 2026-09-18, D49)

Run on a hand-curated practitioner document — six strategies, explicit
`Client decision logic` subsections, already distilled and deduplicated by
a human. Rows: `docs/evidence/curated_source_run.md`. **A confirmed
failure mode, not a hypothetical concern.**

- **6 strategies became 5 claims. Strategy 6 disappeared entirely** — and
  its `Decision intelligence` subsection is the largest chunk in the
  document, holding the whole bottleneck-routing table.
- **`Client decision logic` is not preserved as a first-class field
  anywhere.** No claim carries a "when to reach for this" condition. The
  tiering signal is not in the database in any form.
- **K09 INVENTS THE `mechanism` FIELD FROM MODEL KNOWLEDGE.** §R11 says
  `mechanism` is "the mechanism **the source** proposes" and "**never fill
  a field the source did not supply**". The document contains no
  physiology at all; all seven mechanisms were fabricated. GLUT4,
  incretin, disaccharidase, gastric emptying, beta-cell, acetic acid,
  euglycemia, self-efficacy — **each occurs ZERO times in the source.**
  This is D48's failure class one layer earlier, and it reaches the
  ontology: 8 of 19 new PROPOSED concepts are fabricated mechanism
  sentences.
- **Text that deliberately withheld an evidence claim was rewritten into a
  stronger one.** The source says do not manufacture a vinegar protocol
  because dose, selection and limitations are absent; K09 wrote "acts as a
  low-friction tool to reduce postprandial glucose spikes",
  `INTERVENTION_EFFECT` 0.900. Five claims are `INTERVENTION_EFFECT` and
  one `SAFETY`, so under `RESEARCH_TYPES` **six of seven would go to K10.**

**K09 is useful for RAW material. K09 must NOT automatically re-distill
practitioner knowledge that is already curated.** Curated sources need
**deterministic structural extraction**, and it goes **INSIDE the existing
Knowledge Inbox path** — not a second ingestion path (D37).

## GATE 1 PASSED — curated preservation is built (2026-09-18, D50)

`docs/evidence/curated_gate1.md` has every row. Migrations `032`/`033`,
`curated_parser.py`, `curated_import.py`, `test_curated.py`. **6 of 6
strategies, 24 fields all VERBATIM, 0 transformed.** The Strategy 6 routing
table — the block K09 lost entirely — is stored byte-identical to a span
fixed before the importer existed.

**PRESERVATION AND NORMALIZATION ARE SEPARATE GUARANTEES, and only the
first is zero-provider.** The deterministic PARSE makes no model call and
the code enforces that: `curated_parser.py` has no provider in it. Concept
normalization is a different step, and since GATE 2 it reaches the semantic
tier — **measured on Video 1: 8 embedding calls, $0.000017**, one per
strategy name, when `MODEL_EMBEDDING` and `LLM_API_KEY` are configured.
`test_curated.py` measures zero only because it sets `LLM_API_KEY = ""`.
Do not restate "0 provider calls" for a curated import as a whole unless
the code still enforces it.

**The only architectural change is `source_kinds.extractor`.** An envelope
whose kind is registered `CURATED_DETERMINISTIC` goes to the parser
instead of K09; routing a kind stays an INSERT (hard rule 13). Everything
else is reused: inbox, envelope, rights, content hash, §57 dedup, K08's
chunker, the concept resolver, and `knowledge_entities` /
`envelope_derived_records` (a new derived kind = enum value + registration
trigger, hard rule 12).

**`curated_fields` carries PER-FIELD provenance**, which nothing existing
could express. Every stored text is `VERBATIM_SOURCE` — findable in the
original at the span it names — or `TRANSFORMED` with the rule named.
There is no third option, and that is what makes "no invented mechanism"
and "no claim stronger than the source" **tests** rather than opinions.

**The grammar is a REGISTRY** (`curated_grammar_rules`), and every rule
must state why its construct is REUSABLE. **9 of 17 rules were needed
here; 11 of 42 blocks are `REVIEW_REQUIRED`** — deliberately. A construct
that appears in Video 1 and is not on the practitioner's list of expected
constructs does NOT get a rule, because a parser fitted to the fixture is
not a parser. Unknown structure keeps its heading, text and byte range.

**Two defects this found.** The grammar was case-sensitive and the
document is sentence-case, so `Client decision logic` (lowercase `d`) was
lost on Strategies 1 and 4 — now every rule compiles case-insensitively.
And **a DEDUPED envelope carried `content_hash = NULL`**: the row that
existed because of a hash match could not be found by that hash. Fixed in
the shared inbox path.

**SCHEMA GAP, reported not worked around:** `evidence_records` has no
`verification_actor` / `verification_status`, so it cannot distinguish
practitioner verification from automated (D49 state B). Video 1 contains
no such passage so nothing was forced into a generic flag — **but this
must be closed before a section that does is imported.**

**A PASS here means preservation ONLY.** Concept normalization is GATE 2
and retrieval is GATE 3. At the time: **0 of 8 phrases resolved** against
269 seeded concepts, run `read_only=True` so nothing entered the ontology.
**After GATE 2 it is 1 of 8** — `Meal-linked postprandial movement` →
`POST_MEAL_MOVEMENT` at cosine 0.869, by the semantic tier. Still
`read_only=True`, so still nothing entered the ontology.

**The next preservation test is NOT Video 2.** Video 1 is one of the most
structured sections; the next must be one of the LEAST structured, to try
the same grammar at both ends without fixture-specific tuning.

## THE THREE KNOWLEDGE STATES — NEVER COLLAPSE THEM (D49)

| state | what it is | what must happen |
|---|---|---|
| **A — PRACTITIONER INTELLIGENCE** | strategies, decision logic, when useful / when not, implementation, alternatives, sequencing, bottleneck routing, adaptability, coaching logic | Store and use as practitioner knowledge. **It does NOT need re-researching in order to be stored and used.** It is professional knowledge, not a claim awaiting evidence. |
| **B — PRACTITIONER-VERIFIED EVIDENCE** | passages where the practitioner says "I checked the underlying published report", followed by study details | Preserve the verification: `verification_actor = PRACTITIONER`, `verification_status = PRACTITIONER_VERIFIED`. **Never** send through K10 on curated import, **never** make the practitioner verify it twice, **never** downgrade it because automated K10 did not verify it, and **never** silently convert it to `SYSTEM_VERIFIED`. |
| **C — SOURCE CLAIM, NOT PERSONALLY VERIFIED** | "X reduced glucose by 32%" where the practitioner did not check the paper | `verification_status = SOURCE_CLAIM_UNVERIFIED`. Not established evidence. Eligible for automated research **later**, once that layer is repaired. |

Collapsing A into C sends professional judgement to a broken evidence
layer. Collapsing B into C throws away work a human already did.
Collapsing anything into `SYSTEM_VERIFIED` is the D48 failure with a new
label. A separate independent evidence audit may exist later as its own
workflow; **it is not part of curated import.**

**Still do not begin the 20-video pilot.** D47's run produced 71 proposals
and **one** resolution against a seed that holds the right concepts; 51
PROPOSED concepts were created instead, and 4 of 6 strategies ended with no
canonical concept and an OPEN gap. **That blocker is now addressed — see
GATE 2 below — and the pilot is still closed**, because a repaired
normalizer has not been run over a source end to end and K10 remains broken
(D48).

## GATE 2 PASSED — the semantic tier is built and measured (2026-09-18, D51)

`docs/evidence/gate2_semantic_tier.md` has every row.
`normalize._tier_semantic()` was `return [], 0.0` unconditionally; it is now
a real pgvector query through `embedding.embed()` — the ONE embedding
boundary (D38), never a second client — with **its own threshold 0.82**
(floor 0.78, top-3 candidates), never the trigram constant. **56 D47
phrases: 33 RIGHT, 4 PARTIAL, 9 PARTIAL_MISS, 4 REFUSED_CONFUSABLE, 2
MISSED, 4 WRONG**, for $0.000106.

**THE ANSWER KEY WAS COMMITTED BEFORE THE TIER EXISTED** (`dd95388`,
`testing/fixtures/normalization/d47_answer_key.json`). That ordering is the
only thing that stops a threshold being fitted to the sample, and the sample
is failure-selected — these are the phrases D47 FAILED on, so the sweep says
what a threshold recovers and nothing about what it breaks.

**A CANDIDATE IS NOT A RESOLUTION.** Tiers returned `(ids, confidence)` and
`resolve()` cached, aliased AND returned exactly those ids — one list doing
two jobs. A top-3 tier on that contract would have resolved a phrase to
three concepts the moment no confusable pair objected: the failure
`confusable_with()` exists to prevent, arriving through the mechanism meant
to prevent it. `TierResult.candidates` is what the safety checks read;
`TierResult.selected` is the only thing that may be cached, aliased or
returned.

**Selection is the TOP-1 and nothing else.** Trigram's 0.01 tie rule does
not transfer — cosine scores are dense, and `postprandial walking` puts
`post-meal movement` (INTERVENTION) and `postprandial glucose` (PHYSIOLOGY)
five thousandths apart. Two near-equal cosines mean the query sits BETWEEN
two concepts, which is an ambiguity, not a statement that they are the same.

**Each tier owns its threshold** (`TIER_THRESHOLD`); exact tiers map to
`None`, because an alias hit is an identity and not a confidence. Below the
semantic FLOOR the tier says nothing at all, so a genuinely new concept —
`1-deoxynojirimycin` at 0.613 — stays free to AUTO_CREATE instead of
becoming a LOGGED near-match with no concept created.

**A weak tier answer no longer ends the chain.** A trigram near-match at
0.778 used to return LOGGED and the semantic tier was never reached.

**THE SEMANTIC TIER ATTACHES NO ALIAS.** A confirmed alias is an identity
rule the alias tier reads at 1.0 forever, bypassing every guard on the
strength of one cosine score; the first version confirmed one at 0.8211 onto
a SEEDED concept. Unconfirmed does not fix it: **`_tier_trigram` reads
`concept_aliases` without filtering on `confirmed`**, so the row still
returns 1.0 there. That missing filter is pre-existing and reported, not
changed. `normalization_cache` — not the alias table — is what stops a
repeat phrase costing a second call.

**The type guard applies to the SIMILARITY tiers only, and refuses rather
than shopping.** Applied to the exact tiers it refused `postprandial
glucose` against the concept named `postprandial glucose`. If the top
candidate is the wrong kind of thing the tier answers nothing — picking the
second-best BECAUSE it matches the expected type manufactures the answer the
caller asked for.

**`allowed_types=None` MEANS UNKNOWN AND IMPOSES NOTHING.** Only a caller
that structurally knows may supply a type: §R11 defines `target` as "the
measured or claimed outcome" and `intervention` as "what is being done or
taken", so K09 reading those fields knows without inspecting a word. K11's
`role` is the MODEL's assertion and is not used. **Measured: assuming the 43
unknown-provenance phrases were interventions refuses 12, of which ELEVEN
are correct resolutions it would have destroyed.** A type guard without a
trustworthy source type is not a guard.

**`mechanism` reaches NO concept resolver** — `knowledge_extract`,
`knowledge_synthesize.claim_phrases` and `evaluate.py`'s layer B answer key
all sent it. It is unchanged on the claim, and a test asserts both halves.
That the D47 mechanisms were fabricated is D49's defect and is neither fixed
nor hidden by this.

**`resolve()` IS NO LONGER FREE.** Every phrase the cheap tiers cannot
answer costs one embedding call. It degrades to a NAMED skip with no
pgvector, no `MODEL_EMBEDDING`, no `LLM_API_KEY` or nothing embedded (V3) —
the tier is inert on the VPS by configuration, and enabling it is a spending
decision.

**Three of the four WRONG are decided by margins of 0.0112, 0.0036 and
0.0006.** A margin rule is the obvious next change and is deliberately NOT
made: sized to fix those three rows it would be fitted to three rows.

**CALIBRATION IS NOT SOLVED.** 0.82 is PROVISIONAL, and the
production-relevant 49-phrase set still carries **4 known WRONG
resolutions**. The safety work since (`034`–`036`) makes the resolver
harder to bypass; it does not move a single number in the sweep, and
nothing in it should be read as settling the threshold.

**The sweep must run on a CLEAN K1 SEED.** `test_concept_layer` and
`test_knowledge_layer` insert SEEDED concepts under the K1 seed's own
canonical keys, so after `run_all.sh` the ontology is 275 differently-named
concepts and the same sweep scores 17 WRONG.

**DO NOT TOUCH `prompts/` FOR A LONG PHRASE.** §39 specifies `mechanism`
as "the mechanism the source proposes" — a proposition — and the engine
complied; every one of the D47 mechanisms exceeds 60 characters because the
specification asks for a sentence. The bug was always the CALLER sending it
to a concept resolver, and that is fixed. Shortening an authoritative
specification to make a resolver's life easier would be hard rule 1 in
reverse.

**THREE BYPASS PATHS FOUND BY REVIEW AND CLOSED (migrations `034`/`035`).**
Each was a guard that existed with a path around it, each is proven by
reverting the fix and watching the suite go red, and **none moved a number
in the sweep** — it is byte-identical before and after, which is why a green
measurement did not find them.

1. **THE CACHE ANSWERED WHAT THE RESOLVER WOULD REFUSE.** Keyed on
   `phrase_norm` alone and read BEFORE `allowed_types`, the type guard, the
   candidate set and `confusable_with()`. A phrase resolved with no caller
   type knowledge was served unchanged to a caller that had it; and a
   do-not-merge pair added AFTER caching could never invalidate the row,
   because the objection lives in the CANDIDATES and a one-concept answer
   spans nothing. `034` stores `candidate_ids`, `cache_is_safe()` re-runs
   both guards on every read, and a failed check is a MISS that resolves
   properly rather than a deleted row.
   **`resolved_under_types` is PROVENANCE, not the check**: NULL means the
   type was UNKNOWN at write time, which is NOT "valid for every type". The
   check is the cached concept's own type against the READER's set. A row
   written before `034` has no candidate set and is refused, because "we
   cannot check" is not "we checked".
2. **A STRUCTURALLY KNOWN INTERVENTION BECAME A PROPOSED PHYSIOLOGY.**
   `_propose_new(..., "PHYSIOLOGY")` was a literal at the end of the chain,
   so `soleus push-up` from an `intervention` field became PHYSIOLOGY and
   undid the type work above it. There is no honest narrow type — §R11 does
   not say EXERCISE rather than FOOD — so a phrase typed only to a SET now
   gets a `concept_proposals` row carrying that set, decision `NEEDS_TYPE`,
   and **no concept at all**. A set of exactly ONE is knowledge and is used.
   `v_concept_needs_type` is a READ, not a queue (hard rule 3), and these
   rows are not counted against D8's escalation cap.
   **One attempt now leaves ONE row**: the rejection branch used to write
   LOGGED and then fall through to AUTO_CREATE, two rows disagreeing.
3. **AN UNCONFIRMED ALIAS RESOLVED THROUGH TRIGRAM.** `_tier_alias` filters
   `a.confirmed`; `_tier_trigram` did not, so an unconfirmed alias equal to
   the query scored 1.0 and resolved the phrase through the back door.
   "Unconfirmed" meant nothing. Now filtered in both tiers, with the suite
   asserting both directions.

**THE CACHE IS BOUND TO AN ONTOLOGY REVISION (migration `036`).** `034`
re-runs the guards over the STORED candidate set, and that cannot see what
was never a candidate: **a concept added later was not in the set, so no
re-check of the set can surface it**, and every entry decays as the library
grows. The case that settles it is a CONFIRMED ALIAS — the alias tier runs
first and is exact, so a cache serving an older concept over one is
overriding a deliberate human decision, not a stale score.

`ontology_revision` is one counter; a cache row records the revision it was
resolved against and a read at a different revision is a MISS. **Nothing is
re-embedded on a bump** — the row is overwritten when the phrase is next
actually resolved, so invalidation is LAZY.

**THE TRIGGER SET IS COLUMN-SCOPED, AND THAT IS NOT FUSSINESS.**
`retrieval.py` writes `retrieval_hits` on EVERY retrieval read, so a
trigger on any write to `concepts` would have every search invalidate the
whole cache — the opposite of D2. Bumps: a live concept inserted or
deleted; a live concept's `status` crossing the SEEDED/ACTIVE boundary, or
its `canonical_name`, `canonical_key`, `concept_type`, `embedding` or
`merged_into` changing; a CONFIRMED alias appearing, vanishing or changing;
a `CONFUSABLE_DO_NOT_MERGE` relation changing. Does NOT bump: telemetry,
`definition` (no tier reads it — the re-embed bumps on `embedding`),
embedding provenance columns, `parent_concept_id`, a PROPOSED / MERGED /
DEPRECATED concept, an UNCONFIRMED alias, and any other relation type.
Transition tables, not `UPDATE OF col`, so `set status = status` does not
bump.

**MEASURED, so the cost is not discovered in Wave 1.** A global counter
invalidates 100% of the cache, and the realized bill is one embedding per
phrase ACTUALLY RE-ASKED: mean **$0.0000017** a call, so a full re-walk of
the D47 source's 56 phrases is **$0.000094** and a 100,000-phrase library
is ~$0.17. And the counter barely moves where it would hurt: **0 bumps**
across a full K09 ingestion and **0** across a curated import, because the
common write is a PROPOSED concept. Per-concept-neighbourhood scoping was
rejected — a new concept has no prior relationship to any stored
neighbourhood, which is the bug itself.

**TWO HOLES IN `036`, CLOSED BY `037`** (append-only; `036` is not edited).

1. **`036` DOCUMENTED THAT `embedding` BUMPS AND NEVER COMPARED IT.**
   `embed_library.py` updates an EXISTING row's vector whenever its text
   changed, and `_tier_semantic` ranks on that vector, so a re-embedded
   concept became the better answer with the revision unmoved and the stale
   row still served. **The branch is decided at MIGRATION time** — `037`
   inspects `pg_attribute` once and compiles one function or the other —
   because `concepts.embedding` exists only where pgvector was present at
   `002`, and checking the capability inside the trigger would put a table
   read on the path of every `retrieval_hits` write.
   **A deployment that gains pgvector later gets nothing, consistently**:
   `002` creates the column and the capability row together and no later
   migration adds either, so vectors are simply not used. A future
   migration that turns it on MUST rebuild `trg_ontology_concepts_upd()`,
   and that is a TEST rather than a comment — the trigger body must mention
   `embedding` **iff** the column exists, asserted on every floor.
2. **"The trigger is the only thing that should ever move it" WAS NOT
   ENFORCED.** `bump_ontology_revision()` was SECURITY DEFINER with no
   REVOKE, and PostgreSQL grants EXECUTE to PUBLIC by default — any role
   could invalidate the whole normalization cache on demand. **Granting
   `phi_runtime` EXECUTE would recreate the hole**: it is exactly the role
   that writes confirmed aliases, so it must be able to CAUSE a bump
   without being able to ASK for one. The trigger functions are SECURITY
   DEFINER and own the privilege; EXECUTE on the bump is revoked from
   PUBLIC; PostgreSQL checks a trigger function's EXECUTE at CREATE TRIGGER
   time, not at fire time, so the triggers still work. `search_path` pinned
   to `public, pg_temp`, references schema-qualified.

Raised and NOT fixed: the relation trigger bumps on a note-only edit to a
`CONFUSABLE_DO_NOT_MERGE` row — broader than documented, safe direction.

## GATE 3 — the bridge is built; its FIRST RUN was a MISS (2026-09-19, D52)

`docs/evidence/gate3_first_run.md` has every row. Migrations `038`/`039`,
`scripts/curated_concepts.py`, `testing/test_gate3_acceptance.py`.

**THE CURATED TEXT DID NOT MOVE.** `curated_strategies` is a THIRD ROW
SOURCE inside `by_concept()` and `by_fts()` — the same channels, score
normalization, merge, cap and rerank, the way `implementation_patterns`
already is. Copying `curated_fields.text_value` into `strategies` was
rejected: the copy retrieval would return is the one with no span and no
verbatim guarantee, in `strategies.mechanism`, the exact column D49
measured K09 fabricating on this document.

**THE FIRST RUN MISSED — 6 of 8. Strategies 2 and 5 were off the page, and
so was Strategy 3, so the negative-control checks did not execute.** A
check that did not run is not a check that passed. That result is section
4 of the evidence file and **is never replaced by the tuned one**.

**The relative ordering of the six cards was already exactly the frozen
expectation: 4, 1, 6, then 2, 5, then 3 LAST.** The negative control works
on relevance, with no line of retrieval code knowing the word "vinegar".
The miss is page COMPOSITION — 82 of 124 merged results are `kind:
concept`, each its own bucket so the per-bucket cap cannot restrain them.
The post-first-run fix is the `kinds` filter `retrieve()` has always had;
**no retrieval code changed**, and every run still prints what the
default-kinds retrieval returned so the miss stays visible.

**CONCEPT UNITS COME FROM A REGISTRY** (`curated_concept_rules`), each rule
stating why its construct is reusable. **A unit is a NAME, not a sentence,
and the discriminator is GRAMMATICAL** — no sentence-ending punctuation,
comma, quote or arrow; not colon-terminated; at least one lexeme from
PostgreSQL's own dictionary. **There is no character count in it**: a
length threshold is a number that can be moved until a fixture passes.
20 units, **17 bold runs refused as statements and reported**, 2 linked.
The conditional clauses inside `client_decision_logic` are prose and stay
UNLINKED — turning one into a concept phrase needs a claim extractor, and
the claim extractor for curated content is K09 (D49).

**18 of 20 units and 21 of 24 client-profile lines resolved to nothing.**
The K1 seed has no concept for `Breakfast restructuring`, `Client
overwhelmed`, `Metformin` or `Vinegar`, and `read_only=True` created none
(D8). **A library state, reported — not a number to improve by creating
concepts.**

**EVERY LINK CARRIES THE PHRASE AND ITS BYTE RANGE, AND THE RANGE IS
CHECKED.** `ck_link_span_is_phrase` refuses a span that cannot contain its
phrase; `verify()` re-reads the preserved raw file before anything is
stored, and the suite proves it has teeth by moving a span three
characters. D48: a populated location field is not provenance.

**Strategy 6's `client_decision_logic` survives retrieval as its own
field**, verbatim at `[9452:10643]` of the original — the block K09 lost
entirely and GATE 1 recovered.

**`client_decision_logic` DOES influence what comes back** (full text
ranks the card as one document). **Full text has no notion of negation**,
so "LOWER PRIORITY when X" matches a query about X exactly as "prioritize
when X" does; separating indication from contra-indication is E1 Pass B.

**Curated cards are NOT in the vector channel** — no embedding column —
and `diagnostics["curated_vector"]` says so on every retrieval.

**Found and fixed:** `by_vector()` guarded on `MODEL_EMBEDDING` and not on
`LLM_API_KEY`, so a configured model with no credential reached the live
endpoint and raised 404 where V3 requires a named degradation.

**Reported, NOT fixed:** a curated source is chunked by K08 AND parsed
into cards, so its content is on a page twice.

**`test_gate3_acceptance.py` is in `run_all.sh` and SKIPS there** — a full
run leaves the ontology at 269 live concepts and **0 embeddings**, the
same clean-seed condition D51 records for the sweep. It is run against a
clean rebuild. Which suite empties the column is **unresolved and stated
as such**, not guessed; it is pre-existing.

**The 20-video pilot stays closed.** K10 remains closed (D48). One source,
one synthetic client.

### GATE 3 REVIEW CLOSED — the bridge is now in the runtime (D52a)

**GATE 3 WAS NOT IN THE RUNTIME.** `retrieval.py` was imported by NO script
outside the suites, and `client_new.py` handed Engine 7
`NORMALIZED_CONCEPTS` and **no knowledge at all** — so a real case could not
consume the curated strategies this branch made retrievable, and the
post-first-run `kinds` fix lived only in the acceptance test. **A bridge
nothing crosses is not a bridge.** `retrieval.case_knowledge()` is the ONE
assembly both client pipelines call; CLIENT_NEW has a `RETRIEVE` step
between `NORMALIZE` and `E7`, and CLIENT_FOLLOWUP has one before its E1.

**`CASE_KINDS` IS STATED BY THE CALLER, never inherited.**
`retrieval.KINDS` includes `concept` — ontology vocabulary, right for an
ontology query, wrong for a case, and the first run measured what it costs:
27 of 30 places. **The query is Pass A's own phrases and research
questions**, which is its statement of what matters and is identity-free by
construction, not by a filter somebody remembers.

**A CURATED CARD IS EXPANDED, NEVER FLATTENED.** Every preserved field with
its provenance and byte range, so `client_decision_logic` stays its own
field. Collapsing into `summary`/`mechanism` rebuilds the shape GATE 1
refused to write and is how K09 lost it (D49). **`RANKING_BASIS:
RELEVANCE_ONLY` is a FIELD on the block** (D43): retrieval supplies
knowledge, E7 reasons, Pass B decides. Pass B gets `E7_HANDOFF` AND the
block — relaying only through prose makes arrival depend on an engine
having repeated it. Pass A, E2 and E3 do NOT get it.

**n8n PARITY — ANSWERED.** `workflows/run_engine.json` is RUN_ENGINE alone:
it takes `STRUCTURED_INPUT` from its caller and constructs no CASE payload,
and there is no other workflow file. **Python and n8n cannot disagree today
because only Python assembles it.** Whoever writes the n8n CLIENT_NEW must
build the same E7 input, `RETRIEVED_KNOWLEDGE` included, under D26/D31.

**A MISSING OPTIONAL CAPABILITY MUST NEVER DEGRADE ESTABLISHED KNOWLEDGE.**
`store_units()` deleted every link and rewrote what that run resolved — and
the semantic tier is inert on the VPS **by design**, so a re-import there
would have turned a verified link set into zero links and called it a
successful import. Recomputation is now four-state: **`RECOMPUTED`**
(authoritative — the ONLY state that may delete), **`FIRST_ATTACHMENT`**
(no prior links, nothing to lose), **`NOT_RECOMPUTED`** (preserved
untouched, reason reported), **`FAILED_CLOSED`** (prior links no longer sit
on the text they name, so they are deleted rather than kept — retaining a
moved span fabricates provenance, D48). Authority is
`normalize.semantic_tier_available()`, the SAME predicate `_tier_semantic`
acts on, extracted so there is one implementation; decided ONCE per import
before any card is touched. The staleness test is the containment check
itself, not a hash kept in step.

**THE NEGATIVE CONTROL COULD PASS VACUOUSLY.** `if n in rank and low[0] in
rank` ran ZERO comparisons on the first run and the suite could still exit
0. Presence is now its own failable check and the comparisons are COUNTED.

**`testing/test_gate3_bridge.py` IS THE DETERMINISTIC REGRESSION** — no
provider, every floor, because the acceptance suite SKIPS in every
`run_all.sh`. **GATE 2 owns phrase→concept; GATE 3 owns established
concept→curated knowledge.** It RECEIVES K1 concept ids and **manufactures
no semantic corpus**: fabricating vectors would be inventing GATE 2's
answer and then testing it, and would quietly become evidence that 0.82
works. Only phrase→concept is supplied; units, spans, verification and the
insert are production. Its rank fixture asserts the two cards do not merely
TIE (V2), and its RUNTIME section runs the real
`client_new.run_new_client()` and reads what was actually sent at the
PROVIDER BOUNDARY — the request is client data and is not persisted (D28),
so that boundary is the only honest place to look. A test that calls
`retrieval.py` is not proof of runtime integration.

### GATE 3 REVIEW ROUND 2 — availability is not authority (D52b)

**`semantic_tier_available()` WAS DOING TWO JOBS.** D52a made it the authority
for replacing a curated link set, and it answers "CAN the tier execute?" —
satisfied by **one** embedded concept. **Partial embedding coverage is an
ORDINARY SUPPORTED STATE here**: `embed_library.py` batches 25 and reports
`still_stale`. So a run that simply could not SEE a concept could mark itself
authoritative and delete a link a complete run established — the same failure
class as D52a, one level narrower, from a capability check that was **true for
the wrong reason**.

**TWO PREDICATES, NEVER SYNONYMS.** `normalize.semantic_tier_available()` = can
it run. `curated_concepts.semantic_recomputation_authoritative()` = may its
SILENCE delete. The second additionally requires **complete fresh coverage** —
`embed_library.stale_count()`, the ONE freshness definition the loader already
uses (embedding null, hash null, or hash ≠ current `search_text`), never a
second formula that would drift — and a **coherent pinned model**, because D34
pins one model per column and `trg_embedding_coherent` stops a second being
WRITTEN but cannot stop a caller QUERYING with one.

**GATE 2's OPERATIONAL BEHAVIOUR IS UNCHANGED, and a test asserts it**: the
tier stays AVAILABLE in exactly the states where recomputation is refused. Only
the authority to DESTROY got stricter.

**`RETRIEVED_KNOWLEDGE` ARRIVED AT THE ENGINES AND WAS DEFINED IN NONE.** D52a
proved it reaches the provider boundary; that is not proof any engine has a
contract for using it. **Measured, it was not the exception — NONE of the
top-level blocks CLIENT_NEW composes appeared in any prompt**: not
`CANONICAL_STATE`, `E1_PASS_A_HANDOFF`, `E7_HANDOFF`, `NORMALIZED_CONCEPTS`,
`CASE_RESEARCH_QUESTIONS` or any `_HANDOFF`. **The runtime input contract had
never been written down for anything.**

All of them now are, in the **build-owned Addendum A** each prompt already
carries — `## A5` (E1), `## A6` (E2), `## A7` (E3), `## A8` (E6), `## A9` (E7).
**The practitioner's specification is untouched** (hard rule 1) and the
manifest's `sections` count is **unchanged for all seven prompts**, because
`SECTION_RULE` does not count `## A`-form headings. Prompt hashes changed and
were reloaded through the registry.

E7 CASE is told: **the library query has ALREADY been run and this is its
result** — read it first; `RANKING_BASIS: RELEVANCE_ONLY` is never clinical
priority; use `ITEMS` before declaring `KNOWLEDGE_SUFFICIENT: false` or
`LIVE_RESEARCH_REQUIRED: true`; a `curated_strategy` is practitioner
intelligence, **not published evidence**; `client_decision_logic` is
professional judgement that does not need re-researching to be used; the three
layers stay separate (§67). E1 is told: **Pass A gets no retrieval because it
is what decides what to retrieve**; on Pass B `E7_HANDOFF` is the REASONING and
`RETRIEVED_KNOWLEDGE` the preserved RETRIEVAL beside it, so a
practitioner-authored field arrives verbatim rather than depending on Engine 7
having repeated it; rank is relevance; **Engine 1 remains the decision-maker**.

**THE REGRESSION ASSERTS CONTRACT PRESENCE, NEVER MODEL WORDING.** It drives
the real CLIENT_NEW pipeline, captures each engine's actual `structured_input`
keys from the real request objects, subtracts intake-derived fields using
`intake.to_e6_input()` **itself** rather than a hand-written exclusion list that
would go stale with the intake schema, and checks the receiving engine's ACTIVE
prompt row. **22 blocks.** Proven to have teeth by deleting `## A9`, reloading,
and watching five go red. Provider-boundary delivery is asserted separately.
The append-only registry refused a direct tamper of the stored content
(`trg_engine_prompts_append_only`) — the guard working.

**Reported, NOT closed:** CLIENT_FOLLOWUP's own blocks (`E4_HANDOFF`,
`E6_DELTA`, `LIVE_INTERVENTIONS`, `FOLLOWUP_ANSWERS`, `FOLLOWUP_STRUCTURED`,
`CURRENT_STATE`, `REVIEW_PERIOD`) have the same pre-existing gap. The
regression covers CLIENT_NEW as the review scoped it; `RETRIEVED_KNOWLEDGE` on
that path IS covered, because E1's `## A5` names it.

### GATE 3 REVIEW ROUND 3 — the contract named the wrong mode (D52c)

**D52b's Engine 6 section said those blocks arrive "on an `UPDATE` run".
CLIENT_NEW calls Engine 6 with `mode="REBUILD"`** — the step is only NAMED
`E6_UPDATE`, and A1 already explains why REBUILD: a delta's fields describe
changes and do not map onto the state's fields. The `<RUNTIME_INVOCATION>`
envelope said REBUILD while the contract governing it said UPDATE. A8 is now
organised BY MODE: `INIT`, `REBUILD`, and `UPDATE` named as the follow-up
path whose contract is deliberately not declared.

**THE THIRD PRESENCE CHECK IN THIS GATE.** D52b's regression asked `if key
not in content` — *does this word appear anywhere in the prompt?*
`E1_HANDOFF` appeared, under an UPDATE paragraph, and a REBUILD invocation
passed. Same shape as the first-run negative control (`if n in rank and
low[0] in rank` ran ZERO comparisons and stayed green) and as "the block
reaches the provider boundary" (an engine with no contract for it).
**BEFORE TRUSTING A CHECK, ASK WHAT IT WOULD STILL PASS ON. If the answer
includes the bug it exists to prevent, the check is decorative.**

**DECLARATIONS ARE COMPARED AS SETS, PER INVOCATION.** Each build-owned
Addendum carries `RUNTIME_INPUT_CONTRACT E6/REBUILD = CASE_VERSION, ...`.
**The key is the invocation as the RUNTIME RECORDED IT** — the test reads
`engine_runs.engine_mode` and `pass` (D27's stored mode, what the envelope
carried), so a step named `E6_UPDATE` running in REBUILD is keyed
`E6/REBUILD`; a check keyed on the caller's label would have agreed with the
wrong one. Set equality **both directions**: undeclared-but-sent,
declared-but-not-sent, and either attached to the wrong mode. All three
proven by breaking them. Seven invocations, and the COUNT is asserted
because a loop over an empty capture passes having inspected nothing.

`INTAKE_PAYLOAD` is the one sentinel: E6 INIT receives the converted intake
submission, and it expands to what `intake.to_e6_input()` itself produces —
never a hand-written list that would go stale with the intake schema.

**THE FOLLOW-UP E1 RUNS ONCE, `pass = SINGLE`, AND GETS NO `E7_HANDOFF`** —
Engine 7 does not run on that path, so `RETRIEVED_KNOWLEDGE` is the only
library input and nothing will have reasoned over it first. E1's A5 says so.
**No declaration line is written for it**: a declaration is a COMPLETE set,
and completing it means settling the whole follow-up contract, which is a
pre-existing cleanup recorded rather than guessed at. E7's seven
knowledge-clock modes are undeclared for the same reason.

### GATE 3 REVIEW ROUND 4 — the contract key needed a pipeline (D52d)

**`(engine, mode, pass)` DOES NOT DETERMINE THE PAYLOAD.** `client_new.py:571`
and `client_followup.py:393` BOTH call `engine="E6", mode="REBUILD"`, for the
same stated reason, and hand it completely different things — CLIENT_NEW's six
blocks against the follow-up's thirteen (`FOLLOWUP_ANSWERS`, `CURRENT_STATE`,
`LIVE_INTERVENTIONS`, `E4_HANDOFF`, `E6_DELTA`, …). `E2/SINGLE` and
`E3/SINGLE` collide the same way once Engine 4 routes `MULTIPLE`. D52c's
declaration would have read as the governing contract for a follow-up
invocation, and a checker would have reported that payload as violating a
contract that was never about it.

**DECLARING NOTHING IS A POSITION AND HAD TO BE EXPRESSIBLE.** D52c said the
follow-up contract was "deliberately not declared" and the syntax could not
say it — a line already existed for those triples, written for the other
pipeline. The key is now **`PIPELINE ENGINE/MODE/PASS`**, and the absence of a
`CLIENT_FOLLOWUP` line now means what it says.

**ONE PARSER** — `testing/runtime_contract.py`, read by `test_client_new.py`
(CLIENT_NEW's invocations must match exactly, both directions) and
`test_followup.py` (the follow-up's must NOT silently fall under them). Two
copies of the regex would be two definitions of the contract.

**THE REGRESSION DRIVES THE REAL COLLISION**, routing `MULTIPLE` so E1/E2/E3
actually run rather than the E2/E3 half being assumed, and asserts that **a
pipeline-blind lookup would have collapsed all three onto CLIENT_NEW's
contract and reported false violations**. Reverting the key to three parts
turns BOTH suites red.

**CLIENT_FOLLOWUP's contract is still deliberately undeclared.** Completing it
means settling every block that path sends, which is a separate cleanup. E1's
prose about `RETRIEVED_KNOWLEDGE` on the follow-up's `pass = SINGLE` run stays
and the regression asserts the block arrives — but prose about one block is
not a complete declaration and is not presented as one.

### GATE 3 REVIEW ROUND 5 — the prose was still mode-only (D52e)

D52d scoped the MACHINE declaration by pipeline and left Engine 6's `A8`
PROSE organised by mode — *"`REBUILD` — the end of a new-client cycle. You
receive `CASE_VERSION`, `CANONICAL_STATE`, `NORMALIZED_CONCEPTS`, …"*. True of
CLIENT_NEW, **false of CLIENT_FOLLOWUP**, which invokes `REBUILD` for its own
final state reconstruction and receives neither `CANONICAL_STATE` nor
`NORMALIZED_CONCEPTS`. **The declaration a MACHINE reads was scoped and the
paragraph a MODEL reads was not** — the checker could no longer be misled and
the engine still could.

`A8` is organised BY PIPELINE first now, and says explicitly: **DO NOT APPLY
THE CLIENT_NEW `REBUILD` FIELD LIST TO A FOLLOW-UP RUN.** No
`CLIENT_FOLLOWUP` declaration was created — the absence is still the
deliberate position. Declarations byte-identical, `sections` unchanged at 89,
one file touched.

**The first live call to any real API in this build FAILED, and the
failure was informative.** The actor answers HTTP 201 from a SUCCEEDED
run and reports item-level failure in an `error` field nothing read; a
transient read failure and a genuinely caption-less video were recorded
identically as `FULL_TEXT_NOT_AVAILABLE`, which is not rediscoverable, so
a readable video was permanently marked unreadable. Both real payloads
are now fixtures. **Both set `isAutoGenerated: false`, never null** — the
"NULL never means human" rule is not something the provider gives us for
free; what protects the envelope is that a failed item never gets one.

**The rolling-caption overlap is a TIMING artefact, not a text one.** On
the real 391 segments, 386 pairs overlap in time, **one** has a text
match, and the single word dropped was a speaker saying "Woo!" twice. The
"naive concatenation duplicates words throughout" premise in D46 and in
`test_youtube.py`'s hand-written fixture is wrong for this actor. Raised,
not changed: altering `dedupe_segments()` changes every future
transcript.

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
