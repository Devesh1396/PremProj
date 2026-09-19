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
