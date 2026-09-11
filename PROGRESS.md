# PROGRESS

## STATE AS OF 2026-09-10 — RUNNING ON REAL INFRASTRUCTURE

Read this first. The sections below are the working record and are written
in the order things happened, so a few of them describe a position that a
later section supersedes. Where they disagree, this summary is current.

**The distinction this record now makes, and did not before:**

| | |
|---|---|
| **Container-verified** | ran on a PostgreSQL this build controls, on a developer machine or in CI, usually with trust auth and a superuser DSN |
| **Infrastructure-verified** | ran on the Hostinger VPS, on a database it does not control the surroundings of, with real roles, scram passwords over TCP, alongside three live business automations |

They are not the same claim and the second is much stronger. Everything
below is container-verified; the section *Deployed to the VPS* says what is
now infrastructure-verified as well. **The reason to separate them is not
bookkeeping.** Everything passed in containers for weeks while
`RUN_ENGINE` could not have run as `phi_runtime` at all (D25) — trust auth
and a superuser DSN hid it. Container-green is evidence about the code, not
about the deployment.

**Build steps 1–15 are complete and verified against a real PostgreSQL,
not inspected by eye.**

| | |
|---|---|
| Schema | 31 migrations, 97 tables, 41 views, 55 enums, 255 indexes, 103 check constraints, 54 triggers, 62 policies, 31 RLS tables |
| Suites | **28** (`ls testing/test_*.py | wc -l`, and the same 28 names in `run_all.sh`'s loop), green from an empty database, each run followed by a re-run, and in three configurations: full, no optional extension, and **`MODEL_EMBEDDING` unset with pgvector present** |
| CI | `.github/workflows/tests.yml` — every push on every branch, **with and without pgvector** |
| Engines | All seven canonical prompts installed; E6 → E1 Pass A → E7 → E1 Pass B proven **live** |
| Ontology | 26 domains, 269 concepts seeded from the curriculum, hash-verified |
| Registries | **Four**: prompts (`010`), contract (`012`), handoffs (`013`), prices (`016`) |
| Backup | Restore drill performed 2026-09-10; roles gap found and fixed |
| Bugs | 68 found and fixed, each with a regression test |

*Counts measured 2026-09-10 against the local full-capability database, not
carried forward: `pg_tables`, `pg_views`, `pg_type typtype='e'`,
`pg_indexes`, `pg_constraint contype='c'`, `pg_trigger NOT tgisinternal`,
`pg_policies`, `pg_tables.rowsecurity`, all filtered to `public`. Earlier
entries in this file used a different (unrecorded) method and do not
reconcile with these; re-measure rather than adjusting them.*

**D5 is ANSWERED and Engine 1 is not to be staged.** Measured on a live
provider 2026-09-09 (see *D5 ANSWERED* below):

```
E6     18,909 →  12,580   $0.061   41s
E1  A  20,869 →  32,687   $0.138  117s
E7     20,558 →   8,885   $0.049   34s
E1  B  20,922 →  32,529   $0.138  115s
CYCLE  81,258 →  86,681   $0.386  306s
```

Both passes produced complete 19-part reports (116,661 and 116,436 chars)
on one prompt hash. Second-half-to-first-half ratios **1.07** and **0.98**:
the back of the report carries as much as the front. If splitting Engine 1
is proposed again, the measurement is one command and the answer is
currently no.

**Cost, measured rather than estimated:** ~$0.39 per 4-call measurement,
so a full 8-call new-client cycle lands near **$0.75–0.80** on
`gemini-3.8-flash`. The free tier (20 requests/day/model) is not viable for
this system — billing is a prerequisite, not an optimisation.

**Step 11 is COMPLETE and FROZEN.** `workflows/run_engine.json` is built,
14 nodes, and proven byte-identical to `scripts/run_engine.py` on one
golden corpus: 15 requests identical to the byte, 15 responses identical
field for field, and the workflow's **SQL executed** against a real
database as `phi_runtime` (D31). The JavaScript under test is extracted
from the workflow at run time, so a copy cannot drift from it. No further
step-11 work is to be started; changes to it are bug fixes only.

**The case track runs end to end.** `scripts/client_new.py` takes a
submitted intake to the practitioner's review queue: E6 → E1 Pass A →
normalization → E7 → E1 Pass B → E2 → E3 → E6, on one prompt hash. It
stops at the queue by design — Engine 5 is gated on a practitioner
decision, and an open HOLD never stops the analysis (hard rule 9).

### Before the first full synthetic case is run — set expectations now

**Engine 7 will retrieve from an empty library, and Engine 1 Pass B will
reason from an empty retrieval set.** That is expected and it is not a bug.
The Knowledge Factory is step 16 and has not been built; until it has run,
there is nothing in `strategies`, `evidence_records`, `claims` or
`knowledge_chunks` to retrieve. A first full case will therefore produce a
structurally complete report whose evidence citations are thin or absent.

Read that as the library being empty, never as Engine 7 or Pass B being
broken, and do not "fix" it by loosening a floor or a gate.

**Step 16: K07–K11 are built and tested.** One source runs the complete
loop, on the fixture provider, with every boundary asserted:

```
inbox → raw preserved → normalized → claims extracted → concepts
normalized → delta analysis → evidence researched → strategy decided
                                        (CREATE / UPDATE / MERGE / NO_CHANGE)
```

| | |
|---|---|
| K07 + K08 | `knowledge_ingest.py` — deterministic, **no model call** |
| K09 | `knowledge_extract.py` — E7 `INBOX` → Claim Cards, concepts, §54 delta |
| K10 | `knowledge_research.py` — E7 `EVIDENCE` → independent evidence + the claim's reading |
| K11 | `knowledge_synthesize.py` — E7 `SYNTHESIS` → four decisions, dedup done first |

**Discovery (K02–K06) is built too** — `knowledge_discover.py` and the
`acquisition.py` chokepoint. Five ways to arrive, no new way to process.

### The embedding endpoint is live — verified 2026-09-10

`gemini-embedding-2` was called through `embedding.embed()` — the
production path, no stub — and returned:

```
model gemini-embedding-2   dims 1536 (column 1536)   L2 norm 1.000000028
```

Every check passed at the call: text-only, dimension against
`embedding_dim()`, unit norm inside `embedding_norm_tolerance()` (1e-3),
and the cost row priced `PRICE_REGISTRY` at the TEXT rate — 7 tokens,
$0.000001. So **D34 Option A is confirmed on the live provider**, not only
in the probe: 1536 dimensions come back already normalised, which is the
single thing `gemini-embedding-001` did not do.

Two calls in total, both incidental to a CLI smoke test. This is a
one-call verification of the wire format and **not** evidence about
throughput, rate limits or cost at corpus scale.

**K06: the YouTube adapter, shaped by the actor's REAL output.**

The actor `automation-lab/youtube-transcript` was run live on 2026-09-10
before any code was written against it. **The first guess at the input
field was `videoUrls`; it is `urls`.** One video cost **$0.01** — the
per-run start fee dominates a single-video run, so `run_actor()` takes a
list and the suite asserts two videos cost one run.

| | |
|---|---|
| `030` | the authorization note, `allowed_hosts`, transcript provenance columns, `uq_item_source_external`, creator external identity, `v_asr_derived_claims` |
| `youtube_apify.py` | de-overlap, canonicalisation, the timestamped markdown |
| `test_youtube.py` | 59 checks |

**The authorization is with APIFY, not from YouTube**, and the registry
note says so in those words. `allowed_hosts` is `api.apify.com` alone and
the suite asserts a youtube.com URL is refused by the same adapter.
Clearing the note — or unsetting `APIFY_TOKEN` — returns it to refusing;
both are the same finding, so a missing token is **recorded as a refusal**
and the item is `ACCESS_DENIED`, never a crash that takes a run down.

**There is no flat transcript field, and the segments OVERLAP.** Segment 1
runs 0 → 2.16 and segment 2 *starts* at 1.04 — YouTube's rolling-caption
format. Naive concatenation duplicates words throughout, and the damage
does not look like a joining bug downstream: it looks like a rambling
source, so claim extraction blames the speaker. The de-overlap gates on the
**timings**, not the text, and the suite proves the distinction with the
same words twice — with a time overlap (trimmed) and without one (kept
intact), because a speaker who genuinely repeats themselves must survive.

**`isAutoGenerated` was true — this is ASR.** It rides on the envelope,
reaches every chunk's metadata, and `v_asr_derived_claims` answers "which
conclusions rest on machine transcription?". NULL means *not a transcript*,
never "human". The view joins through `envelope_derived_records`, the
provenance registry hard rule 12 already requires — the obvious join via
`source_items.source_id` looks right and silently returns nothing.

**Identity is `videoId`.** The live input URL carried playlist and
timestamp parameters and the canonical id does not.

**`channelId` is the creator, not `channelName`** — a rename updates the
same profile instead of starting a second one holding half the history.
`creator_type` is `OTHER`: a channel id says who published, never whether
they are a researcher, a clinician or a coach.

**Timings reach the derived knowledge through the normalizer we already
have.** The transcript is markdown whose block headings ARE timestamps, and
`segment()` already turns a heading path into the chunk's `location`
(§16, §42). A claim citing minute 14 is provenance — with no second
ingestion path and no change to the chunker (D37).

**The chokepoint grew rather than the adapter growing a socket.**
`fetch()` gained `method`, `body` and `extra_headers`; the credential
travels in a header and `redact()` now strips credential-bearing query
parameters for every adapter, because `source_fetches.url` is permanent.

**Bug 67: `register_item()` raised a unique violation on a second
sighting**, taking the whole discovery run down — and seeing a source again
is the normal case. It is an upsert now, and a re-discovery never moves a
status backwards: resetting a `NORMALIZED` item to `QUEUED` would invite
the pipeline to run over it again.

**Bug 68: a suite left an adapter's authorization NULL.** The K06 section
of `test_discovery.py` cleared the note inside `with conn.transaction():`
and let it COMMIT, so every later suite ran against an adapter that had
quietly lost its authorization. Restored in a `finally` now. The shape is
V2's: the harness differed from production, and it differed *because of the
harness*.

---

## The first real source through the complete loop — 2026-09-11

**One video, live from Apify, end to end, then again.** Full record with
every row: `docs/evidence/first_source_loop.md`. `zg3GBH6fG2I`, "Move Like
This After Eating", Glucose Revolution — 391 segments, ASR, 13 chunks,
**7 claims, 16 evidence records, 6 strategy cards**, retrievable by a
later case query. **$0.4959** in 14 LLM calls, 0 UNPRICED, on the
no-pgvector / `MODEL_EMBEDDING`-unset floor the VPS runs.

**RUN 2 added nothing.** Same claims, same strategies, same proposals,
same evidence — same rows, not just the same counts. Caught twice: by
canonical URL in `register_item()` and by content hash in `open_envelope()`
(both fetches returned exactly 53,701 bytes). It DOES write a second
envelope row, deliberately, marked `DEDUPED` — and that row says two false
things, recorded in the evidence doc and NOT fixed: its note claims "the
source changed since it was last ingested" for byte-identical content
(§56's URL versioning runs before §57's hash dedup, unconditionally), and
its `content_hash` is NULL, so the row that exists because of a hash match
cannot be found by that hash.

**Three things had never executed against a real API and all three were in
the first stage.** `acquisition.fetch()` and its registry policy check, the
YOUTUBE adapter row, and `youtube_apify.py` parsing a live response. All
three worked. The bugs were elsewhere.

**Bug 69: the actor's `error` field was never read, and two different
failures were recorded as the same fact.** The FIRST live call returned
HTTP 201 from a SUCCEEDED run carrying a 532-byte item with every field
blank and `error: "Failed to fetch transcript XML: HTTP 404"`. A retry 63
seconds later returned 391 segments. Both that and a genuinely caption-less
video became `FULL_TEXT_NOT_AVAILABLE` — a claim about the VIDEO, and
deliberately not rediscoverable — so the adapter's first live run
permanently recorded a readable video as having no transcript. The actor
distinguishes them and we discarded the distinction. `actor_error()` now
carries its words verbatim; `reached_video()` decides which failure it is
from **metadata presence, not the wording of `error`**; `FAILED` (a
statement about an attempt) joins `REDISCOVERABLE` and
`FULL_TEXT_NOT_AVAILABLE` (a statement about the source) does not. Both
real payloads are fixtures under `testing/fixtures/apify/`. **Both set
`isAutoGenerated: false`, not null** — the "NULL never means human" rule is
not something this provider gives us for free.

**Bug 70: evidence was joined to claims by a TIME WINDOW.**
`evidence_for()` returned "every evidence record created after this claim,
newest 20". Seven claims from one video, six researched in one batch, so
the first claim collected **all 16** records — four of them about a
mulberry-leaf supplement researched for a different claim entirely, and the
strategy card would have cited them. Every suite passed over it because
**every fixture researches ONE claim**, where "written after" and "written
for" return the same rows: the fixture could not tell the right answer from
the wrong one (V2). Migration `031` adds `evidence_records.claim_id`
(`ON DELETE SET NULL` — the study outlives the claim that led us to it,
D10). Existing rows are left NULL rather than back-filled by timestamp,
because the timestamp is precisely the signal that was proven unreliable;
`v_evidence_without_claim` separates "older than the link" from "the link
exists and this row has none".

**Bug 71: `study_item()` could never record an identifiable study.** Bare
`%s is not null` parameters — `IndeterminateDatatype` before the query
runs. The identical bug, with the identical fix and a comment explaining
it, was already in `knowledge_discover.already_known()`. It survived
because every evidence fixture has no DOI, PMID or URL, so the function
returned at its first branch and **the SQL below it had never executed in
any test**; the one assertion over it tested the early return. Fixed with
explicit `::text` casts, and the new coverage drives the branch that
touches the database. Reverting the fix turns the suite red.

**Bug 72: `test_knowledge_factory`'s `clear()` never removed
`evidence_records`**, so every run of that suite added studies to the
library permanently — invisible until something started asserting over
that table, and indistinguishable from a live run's rows once one existed.
Deleted before the claims now, since `claim_id` is `ON DELETE SET NULL` and
dropping the claims first orphans the rows and takes the only handle on
them with it. **The wider gap is NOT fixed:** `test_youtube.py`'s `clear()`
also leaves claims and proposals behind, and "clear their own fixtures"
needs a pass of its own across the suites.

**Bug 73: an assertion that only held while the database was empty.**
`test_knowledge_layer`'s "podcast excluded from evidence-role sources"
compared an exact set over the WHOLE `knowledge_sources` table against
`{"Example Journal"}`. It passed for as long as nothing else had ever
carried the EVIDENCE role — and fixing bug 71 meant `study_item()` started
registering `Independent evidence (K10)`, which production does too, so
the suite went red on its SECOND run against a used database. Scoped to
the two rows the block itself creates. The bug is not the new row; it is
an assertion that depended on the rest of the database being empty and so
was not testing what it said it was.

### Two findings raised, deliberately not acted on

**The rolling-caption overlap is a TIMING artefact, not a text one.** On
the real 391 segments: 386 pairs overlap in time, **1** has a text
suffix/prefix match, **1 word** was dropped in total — and that one was a
speaker saying "Woo!" twice at 954.36 and 955.84, so the de-overlap ate a
genuine repetition rather than a redisplay. The actor returns clean
continuations. The premise in D46, in this file and in `test_youtube.py`'s
hand-written `OVERLAPPING` fixture — "naive concatenation duplicates words
throughout" — is wrong for this actor. Changing `dedupe_segments()` changes
the content of every future transcript, so it is raised here rather than
routed around.

**Concept normalization matched almost nothing, and that is the biggest
quality problem in the run.** 71 proposals, **one** resolution: `insulin
resistance`, by exact match. One near-match in the whole run
(`Postprandial glucose spike` → `postprandial glucose`, trigram 0.778,
LOGGED at impact 0). The K1 seed holds exactly the right concepts —
`post-meal movement`, `walking`, `post-meal glucose`, `skeletal-muscle
glucose disposal`, `exercise timing` — and the run reached none of them,
creating 51 PROPOSED concepts instead, 10 over 60 characters and 6
containing a subordinate clause. Three causes: the engine answers `target`
and `mechanism` with compound phrases and whole sentences;
**`normalize_claim_concepts()` calls `resolve()` with `llm=None`**, so the
LLM tier that exists for exactly this can never be reached from K09; and
with pgvector absent the semantic tier cannot run either — leaving alias
and structured matching as the only tiers that can ever fire here. The
downstream cost is visible one stage later: **4 of 6 strategies carry no
canonical concepts**, each correctly recorded as an OPEN gap (D8 behaving
right over a bad input), and the concept retrieval channel could offer only
two of six cards. Passing an LLM into K09's resolver is a spending decision
and a change to D2's ordering; it belongs to the practitioner and to
`DECISIONS.md`.

### What the output was actually like

Good, and in one respect better than the source. The card built on the
calf-raise claim says the ~50% figure came from a multi-hour protocol and
that brief bouts have limited direct evidence — the video did not. The
video's sponsor read for its own commercial supplement, whose only cited
support was "personal endorsement and customer testimonials", came out as
**"Mulberry Leaf Extract (DNJ) for Acute Postprandial Glycemic
Attenuation"** with four independent records and `evidence_confidence =
UNKNOWN`: brand dropped, bioactive kept, confidence not inflated. Full
provenance closes — strategy → claim → `[04:12]` → chunk → preserved raw
file → actor segment at t=252.2s.

**Do not begin the 20-video pilot yet.** At ~$0.50 a source it is ~$10 in
model spend, and §3 of the evidence doc is the reason to fix concept
normalization first: 20 sources would add roughly a thousand proposals and
several hundred sentence-shaped PROPOSED concepts to an ontology this run
reached exactly once.

**Step 23: practice intelligence — the fifth name with nothing behind it.**

`practice_strategy_outcomes` has carried `ck_min_cohort CHECK (n_clients >=
5)` since migration `003` and **had never held a row**. The constraint had
been passing every insert it never saw, exactly like
`client_interventions` (D42), `client_interventions.outcome` (D43),
`client_followups` (D43) and `KNOWLEDGE_DAILY_TOKEN_BUDGET` (D44) before
it. Step 21 is what changed: started interventions with recorded outcomes,
and `intervention_outcome_history` holding what each one replaced.

| | |
|---|---|
| `029` | four coherence constraints, `jsonb_counts_total()`, `adherence_band()`, `trg_practice_deidentified`, `uq_practice_generated`, `v_practice_cohort_candidates`, `v_practice_experience` |
| `practice_intelligence.py` | the aggregation, the labelled block, `--plan` by default |
| `test_practice.py` | 49 checks |

**The cohort counts PEOPLE, once each.** `n_clients` is distinct clients
with a recorded outcome, taking each client's latest — so five intervention
rows from two clients is a cohort of two, and one client's three attempts
is one observation. The database agrees rather than trusting the runner:
`ck_practice_outcomes_account_for_cohort` refuses a distribution that does
not sum to `n_clients`, and `jsonb_counts_total()` is `IMMUTABLE` so a
per-row `CHECK` can call it.

**The denominator travels with the numerator.** Five improved out of five
assessed, where thirty started it and twenty-five were never looked at, is
a selection effect with a number in front of it — and the two are the same
row unless the exposed count is stored beside the cohort.
`ck_practice_generated_complete` refuses a generated aggregate that cannot
say out of how many, over what window, with what distribution.

**Three states that all look like an absent row.**
`v_practice_cohort_candidates` separates "nobody ran the aggregator" from
"the cohort is three" from "eleven clients started it and **nobody has
assessed one**". Only the last is a standing failure to look, and it is the
one an absent row hides.

**A proposal nobody started is not experience** (`started_on IS NOT NULL`).
Counting proposals inflates every cohort with things that never happened.

**Counts, never copied client text.** No stop reason, adherence note or
outcome evidence leaves the client layer: at a cohort of five one verbatim
sentence is quasi-identifying. `trg_practice_deidentified` is the backstop
— a UUID, an email, a display name or an external ref is refused — and it
is `SECURITY DEFINER` because `clients` is RLS-forced and a check running
with the caller's visibility would compare against the one client in scope
and pass. The suite writes a distinctive token into a client's
`stop_reason` and asserts it reaches no column of the aggregate.

**The runtime reads aggregates and cannot create one.** `005` granted
`phi_runtime` DML on every global table before anything wrote to this one,
but aggregation is a cross-client read and `phi_runtime` is
single-client-scoped: the cohort would always be one person or zero. `029`
revokes INSERT/UPDATE/DELETE and keeps SELECT.

**Adherence never folds into outcome** (D43), at cohort scale too. Where
adherence is unrecorded for the majority the summary says a neutral result
there is *untested, not ineffective*. The suite asserts both directions —
a measured cohort carries no such caveat, so it is not boilerplate.

**The label is a column, not a caption.** `basis` and `evidence_status` are
fields on every row and on every block entry. The block reaches E7 and E1
Pass B as a **top-level key**, never nested inside `E7_HANDOFF`, and E4 on
the follow-up path; the suite drives the real CLIENT_NEW pipeline and
asserts both. Engine 1's Pass B section, Engine 7 §A4 and Engine 4 all
already said how to weigh practice experience — nothing had ever produced
it.

**Bug 66: `count(*)` over a LEFT JOIN counts the outer row.**
`v_practice_cohort_candidates` reported **one intervention for every
strategy nobody had ever started**. Caught by the fixture that gives six
clients a proposal none of them started and asserts the cohort is zero —
`count(e.intervention_id)` is the fix.

**Step 22: K00_FOUNDATION_CONTROLLER — and the budget that was a name.**

`KNOWLEDGE_DAILY_TOKEN_BUDGET` has been in `.env.example` since the
beginning and **nothing had ever read it**. That mattered nowhere while
every stage ran on fixtures or one item at a time under a human who could
see the bill. K00 is where it matters — a loop across 26 domains,
unattended — and an unenforced budget on that is the entire risk.

| | |
|---|---|
| `028` | `knowledge_spend_today()`, `foundation_progress`, `foundation_batches`, `v_wave1_readiness`, `v_foundation_queue` |
| `foundation_controller.py` | the loop: what runs next, where it is, when it stops |

**The controller adds no new knowledge work.** Every stage it drives
already exists (K02–K13). What it adds is the decision, the cursor and the
stop.

**It does not execute by default.** `--plan` is the default and
`--execute` is an explicit act, because K00 is the one component that could
begin mass ingestion unattended. `DISCOVER` and `INGEST` are not executable
stages at all — reported as **MANUAL with the reason**, never quietly
omitted.

**The cap is measured from `cost_events`**, not a counter the controller
keeps: a counter can be forgotten to increment, rows cannot. Client work is
excluded in **both** directions — a case neither eats the foundation budget
nor waits on it. **Unset means unbounded and says so**; no default is
invented, because that is a spending decision.

**Library stages are not per-domain, and pretending otherwise was a bug**
the first `--plan` caught: a claim belongs to a source, so running
extraction per domain had three domains claim the same item.
`CONTROVERSY` and `GAP` genuinely are per-domain (D41), so `Stage.scope`
separates them.

**The cursor is a row**, so a restart resumes rather than restarting every
domain from `DISCOVER`. A domain failing repeatedly is **paused with its
reason** rather than retried forever.

**`WAVE1_FOUNDATION_READY` is computed, never stored** — A4's four
dimensions at once, every one a floor. `foundation_stage` has no
`COMPLETE` (§70); `IDLE` stays in the queue.

**Step 21: CLIENT_FOLLOWUP and E4 — the second and every later cycle.**

```
follow-up -> E6 UPDATE -> E4 -> routing -> E1/E2/E3 -> E6 -> review
```

`client_followups` has existed since `004` and nothing ever read one;
`client_interventions.outcome` has existed just as long and **nothing ever
wrote one** — so `WORSENING_MARKER` read a column nobody had filled and
could never fire for any client. Engine 4 now emits §64B
`<PROGRESS_OUTCOMES>`, and the suite proves the rule finally fires.

**A follow-up is a different pipeline, not CLIENT_NEW with a flag (D43).**
Engine 4 is the routing authority: `ROUTING_RECOMMENDATION` — a **typed**
control-block field, never prose — decides which of E1/E2/E3 run, and an
unknown value **stops** rather than routing nowhere. The contract also
refuses a recommendation carrying no `ROUTING_REASON`, which the suite
asserts rather than merely satisfies.

| | |
|---|---|
| `027` | `processed_at`, `intervention_outcome_history`, `record_intervention_outcome()`, `v_followup_queue`, `v_intervention_response` |
| `client_followup.py` | the cycle, ending at the review queue |
| §64B | one outcome per live intervention, as data |

**An outcome that changes leaves what it changed from.** IMPROVING becoming
WORSENING is arguably the most important fact a follow-up produces, and a
bare `UPDATE` loses it. One function writes the history row **before** the
column. `STOPPED` requires a reason. Adherence is stored **beside** the
outcome, never folded into it — an intervention nobody carried out has not
failed, it has not been tested.

**`TOO_EARLY` and `NOT_TRACKED` are real answers.** An unreadable outcome
lands at `NOT_TRACKED`, never `STABLE`: `STABLE` claims a measurement never
made. `v_intervention_response.never_assessed` separates "nobody looked"
from "looked and found nothing", which the column default otherwise makes
identical.

**A follow-up is processed once** and spends one routing hop;
`ck_loop_bound` refuses the hop past `max_loops` (hard rule 3). The cycle
ends at the review queue — E5 and release stay behind a practitioner
decision and the safety gate.

**Step 20: the safety gate finally has something to gate.**

`trg_block_unapproved_communication` and `case_flags` have existed since
migration `004` and **nothing ever evaluated a rule**, so no HOLD could
open and the gate had never blocked anything.

| | |
|---|---|
| `026` | `safety_rules`, `critical_lab_thresholds`, `safety_match_patterns`, `evaluate_safety_rules()`, `apply_safety_rules()`, `v_release_readiness` |
| `client_release.py` | E5 draft, practitioner approval, gated release |
| §60B / §70B | E2 and E3 emit their plans as strict JSON, not only as prose |

**The acceptance case is a NEGATIVE, and it is asserted first.** A client
on metformin, a statin, an ACE inhibitor, thyroid replacement and
amlodipine — with abnormal-but-not-critical labs and a carbohydrate
reduction proposed — passes **clean**. A gate that fires constantly is a
rubber stamp (D6), so the thing worth testing is that it stays shut up.

**A plan that leaves no row cannot be checked (D42).** Every rule that
matters turns on what is being proposed, and matches on the intervention's
NAME. `client_interventions` had existed since `004` with nothing writing
to it, so those rules would have passed every client clean **having
inspected nothing**. E2 and E3 now emit `<BEHAVIOUR_PLAN_ITEMS>` and
`<NUTRITION_PLAN_ITEMS>` — the seventh and eighth build-added output
contracts, same pattern as §R10–§R15.

Two rules need **both halves**: insulin *and* a glucose-lowering
intervention, warfarin *and* an interacting one. Either alone is an
ordinary client, which is exactly why metformin passes.

**Drug names are rows, not code** (hard rule 13). The suite proves it:
an unregistered sulfonylurea is honestly not matched, and one INSERT later
it is. `trg_flag_rule_registered` refuses a deterministic flag whose
rule_key is not in the catalogue — which is how two existing suites were
found writing invented keys.

**Release is three conditions and none substitutes.** Drafting is never
gated (hard rule 9) — the practitioner may need to see what would be said
before deciding whether the HOLD matters. The approval check is in the
script and the HOLD check is a trigger, deliberately: a workflow can be
edited, a trigger cannot be forgotten.

**Step 19: K12 and K13 are built — the two passes nothing else produces.**

`controversies`, `controversy_positions` and `negative_knowledge` have
existed since migration `003` and **nothing had ever written to them**.
That is a property of the pipeline, not an oversight: K09 reads one source
and K11 turns claims into strategies, and neither can produce "these two
bodies of evidence contradict each other" or "this was examined and does
not work", because no single source says either.

| | | |
|---|---|---|
| K12 | `knowledge_controversy.py` | E7 `CONTROVERSY` (§R14) — per domain, over accumulated evidence |
| K13 | `knowledge_gap.py` | E7 `GAP` (§R15) — per domain, plus capped escalation |

Two new knowledge-clock modes, added as **registry rows** plus their output
contracts. `v_controversy_state`, `v_knowledge_gap_queue`,
`domain_controversy_assessments`. 41 checks, both capability floors.

**Four refusals carry it** (D41):

- **A controversy with one position is refused at COMMIT.** It is a
  consensus statement or a gap, and stored here it is retrieved and shown
  as a live disagreement. A CONSTRAINT TRIGGER, deferred, because the
  positions are written after the parent — deleting one back down to a
  single position is refused the same way.
- **Negative knowledge needs `why_investigated`, `evidence_examined` and
  `revisit_trigger`.** Its only job is to stop the same question being
  researched twice, and it cannot without the first two. Without the
  third, "this does not work" is a `COMPLETE` status by another name,
  which §70 forbids.
- **`knowledge_gaps.status` is a closed set now.** It was free text, and
  `foundation_ready` turns on `status = 'OPEN'` — a row written `'open'`
  would have hidden a CRITICAL gap and marked a domain ready, silently and
  in the direction that hides the problem.
- **"Nobody looked" is not "nothing found".** `domain_controversy_assessments`
  gives K12 the record `domain_gap_assessments` already gave K13. Without
  it both states are an absent row, and the second is the dangerous one
  (hard rule 11).

**Escalation is capped and ranks by impact** (hard rule 3), and
`RESEARCHING` means a gap was **taken up, not researched** — wiring one
into a live E7 run is step 21's continuous update, and a gap question is
not a claim. Named rather than half-built.

**Step 18: evaluation layers A-E are built, and layer A has a baseline.**

D7's five layers, none of which asks the practitioner to author an answer:

| | | |
|---|---|---|
| A | seeded domain structure | `generate_a` splits each family — probes in the query, the rest expected |
| B | held-out sources | `holdout_answer_keys`, extracted separately, read-only resolution |
| C | cross-domain synthetic cases | `DOMAIN_BREADTH` against the domains the library actually spans |
| D | practitioner spot check | drawn automatically, capped, one sample at a time |
| E | discovery value | a RATE per sample, denominator = items **reviewed** |

**Measured, not asserted** (`docs/evidence/layer_a_baseline.md`):

```
full text only        mean recall 0.1372    3 of 14 tests pass
full text + vector    mean recall 0.3255    9 of 14 tests pass
```

Same fourteen tests, same day; 269 concepts embedded in between, on the
**live provider** — 283 calls, 1,204 tokens, **$0.000234**, 2m27s. Every
vector unit-norm at 1536 dimensions, none rejected. The floor was 0.30
before either run.

**Layer A found bug 63 on its first run** — the full-text channel had been
returning nothing for any query longer than a few words since step 17,
silently, and every step 17 test passed because its fixture queries are
three words long. That is what an evaluation layer is for, and it paid for
itself before it was finished.

**Three refusals hold the layers up**, each one a way this could have
become decorative:
- `ck_test_has_expectation` — recall over an empty expected set is
  undefined, not 1.0. A young library must not score 100% for knowing
  nothing.
- `normalize.resolve(..., read_only=True)` — the ordinary resolver creates
  PROPOSED concepts and trigram aliases, so building the layer B answer key
  the ordinary way would have taught the library the held-out vocabulary it
  is being measured against. Same tiers, no writes.
- `UNSCORABLE` — a library spanning no domain has not failed retrieval, and
  is excluded from the mean rather than counted as zero.

**Step 17: K14 embedding and hybrid retrieval are built and tested.**

```
metadata filter → full text → vector → dedupe → rerank
```

| | |
|---|---|
| `023_embedding_freshness.sql` | `embedding_source_hash` + `embedded_at` on the five embeddable tables, `v_embedding_coverage` |
| `embed_library.py` | the backfill. Chooses rows and text; never calls a provider — that is `embedding.py` (D38) |
| `retrieval.py` | the four channels, the dedupe, and the rerank |
| `test_retrieval.py` | 35 checks, green with pgvector and on the D15 floor without it, **ten consecutive runs on each** |

**The acceptance criterion is met at the DEFAULT setting, which is the
only version of it worth anything (D39).** The suite seeds a deliberately
lopsided library — six strategies in each of three disease folders, one in
each of six other domains, with the folders on PRIMARY concept links (1.0)
and the rest on weaker ones (0.4) — and a page of twelve reaches all nine
domains. The counterfactual runs **the same function** with the per-bucket
cap lifted and returns **disease folders only**, so the breadth is
attributable to the mechanism rather than to the fixture.

The first version of this check passed on a coin flip. See **bug 62** —
worth reading before writing any other ranking test.

`per_bucket_cap` is **derived** (`limit // len(concepts)`), not a
constant. A fixed 3 fails the criterion at a page of 12. An acceptance
test that passes because the test chose the cap has tested the test.

**"Do not regenerate unchanged embeddings" is proved by counting real
calls**, not asserted: a second backfill pass makes **zero** provider
calls and editing one row costs exactly one. The hash is of the embedded
TEXT, not of the row — `retrieval_hits` moves on every retrieval, so a
row hash would have made reading the library pay to re-embed it.

**Without pgvector it degrades loudly (D15).** The vector channel is
skipped, the diagnostics say why, weights renormalize over the channels
that ran, and `v_embedding_coverage` reports NULL rather than zero —
"not applicable", not "backfill has not run". Verified by running the
suite on the no-extension floor, not by reading the branch.

**What is NOT done, and should not be assumed:**
- **No discovery adapter's WIRE FORMAT is verified from inside this
  build.** The egress proxy blocks `eutils.ncbi.nlm.nih.gov`,
  `api.crossref.org` and `pubmed.ncbi.nlm.nih.gov`; all three returned
  `000`. The suites drive the real adapters with the transport stubbed, so
  the policy, the cursor, the query history, the refusal paths, the parsing
  and the handoff are verified — and **the wire format is not**. Treat the
  first live `PUBMED` run as unverified code rather than as a regression.
  **`YOUTUBE` is the exception and only partly**: the actor was run live
  and its real output read, so the field names, the segment shape and the
  input field are known rather than assumed — but the code was written
  afterwards and has still never executed against the live endpoint.
- **The no-captions payload has never been observed.** A video without
  captions has not been run, so the `FULL_TEXT_NOT_AVAILABLE` path for
  `YOUTUBE` is **UNVERIFIED against a real payload**. What is enforced is
  the shape-independent invariant — no usable segments means no transcript
  — and no fixture asserts a guessed shape. This is the honest limit of
  step 16's K06 work and the first thing to check on the pilot.
- **One element shape in the Apify request is assumed.** The input FIELD
  is `urls`, confirmed live (`videoUrls` was the wrong first guess). Whether
  each element is a plain string or a `{url: …}` object was not separately
  confirmed. `youtube_apify.INPUT_ITEMS_AS_OBJECTS` is the one line to
  change and the first place to look if a live batch returns empty.
- **Bulk embedding has never been run on the live provider.** The wire
  format now HAS been verified — see *The embedding endpoint is live* —
  but every embedding in every suite still comes from an injected
  transport, and no corpus has been embedded for real. The per-call
  guarantees are proven; the throughput, the rate limits and the bill are
  not.
- **No real source has run the loop yet** — only fixtures and synthetic
  documents. Do not begin mass ingestion; one real source first, then the
  20-video pilot.
- **Practice aggregates exist as a mechanism, not as data.** Step 23 is
  built and `practice_strategy_outcomes` is still empty in production
  terms: the minimum cohort is five assessed clients per strategy, and no
  real client has been through a follow-up. The engines receive an empty
  `PRACTICE_EXPERIENCE` block today, which is correct and is not the same
  as the feature working on real data.
- `STRIP_IDENTITY_FROM_ENGINE_PAYLOADS` is documented and **not enforced**
  in `RUN_ENGINE`.
- On the VPS specifically: the restore drill has not been run **on that
  box**, the backup cron has not yet fired once, and SSH still allows
  password authentication. See *Deployed to the VPS*.

---

## Deployed to the VPS — 2026-09-10

The first time any of this has run on real infrastructure. Hostinger,
`srv1498536`, Ubuntu, 2 vCPU / 7.8 GB RAM, 90 GB free.

| | |
|---|---|
| Container | `phi-postgres`, `pgvector/pgvector:pg16`, healthy |
| Network | joined to the existing `n8n-sdc9_default`; **no published port**; reachable only as `phi-postgres:5432` |
| Migrations | deployed from `main` = **000–011 only**. `012`–`016` land on merge |
| Roles | `phi_admin`, `phi_runtime`, `phi_practitioner` — verified, scram auth over TCP |
| Prompts | all seven loaded; `load_prompts.py --check` exits 0; E7 hash `c1276c136368` |
| Suites | `run_all.sh` — ALL SUITES PASSED (13 suites at that revision) **against the real roles**, not a superuser DSN |
| Backup | `backup.sh` nightly, cron `30 2 * * *` UTC, GPG-encrypted; the private half is **not on the VPS**; decryption verified from a separate machine |
| `BACKUP_REMOTE_TARGET` | unset — backups are on the same box as the database |
| `LLM_API_KEY` | deliberately **EMPTY** on the VPS. Nothing there makes a paid call yet |

### Do not touch the n8n side

The existing stack runs **three live business automations** (GFG T1 v2,
AiSensy, a detection PoC) on volume `n8n-sdc9_n8n_data`, backed up to
`/root/n8n-data-2026-09-10.tar.gz`. That stack, that volume and its
`docker-compose.yml` are out of scope for this build, permanently. This
repo adds a database to the same network and nothing else.

### The n8n version question is answered, and the pin follows the VPS

**DECIDED: pin to 2.11.4, do not upgrade the VPS** (D32). Verifying against
`n8n-nodes-base` 2.11.2 — what n8n 2.11.4 ships — found two things that
would have failed on first import, neither of them a version regression:

1. The Postgres node's `queryReplacement` **array branch does not exist in
   2.11.2**. Every binding had been written to use it, and would have bound
   **one** parameter where the statement wanted twelve.
2. The Code node has **no `fetch`** — it runs in `vm2` — on 2.35.7 as much
   as on 2.11.4 (D33). The provider call could never have run anywhere, and
   the retry harness could not see it because it ran the extracted source in
   plain Node.

Both are fixed and both are now covered by tests that would catch a
recurrence. See `docs/OPERATIONS.md` "n8n version".

### Two things the deployment taught

1. **GPG refused to encrypt to an untrusted key and `backup.sh` exited 2,
   leaving the files unencrypted rather than reporting success.** That is
   the correct failure: a backup script that claims success while writing
   plaintext PHI is worse than one that stops.
2. **Everything passing in containers passed on the VPS only because the
   role and DSN bugs had already been found.** Trust auth and a superuser
   DSN hid D25 for weeks. This is why the two verification claims are now
   recorded separately.

---

---

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
- `003_knowledge.sql` — the knowledge library: domains with tracked
  coverage dimensions (**18** since `007` corrected the enum; `003` shipped
  19, one of which was `KNOWLEDGE_GAPS` and was not a coverage question at
  all — see below and D17), source creators / sources / items / documents /
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

### Step 10b — synthetic client and call measurement `COMPLETE (measured live)`
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

### Step 14 — Core Intake V1 `BUILT 2026-09-10`
The exclusions were written **first** (`DECISIONS.md` D22) and the fields
derived from them, not the other way round. What Core Intake deliberately
does not ask — everything RHT owns, calorie self-quantification, symptom
checklists, behavioural batteries, client-authored diagnoses, fields no
engine consumes — is the design; the 52 askable fields are what survived it.

- `009_intake.sql` — `intake_submissions`, `intake_sections`,
  `intake_field_catalog` (the registry: conditional logic and classification
  as **data**, so V2 is an `INSERT`), `client_report_files`,
  `v_intake_completeness`. RLS enabled and FORCED on all three
  client-scoped tables from the first migration, not retrofitted.
- **No new store for clinical facts.** Intake extracts into the existing
  004 tables — labs, medications, supplements, conditions, symptoms,
  measurements, food logs — so every view, engine and policy already built
  on them works on intake-sourced data unchanged.
- `scripts/intake.py` — validation that records gaps and never refuses,
  conditional applicability, extraction, RHT linkage, and conversion to the
  E6 canonical-state v1 input.
- Gaps go to the **existing** `missing_data_reports` machinery with
  `engine` NULL and `submission_id` set; `ck_gap_has_a_source` makes an
  intake gap impossible to launder into an engine attribution.

Proven by `test_intake.py`: a sparse intake missing labs, food log, food
environment and most of the profile still produces a runnable E6 v1 with
`HIGH_PRIORITY_MISSING_DATA` populated; an unasked section reads `UNKNOWN`
rather than an empty object; an unknown medication dose stays `UNKNOWN`;
RHT `NOT_ASSESSED` carries "absence is not evidence of normality" and no
scores; a `COMPLETED` claim with nothing linked is downgraded to
`NOT_ASSESSED`; a male client is not asked the reproductive questions while
a female client with no answers is.

### Step 14 value validation `ADDED 2026-09-10`
009 proved **completeness** — which applicable fields had no answer — and
said nothing about whether a supplied answer was **usable**. `011` closes
that, and D22 records the boundary.

Three outcomes and never a fourth: **missing** is a gap, exactly as
before; **valid** is accepted; **supplied but unreadable** becomes an issue
in `intake_submissions.validation_issues` and is treated as unknown or
dropped. Intake still never blocks a case — nothing here can refuse a
submission.

- `raw_payload` stays **raw**. Sanitizing happens on the way out, at
  extraction and at E6 conversion, so what was actually submitted stays
  recoverable and stays comparable against what was made of it.
- Nothing is repaired. `"14/08/2026"` is a different day in Mumbai and in
  New York, so an ambiguous date is unknown; a lab result dated today
  because its own date was unreadable would be a false fact that outlives
  everyone who remembers why. **Removing is allowed, defaulting is not.**
- The allowed RHT statuses are read from the `assessment_status` enum via
  `v_assessment_status_values`, not from a list in Python that would drift.
- A field whose only answer was unusable becomes a **gap**, so Engine 5
  asks the question again. `UNUSABLE_ANSWERS` travels to Engine 6
  separately from `HIGH_PRIORITY_MISSING_DATA`: "not asked" and "answered
  unusably" are different facts, and only the second says the question
  needs asking differently.

Only the shapes that bear safety or data integrity are checked — what step
15 writes into typed columns and what an engine reads as clinical fact. A
validate-everything layer would freeze the field registry D22 keeps as
data.

### D24 — the substantive handoffs now flow `FIXED 2026-09-10`
Found in review, before the n8n port, and confirmed against the code rather
than taken on trust.

Every prompt defines **two** machine-readable outputs. `<CONTROL_BLOCK>` is
~17 typed routing fields (D14); `<..._HANDOFF>` is the reasoning the next
engine thinks with. `RUN_ENGINE` parsed only the first —
`EngineResult.structured` was `None` on both return paths, and
`engine_outputs.structured` was written from the **input's** `_echo` key,
which nothing sets, so it stored `{}` on every run since the engine layer
was built. `CLIENT_NEW` then passed control blocks downstream as
`E7_HANDOFF` and `E1_HANDOFF`, and built both case versions from the input
it had handed Engine 6.

Engine 1 Pass B — which exists **solely** to see Engine 7's retrieval (D4)
— was receiving eight routing booleans where strategies and evidence should
have been. The sequence executed perfectly and the thinking did not move.

- `013_handoff_registry.sql` — `engine_handoffs` keyed
  `(engine, mode, tag)` with a `required` flag. The third instance of the
  pattern `010` and `012` established, not a third bespoke mechanism. The
  loader **verifies every tag against the registered prompt**, and caught a
  real discrepancy on the first run.
- **E6 and E7 have no default mode.** Guessing means expecting a delta
  where a state was needed, or the reverse.
- **A delta is never `canonical_state`.** `_new_case_version` refuses a
  version without a full state; the delta goes in the column `004` created
  for it. `CLIENT_NEW`'s second E6 call runs `REBUILD`, not `UPDATE` — see
  D24 for why that is a deliberate deviation.
- A missing required handoff joins the same `errors` list as a contract
  violation, so it repairs and then dead-letters rather than adding a third
  failure path.
- `test_handoff_flow.py` — sentinels that exist in exactly one block,
  asserted to reach specific downstream **inputs**, captured from what was
  actually transmitted. Plus the negative: a perfect control block with no
  handoff must dead-letter.

### Step 11 — n8n `RUN_ENGINE` `BUILT 2026-09-10`
`workflows/run_engine.json`, 13 nodes, mirroring `scripts/run_engine.py`
rather than reinterpreting it: three registries read as rows, the runtime
envelope, three separate outputs, the repair and dead-letter branch, cost
accounting, and transaction-local client scope on every write.

**Parity is byte-identical, not behavioural** (D26). One golden corpus,
two implementations — the third use of the pattern the contract registry
established, and the third time it caught something:

- **15 requests, identical to the byte** — envelope, key order,
  indentation, escaping. Covers every engine, every E6 and E7 mode, both
  E1 passes, non-ASCII, integral floats, empty containers, every JSON
  escape, deep nesting and large integers.
- **15 responses, identical field for field** — valid execution, an
  invalid control block three ways, a missing handoff, an empty handoff
  block, the wrong block for the mode, a fenced control block, a handoff
  whose value lines look like keys, an empty response, and token
  accounting including reasoning tokens.
- The JavaScript under test is **extracted from the workflow at run time**,
  so a copy cannot drift from the thing it claims to test.

No paid live calls were made to prove any of it.

**Pinned to n8n 2.11.4** to match the VPS (D32) — see
`docs/OPERATIONS.md` "n8n version" before deploying.

### Step 15 — `CLIENT_NEW` `BUILT 2026-09-10`
`scripts/client_new.py`. A submitted intake to the practitioner's queue in
one call:

```
intake -> extract -> E6 v1
       -> E1 Pass A -> normalization -> E7 -> E1 Pass B
       -> E2 -> E3 -> E6 v2
       -> practitioner review queue.  STOP.
```

Three properties are decisions, not transcription, and each is asserted:

- **A fixed pipeline, not a routing loop.** Phase 4 is a sequence; phase 5
  is the one that routes. `NEXT_ENGINE` is therefore not consulted to
  choose what runs next — a new client always needs E1, E2 and E3, and
  following the field would let an engine skip the nutrition plan. The
  control block still **gates**: a run that did not succeed stops the
  pipeline before anything downstream runs.
- **It stops at the queue.** E5 is not part of it (hard rule 9: gates
  release, not analysis), and E4 does not run because there is no response
  data yet. An open **HOLD flag does not stop the analysis** — the suite
  asserts that directly.
- **A new client is queued whatever the control block says.** Engine 1
  sets `REVIEW_REQUIRED` on its own analysis, but "the engines did not ask
  for review" is not a reason to send a first plan to a client unseen.

History is appended, never overwritten. The same submission cannot
initialize a second case. A sparse intake still reaches the queue with its
gaps recorded (D22).

### Step 11 — control-contract registry `BUILT 2026-09-10`
`012_contract_registry.sql` + `scripts/load_contracts.py`. The second half
of D23: `run_engine.py` validated every control block against a file on the
working tree, and hard rule 5 has n8n routing on exactly those typed
fields, so a port with no access to the contract cannot route at all.

**One document, two validators.** Python keeps `jsonschema`; the n8n Code
node will use `ajv`, which ships inside n8n. Both read the same row, so the
specification is single-sourced and only the library differs.
`test_contract_registry.py` runs 26 control blocks through both and asserts
identical verdicts **and identical blamed fields** — the blame matters as
much as the verdict, because it is what goes into the repair prompt. CI
installs `ajv@8` in all three jobs so this is a real gate.

The corpus found something about the contract rather than the code:
`additionalProperties` is **true**, so an engine emitting a field nobody has
typed yet is not violating anything. That is D14, and it is now asserted
rather than assumed.

### Step 13 — C3 normalization layer `BUILT 2026-09-10`
`scripts/normalize.py`. Resolves a Pass A `NORMALIZATION_PHRASES` entry
through the cheapest tier that can answer it and stops there:

```
cache -> exact alias -> structured identifier (LOINC/RxNorm/ICD/SNOMED)
      -> trigram -> semantic embedding -> LLM
```

The LLM is the last tier, not the first, and `test_normalization.py`
proves it by installing an LLM callable that raises if it is reached: the
deterministic tiers must answer without it.

- **Extraction proposes; it never creates canonical.** An unresolved
  phrase becomes a concept with `status='PROPOSED'` and is deliberately
  **not** cached, so a proposal cannot harden into a fact by being reused.
- **Confusable pairs are checked before any answer is returned**,
  including the LLM's. A resolution that would merge a
  `CONFUSABLE_DO_NOT_MERGE` pair is refused at the exit, not filtered at
  one tier (D3).
- Confirmed mappings are written back as aliases, so a phrase costs a
  model call at most once.
- Escalation is **impact-ranked and capped** per week (D8), not
  uncertainty-ranked: a low-impact unknown is logged, not queued.

### Step 12 — K1 ontology seed `BUILT 2026-09-10`
`scripts/seed_ontology.py`. Seeds **26 domains and 269 concepts** from
`knowledge/seed/foundation_domains.md`, hash-verified against the same
body hash `test_prompt_contracts.py` asserts, so the seed cannot drift
from the curriculum without the seeder refusing to run.

Deterministic — no LLM. The A-Z structure maps to
`(concept_type, domain_type, is_core, priority)`; S and T-Z are scaffold
sections and correctly seed nothing.

- Every concept carries provenance back to its domain letter.
- 21 existing concepts reused rather than duplicated; `canonical_key`
  unique and shaped `^[A-Z][A-Z0-9_]{2,79}$`.
- 12 aliases attached as **aliases**, never as second canonicals.
- 6 `CONFUSABLE_DO_NOT_MERGE` pairs generated **from structure** —
  siblings whose trigram similarity lands in 0.45-0.85 — with notes and
  mirrors, so C3 refuses them.
- Re-seeding is idempotent.

Seeding and then reading the result is what found the parser bugs: domains
cross-reference other domains' concept types after their pivot line, which
had "lipids" and "BP" landing as `EXERCISE` concepts; imperative fragments
were becoming concepts; and `menopause / perimenopause` was making a
clinically distinct state an alias.

`test_ontology_seed.py` asserts the hash guard, idempotency, provenance,
alias separation, the confusable mirrors, seed **quality**, and — per D13 —
that the seed is explicitly **not complete**.

### Step 11 — n8n `RUN_ENGINE`: feasibility settled `DETERMINED 2026-09-10`
*(historical — the port was written the same day; see* Step 11 — n8n
`RUN_ENGINE` `BUILT 2026-09-10` *above)*

The brief's first question was whether step 11 can be developed and
validated from workflow JSON, a local n8n and the existing fixtures alone.
**It can. No n8n credentials, no VPS access and no secrets from the
practitioner are required, now or to finish the port.**

Determined by doing it, not by reading documentation:

| | |
|---|---|
| Container registries | `docker.n8n.io` **403** at the egress proxy, Docker Hub's blob CDN blocked. The documented Docker route is unavailable here. |
| npm registry | reachable. `npm install n8n@2.11.4` → ~2.5 GB, 3 minutes. (Unpinned picks up 2.35.7; the pin follows the VPS, D32) |
| Headless execution | works, with a caveat: n8n 2.x **dropped `execute --file`**. A workflow must be `import:workflow`-ed and then run by id, so workflow JSON in this repo carries a stable id |
| Postgres node | connected as **`phi_runtime`** through a credential seeded from `.env.local`, and read the D23 prompt registry: seven rows, hashes identical to what `load_prompts.py` reported |
| Credentials | seeded by `scripts/local_n8n.sh seed-credentials` from `.env.local`. Nothing is pasted anywhere, and nothing touches the VPS |

`scripts/local_n8n.sh` is that harness. It installs from **npm rather than
Docker** deliberately — it is the one route that has worked in every
environment this repo has been built in — into a directory outside the
working tree, and it does not touch `docker-compose.yml`.

Two things it papers over, both n8n's: `--rawOutput` promises "only JSON
data, with no other text" and prints node-loading warnings before the
payload, so the harness trims to the first brace; and the telemetry client
retries against a proxy that answers 405 until diagnostics are disabled.

**What the port still needs, and what it already has.** D23 landed the
first blocker: the prompts are rows, so n8n can read a specification
without a copy of this repository. Remaining: the control contract needs
the same treatment (one stored schema document, validated by `jsonschema`
in Python and by n8n's bundled `ajv` — two implementations of one
standard, over one document, with a parity suite asserting identical
verdicts), then the workflow itself — prompt read, run insert, the repair
loop, transport retry with backoff, cost per attempt, dead-letter.

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

### Step 24 — restore drill `PERFORMED 2026-09-10`
The first one ever run. `scripts/backup.sh` had been written and never
executed; an untested backup is not a backup.

Drill A — restore onto the live cluster, into a scratch database:
- `pg_restore` exit 0, **zero errors**
- all 70 tables compared **row by row** with content hashes, not counts:
  49 non-empty identical, 21 empty identical, **0 mismatched**
- 52 policies, 26 RLS tables, 26 FORCE RLS preserved
- **all eight suites pass against the restored database**, and
  `migrate.py` reports "Up to date" rather than re-applying

Drill B — restore onto a **fresh cluster with no phi roles**, which is what
losing the VPS actually looks like. This is where the drill earned itself:

```
pg_restore exit=1   1,438 error lines
  259 x role "phi_runtime" does not exist
   39 x role "phi_practitioner" does not exist
  → 52 CREATE POLICY failed, 246 GRANTs failed
  → database restored with ALL the data and NONE of the access controls
```

`pg_dump` dumps one database; roles are cluster-wide and are not in it. The
tables look populated, so `pg_restore`'s exit code is easy to miss.

It **fails safe, not open** — verified, not assumed: RLS stays enabled and
FORCED with zero policies, so a re-created `phi_runtime` gets
`permission denied`, not rows. The danger is operational, not a leak: the
runtime cannot connect, and the fix under pressure is to hand-grant
permissions, which is how the security model gets dismantled.

Fixed: `backup.sh` now dumps roles alongside the database
(`pg_dumpall --roles-only --no-role-passwords` — no credentials in the
backup, so a leaked dump is client data rather than client data plus the
keys to it). Re-run end to end: roles first, then the dump, onto a fresh
cluster — **zero errors, 52 policies, all eight suites pass.**

Also proven: **encoding must match.** The recovery cluster came up
`SQL_ASCII` under default `initdb` settings and psycopg then returned text
columns as **bytes**, so `migrate.py` thought applied migrations were
pending and died on a duplicate key, and `set_role_passwords.py` raised a
TypeError. Client data was intact underneath — byte-identical, matching
hashes — but every tool that touched it misbehaved. `docker-compose.yml`
already gets this right via `POSTGRES_INITDB_ARGS`; a hand-built cluster
does not.

## Before the first full synthetic case: what E7 will and will not show

Written **before** the run, so the result is not misread.

**Engine 7 will return little or nothing, and that is correct.** The
knowledge library is empty of the things E7 retrieves. K1 seeded the
concept dictionary — 269 concepts — and nothing else:

| | |
|---|---|
| concepts | 269 (K1 seed) |
| strategies | 5 — **test fixtures**, not knowledge |
| evidence records | 3 — **test fixtures** |
| claims | 0 |
| implementation patterns | 0 |

Step 16 (Knowledge Factory K02–K11) builds strategies, claims and evidence.
Step 17 (K14) makes them retrievable by embedding and hybrid search.
Neither exists yet.

**So Engine 1 Pass B will reason from an empty retrieval set.** Pass B is
still worth running and its output is still worth reading — but it is
reading its own Pass A picture with an empty E7 slot, not a library.

What the first full case therefore **does** tell us:

- whether the pipeline flows end to end on a live provider
- whether Engine 1 produces a coherent 19-part report
- whether Engine 2 and Engine 3 build on Pass B rather than restating it
- whether the substantive handoffs propagate (D24) with real model output
  rather than fixtures
- what a real cycle costs

What it **does not** tell us:

- whether the retrieved knowledge is any good. There is none to retrieve.
- whether E7's case retrieval works. An empty result from an empty library
  is indistinguishable from a broken retriever until step 16 puts something
  in it.

**An empty `RESEARCH_PRACTICE_CASE_HANDOFF` is not a bug report.** The
block must still be present and well-formed — D24 requires that, and a
missing one still dead-letters — but its strategy and evidence fields
being thin is the expected state of the system today.


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
29. **Fixture estimates were costed as money.** RUN_ENGINE recorded
    `model_name` from the role's env var, falling back to a fixture
    placeholder only when it was empty — so setting `MODEL_ANALYSIS` before
    the key arrived made a fixture run match the price registry and report
    `$0.039902` for a cycle that never left the machine, printed under the
    banner saying the tokens are estimates. Fixture runs now record
    `fixture:<model>`: nothing matches, cost stays NULL, and UNPRICED keeps
    the meaning 008 documents.
30. **An unset model role was sent to the provider as a model id.** The same
    fallback put the literal `fixture:live` in the request when
    `LLM_API_KEY` was set and the role was not, so a configuration error
    arrived as an opaque 400. Now raises `ModelRoleUnset` naming the
    variable.
31. **The test suite made real API calls.** Both engine-running suites took
    their provider from the environment. Correct in production, wrong in a
    test: the moment a real key reached the environment,
    `bash testing/run_all.sh` would spend money on every run, vary between
    runs, and go red whenever the provider was down or out of quota. Hidden
    because CI sets the key empty. Both suites now force the fixture
    provider and assert they got it.
32. **`measure_engine1.py` crashed on its last line.** A refactor replaced
    the two-pass pass/fail boolean with a three-way verdict string and left
    the `return` referencing the deleted name. Every line of the report
    printed correctly, then `NameError`. **`run_all.sh` never ran this
    script**, so only the CI step caught it — the first thing CI found that
    a local run could not. The suite now exercises `print_report`'s exit
    code directly, on a complete cycle and on one missing Pass B.
36. **The backup did not include the roles.** `pg_dump` dumps one database;
    roles are cluster-wide. Restoring onto a machine that does not have
    them failed 52 CREATE POLICY and 246 GRANT statements while the data
    landed fine — a database with all the PHI and none of the access
    controls. Found by the 2026-09-10 restore drill, which is the only
    thing that could have found it. `backup.sh` now dumps roles too.
37. **A non-UTF8 database broke the tooling in a way that pointed nowhere
    near the cause.** On SQL_ASCII, psycopg returns text columns as bytes;
    `schema_migrations` lookups miss, so `migrate.py` treats applied
    migrations as pending and dies on a duplicate primary key.
    `migrate.py` now checks the encoding first and refuses with a message
    naming the real problem and the fix.
34. **Reasoning tokens were generated, billed, and invisible.** The live
    provider returns `prompt_tokens` 8, `completion_tokens` 1,
    `total_tokens` 75 — 66 tokens produced and charged that
    `completion_tokens` never reports. Recording `completion_tokens` as
    output would have understated the measured cycle by most of its cost,
    and D5 is a decision made on those numbers. Output is now
    `max(completion_tokens, total − prompt)`.
35. **`message.content` is absent, not empty, when the budget goes to
    reasoning.** `finish_reason: "length"` arrives with no `content` key at
    all; `payload["choices"][0]["message"]["content"]` raised `KeyError`,
    which RUN_ENGINE classified as a transport failure — a misleading
    diagnosis for a response that arrived intact. Now returns the empty
    string and fails honestly at control-block extraction. Both shapes are
    recorded from live responses and asserted in `test_run_engine.py`.
33. **An incomplete cycle was reported as a fork.** A run where Pass B never
    happened is not evidence of two Engine 1 specifications; calling it
    `NO — FORK DETECTED` sends the reader hunting an architectural
    violation that is not there. Now `INCOMPLETE`, still a non-zero exit.

38. **`missing_data_reports.engine` was `NOT NULL` over E1–E7, so an
    intake gap had no honest home.** Intake is not an engine; the choices
    were to invent a fake attribution, duplicate the whole gap machinery
    for intake, or make the column tell the truth. `engine` is now
    nullable, `submission_id` was added, and
    `ck_gap_has_a_source CHECK (num_nonnulls(engine, submission_id) = 1)`
    makes an intake gap impossible to launder into an engine attribution
    and an engine gap impossible to file as intake.
39. **Making `engine` nullable silently broke `v_missing_data_recurrence`.**
    Its `array_agg` started returning `{NULL}` for intake-sourced gaps —
    the view still ran, so nothing failed; it just reported nonsense. The
    view was rebuilt in the same migration. (`CREATE OR REPLACE VIEW`
    cannot insert a column mid-list, so it is a drop and recreate.)
40. **`record_gaps` auto-wrote `classification`.** Migration 005's
    invariant is that `classification` stays NULL until a human triages
    the gap; writing it from code turns triage into a rubber stamp.
    **Caught by an existing test, not by me** — which is the argument for
    tests that assert an invariant rather than a table. Severity is still
    written, because severity follows from the field catalogue and is not
    a judgment.
41. **The resolver wrote lowercase tier names into `resolution_method`.**
    Every method column is that enum. Fixed at a single mapping point
    (`DB_METHOD`) rather than at each call site, so a new tier cannot be
    added without deciding what it is called in the database.
42. **A test passed on run 1 and failed on run 2.**
    `test_normalization.py` left a confusable pair behind and
    `test_concept_layer.py` asserted a **global** confusable-pair count, so
    the pairs K1 now seeds by design broke it. Both halves were wrong: the
    test now cleans up after itself, and the assertion is scoped to its own
    fixtures. A global count assertion cannot survive a seeder whose job is
    to add rows.
43. **Removing `PROMPTS_DIR` broke the D5 call-size report.** Nothing
    else read it, so the loss did not surface until `test_measurement.py`
    ran the report's exit path — the same corner of `measure_engine1.py`
    that bug 32 lived in, which is a hint that the report is under-covered
    rather than unlucky. Fixed by reading `v_active_engine_prompts`, which
    is also the more honest number: it reports the size of the
    specification that actually ran, not the size of an unloaded edit
    sitting in `prompts/`.
44. **Steps 12 and 13 broke the D15 degradation guarantee and nothing
    noticed for two build steps.** `seed_ontology.py` called `similarity()`
    with no capability gate and died with `UndefinedFunction` on a database
    without pg_trgm; `test_normalization.py` asserted a trigram tier had
    answered when it could not have. Step 10b had proved that path worked.
    **CI could not have caught it**: pg_trgm and btree_gin are contrib and
    ship in both matrix images, so the `degraded` job only ever removed
    pgvector. There is now a `bare` job that deletes the contrib control
    files inside the service container, and `testing/run_bare.sh` for the
    same thing locally. K1 seeds the identical ontology either way —
    `scripts/trigram.py` reproduces pg_trgm's similarity exactly, checked
    against the real function over 5000 seeded pairs whenever it is
    available.
45. **A malformed intake value killed extraction hundreds of lines from
    where it was accepted.** `height_cm: "about 170"` reached a numeric
    column as `InvalidTextRepresentation`; a medication with a dose and no
    name hit a NOT NULL; an unrecognised section key raised on the
    `intake_section` enum inside `submit()` itself, which is intake
    blocking a case over a typo. 009 proved completeness and never asked
    whether a supplied answer was usable.
46. **`rht_status: "probably fine"` reached Engine 6 as `RHT_STATUS
    "PROBABLY FINE"`.** The worse half of 45 and the reason it is a
    separate entry: a field whose entire job is to say whether these
    signals are known was accepting a value that is neither known nor
    unknown, in the one place D22 insists `NOT_ASSESSED` means unknown.
    Now validated against the `assessment_status` enum read from the
    database — not a list in Python, which would drift — and an
    unrecognised status becomes `NOT_ASSESSED` **with a `DISCREPANCY` note
    naming what was declared**, because silently defaulting it would hide
    that someone answered the question badly.
47. **A phrase with punctuation could not be proposed as a concept, and
    the phrase in question is D2's own example.** `normalize.py` built a
    `canonical_key` as `phrase_norm.upper().replace(" ", "_")`, which
    produced `LARGE_POST-MEAL_GLUCOSE_EXCURSIONS` and was rejected outright
    by `ck_canonical_key_shape`. C3's suite never hit it because its
    fixtures contain no punctuation; the first real `CLIENT_NEW` run hit it
    immediately. Two places create concepts and were using different rules
    — there is now one, in `scripts/concept_key.py`. Also fixed while
    there: a phrase yielding no usable key is hashed rather than lost, and
    a key collision after 80-character truncation disambiguates instead of
    reusing the existing concept, which was a silent merge (D3).
48. **`loop_count` is routing depth, not a count of engine calls.**
    Migration 004 says so on the constraint — "Prevents Engine 4 → 1/2/3 →
    4 cycling without bound" — and `max_loops` defaults to **3**, which is
    fewer than `CLIENT_NEW` has engines. Charging a hop per engine made a
    correct run exhaust its budget at E1 Pass B. One hop is one pass
    through the engines, charged once on entry, so re-entering the same
    cycle trips `ck_loop_bound` rather than running the engines again.

49. **A relative module path made the parity check fail in CI and pass
    everywhere else.** `find_ajv()` built its first candidate as
    `Path(os.environ.get("N8N_HOME", "")) / "node_modules"`, and with
    `N8N_HOME` unset that is the RELATIVE path `node_modules` — which
    exists in CI, because CI installs ajv into the repository root. Node
    resolves a relative `require()` against the requiring module rather
    than the working directory, so the check found ajv, handed node a path
    it could not use, and reported `ajv ran: exit 3`. Every candidate is
    resolved to an absolute path now, empty roots are skipped instead of
    silently becoming the current directory, and `ajv_validate.js` resolves
    its own argument too. Reproduced locally by installing ajv exactly the
    way the workflow does, rather than by reading the diff.

50. **Every value in a handoff block is a string, and that killed the
    first real run.** The format the prompts specify is line-oriented
    `KEY: text`, so Engine 6's `CASE_VERSION: 1` parses as `"1"` — and the
    control contract correctly rejected it as not an integer, dead-lettering
    E1 Pass A the moment the pipeline ran on real handoffs. Not fixed by
    coercing per field, which would invent a typing rule per key:
    `client_case_versions.case_version` is an integer column assigned by the
    insert, and D18 rests on stored versions starting at 1. Engine 6's line
    is its claim; the row is the fact. The general form of the lesson —
    typed values come from typed places, the handoff is prose-shaped and is
    reasoning — is in D24 and matters for the n8n port too.

51. **The selected mode was resolved and never transmitted.** It went into
    provider `params`; the fixture read it and
    `openai_compatible_provider` ignores `params` entirely, so `INIT`
    versus `REBUILD` — Engine 6 emitting a full state versus a delta —
    reached the wire as nothing. E1 looked fine only because
    `client_new.py` hand-wrote `"MODE": "PASS_A"`, which is the accident
    rather than the fix. `RUN_ENGINE` now injects a
    `<RUNTIME_INVOCATION>` envelope for every engine and no call site
    writes a mode. **The fixture could not have caught this** — it reads
    the param the live path discards — so the test intercepts `urlopen`
    and asserts against the bytes the live provider would have sent.
52. **Two of Engine 7's four modes were unregistered, and one of them had
    no output contract at all.** `ENGINE7_MODE` is
    `FOUNDATION | UPDATE | CASE | INBOX` (§3262); only CASE and FOUNDATION
    existed. UPDATE shares the foundation contract. **INBOX had no
    substantive handoff block anywhere in the specification** — §55
    describes the information gain in prose — so an INBOX run could only
    ever have produced a control block, and reusing that as the handoff
    would have been D24 again. §R10 was added (build-owned, D16).
53. **`<RESEARCH_PRACTICE_FOUNDATION_HANDOFF>` and
    `<RESEARCH_PRACTICE_CASE_HANDOFF>` had no standalone opening tag in
    their field templates.** A model following either literally would emit
    a block the runtime cannot find. The case tag passed the first check
    only because it appears standalone in the §R3 *example*. Both are
    build-owned (D16, Parts II/III), so the prompt was corrected rather
    than the verifier taught to accept a formatting accident — and the
    verifier now requires the standalone **opening** line, keeping the
    closing-tag check as a second assertion.

54. **`RUN_ENGINE` could not run as `phi_runtime` at all.** Connecting as
    the role n8n uses and calling `run_engine()` failed on its FIRST
    statement, both for a client run and for a knowledge-clock run:
    `InsufficientPrivilege: new row violates row-level security policy for
    table "engine_runs"`. Two causes. Nothing ever called
    `set_client_scope()` — it appears only in `test_case_events.py`. And
    the policy `client_id = current_client_scope()` can never match a
    knowledge-clock run, which has no client (D18). **The Python reference
    has only ever worked because `DATABASE_URL` connects as `phi_admin`,
    which is SUPERUSER and bypasses RLS** — every engine run this system
    has made went around the policies rather than through them. D25 and
    migration `014`.
55. **Python and JavaScript serialized the request differently, in two
    measurable ways.** Python escaped non-ASCII to `\uXXXX` by default and
    wrote integral floats as `78.0` where JavaScript wrote `78`. Either
    would have produced a different model request from the same inputs
    with nothing to notice, because the prompt hash plus the request IS
    the call. `canonical_json()` fixes both (D26).
56. **The two validators phrased the same violation differently, and that
    string is not cosmetic.** `jsonschema` says `'CASE_VERSION' is a
    required property`; `ajv` says `must have required property
    'CASE_VERSION'`. It is persisted to `engine_runs.error_detail` and it
    is what the repair prompt sends the model on attempt two — so n8n
    would have asked the model to fix something in different words than
    the reference does, on the one retry that matters.
    `format_violation()` defines the wording and both sides build it from
    their own library's structured error data.

57. **`test_n8n_parity.py` crashed instead of skipping when node was
    present and ajv was not.** The response-parity half runs the Validate
    control node's own source, which requires ajv. Without it the
    JavaScript returns one error dict per case — and the suite indexed
    `["valid"]` on it, raising `KeyError` after first reporting fifteen
    mismatches that were not mismatches.

    **This is the pg_trgm shape one layer up.** All three CI jobs install
    ajv, so all three were green and the degraded branch was reachable on a
    developer machine and nowhere else — the same way an ungated
    `similarity()` call survived steps 12 and 13 (bug 44). A branch that
    only runs where nothing watches is a branch that is not tested.

    `test_contract_registry.py` had always handled the condition correctly,
    with a loud SKIP, so the fix is to match it: the response half is gated
    on ajv as well as node; a per-case error is reported and the comparison
    skipped rather than indexed; and `find_ajv()` is now imported from
    `test_contract_registry` instead of being a second copy that did not
    honour `AJV_MODULE_PATH`.

    The floor is now tested. The bare job — the one whose purpose is
    running with nothing optional available, and ajv is optional in exactly
    that sense — deletes `node_modules/ajv` after the full suite and re-runs
    both parity suites, **asserting a SKIP actually appears**: a suite that
    passed for some other reason would prove nothing.
    `testing/run_bare.sh` does the same locally and restores ajv on exit,
    because a check that exists only in CI is how this class of gap forms
    (bug 49).


58. **Every Postgres binding in the workflow was written for a branch the
    target version does not have.** D31's fix — one `{{ [a, b, c] }}` array
    per node — was made against `n8n-nodes-base` 2.35.7. The VPS runs
    2.11.4, whose 2.11.2 nodes have **no array branch**: an array is
    `JSON.stringify`'d like any other object and pushed as ONE value.
    Driving the real 2.11.2 module over the workflow's own expressions:
    Open run bound 1 of 12, Record attempts 1 of 9, Record success 1 of 12,
    Dead letter 1 of 10. Every Postgres node would have failed on the first
    run.

    Replaced with one resolvable per parameter, each a JSON literal,
    unwrapped in SQL with `($n::jsonb #>> '{}')` — verified identical
    against **both** real implementations. `test_n8n_sql.py` now asserts,
    for every node on every run, that the bound count equals the highest
    `$n` the statement uses, and that no node uses the array form. See D32.

59. **The Call provider node used `fetch`, which the Code node does not
    have.** n8n's Code node runs inside `vm2`; that sandbox provides
    `setTimeout`, `Promise`, `Math`, `JSON`, `Date` and `helpers`, and
    **not** `fetch` or `URL` — verified empirically, the same answer on
    2.11.4 and 2.35.7. The node could never have run on any version.

    Every retry assertion passed regardless, because `n8n_retry.js`
    extracted the source and ran it with `new Function(...)` in plain Node,
    where `fetch` is a global. **The harness was more capable than the
    runtime it modelled** — bug 57 in different clothes. The node now uses
    `helpers.httpRequest` with `returnFullResponse` and
    `ignoreHttpStatusErrors`, read from n8n-core 2.11.1 rather than
    guessed, and the harness runs the source in `node:vm` with only the
    globals vm2 provides. See D33.

60. **A `ReferenceError` in that node was retried five times with
    exponential backoff and then dead-lettered as a transport failure.**
    Found while proving the new harness catches bug 59: the node treated
    every thrown error as a network error. Python retries `URLError`,
    `TimeoutError` and `ConnectionError` and nothing else, so a `NameError`
    there fails on the first attempt. Thrown errors are now classified by
    network `code` exactly as statuses are classified by number; a
    programming error has no such code, fails once, and is reported as
    itself. A bug in that node must be loud, not slow.


61. **The n8n SQL parity suite compared two things it had invented.** It
    ran the workflow with `MODE: "PASS_A"` — which no caller produces, and
    which is not a mode at all; E1 has one handoff mode, `SINGLE`, and its
    pass is a separate column — and then hand-wrote a "reference" row to
    match. Both halves were mine, so they agreed, and the suite reported
    field-for-field parity while proving nothing.

    Exposed by migration 020 making the coherence trigger look the mode up
    in the registry: `no active handoff is registered for E1 in mode
    PASS_A`. The suite now runs the real caller's mode and builds the
    reference row by calling `run_engine()` rather than by writing a second
    INSERT. **A harness that differs from production proves nothing about
    production** — the same lesson as bug 49, bug 57 and bug 59, and the
    fourth time in this build.

    *Checked and NOT a bug:* the workflow requires an explicit `MODE` where
    Python defaults for E1–E5, and `Build request` throws `HandoffMissing`
    when the registry returns nothing. n8n is stricter than the reference in
    the safe direction, which is a documented difference rather than a gap.

62. **The step 17 acceptance test passed on a coin flip.** The fixture gave
    every strategy an identical link weight of 1.0, and the query
    (`insulin resistance with hepatic fat and raised triglycerides`) matched
    **no** strategy under `websearch_to_tsquery`, which ANDs its terms — a
    summary saying "insulin sensitivity" does not contain `resist`, `hepat`
    and `triglycerid` at once. So the full-text channel returned nothing,
    every result scored identically on the concept channel, and the page was
    decided by the tie-break: `ORDER BY (-score, kind, id)` on freshly
    generated UUIDs. The stub embedder made it worse rather than better —
    hashing the whole string gives distinct texts a near-zero, effectively
    random similarity, and per-channel normalization then rescales that
    noise across the full range, so the vector channel voted at random too.

    It was green four times running before the bare floor caught it, and
    green is exactly what a coin flip looks like most of the time.

    Two fixes, both making the fixture carry signal a real library has:
    the presenting complaint's concepts are **PRIMARY** links (1.0) and the
    concepts Engine 1 raised alongside them are weaker (0.4) — which makes
    the breadth *harder* to achieve, not easier; and the stub embedder gives
    each topic keyword its own direction so texts about insulin land near
    texts about insulin. The counterfactual was also sharpened from "returns
    fewer domains" to "returns **only** the three disease folders", because
    "fewer" still passes on a tie. Verified deterministic over **20
    consecutive runs**, ten on each capability floor.

    This is **V2 in a fifth disguise**. Nothing was hand-written twice this
    time; the harness simply had no signal in it, so the assertion measured
    randomness and reported it as retrieval quality. *A test whose fixture
    cannot distinguish the right answer from the wrong one proves nothing,
    the same way one that constructs both halves does.*

    **Putting signal in then exposed three more assertions that were
    statements about the fixture rather than about retrieval**, each caught
    by a capability floor or by running from an empty database:

    - *"uncapped returns exactly the three folders"* — it returns **two**,
      twelve slots taken by hepatic fat and triglycerides alone. A sharper
      collapse than the criterion names. Now: folders **only**, and strictly
      fewer domains than the capped page.
    - *"with no concepts, the query cannot reach sleep"* — a statement about
      library size. In a library of 29 strategies a page of 10 reaches most
      of it. Now measured as rank movement, which is size-independent.
    - *"named material ranks first"* — true without pgvector and **false
      with it**, because a row that both the lexical and vector channels
      found legitimately outranks one the spine alone reached. Asserting it
      would have been asserting a capability floor. Now: the spine is the
      channel that **drove** the row onto the page.

    Every one of those passed on the floor it was written on. The floors are
    not a formality — they are three different libraries, and an assertion
    that is really about corpus shape survives exactly one of them.

63. **The full-text channel had been returning nothing, for months of
    build time, for any query longer than a few words.**
    `websearch_to_tsquery` — and `plainto_tsquery`, and
    `phraseto_tsquery` — **AND every term**. So

    ```
    'CONDITIONS & CLINICAL STATES: acne, adrenal fatigue, alopecia'
      ->  'condit' & 'clinic' & 'state' & 'acn' & 'adren' & 'fatigu' & 'alopecia'
    ```

    and a document had to contain all seven. No real clinical query — which
    is a paragraph — could ever match. The channel was not degraded; it was
    off, silently, and `by_fts` returned `[]` with no error anywhere.

    Every step 17 test passed regardless, because every fixture query in
    that suite is two or three words. **Layer A found it on its first run**:
    fourteen domain tests, all scoring exactly 0.00, which is not a number
    retrieval produces by accident.

    Fixed by ranking rather than filtering: the query becomes an **OR of its
    lexemes**, taken from `to_tsvector`'s own output and quoted with
    `quote_literal`, and `ts_rank_cd` — which was already there — separates
    a document matching six terms from one matching one. ANDing is not a
    relevance strategy; it is a filter that removes everything.

    Layer A: **0.1372 -> 0.3255** mean recall after the fix and the
    embeddings, 3 of 14 tests passing to 9 of 14.
    See `docs/evidence/layer_a_baseline.md`.

    *Also found, fixing it:* `test_retrieval.py` edited whichever strategy
    `next(iter(...))` returned, which happened to be the row a later
    ranking check queried for. The two sections had been coupled since the
    suite was written and it surfaced only once full text started matching
    at all. The edit target is named now.

64. **`test_retrieval.py` raised instead of skipping when `MODEL_EMBEDDING`
    was unset** — pgvector present, no model configured, `BadVector`
    halfway through. Reported by the practitioner.

    **Third instance of one shape** — `pg_trgm`, then `ajv`, now this: a
    suite that only passes where an optional dependency happens to be
    configured, invisible in CI because CI configures it. `MODEL_EMBEDDING`
    is unset **on the VPS on purpose**, so this is the configuration the
    system is actually deployed into.

    Fixed as a mechanism rather than a third patch:

    - `testing/preflight.py` — one skip format, one registry of what is
      optional and what its absence costs. `have_env`, `have_capability`,
      `have`.
    - `testing/test_optional_deps.py` — removes each registered variable,
      finds the suites that reach it by **walking the import graph** (a
      list would go stale the first time somebody added a suite), and runs
      each one twice. The degraded run must exit 0, and every skip it
      prints that the baseline did not must **name** the removed
      dependency. It runs inside `run_all.sh`, so it holds on every floor.
    - **Production degrades too.** `retrieval.by_vector` now returns
      `"MODEL_EMBEDDING is not set: ..."` instead of raising, because the
      VPS runs that way deliberately. `embedding.embed()` still refuses —
      asking it to embed with no model pinned IS an error (D34); a query
      is not asking it to.
    - `run_all.sh` **prints every named skip**. Naming a dependency inside
      a suite whose output the summary then throws away is not naming it to
      anyone, and a reader could not tell which floor a green run was green
      on.

    Now **rule V3 in `CLAUDE.md`**.

    *Found while fixing it, by the new suite and its static half:*

    - `test_retrieval` collapsed two different conditions into one flag.
      "No pgvector" means there is no embedding column and coverage is
      NULL; "pgvector with no model" means the column exists and is empty.
      Three assertions were keyed to the wrong one.
    - `test_n8n_sql.py` skipped to **stderr** in a different wording, so
      `run_all`'s summary never showed it and no floor could grep it. That
      suite could skip its only real assertion and look identical to a full
      pass.
    - `test_retrieval`'s "naming the concept moves its material UP the
      page" was **rank**-based, and rank is a function of what else is on
      the page: six hepatic strategies legitimately outrank the sleep row
      both with and without the spine. It passed only because another
      suite's five strategies happened to sit in between. Now asserts the
      **score** rises — the mechanism, not the seating plan. Bug 62's
      lesson in a third costume.
    - `test_evaluation` needed the K1 ontology seed and **failed** rather
      than skipping when another suite had not run it first. A precondition
      gets the same treatment as an optional dependency.

65. **The K1 seeder silently dropped a concept's domain provenance.**

    ```sql
    update concepts set origin_detail = origin_detail || '; also DOMAIN B'
     where concept_id = %s and origin_detail not like '%DOMAIN B%'
    ```

    `NULL not like ...` is **NULL**, so the `WHERE` excluded every concept
    whose `origin_detail` was NULL — the update never ran, and the concept
    gained a `concept_domains` edge with no provenance naming the domain.
    Hard rule 7: provenance is enforced, not requested.

    Surfaced by layer A's cross-check disagreeing 290 vs 286, which is what
    that check is for. `coalesce(origin_detail, '')` on both sides.


**Also, and recorded rather than amended away:** commit `c99ebf4` was made
on a red suite. `run_all.sh` printed `FAILURES PRESENT` and the command
chain did not gate on its exit code. The rule in `CLAUDE.md` is to run the
suites before every commit; running them and not reading the result is the
same failure with an extra step.

**It happened a second time**, at commit `2f5448d`, in a slightly different
disguise: the verification was chained behind a `grep`, which succeeded on
the output of a failing suite, so `&&` saw success. Both instances are now
**rule V1 in `CLAUDE.md`**, with the wrong and right shell forms written
out, because twice is a pattern and a `PROGRESS` entry is not where a
session looks first.

The companion rule, **V2**, is the four-instance one: a test must not
construct both halves of a comparison, and the reference side must come
from calling the real implementation (bugs 49, 57, 59, 61).

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

## D5 ANSWERED — Engine 1 measured on a live provider

Ran `scripts/measure_engine1.py` against gemini-3.8-flash on the synthetic
client. **Real token counts, not estimates.**

```
engine pass   status      att retry   prompt   compl   total         cost       ms  parsed
E6     SINGLE SUCCEEDED     1     0   18,909  12,580  31,489    $0.061357   41,254   yes
E1     A      SUCCEEDED     1     0   20,869  32,687  53,556    $0.138228  116,621   yes
E7     SINGLE SUCCEEDED     1     0   20,558   8,885  29,443    $0.048737   33,842   yes
E1     B      SUCCEEDED     1     0   20,922  32,529  53,451    $0.137675  114,747   yes
CYCLE                       4     0   81,258  86,681 167,939    $0.385997  306,464
```

Both passes on one prompt hash `33d857c2dd6f`, one prompt file. Control
block parsed on all four calls. Zero retries, zero dead letters. 5m07s.

**Engine 1 does not degrade across the 19-part report.** Both passes
produced every part of §62:

| | chars | parts | first half | second half | ratio |
|---|---|---|---|---|---|
| Pass A | 116,661 | 19/19 | 56,306 | 60,119 | **1.07** |
| Pass B | 116,436 | 19/19 | 58,795 | 57,358 | **0.98** |

The back half carries as much as the front; PART 19 is among the largest
sections in both. The smallest section is PART 15 at ~2,000 chars, which is
proportionate to what it asks for, not truncation. The control block sits
*after* the report and parsed, so the model reached the end of the sequence
in both passes.

**D5 stands: do not stage Engine 1.** The proposal to split it was
withdrawn on principle and is now refused on evidence. Revisit only if a
different model degrades — the measurement is one command.

**Cost per client.** ~$0.39 for these 4 calls, so a full 8-call new-client
cycle lands near **$0.75–0.80** on this model. That replaces the earlier
prompt-side-only estimate, which omitted output entirely.

**Free tier is not viable.** `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
is 20 requests/day: about two clients, and Step 16's Knowledge Factory is
high-volume extraction by design. Billing is a prerequisite, not an
optimisation.

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

**As of 2026-09-11, after the first real source through the complete loop
(`docs/evidence/first_source_loop.md`): fix concept normalization before
ingesting anything else.** One source produced 71 concept proposals and
exactly one resolution against a 269-concept seed that contains the right
concepts. Twenty sources would bury the ontology. The three causes and the
one that is a plain gap — `normalize_claim_concepts()` passing `llm=None`,
so the resolver's LLM tier is unreachable from K09 — are in §3 of that
document. It is a spending decision and a change to D2's cheapest-first
ordering, so it needs a decision recorded, not just a patch.

Then, and only then, the 20-video pilot.

Two smaller things from the same run, both recorded and neither fixed:
the DEDUPED envelope's note claims the source changed when the content
hash is identical (§56 versioning runs before §57 dedup) and its
`content_hash` is NULL; and "tests clear their own fixtures" holds in
`test_knowledge_factory` now but not across the suites.


*(The live measurement that stood here is DONE — see D5 ANSWERED. Re-running
`python3 scripts/measure_engine1.py` costs ~$0.39; do it to re-measure after
a model change, not to re-confirm a settled result.)*

**Steps 12, 13, 14 and 15 are BUILT**, and step 11's registry half with
them. `scripts/client_new.py` runs a submitted intake to the practitioner's
queue in one call.

*(**Superseded.** This section recorded the n8n `RUN_ENGINE` subworkflow
JSON as the next task. It was written on 2026-09-10 and built the same
day: `workflows/run_engine.json`, 14 nodes, byte-identical parity, SQL
executed against a real database. Step 11 is complete and frozen — see the
state summary at the top. The next exact task is **step 16, the Knowledge
Factory**.)*

**After that, the release path.** `CLIENT_NEW` stops at the review queue by
design; nothing yet turns a practitioner approval into Engine 5 output.
That is step 20.

**Cheap now, awkward later:** enforce
`STRIP_IDENTITY_FROM_ENGINE_PAYLOADS` in `RUN_ENGINE` before real client
data exists, and run `scripts/backup.sh` on the VPS once with GPG and an
off-site target configured.

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
- `scripts/backup.sh` written; **restore drill performed 2026-09-10**
  and it found the backup contained no roles (bug 36). Still unproven:
  the script has never run **on the VPS**, under cron, with GPG
  encryption or an off-site target.
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

## Live measurement attempt — 2026-09-09 `SUPERSEDED — see D5 ANSWERED`

> **This section is a record of the FIRST attempt, which failed on provider
> quota. Its conclusion — that D5 was still open — was overtaken the same
> day once billing was enabled: the measurement completed and D5 is
> answered. Kept because its observations about provider behaviour and the
> fixes it produced still stand. Do not read its conclusion as current.**

First run of `scripts/measure_engine1.py` against a real provider
(OpenAI-compatible Gemini endpoint). **This attempt did not complete.**
Engine 1 Pass A never returned, so at the time D5 remained open.

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
window; nothing in the repo is at fault. **Billing was enabled and the run
completed — see *D5 ANSWERED*.**

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
`LLM_API_KEY`, the base URL and billing are all **in place and proven**:
the full cycle completed live and D5 is answered. `MODEL_ANALYSIS` and
`MODEL_RESEARCH` are set to `gemini-3.8-flash`; `MODEL_EXTRACTION`,
`MODEL_EMBEDDING` and `MODEL_FAST` are still unassigned and are needed as
their engines come online — `MODEL_EXTRACTION` first and on the cheapest
capable model, since it carries the highest volume.

Nothing is blocked on credentials any more.

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
- `RUN_ENGINE` is **built** in both implementations and validated by one
  suite, so behaviour cannot drift (D26, D31). The remaining n8n gap is
  that `CLIENT_NEW` exists only as `scripts/client_new.py`; the workflow
  form of it is step 15's n8n half and is not written.
- **n8n is pinned to 2.11.4, matching the VPS (D32).** Two runtime
  settings on that instance still decide whether the workflow works and are
  not in this repo: `N8N_BLOCK_ENV_ACCESS_IN_NODE` (the workflow reads
  `$env`) and `N8N_RUNNERS_ENABLED` (which sandbox the Code node uses).
  Check both before importing — `docs/OPERATIONS.md` "n8n version".
- Deterministic flag rule set not yet written; `case_flags` and the gate
  work, but the SQL rules that populate HOLD/NOTE are still to come and
  must start narrow
- `006` is schema only. No inbox UI, no ingestion pipeline, no acquisition
  adapters. It exists so those can be built without a retrofit.
- Restore drill **performed 2026-09-10** (see above). Re-run it after any
  migration that changes roles, policies or grants.
- `scripts/backup.sh` has still never run **on the VPS**, under cron, with
  GPG encryption or an off-site target configured. The drill exercised it
  in `direct` mode against a development database with both
  `BACKUP_GPG_RECIPIENT` and `BACKUP_REMOTE_TARGET` unset, so the encrypt
  and rsync paths remain unproven.
- `EMBEDDING_DIM` is hard-coded to 1536 in `002_concepts.sql`; changing it
  needs a migration and a full re-embed
- `norm_phrase` backs STORED generated columns; changing it later requires
  a migration that also rewrites those columns and rebuilds their indexes
