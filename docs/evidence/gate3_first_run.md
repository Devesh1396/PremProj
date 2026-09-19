# GATE 3 — FIRST RUN OF THE SYNTHETIC CLIENT

**2026-09-19. Branch `claude/gate3-retrieval`. Implementation committed at
`b28ae4b`, BEFORE this run. Answer key frozen at `b5b2477`, before any GATE
3 code existed.**

## VERDICT: MISS

**6 of 8 acceptance checks passed. Strategies 2 and 5 were not on the page.**
Exit code 1.

This file records that result. It is not replaced by any later, better
number. The post-first-run section at the end is marked as such and its
result is recorded separately, below the original.

---

## What was run

```
bash rebuild (40 migrations, K1 seed: 269 concepts, 269 embedded)
python3 testing/test_gate3_acceptance.py --report
```

`MODEL_EMBEDDING=gemini-embedding-2`, `LLM_API_KEY` set. Video 1 ingested
through the real Knowledge Inbox (K07 → K08 → `CURATED_DETERMINISTIC`
dispatch), 6 strategies, 2 principles, 24 fields, 24 VERBATIM, 0
TRANSFORMED — GATE 1 unchanged.

The retrieval INPUT is the answer key's CLIENT PROFILE block, verbatim and
entire, cut between the two `====` rules that delimit it. Nothing below the
profile was read until after retrieval had run.

---

## 1. Concept attachment — every unit, its span, its outcome

`curated_concept_rules` fired 2 of its 3 registered rules. **20 units
extracted, 2 linked.**

```
 ord rule        field                  phrase                                        span            status      tier      score   -> concept
   3 CARD_NAME   strategy_name          Breakfast restructuring                       [1365:1388]     UNRESOLVED  none      0.0000
   9 CARD_NAME   strategy_name          Pre-meal vegetable/fibre structure            [3395:3429]     UNRESOLVED  none      0.0000
  14 CARD_NAME   strategy_name          Vinegar as a candidate meal-level tool        [4597:4635]     UNRESOLVED  none      0.0000
  17 CARD_NAME   strategy_name          Meal-linked postprandial movement             [5493:5526]     LINKED      semantic  0.8688  POST_MEAL_MOVEMENT
  17 BOLD_LABEL  what_it_means          10 minutes of walking after one meal per day  [5722:5766]     UNRESOLVED  semantic  0.7978
  17 BOLD_LABEL  alternatives           post-meal muscular activity                   [6814:6841]     LINKED      semantic  0.8741  POST_MEAL_MOVEMENT
  23 CARD_NAME   strategy_name          Progressive layering instead of interventi…   [7169:7222]     UNRESOLVED  none      0.0000
  23 BOLD_LABEL  client_decision_logic  Poor adherence history / overwhelmed client   [7896:7939]     UNRESOLVED  none      0.0000
  23 BOLD_LABEL  client_decision_logic  Highly motivated and capable client           [8012:8047]     UNRESOLVED  none      0.0000
  23 BOLD_LABEL  client_decision_logic  Strong response                               [8097:8112]     UNRESOLVED  none      0.0000
  23 BOLD_LABEL  client_decision_logic  Weak or absent response                       [8168:8191]     UNRESOLVED  none      0.0000
  26 CARD_NAME   strategy_name          Preserve agency and reduce unnecessary dep…   [8524:8574]     UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  High-carb breakfast                           [9586:9605]     UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Diet-change resistance                        [9653:9675]     UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Client overwhelmed                            [9742:9760]     UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Client already follows a strategy well        [9867:9905]     UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Preferred strategy is not practical           [10007:10042]   UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Client cannot walk comfortably                [10111:10141]   UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Client does not respond despite good adher…   [10285:10331]   UNRESOLVED  none      0.0000
  26 BOLD_LABEL  client_decision_logic  Several options are possible                  [10428:10456]   UNRESOLVED  none      0.0000
```

`score 0.0000 / tier none` means **no tier produced a candidate at all** —
the phrase fell below the semantic FLOOR (0.78), so nothing was even a
near-match. `10 minutes of walking after one meal per day` at 0.7978 is
the one case that produced a candidate and was refused by the threshold
(0.82), correctly: it is a dose, not the concept.

**Every one of the 20 is a verbatim slice of the source at the span shown,
checked mechanically against the preserved raw file before anything was
stored.** Nothing was summarised, shortened or invented.

### What the phrase test refused, and why — reported, never silently dropped

17 bold runs matched `BOLD_LABEL` and were refused as statements rather
than names.

```
   3 what_it_means          'not simply "eat savoury food."'                [1766:1796]    contains '.': a statement, not a name
   3 what_it_means          'Convert a predominantly carbohydrate-deliv…'   [1827:1957]    contains '.': a statement, not a name
   3 client_decision_logic  'Prioritize this strategy when:'                [2396:2426]    colon-terminated: a lead-in, not a name
   3 client_decision_logic  'Do not prioritize breakfast merely because…'   [2684:2751]    contains '.': a statement, not a name
   3 practitioner_leverage  '"For now, let\'s improve one meal that hap…'   [3251:3312]    contains '.': a statement, not a name
   3 practitioner_leverage  '"Your entire diet must change immediately."'   [3332:3375]    contains '.': a statement, not a name
   9 what_it_means          'Sometimes we can improve a meal by changin…'   [3821:3941]    contains '.': a statement, not a name
   9 practitioner_leverage  '"Can we improve this meal before deciding …'   [4508:4577]    contains '?': a statement, not a name
  14 what_it_means          'A candidate low-friction meal-level glucos…'   [4833:4893]    contains '.': a statement, not a name
  17 what_it_means          'Attach a manageable amount of movement to …'   [5829:5909]    contains '.': a statement, not a name
  17 why_useful             'meal finishes → movement begins.'              [6138:6170]    contains '.': a statement, not a name
  23 opening_statement      'Start with an appropriate number of high-v…'   [7500:7666]    contains '.': a statement, not a name
  23 why_useful             'Intervention load itself should be persona…'   [7822:7870]    contains '.': a statement, not a name
  26 opening_statement      'When clinically reasonable, preserve foods…'   [8778:9000]    contains '.': a statement, not a name
  26 why_useful             'not'                                           [9180:9183]    no lexemes: stopwords only
  26 why_useful             'Restriction should have a reason. It shoul…'   [9302:9421]    contains '.': a statement, not a name
  26 client_decision_logic  'not "give everybody the same four hacks."'     [9477:9518]    contains '.': a statement, not a name
```

**Every one of those 17 is a sentence the practitioner emphasised, not a
name.** Sending them to `normalize.resolve()` is the D51 `mechanism`
failure in a new costume, and the test suite asserts that none of them
reaches it.

### What stayed unlinked, and the limitation that explains it

**18 of 20 units did not resolve, and 5 of 6 cards carry no concept link
at all.** The K1 seed holds 269 concepts and has no concept for
`Breakfast restructuring`, `High-carb breakfast`, `Client overwhelmed`,
`Progressive layering`, or `Vinegar`. That is a LIBRARY state, not a
resolver fault: `read_only=True` means nothing was created, which is
deliberate (a PROPOSED concept is not a retrieval anchor, D8).

The conditional clauses inside `client_decision_logic` — `sedentary
behavior is substantial`, `protein/fibre are minimal` — carry real
knowledge and were **not** offered to the resolver at all, because they
are clauses and no registered rule recognises a whole bullet item. That is
the stated limitation of D52 and it is why Strategy 5's routing table
contributes nothing to the concept spine.

---

## 2. The client profile through the GATE 2 resolver

One line per fact, as written, `read_only=True`. **3 of 24 lines
resolved.**

```
  Age: 46                                                    UNRESOLVED  none      0.0000
  Sex: Male                                                  UNRESOLVED  none      0.0000
  Type 2 diabetes for 5 years                                RESOLVED    semantic  0.8301  TYPE_2_DIABETES
  Metformin                                                  UNRESOLVED  none      0.0000
  Vegetarian                                                 RESOLVED    alias     1.0000  VEGETARIAN
  tea + sweetened/processed cereal OR poha/bread-type carb…  UNRESOLVED  none      0.0000
  Breakfast contains very little meaningful protein          UNRESOLVED  none      0.0000
  Breakfast contains little fibre                            UNRESOLVED  none      0.0000
  Lunch and dinner are familiar Gujarati meals that the cl…  UNRESOLVED  none      0.0000
  prefers to keep                                            UNRESOLVED  none      0.0000
  Vegetable intake around lunch/dinner is low                UNRESOLVED  none      0.0000
  Client dislikes highly restrictive diets and does not wa…  UNRESOLVED  none      0.0000
  automatically removed                                      UNRESOLVED  none      0.0000
  Desk job                                                   UNRESOLVED  none      0.0000
  Sits for most of the working day                           UNRESOLVED  none      0.0000
  No current post-meal walking or other meal-linked movement  RESOLVED    semantic  0.8308  POST_MEAL_MOVEMENT
  Walking is physically comfortable and practical            UNRESOLVED  semantic  0.8158
  Has previously been given several diet/exercise instruct…  UNRESOLVED  none      0.0000
  Reports feeling overwhelmed by large lifestyle plans       UNRESOLVED  none      0.0000
  Says he is willing to start with one or two specific cha…  UNRESOLVED  none      0.0000
  Would prefer improving his existing routine rather than …  UNRESOLVED  none      0.0000
  entire diet immediately                                    UNRESOLVED  none      0.0000
  This is the FIRST encounter.                               UNRESOLVED  none      0.0000
  There is no follow-up response data yet.                   UNRESOLVED  none      0.0000
```

**3 concept ids into the spine.** `Metformin` resolving to nothing, and
`Sits for most of the working day` resolving to nothing, are ontology
coverage gaps. `Walking is physically comfortable and practical` at 0.8158
is a near-miss below the 0.82 threshold — one of the calibration
observations D51 already logs as unresolved.

---

## 3. The page, exactly as returned (limit 30, default `kinds`)

```
   1. 0.6842  curated_strategy  Meal-linked postprandial movement           [concept,fts]  Strategy 4
   2. 0.3158  concept           type 2 diabetes                             [fts,vector]
   3. 0.3065  concept           post-meal glucose                           [fts,vector]
   4. 0.3000  curated_strategy  Breakfast restructuring                     [fts]          Strategy 1
   5. 0.2985  concept           post-meal movement                          [fts,vector]
   6. 0.2964  concept           meal-related glucose dynamics               [fts,vector]
   7. 0.2919  concept           prediabetes                                 [vector]
   8. 0.2862  concept           CGM metrics                                 [vector]
   9. 0.2860  concept           obesity                                     [vector]
  10. 0.2857  concept           diabetes remission                          [fts,vector]
  11. 0.2849  concept           HbA1c                                       [vector]
  12. 0.2844  concept           ApoB particle burden                        [vector]
  13. 0.2830  concept           insulin resistance                          [vector]
  14. 0.2823  concept           substantial metabolic improvement           [fts,vector]
  15. 0.2820  concept           time-restricted eating                      [fts,vector]
  16. 0.2801  concept           fasting glucose                             [vector]
  17. 0.2798  concept           fat loss                                    [vector]
  18. 0.2794  concept           metabolic syndrome                          [vector]
  19. 0.2792  concept           postprandial glucose                        [vector]
  20. 0.2788  concept           IBS-pattern symptoms                        [vector]
  21. 0.2783  concept           visceral-fat reduction                      [vector]
  22. 0.2783  concept           weight-loss strategies                      [vector]
  23. 0.2775  concept           PCOS metabolic                              [vector]
  24. 0.2771  concept           dyslipidaemia                               [vector]
  25. 0.2771  concept           reproductive-metabolic health               [vector]
  26. 0.2764  concept           “Protein helps.”                            [fts,vector]
  27. 0.2764  concept           protein                                     [fts,vector]
  28. 0.2762  concept           fatty-liver resolution                      [vector]
  29. 0.2737  curated_strategy  Preserve agency and reduce unnecessary de…  [fts]          Strategy 6
  30. 0.2728  concept           beta-cell function                          [vector]
```

```
  concepts_in            3
  concept                1 via strategy_concepts
  fts                    84 via ts_rank_cd
  vector                 50 hits: embedded query against concepts
  curated_vector         curated cards are not embedded: concept + full text only
  weights                {'concept': 0.4, 'fts': 0.3, 'vector': 0.3}
  deduped                135 hits -> 124 results
  per_bucket_cap         10
  buckets_represented    28
  result                 30 of 124 returned
```

---

## 4. The acceptance verdict, check by check

```
  PASS  Strategy 1 is surfaced (PRIMARY)
  PASS  Strategy 4 is surfaced (PRIMARY)
  PASS  Strategy 6 is surfaced (PRIMARY)
  FAIL  Strategy 2 may appear as secondary knowledge        not on the page
  FAIL  Strategy 5 may appear as secondary knowledge        not on the page
  PASS  the three PRIMARY strategies hold the top three curated places
  PASS  Strategy 6's client_decision_logic survives retrieval as its own field
  PASS  ...verbatim at the byte range it names

FAILED: 2
```

Strategy 3 (vinegar, the negative control) is **not on the page either**,
so the "does not outrank" checks did not execute. Its absence rather than
its rank is what produced that, and a check that did not run is not a
check that passed.

---

## 5. Diagnosis — measured after the run, changing nothing

The same retrieval at `limit=500`, so the whole merged set is visible:

```
 rank   score  kind              channels     card
    1  0.6842  curated_strategy  concept,fts  Strategy 4 — Meal-linked postprandial movement
    4  0.3000  curated_strategy  fts          Strategy 1 — Breakfast restructuring
   29  0.2737  curated_strategy  fts          Strategy 6 — Preserve agency and reduce unnecessary deprivation
   55  0.1842  curated_strategy  fts          Strategy 2 — Pre-meal vegetable/fibre structure
   58  0.1316  curated_strategy  fts          Strategy 5 — Progressive layering instead of intervention overload
   63  0.0684  curated_strategy  fts          Strategy 3 — Vinegar as a candidate meal-level tool

kinds across the 124 merged results:  curated_strategy 6, concept 82, chunk 36
kinds in the first 30:                curated_strategy 3, concept 27, chunk 0
```

**The RELATIVE ordering of the six curated cards is exactly the frozen
expectation — 4, 1, 6, then 2, 5, then 3 last.** Every band boundary in
the key falls where the key put it, and Strategy 3 is sixth of six: the
negative control works on relevance, and it works without a single line of
retrieval code knowing the word "vinegar".

**The miss is page COMPOSITION, not ranking.** 82 of the 124 merged
results are `kind: concept` — ontology entries matching the query by
cosine and full text. They are legitimate results of the pre-existing
design (`concept` is one of `KINDS`), each sits in its own bucket so the
per-bucket cap cannot restrain them, and at `limit=30` they take 27 of the
30 places.

### A second finding, reported and NOT fixed here

A curated source is **chunked by K08 AND parsed into cards**, so its
content appears on the page twice — 36 `chunk` rows are slices of the same
Video 1 document the 6 curated cards preserve. Excluding only `concept`
still misses Strategies 2 and 5, because the source's own chunks then fill
the page instead. Whether K08 should chunk a source that is going to the
deterministic parser is a real question and it is **outside GATE 3**,
which is the bridge plus concept attachment and nothing else.

---

## 6. POST-FIRST-RUN MEASUREMENT — no production code changed

`retrieve()` has always taken a `kinds` filter. Asking for knowledge
objects rather than vocabulary, with retrieval untouched:

```python
R.retrieve(conn, query=profile, concept_ids=concept_ids, limit=30,
           kinds=("strategy", "curated_strategy", "pattern"))
```

```
  1. 0.9774  curated_strategy  Meal-linked postprandial movement                    Strategy 4
  2. 0.4286  curated_strategy  Breakfast restructuring                              Strategy 1
  3. 0.3910  curated_strategy  Preserve agency and reduce unnecessary deprivation   Strategy 6
  4. 0.2632  curated_strategy  Pre-meal vegetable/fibre structure                   Strategy 2
  5. 0.1880  curated_strategy  Progressive layering instead of intervention over…   Strategy 5
  6. 0.0977  curated_strategy  Vinegar as a candidate meal-level tool               Strategy 3
```

**This is the tuned result and it does not replace the first run.** The
first run is section 4, it is a MISS, and it stays a MISS. What this shows
is only where the miss lives: in what a caller asks retrieval for, not in
the bridge, the links or the scoring.

---

## 7. One retrieved card, traced end to end

```
query (client profile)
  -> concept POST_MEAL_MOVEMENT
  -> link  curated_strategy_concepts
           source_phrase 'Meal-linked postprandial movement'
           field strategy_name, span [5493:5526], via semantic 0.8688
  -> card  Strategy 4 — Meal-linked postprandial movement
           heading_path  T2D / Insulin Resistance — Engine 7 Practitioner
                         Intelligence > Strategy 4 — Meal-linked postprandial movement
  -> envelope  raw/87/87a893e8cade99bee31b19b476e70dd364d7df04aec4adfe35346efecc4e3b41.md
  -> bytes 5493-5526 of that file == 'Meal-linked postprandial movement'
```

And for Strategy 6, whose fields carry the routing intelligence:

```
  field  opening_statement       VERBATIM_SOURCE  [8576:9002]
  field  why_useful              VERBATIM_SOURCE  [9026:9423]
  field  client_decision_logic   VERBATIM_SOURCE  [9452:10643]
```

Each verified byte-for-byte against the preserved original during the run.

---

## 8. Strategy 6's `client_decision_logic`, IN FULL, as retrieved

`raw/87/87a893e8…md [9452:10643]`, provenance `VERBATIM_SOURCE`:

```
The important value is **not "give everybody the same four hacks."**

Use the options according to the client's actual bottleneck.

**High-carb breakfast**\
→ breakfast restructuring may be useful.

**Diet-change resistance**\
→ meal-linked movement may be an easier first intervention.

**Client overwhelmed**\
→ start with one or two high-value changes rather than rebuilding the entire lifestyle immediately.

**Client already follows a strategy well**\
→ don't prescribe it again merely because it is in the library; find the next limiting factor.

**Preferred strategy is not practical**\
→ choose another leverage option serving a similar objective.

**Client cannot walk comfortably**\
→ don't abandon the movement lever automatically; consider another appropriate muscular-activity implementation as our library develops.

**Client does not respond despite good adherence**\
→ reassess the assumed bottleneck rather than endlessly increasing the same intervention.

**Several options are possible**\
→ prioritize based on likely importance + feasibility + client readiness.

This is the reasoning Engine 7 should enable, while E1/E3 ultimately decide what fits the individual client.
```

**This is the block K09 lost entirely (D49) and GATE 1 recovered (D50).**
It survives retrieval as its own field, verbatim, at a byte range that
contains it — which is the thing GATE 3 had to prove it had not spent.

---

## 9. What this run does NOT show

* **Nothing about 20 videos.** One source, one synthetic client.
* **Nothing about calibration.** 18 of 20 units and 21 of 24 profile lines
  resolved to nothing, and 0.82 is still PROVISIONAL (D51).
* **Nothing about K10.** It was not run and remains closed (D48).
* **Nothing about clinical correctness.** GATE 3 ranks by relevance. Which
  strategy the client should actually start with is E1 Pass B's decision,
  and nothing here computes it.
* **Nothing about vector recall for curated cards.** They are not embedded;
  every curated hit above came from the concept spine or full text.

---

## 10. POST-FIRST-RUN CHANGE to the acceptance suite, and where it runs

`testing/test_gate3_acceptance.py` now asks for
`kinds=("strategy", "curated_strategy", "pattern")`. **No retrieval code
changed.** Every run still performs the default-kinds retrieval first and
prints which curated cards it returned, so the recorded miss stays visible
rather than being replaced by the configuration that passes.

With that change the suite passes 13 of 13, including the five negative-
control checks that could not execute on the first run because Strategy 3
was not on the page at all:

```
  FIRST-RUN configuration (default kinds, limit 30) returned curated cards [4, 1, 6] of 6
  curated cards by rank: [(4, 0.9774), (1, 0.4286), (6, 0.3910),
                          (2, 0.2632), (5, 0.1880), (3, 0.0977)]
  PASS  Strategy 1 / 4 / 6 surfaced (PRIMARY)
  PASS  Strategy 2 / 5 appear as secondary knowledge
  PASS  the three PRIMARY strategies hold the top three curated places
  PASS  Strategy 3 does not outrank Strategy 1 / 4 / 6 / 2 / 5
  PASS  Strategy 6's client_decision_logic survives retrieval as its own field
  PASS  ...verbatim at the byte range it names
```

**Section 4 is still the first-run result and it is still a MISS.**

### Where this suite actually runs, measured

It is wired into `run_all.sh` and **skips there**. Measured 2026-09-19: a
full `run_all.sh` leaves the ontology at **269 live concepts and 0
embeddings**, so the semantic tier — the only tier that answers anything
in this fixture — is inert and the suite says so by name rather than
failing. That is the same condition D51 already records for the
normalization sweep ("the sweep must run on a CLEAN K1 SEED"), and the
acceptance run above was made against a clean rebuild.

Which suite empties the column was NOT established. Only
`test_embeddings.py` nulls `concepts.embedding` at all and it scopes the
UPDATE to its own `EMBTEST_` keys, so the cause is elsewhere — most likely
concepts being deleted and re-inserted under the K1 seed's own canonical
keys, which D51 already records happening. **Stated as unresolved rather
than guessed at**, and it is pre-existing: nothing in GATE 3 touches it.

### The bare floor caught the acceptance suite crashing instead of skipping

First `run_bare.sh` after wiring the suite in: **RED**.

```
=== gate3_acceptance ===
psycopg.errors.UndefinedColumn: column "embedding" does not exist
LINE 1: select count(*) from concepts where embedding is not null …
```

Without pgvector there is no `concepts.embedding`, so the query that
checks *whether anything is embedded* raised — the exact "crashes instead
of skipping" shape V3 exists to stop, introduced by this suite and caught
by the floor that exists for it. Fixed by checking
`preflight.have_capability(conn, "vector")` FIRST, before any query that
names the column. `run_bare.sh` green afterwards.

---

## 11. REVIEW ROUND (D52a) — what changed after the first run, and what did not

An independent review of the branch raised three correctness issues and one
verification gap. **Sections 1–9 above are unchanged. The first run is still
a MISS, 6 of 8.** No retrieval score was retuned and `b5b2477` was not
edited.

### R1 — GATE 3 was not in the runtime

`retrieval.py` was imported by no script outside the suites, so the six
curated strategies were retrievable and nothing retrieved them. Measured
before the fix: `client_new.py`'s E7 `structured_input` held
`CASE_RESEARCH_QUESTIONS`, `E1_PASS_A_HANDOFF`, `NORMALIZED_CONCEPTS` and
`PRACTICE_EXPERIENCE` — no knowledge.

After: a `RETRIEVE` step between `NORMALIZE` and `E7`, and the block
verified at the PROVIDER BOUNDARY on a real `client_new.run_new_client()`
run, which is where what-was-actually-sent can be read (the request is
client data and is not persisted, D28):

```
  PASS  RETRIEVE runs between NORMALIZE and E7 in the real pipeline
  PASS  E7 was sent a RETRIEVED_KNOWLEDGE block
  PASS  ...labelled RELEVANCE_ONLY
  PASS  ...that asked for knowledge objects, not vocabulary
  PASS  ...carrying a curated Video 1 card BY NAME
  PASS  ...with client_decision_logic as its own named field, not prose in a summary
  PASS  ...and the practitioner's own words inside it
  PASS  ...traceable to the preserved raw file
  PASS  Pass B receives E7's REASONING over that retrieval   [SENT-E7-CASE-STRATEGY]
  PASS  ...and the retrieval block beside it
  PASS  Pass A is NOT given the retrieval: it is what decides what to retrieve
  PASS  E2 and E3 reason over E1's decision, not over the library
```

In that run the curated cards arrive through **full text, not the concept
spine** — the fixture's Pass A phrases do not resolve to K1 concepts
without the semantic tier, which is inert there. The bridge has two
channels and this is the one that works with no provider at all.

**n8n parity, answered rather than left open:** `workflows/run_engine.json`
holds one workflow, `RUN_ENGINE`, which takes `STRUCTURED_INPUT` from its
caller and constructs no CASE payload; there is no other workflow file in
the repository. Python and n8n cannot diverge today because only Python
assembles the E7 input. The obligation transfers to the unwritten n8n
CLIENT_NEW and is recorded in `PROGRESS.md` *Known gaps*.

### R2 — a weaker re-import could erase valid links

Reproduced before the fix: a capable import wrote 2 links; the same source
re-imported with the semantic tier unavailable wrote 0 and **deleted both**,
reporting a successful import.

After, measured by `test_gate3_bridge.py` sections 8–10:

```
  PASS  there are links to lose                                  (2)
  PASS  a degraded re-import preserves every link, identity and span
  PASS  ...and reports NOT_RECOMPUTED for the cards that had links
  PASS  ...with a reason naming what was unavailable
  PASS  ...and the card is still retrievable afterwards
  PASS  an authoritative run with nothing resolved removes the link
  PASS  ...and the card stops being retrievable by that concept
  PASS  a link that no longer sits on the text it names is DELETED, not kept,
        when it cannot be recomputed
```

The second of those is what stops the first passing on a store that simply
never deletes anything.

### R3 — the negative control could pass vacuously

`if n in rank and low[0] in rank: check(...)` executed **zero** comparisons
on the first run, because Strategy 3 was absent — and the suite could still
have exited 0 with its negative control never once tested. Presence is now
asserted first as its own failable check, and the comparisons are counted:

```
  PASS  the negative control (Strategy 3) is ON the page, so its rank can be
        measured at all
  PASS  Strategy 3 does not outrank Strategy 1 / 4 / 6 / 2 / 5
  PASS  ...and all 5 negative-control comparisons actually executed
```

### R4 — no GATE 3 regression ran in ordinary CI

`testing/test_gate3_bridge.py`, deterministic and provider-free, 40 checks
across 11 sections, green on every floor. It receives established K1
concept ids and **manufactures no semantic corpus**; nothing in it says
anything about 0.82.

### Verification, exit codes captured and checked, never behind a pipe

```
  rebuild + test_gate3_acceptance (live provider)   0    13 of 13
  bash testing/run_all.sh                           0    ALL SUITES PASSED
  bash testing/run_all.sh  (re-run, idempotent)     0    ALL SUITES PASSED
  bash testing/run_bare.sh (no optional extension)  0    ALL SUITES PASSED
```

---

## 12. REVIEW ROUND 2 (D52b) — two findings, closed

**Sections 1–9 are unchanged. The first run is still a MISS, 6 of 8.** 0.82,
the channel weights and `b5b2477` were not touched; no margin rule was added;
K10 was not run; no source was imported.

### R5 — availability was standing in for authority

`semantic_tier_available()` is satisfied by **one** embedded concept, and D52a
used it to decide whether a re-import may delete links. Partial coverage is
ordinary here (`embed_library` batches 25 and reports `still_stale`), so a run
that could not SEE a concept could have marked itself authoritative.

Measured against the real predicates, on a full 269/269 ontology:

```
  PASS  with FULL, FRESH coverage a recomputation is authoritative
  PASS  ...and `stale_count` agrees there is nothing to embed

  ONE vector removed:
  PASS  ONE missing vector still leaves the semantic tier AVAILABLE
        -- Gate 2 semantics are unchanged
  PASS  ...but the recomputation is NOT authoritative
  PASS  ...and the reason names partial coverage

  vector present but its source hash no longer matches search_text:
  PASS  a STALE vector is not coverage either
  PASS  ...and the semantic tier is still available, so the two
        predicates are genuinely different

  end to end:
  PASS  a link is established under full coverage
  PASS  a re-import under PARTIAL coverage preserves it  [NOT_RECOMPUTED]
```

The two predicates are named differently on purpose:
`normalize.semantic_tier_available()` answers *can it run*;
`curated_concepts.semantic_recomputation_authoritative()` answers *may its
silence delete*. Freshness is `embed_library.stale_count()` — the definition
the loader that maintains the vectors already uses — plus a check that
`MODEL_EMBEDDING` matches the model `embedding_provenance` pinned, because a
query vector from a different model measures the model gap and not the phrase.

### R6 — the block arrived at engines that had no contract for it

`RETRIEVED_KNOWLEDGE` was delivered to E7 and E1 Pass B and defined in neither
prompt. **Measured, it was not the exception.** Of the top-level blocks
CLIENT_NEW composes, the number named in any prompt was:

```
  CASE_VERSION              named
  CANONICAL_STATE           NOT named in any prompt
  E1_PASS_A_HANDOFF         NOT named in any prompt
  CASE_RESEARCH_QUESTIONS   NOT named in any prompt
  NORMALIZED_CONCEPTS       NOT named in any prompt
  E7_HANDOFF                NOT named in any prompt
  E1_HANDOFF / E2_HANDOFF / E3_HANDOFF   NOT named as inputs
  PRACTICE_EXPERIENCE       named (E7 only)
  RETRIEVED_KNOWLEDGE       NOT named in any prompt
```

The runtime input contract had never been written down for anything. It is
written now, in the build-owned Addendum A each prompt already carries — `## A5`
(E1), `## A6` (E2), `## A7` (E3), `## A8` (E6), `## A9` (E7). The
practitioner's specification is untouched, and the manifest confirms the
`sections` count is unchanged for all seven prompts:

```
  engine1_prevention.md         70 sections   51,178 chars  4f9883bb65a3
  engine2_behaviour.md          62 sections   43,710 chars  3534d02c2069
  engine3_nutrition.md          72 sections   38,959 chars  b69eae25b620
  engine4_progress.md           66 sections   43,504 chars  baca8ed84caa
  engine5_communication.md      73 sections   29,777 chars  2acc29e0c5fe
  engine6_memory.md             89 sections   40,690 chars  28223b899489
  engine7_research_practice.md  88 sections  105,595 chars  436af579ea10
```

The regression asserts contract PRESENCE, never model wording:

```
  PASS  all 22 runtime block(s) sent are named in the receiving engine's prompt
  PASS  ...and there were runtime blocks to check
  PASS  RETRIEVED_KNOWLEDGE specifically reached E7 and Pass B
  PASS  ...and NOT Pass A, which is what decides what to retrieve
```

**Teeth, proven:** deleting `## A9` from the Engine 7 prompt, regenerating the
manifest and reloading turns it red on five blocks —

```
  FAIL  all 22 runtime block(s) sent are named ...
        ['E7 <- CANONICAL_STATE', 'E7 <- CASE_RESEARCH_QUESTIONS',
         'E7 <- E1_PASS_A_HANDOFF', 'E7 <- NORMALIZED_CONCEPTS',
         'E7 <- RETRIEVED_KNOWLEDGE']
```

— and restoring it returns to green. The first attempt at that proof, editing
`engine_prompts.content` directly, was **refused by the database**:

```
ERROR:  engine_prompts is append-only: prompt engine7_research_practice.md
        (hash 436af579ea10) cannot be rewritten. engine_runs cites this hash
        as the text that produced an output.
```

which is `trg_engine_prompts_append_only` working exactly as intended.

### Reported, NOT closed

CLIENT_FOLLOWUP's own blocks — `E4_HANDOFF`, `E6_DELTA`, `LIVE_INTERVENTIONS`,
`FOLLOWUP_ANSWERS`, `FOLLOWUP_STRUCTURED`, `CURRENT_STATE`, `REVIEW_PERIOD` —
have the same pre-existing gap. The regression covers CLIENT_NEW, as the review
scoped it. `RETRIEVED_KNOWLEDGE` on the follow-up path IS covered, because E1's
`## A5` names it and E1 is where that path sends it.

### Verification, exit codes captured and checked, never behind a pipe

```
  rebuild + test_gate3_acceptance (live provider)   0    13 of 13
  bash testing/run_all.sh                           0    ALL SUITES PASSED
  bash testing/run_all.sh  (re-run, idempotent)     0    ALL SUITES PASSED
  bash testing/run_bare.sh (no optional extension)  0    ALL SUITES PASSED
```

---

## 13. REVIEW ROUND 3 (D52c) — the contract named the wrong mode

**Sections 1–9 unchanged. The first run is still a MISS, 6 of 8.**

### R7 — Engine 6's contract said UPDATE; CLIENT_NEW invokes REBUILD

Measured from the real pipeline, reading the mode each run actually recorded
in `engine_runs` rather than the caller's label for the step:

```
  E6/INIT/SINGLE     : (the converted intake payload)
  E1/SINGLE/A        : CASE_VERSION, CANONICAL_STATE
  E7/CASE/SINGLE     : CASE_VERSION, CANONICAL_STATE, CASE_RESEARCH_QUESTIONS,
                       E1_PASS_A_HANDOFF, NORMALIZED_CONCEPTS,
                       PRACTICE_EXPERIENCE, RETRIEVED_KNOWLEDGE
  E1/SINGLE/B        : CASE_VERSION, CANONICAL_STATE, E1_PASS_A_HANDOFF,
                       E7_HANDOFF, PRACTICE_EXPERIENCE, RETRIEVED_KNOWLEDGE
  E2/SINGLE/SINGLE   : CASE_VERSION, CANONICAL_STATE, E1_HANDOFF
  E3/SINGLE/SINGLE   : CASE_VERSION, CANONICAL_STATE, E1_HANDOFF, E2_HANDOFF
  E6/REBUILD/SINGLE  : CASE_VERSION, CANONICAL_STATE, NORMALIZED_CONCEPTS,
                       E1_HANDOFF, E2_HANDOFF, E3_HANDOFF
```

The last line is the bug: the step is *named* `E6_UPDATE` in
`client_new.py` and runs in mode `REBUILD`, and D52b's A8 declared those
blocks for `UPDATE`. `UPDATE` belongs to CLIENT_FOLLOWUP.

### R8 — the presence check could not see it, and that is a pattern

`if key not in content` asks *does this word appear anywhere in the prompt*.
`E1_HANDOFF` appeared — under an `UPDATE` paragraph — so a `REBUILD`
invocation passed. Third time in this gate:

| | the check | what it still passed on |
|---|---|---|
| first run | `if n in rank and low[0] in rank` | Strategy 3 absent → zero comparisons, green |
| D52a | the block reaches the provider boundary | an engine with no contract for it |
| D52b | the name appears in the prompt | the name attached to the wrong mode |

Replaced with a per-invocation **set equality** against a machine-checkable
declaration carried in each build-owned Addendum:

```
RUNTIME_INPUT_CONTRACT E6/REBUILD = CASE_VERSION, CANONICAL_STATE, NORMALIZED_CONCEPTS, E1_HANDOFF, E2_HANDOFF, E3_HANDOFF
```

```
  PASS  all 7 CLIENT_NEW invocation(s) match their declared runtime input
        contract exactly
  PASS  ...and all seven invocations were captured
  PASS  the final Engine 6 run is REBUILD, not UPDATE -- the mismatch this
        check exists to catch
  PASS  RETRIEVED_KNOWLEDGE is declared for E7 CASE and E1 Pass B
  PASS  ...and NOT Pass A, which is what decides what to retrieve
```

**Teeth, all three directions, each proven by breaking it:**

```
moved REBUILD's declaration under UPDATE  (the original bug, restaged)
  FAIL  E6/REBUILD/SINGLE: NO declaration in the prompt

dropped CASE_VERSION from E7's declaration
  FAIL  E7/CASE/SINGLE: sent but NOT declared ['CASE_VERSION']

added E7_HANDOFF to E2's declaration
  FAIL  E2/SINGLE/SINGLE: declared but NOT sent ['E7_HANDOFF']
```

### R9 — the follow-up piece GATE 3 introduced, and only that

CLIENT_FOLLOWUP's Engine 1 runs **once**, `pass = SINGLE`, and receives **no
`E7_HANDOFF` because Engine 7 does not run on that path** — so
`RETRIEVED_KNOWLEDGE` is the only library input it gets and nothing will
have reasoned over it first. Engine 1's A5 now states that case and repeats
the three rules: rank is relevance, a curated card is not published
evidence, Engine 1 remains the decision-maker.

**No declaration line is written for `E1/SINGLE/SINGLE`.** A declaration is
a complete set, and completing it means settling the whole follow-up
contract — recorded as a pre-existing gap rather than guessed at. The
regression drives CLIENT_NEW and makes no claim about a path it never runs.

### Verification, exit codes captured and checked, never behind a pipe

```
  rebuild + test_gate3_acceptance (live provider)   0
  bash testing/run_all.sh                           0    ALL SUITES PASSED
  bash testing/run_all.sh  (re-run, idempotent)     0    ALL SUITES PASSED
  bash testing/run_bare.sh (no optional extension)  0    ALL SUITES PASSED
```

---

## 14. REVIEW ROUND 4 (D52d) — the contract key needed a pipeline

**Sections 1–9 unchanged. The first run is still a MISS, 6 of 8.**

### R10 — the same engine/mode/pass, two pipelines, two payloads

D52c keyed the declaration on `(engine, mode, pass)`. Measured by driving
both pipelines for real, that triple does not identify an input shape:

```
CLIENT_NEW       E6/REBUILD/SINGLE
  CASE_VERSION, CANONICAL_STATE, NORMALIZED_CONCEPTS,
  E1_HANDOFF, E2_HANDOFF, E3_HANDOFF

CLIENT_FOLLOWUP  E6/REBUILD/SINGLE
  CASE_VERSION, CLIENT_ID, CURRENT_STATE, REVIEW_PERIOD,
  FOLLOWUP_ANSWERS, FOLLOWUP_STRUCTURED, LIVE_INTERVENTIONS,
  PRACTICE_EXPERIENCE, E4_HANDOFF, E6_DELTA,
  E1_HANDOFF, E2_HANDOFF, E3_HANDOFF
```

`client_new.py:571` and `client_followup.py:393` both call `engine="E6",
mode="REBUILD"` for the same stated reason. The full follow-up capture, with
Engine 4 routing `MULTIPLE` so E1/E2/E3 actually run:

```
E6/UPDATE/SINGLE   CASE_VERSION, CLIENT_ID, CURRENT_STATE, FOLLOWUP_ANSWERS,
                   FOLLOWUP_STRUCTURED, LIVE_INTERVENTIONS,
                   PRACTICE_EXPERIENCE, REVIEW_PERIOD
E4/SINGLE/SINGLE   … + E6_DELTA
E1/SINGLE/SINGLE   … + E4_HANDOFF, RETRIEVED_KNOWLEDGE
E2/SINGLE/SINGLE   … + E1_HANDOFF
E3/SINGLE/SINGLE   … + E2_HANDOFF
E6/REBUILD/SINGLE  … + E3_HANDOFF
```

`E2/SINGLE`, `E3/SINGLE` and `E6/REBUILD` all collide with CLIENT_NEW's.

### R11 — an absence the syntax could not express

D52c's prose said the follow-up contract is "deliberately not declared". With
a three-part key that could not be stated: a line already existed for each of
those triples, written for the other pipeline. The key is now
`PIPELINE ENGINE/MODE/PASS`, and the absence of a `CLIENT_FOLLOWUP` line now
means what it says.

```
  PASS  the follow-up routed to E1, E2 and E3
  PASS  CLIENT_FOLLOWUP invokes the same engine/mode/pass CLIENT_NEW does
  PASS  the follow-up has NO declaration of its own -- deliberately
        undeclared, and the pipeline scope is what makes that sayable
  PASS  ...and a PIPELINE-BLIND key would have collapsed all three onto
        CLIENT_NEW's contract and reported false violations
  PASS  CLIENT_NEW's E6/REBUILD declaration exists and is NOT the
        follow-up's payload
  PASS  ...and the follow-up E1 really does carry RETRIEVED_KNOWLEDGE,
        the block GATE 3 added to this path
```

**Teeth: reverting `runtime_contract.py` to the three-part key turns BOTH
suites red.**

```
test_client_new
  FAIL  all 7 CLIENT_NEW invocation(s) match their declared contract
        ['CLIENT_NEW E1/SINGLE/A: NO declaration',
         'CLIENT_NEW E1/SINGLE/B: NO declaration',
         'CLIENT_NEW E2/SINGLE/SINGLE: NO declaration',
         'CLIENT_NEW E3/SINGLE/SINGLE: NO declaration',
         'CLIENT_NEW E6/INIT/SINGLE: NO declaration',
         'CLIENT_NEW E6/REBUILD/SINGLE: NO declaration',
         'CLIENT_NEW E7/CASE/SINGLE: NO declaration']

test_followup
  FAIL  ...and a PIPELINE-BLIND key would have collapsed all three …
  FAIL  CLIENT_NEW's E6/REBUILD declaration exists and is NOT the
        follow-up's payload
```

`testing/runtime_contract.py` is the single parser both suites read. The
collision regression drives the real follow-up pipeline — it does not
construct the colliding payload by hand.

### Verification, exit codes captured and checked, never behind a pipe

```
  rebuild + test_gate3_acceptance (live provider)   0
  bash testing/run_all.sh                           0    ALL SUITES PASSED
  bash testing/run_all.sh  (re-run, idempotent)     0    ALL SUITES PASSED
  bash testing/run_bare.sh (no optional extension)  0    ALL SUITES PASSED
```

---

## 15. REVIEW ROUND 5 (D52e) — the prose was still mode-only

**Sections 1–9 unchanged. The first run is still a MISS, 6 of 8.** No runtime
code, retrieval, test, ranking, `0.82`, `b5b2477`, `038`/`039`, K10 or source
coverage changed. One file touched.

D52d scoped the machine-checkable declaration by pipeline. Engine 6's `A8`
prose was still organised by mode:

```
**REBUILD** — the end of a new-client cycle. You receive CASE_VERSION,
CANONICAL_STATE, NORMALIZED_CONCEPTS, E1_HANDOFF, E2_HANDOFF, E3_HANDOFF.
```

True of CLIENT_NEW. False of CLIENT_FOLLOWUP, which invokes `REBUILD` for its
own final state reconstruction (`client_followup.py:393`) and receives neither
`CANONICAL_STATE` nor `NORMALIZED_CONCEPTS`, plus eight blocks the new-client
path never sends. **The declaration a machine reads was scoped and the
paragraph a model reads was not** — the checker could no longer be misled and
the engine still could.

`A8` is now organised by PIPELINE first:

* **CLIENT_NEW** — `INIT`, then `REBUILD`, the six-block shape unchanged.
* **CLIENT_FOLLOWUP** — `UPDATE`, then **`REBUILD` again**, named as the same
  mode with a different payload; its context described in prose (review
  period, follow-up answers, current state, live interventions, Engine 4's
  reasoning, Engine 6's earlier delta) rather than as a field list.
* **"DO NOT APPLY THE CLIENT_NEW `REBUILD` FIELD LIST ABOVE TO A FOLLOW-UP
  RUN"**, with the instruction to read what the envelope and payload actually
  give on that path.

**No `CLIENT_FOLLOWUP` declaration was created.** The absence is still the
deliberate position D52d made expressible.

Mechanically confirmed: the `RUNTIME_INPUT_CONTRACT` lines are byte-identical
(no `+`/`-` declaration line in the diff), the manifest's `sections` count for
Engine 6 is unchanged at **89**, and `git diff --stat prompts/` reports one
file, 37 insertions, 11 deletions.

### Verification, exit codes captured and checked, never behind a pipe

```
  rebuild + test_gate3_acceptance (live provider)   0
  bash testing/run_all.sh                           0    ALL SUITES PASSED
  bash testing/run_all.sh  (re-run, idempotent)     0    ALL SUITES PASSED
  bash testing/run_bare.sh (no optional extension)  0    ALL SUITES PASSED
```
