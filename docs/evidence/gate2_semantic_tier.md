# GATE 2 — the semantic tier, built and measured

**2026-09-18.** D51 diagnosed concept normalization and changed nothing.
This is the change, and what it did to the phrases the diagnosis was about.

Reproduce it from an empty database:

```bash
psql "$DATABASE_URL" -c 'drop schema public cascade; create schema public;'
python3 scripts/migrate.py
python3 scripts/load_prompts.py && python3 scripts/load_contracts.py
python3 scripts/load_handoffs.py && python3 scripts/load_prices.py
python3 scripts/seed_ontology.py            # 269 concepts
python3 scripts/embed_library.py --table concepts --limit 400
python3 scripts/normalization_sweep.py
```

**The measurement must run on a CLEAN K1 seed.** Taken after
`testing/run_all.sh` it is wrong, and quietly: `test_concept_layer` and
`test_knowledge_layer` insert SEEDED concepts under the K1 seed's own
canonical keys — `POSTPRANDIAL_GLUCOSE` becomes "Postprandial glucose",
`SKELETAL_MUSCLE_GLUCOSE_DISPOSAL` becomes "Skeletal muscle glucose
disposal" — so the ontology afterwards is 275 concepts, not 269, with
different names and types. The first run of this sweep was taken on that
database and scored 17 WRONG. Nothing was wrong with the tier. Raised here
rather than changed: the suites are entitled to their fixtures, and the
fix is a namespace, not a patch to the sweep.

Library measured: **269 SEEDED concepts, 269 embedded**, `gemini-embedding-2`,
1536 dimensions. Sweep cost **$0.000212** over 56 embedding calls.

---

## What changed

| | before | after |
|---|---|---|
| `_tier_semantic` | `return [], 0.0`, unconditionally | a real pgvector query through `embedding.embed()` |
| tier contract | `(ids, confidence)` — one list used as both "considered" and "resolved" | `TierResult(selected, candidates, confidence, rejected)` |
| thresholds | one `ALIAS_THRESHOLD` = 0.92 applied to whichever tier answered | `TIER_THRESHOLD` per tier; semantic 0.82 with its own floor 0.78 |
| a weak tier answer | ended the chain — a trigram near-match at 0.778 meant the semantic tier was never reached | remembered, and used only if nothing later does better |
| `concept_type` | never consulted | a caller-supplied allowed set, on the similarity tiers only |
| `mechanism` | sent to the concept resolver by K09, K11 and layer B | sent by none of them; unchanged on the claim |

---

## 1. Every phrase

56 distinct phrases, from the 71 proposal rows of the real D47 run
(`docs/evidence/first_source_loop_rows.md` §2). K09 was not re-run.
`nearest existing concept` is what the phrase RESOLVED to where it
resolved, and the nearest cosine neighbour where it did not. `score` is
always the raw top-1 cosine, so a refusal can be read against what it
refused.

```
  #  phrase                                         fld      nearest existing concept          score tier      status     verdict           
------------------------------------------------------------------------------------------------------------------------------------------------------------
  1  Postprandial glucose excursion and hyperinsuli target   meal-related glucose dynamics     0.848 semantic  RESOLVED   WRONG             
  2  Seated soleus push-up / calf raise             intv/K11 sarcopenia                        0.627 none      UNRESOLVED RIGHT             
  3  Magnification and sustained cellular oxidative mech     skeletal-muscle glucose disposal  0.758 none      UNRESOLVED PARTIAL_MISS      
  4  Postprandial glucose spike                     target   postprandial glucose              0.858 semantic  RESOLVED   RIGHT             
  5  Seated calf raises / soleus push-up            intv/K11 resistance training               0.644 none      UNRESOLVED RIGHT             
  6  Soleus muscle glucose uptake into contracting  mech     skeletal-muscle glucose disposal  0.847 semantic  RESOLVED   PARTIAL           
  7  Postprandial blood glucose concentration       target   post-meal glucose                 0.837 semantic  RESOLVED   RIGHT             
  8  Light-to-moderate continuous walking           intv/K11 walking                           0.754 none      UNRESOLVED MISSED            
  9  Contracting leg, arm, and core muscles clear g mech     skeletal-muscle glucose disposal  0.839 semantic  RESOLVED   PARTIAL           
 10  Postprandial glycemic control / glucose variab target   meal-related glucose dynamics     0.852 semantic  RESOLVED   WRONG             
 11  10 bodyweight air squats repeated every 45 min intv/K11 sedentary breaks                  0.668 none      UNRESOLVED RIGHT             
 12  Repeated interrupted sitting with large-muscle mech     sedentary interruption            0.804 semantic  UNRESOLVED PARTIAL_MISS      
 13  Light household activity / domestic exercise s intv/K11 physical activity                 0.738 none      UNRESOLVED PARTIAL_MISS      
 14  Low-intensity incidental muscular contraction  mech     skeletal-muscle glucose disposal  0.831 semantic  RESOLVED   PARTIAL           
 15  Non-insulin-mediated glucose uptake and circul target   skeletal-muscle glucose disposal  0.818 semantic  UNRESOLVED PARTIAL_MISS      
 16  Active skeletal muscle contraction (aerobic or intv/K11 skeletal-muscle glucose disposal  0.797 semantic  UNRESOLVED PARTIAL_MISS      
 17  Contracting muscle fibers uptake glucose indep mech     skeletal-muscle glucose disposal  0.844 semantic  RESOLVED   PARTIAL           
 18  Abdominal bloating, energy stability, sugar cr target   IBS-pattern symptoms              0.773 none      UNRESOLVED PARTIAL_MISS      
 19  Anti-Spike Formula (proprietary commercial sup intv/K11 supplement interventions          0.683 none      UNRESOLVED RIGHT             
 20  Natural plant-derived bioactive molecules miti mech     meal-related glucose dynamics     0.742 none      UNRESOLVED PARTIAL_MISS      
 21  Soleus push-up                                 intv/K11 sarcopenia                        0.619 none      UNRESOLVED RIGHT             
 22  Postprandial glucose excursion                 intv/K11 meal-related glucose dynamics     0.838 semantic  RESOLVED   WRONG             
 23  Postprandial hyperinsulinemia                  intv/K11 postprandial glucose              0.810 semantic  UNRESOLVED RIGHT             
 24  Oxidative phosphorylation                      intv/K11 VLDL production                   0.728 none      UNRESOLVED RIGHT             
 25  Sedentary behavior interruption                intv/K11 sedentary interruption            0.898 semantic  RESOLVED   RIGHT             
 26  soleus pushup                                  intv/K11 sedentary interruption            0.649 none      UNRESOLVED RIGHT             
 27  seated calf raises                             intv/K11 resistance training               0.693 none      UNRESOLVED RIGHT             
 28  postprandial glucose excursion                 intv/K11 postprandial glucose              0.895 semantic  RESOLVED   RIGHT             
 29  sedentary desk workers                         intv/K11 sedentary adults                  0.881 semantic  RESOLVED   WRONG             
 30  postprandial blood glucose concentration       intv/K11 postprandial glucose              0.955 semantic  RESOLVED   RIGHT             
 31  postprandial walking                           intv/K11 post-meal movement                0.833 semantic  RESOLVED   RIGHT             
 32  skeletal muscle glucose uptake                 intv/K11 skeletal-muscle glucose disposal  0.897 semantic  UNRESOLVED REFUSED_CONFUSABLE
 33  GLUT4 translocation                            intv/K11 glucose transport                 0.783 semantic  UNRESOLVED RIGHT             
 34  carbohydrate-rich meal                         intv/K11 carbohydrate quality              0.801 semantic  UNRESOLVED REFUSED_CONFUSABLE
 35  healthy adults                                 intv/K11 older adults                      0.763 none      UNRESOLVED RIGHT             
 36  Postprandial Glycemic Control                  intv/K11 postprandial glucose              0.838 semantic  RESOLVED   RIGHT             
 37  Sedentary Behavior Interruption                intv/K11 sedentary interruption            0.897 semantic  RESOLVED   RIGHT             
 38  Non-Insulin-Dependent Glucose Disposal         intv/K11 skeletal-muscle glucose disposal  0.840 semantic  UNRESOLVED REFUSED_CONFUSABLE
 39  GLUT4 Translocation                            intv/K11 glucose transport                 0.782 semantic  UNRESOLVED RIGHT             
 40  Air Squats                                     intv/K11 aerobic exercise                  0.651 none      UNRESOLVED RIGHT             
 41  Overweight and Obese Adults                    intv/K11 obesity                           0.763 none      UNRESOLVED RIGHT             
 42  Severe Knee Osteoarthritis                     intv/K11 bone-health issues                0.686 none      UNRESOLVED RIGHT             
 43  Mulberry leaf extract                          intv/K11 polyphenols                       0.633 none      UNRESOLVED RIGHT             
 44  1-deoxynojirimycin                             intv/K11 HbA1c                             0.613 none      UNRESOLVED RIGHT             
 45  Alpha-glucosidase inhibition                   intv/K11 HbA1c                             0.704 none      UNRESOLVED RIGHT             
 46  Postprandial hyperglycemia                     intv/K11 postprandial glucose              0.846 semantic  RESOLVED   RIGHT             
 47  Abdominal bloating                             intv/K11 bloating                          0.826 semantic  RESOLVED   RIGHT             
 48  Prescription antihyperglycemic medications     intv/K11 HbA1c                             0.771 none      UNRESOLVED RIGHT             
 49  Postprandial Glycemia                          intv/K11 postprandial glucose              0.847 semantic  RESOLVED   RIGHT             
 50  Glucose Incremental Area Under the Curve       intv/K11 CGM metrics                       0.791 semantic  UNRESOLVED PARTIAL_MISS      
 51  Type 2 Diabetes Mellitus                       intv/K11 type 2 diabetes                   0.828 semantic  RESOLVED   RIGHT             
 52  Impaired Glucose Tolerance                     intv/K11 prediabetes                       0.774 none      UNRESOLVED PARTIAL_MISS      
 53  Non-Insulin-Mediated Glucose Disposal          intv/K11 skeletal-muscle glucose disposal  0.841 semantic  UNRESOLVED REFUSED_CONFUSABLE
 54  Skeletal Muscle Contraction                    intv/K11 skeletal-muscle glucose disposal  0.685 none      UNRESOLVED RIGHT             
 55  Light-Intensity Physical Activity              intv/K11 physical activity                 0.769 none      UNRESOLVED MISSED            
 56  Postprandial Window                            intv/K11 postprandial glucose              0.808 semantic  UNRESOLVED RIGHT             
```

### Verdicts

```
  RIGHT                33
  PARTIAL_MISS         9
  WRONG                4
  PARTIAL              4
  REFUSED_CONFUSABLE   4
  MISSED               2
```

Scored against `testing/fixtures/normalization/d47_answer_key.json`, which
was committed in `dd95388` — **before the tier existed**. Nothing here
assigned a verdict after seeing a score.

- **RIGHT 33.** 20 resolutions the key names, plus 13 phrases the key says
  should NOT resolve and did not.
- **PARTIAL 4 / PARTIAL_MISS 9.** Sentences and compounds. No single
  concept IS the phrase, so neither resolving to one of its parts nor
  refusing is scored as success.
- **REFUSED_CONFUSABLE 4.** The guard fired. Detail in §4.
- **MISSED 2.** `Light-to-moderate continuous walking` (best 0.754) and
  `Light-Intensity Physical Activity` (0.769) sit under the 0.78 floor.
  These are the measured cost of the floor, not a failure of the tier.
- **WRONG 4**, below.

### The four WRONG, in full, because three of them share one shape

```
  Postprandial glucose excursion and hyperinsulinemia -> meal-related glucose dynamics  0.8478
                                                         postprandial glucose           0.8366
  Postprandial glycemic control / glucose variability -> meal-related glucose dynamics  0.8520
                                                         glycaemic variability          0.8484
  Postprandial glucose excursion                     -> meal-related glucose dynamics  0.8384
                                                         postprandial glucose           0.8378
  sedentary desk workers                             -> sedentary adults               0.8808
```

**The top-1 rule decides the first three on margins of 0.0112, 0.0036 and
0.0006.** Six ten-thousandths is not a judgement, and the concept it picks
each time — `meal-related glucose dynamics` — is a defensible reading that
the answer key's `to` list did not anticipate. Two things follow and they
point in opposite directions, so both are recorded:

1. The key may be under-specified for these three. **It is not being
   edited.** A key rewritten after seeing which concept the tier chose is
   not an answer key.
2. A selection decided by 0.0006 should not be a selection at all. The
   comment that removed trigram's tie rule already says why — "two
   near-equal cosine scores mean the query sits BETWEEN two concepts, which
   is an ambiguity, not a statement that they are the same thing" — and the
   tier then selects the top-1 anyway. **A margin rule is the obvious next
   change and is deliberately NOT made here**, because a margin sized to
   fix exactly these three rows is fitted to three rows. It needs its own
   measurement on phrases that are not these.

`sedentary desk workers -> sedentary adults` is the verdict D51 recorded
and the key inherited, flagged at the time as one a later reading might
call a defensible generalization. It is still counted WRONG.

---

## 2. Score distribution, per tier

Over the 56 phrases, where the tier answered at all:

```
  alias      —
  trigram    min 0.778  median 0.778  max 0.778  n=1
  semantic   min 0.613  median 0.799  max 0.955  n=56
```

The gap is the whole finding, and it reproduces D51's independently: the
trigram tier's best score across this corpus is well under the 0.92 it is
judged against, while cosine's median sits above 0.82. **One constant could
not have served both.**

Measured while fixing a test, and worth its own line: a ONE-CHARACTER typo
in a 26-character phrase scores **0.833** on trigram, and one dropped letter
in 38 characters scores **0.902**. `ALIAS_THRESHOLD` is 0.92, so on
realistic clinical vocabulary **the trigram tier can near-match and
essentially cannot resolve.** That is not changed here — it is a second
threshold decision with its own measurement to do — but it explains why
`test_normalization`'s "the confirmed spelling is learned as an alias"
check had never once executed: it was guarded by `if r.decision ==
"RESOLVED"` and that branch was unreachable.

---

## 3. The threshold sweep — what each one would resolve RIGHT and WRONG

Raw top-1 against the committed key, with the confusable guard applied as
`resolve()` applies it, so the sweep measures the resolver that exists.

```
   thr  admits  RIGHT  PARTIAL   BROADER  WRONG  refusedCD   worst thing admitted
  0.92       1      1        0        0      0         0   —
  0.88       5      4        0        0      1         1   sedentary desk workers -> sedentary adults (0.881)
  0.85       7      5        0        0      2         1   Postprandial glycemic control / glucose variability -> m
  0.84      12      7        2        0      3         3   Postprandial glucose excursion and hyperinsulinemia -> m
  0.82      20     12        4        0      4         3   Postprandial glucose excursion and hyperinsulinemia -> m
   0.8      24     12        6        0      6         4   Postprandial glucose excursion and hyperinsulinemia -> m
  0.78      28     12        8        2      6         4   Postprandial glucose excursion and hyperinsulinemia -> m
  0.76      34     13        9        2     10         4   Postprandial glucose excursion and hyperinsulinemia -> m
  0.72      39     14       11        2     12         4   Postprandial glucose excursion and hyperinsulinemia -> m
  0.65      46     14       11        4     17         4   Postprandial glucose excursion and hyperinsulinemia -> m
   0.6      52     14       11        5     22         4   Postprandial glucose excursion and hyperinsulinemia -> m
```

**0.82 is confirmed, not chosen.** It was fixed in code before this sweep
ran, from D51's independent measurement, and the key it is scored against
was committed before that. Above it the tier answers almost nothing; below
0.80 WRONG grows faster than RIGHT (0.82 → 0.76 buys one more RIGHT and
six more WRONG).

**It is PROVISIONAL and here is what would falsify it:**

- A phrase set that is not failure-selected. These 56 are the phrases D47
  failed to resolve; a phrase that resolved wrote no proposal row and is
  not here. The sweep therefore says what a threshold RECOVERS and is
  silent on what it BREAKS among phrases that already worked.
- A second seeded domain. Metabolic health is vocabulary-coherent, which
  is why the cosine floor across 269 concepts is 0.613 rather than near
  zero. A domain whose vocabulary overlaps less would move the whole
  distribution and the knee with it.
- More than 269 concepts. Every phrase here is ranked against a small
  library; a library ten times the size has more chances to put something
  irrelevant above 0.82.
- Any change of embedding model. The number is a property of
  `gemini-embedding-2` at 1536 dimensions, not of the idea of cosine.

Re-measure with `scripts/normalization_sweep.py` and change
`CONCEPT_SEMANTIC_THRESHOLD`; it is an environment variable for that
reason, and it is not shared with `CONCEPT_AUTO_ALIAS_THRESHOLD`.

---

## 4. Every CONFUSABLE_DO_NOT_MERGE pair, and proof the tier surfaces both

The seed holds **5 distinct pairs** (10 rows, mirrored by
`trg_mirror_confusable`; `seed_ontology.py` reports 6, counting one
differently — worth a look, not chased here).

```
  pair                                                       cosine   both in top-3
  adipose insulin resistance  <->  hepatic insulin resistance  0.8643   no
  carbohydrate amount         <->  carbohydrate quality        0.8296   YES
  fibre strategies            <->  sleep strategies            0.6508   no
  glucose disposal            <->  skeletal-muscle glucose d.  0.8512   YES
  menopause                   <->  perimenopause               0.9143   YES
```

Three of five pairs put both members in a top-3 — including
`menopause`/`perimenopause` at 0.9143, which any threshold worth having
would admit. **A top-1 tier could not have objected to any of them.**

Four phrases in the corpus were refused by the guard, and the reason is
visible in the candidate list rather than inferred:

```
  skeletal muscle glucose uptake          [skeletal-muscle glucose disposal 0.897,
                                           glucose transport 0.832, glucose disposal 0.795]
  Non-Insulin-Dependent Glucose Disposal  [skeletal-muscle glucose disposal 0.840,
                                           glucose disposal 0.784, glucose transport 0.766]
  Non-Insulin-Mediated Glucose Disposal   [skeletal-muscle glucose disposal 0.841,
                                           glucose disposal 0.786, insulin sensitivity 0.763]
  carbohydrate-rich meal                  [carbohydrate quality 0.801,
                                           carbohydrate amount 0.785, meal preparation 0.747]
```

In every one the SELECTION was a single concept and the SECOND or THIRD
candidate is what carried the objection. The last is the case D51 named:
the one wrong merge it admitted at 0.80, refused here by a guard that could
not have seen it under the old contract.

Three of the four are phrases the key expects to resolve. **The guard costs
three correct resolutions on this corpus, and that is the right trade**:
`glucose disposal` and `skeletal-muscle glucose disposal` are marked
do-not-merge because collapsing them loses the distinction between whole-body
and muscle-specific disposal, and a resolver that picked one because it
scored 0.05 higher would be making that clinical call on a rounding.

`testing/test_normalization.py` proves the mechanism rather than the
corpus: a three-candidate tier with a do-not-merge pair in the candidates
and one concept in the selection refuses, and the same phrase with the pair
removed resolves.

---

## 5. Category crossings, and the honest limit of the type guard

**On the phrases whose type is structurally known, the guard fired zero
times.** Only `target` is recoverable — the seven stored claims record
`target` and `mechanism` verbatim, so those 13 phrases are identified
exactly, and the other 43 came from the Claim Card `intervention` field or
from K11's strategy-concept phrases, which the claim row does not
distinguish. For six target phrases the top candidate was PHYSIOLOGY or
BIOMARKER, both of which `TARGET_TYPES` allows.

So the corpus does not demonstrate the guard. It demonstrates something
else, and it is the reason for the rule the guard is built on. Asking what
would happen if those 43 unknown-field phrases were ASSUMED to have come
through `intervention`:

```
  refused by type: 12        admitted: 3
  of the 12 refusals, ONE is a merge the key forbids (sedentary desk workers -> sedentary adults)
  the other ELEVEN are correct resolutions the guard would have destroyed, including
      postprandial blood glucose concentration -> postprandial glucose   0.9545
      Type 2 Diabetes Mellitus                -> type 2 diabetes         0.8276
      Abdominal bloating                      -> bloating                0.8261
```

Those eleven are not interventions; they are targets and conditions that
sit in the unknown bucket because K11 phrases land there. **Feeding a type
set to a phrase whose provenance you do not actually know destroys eleven
right answers to prevent one wrong one.** That is the measured form of
"a type guard without a trustworthy source type is not a guard", and it is
why `allowed_types=None` means *no constraint* rather than a default.

The diagnosis's own category crossings — `Postprandial Window -> postprandial
glucose`, `1-deoxynojirimycin -> HbA1c`, `Prescription antihyperglycemic
medications -> HbA1c`, `Overweight and Obese Adults -> obesity` — are ALL in
the unknown bucket. **The guard would catch them only if those phrases
arrive through a typed field, and this corpus cannot show that they did.**
What can be shown is that the guard works when it has a real type, and
`test_normalization.py` shows exactly that, against a fixture where the
caller's knowledge is real: a POPULATION concept, a caller that
structurally wants a target, a refusal that names the type and what was
allowed, no shopping down the list for a type-compatible second choice, and
the same phrase resolving when no caller claims to know.

Three of the four crossings would also need concept types the enum does not
have — a TIME WINDOW, a MOLECULE and a DRUG CLASS are none of the fifteen.
Refusing them is a separate question from typing them.

---

## 6. Dataset B — the structural tests, scored separately

`testing/test_normalization.py`, 57 checks, run at every candidate
threshold:

```
  0.92  0.88  0.85  0.82  0.80  0.78  0.72  0.65
  pass  pass  pass  pass  pass  pass  pass  pass
```

**Read that carefully: it constrains the MECHANISM and says nothing about
the threshold.** Its fixture vectors sit at cosine 1.000, 0.906 and 0.839
by construction, so the top-1 clears every candidate threshold and the
suite cannot discriminate between them. What it does establish is that no
structural invariant depends on 0.82 — candidate-set-is-not-resolution, the
confusable refusal, the type refusal, the no-confirmed-alias rule and the
V3 degradation all hold from 0.65 to 0.92.

Building a fixture that DID discriminate would mean choosing which fixture
phrases ought to resolve at 0.82 and which ought not — writing both halves
of the comparison, which is V2's recurring failure. The thresholds are
measured on dataset A, where the expectations came from somewhere else.

---

## 7. What this does not claim

- **It is not GATE 3.** `retrieval.by_concept()` reads `strategies`,
  `strategy_concepts` and `implementation_patterns` and does not reference
  `curated_strategies` at all. Nothing here changes that, and the six
  curated Video 1 strategies are no more retrievable than they were.
- **The tier is inert on the VPS.** `MODEL_EMBEDDING` is deliberately unset
  there, so `resolve()` degrades to alias + structured + trigram and says
  so. Enabling it is a spending decision.
- **`resolve()` is no longer free.** Every phrase the cheap tiers cannot
  answer costs one embedding call. `normalization_cache` covers repeats of
  a RESOLVED phrase; a phrase that fails re-embeds every time, so the D47
  run's 71 proposals over 56 phrases would pay 71 calls, not 56. At the
  text rate that is about $0.00005 for a source, and it is a real change to
  what a resolver does.
- **The LLM tier is untouched**, still last, still optional, still
  unreachable from K09. D51 put it at about 2 calls in 56 once the tier
  below it works; nothing here tests that estimate.


---

## 8. After the review — three bypass paths, closed

An independent review of this branch found three places where a guard
existed and a path around it did not. All three are closed, each is proven
by reverting the fix and watching the suite go red, and **none of them
moves a single number in §1–§6**: the historical sweep is byte-identical
before and after, phrase for phrase and verdict for verdict. They were
bypasses, not scoring errors, which is exactly why a green sweep did not
find them.

### 8.1 The cache answered what the resolver would refuse

`normalization_cache` is keyed on `phrase_norm` alone and `resolve()`
returned a hit **before** `allowed_types`, before the type rejection,
before the candidate set existed and before `confusable_with()` ran. Two
distinct holes:

**Context.** A phrase first resolved with nobody claiming to know its type
was served unchanged to a caller that DID know. Measured: `c3test people
who sit at desks` resolves to a POPULATION concept untyped, and the old
cache then returned that same POPULATION concept to a caller supplying
`TARGET_TYPES`. The guard never ran.

**Staleness.** A semantic resolution is the top-1 of a set and the
confusable guard fires on the SET, so re-checking the cached ANSWER cannot
catch a pair added afterwards — one concept spans nothing. Measured: add a
`CONFUSABLE_DO_NOT_MERGE` pair after caching, and the live resolver
escalates while the old cache kept serving the answer.

Migration `034` stores `candidate_ids` (so the confusable guard re-runs
over what the tier considered) and `resolved_under_types`. `cache_is_safe()`
runs both checks on every read; a failed check is a MISS and the tiers
resolve properly, rather than the row being deleted — deleting it would
make the cache depend on who asked last.

**`resolved_under_types` is provenance, not the check.** NULL means the
type was unknown at write time, which is **not** "valid for every type".
What has to hold is that the cached concept is a kind of thing THIS caller
allows, so that is what is checked. One property makes reading a row
written under a narrower set safe: the type guard refuses and never shops,
so a cached answer is always the tier's own top-1 and never a second choice
promoted because it fitted. A row written before `034` has no candidate set
and is refused rather than trusted.

### 8.2 A structurally known intervention became a PROPOSED PHYSIOLOGY

`_propose_new(..., "PHYSIOLOGY")` was a literal at the end of the chain. So
`soleus push-up`, arriving from a Claim Card `intervention` field that §R11
defines as "what is being done or taken", became a PROPOSED **PHYSIOLOGY**
concept — undoing the type work one line below it.

There is no honest narrow type to write: §R11 does not say EXERCISE rather
than FOOD rather than BEHAVIOUR, and choosing from the phrase's wording is
the resolver answering its own question. `concepts.concept_type` is NOT
NULL and the enum has no UNKNOWN, so a phrase typed only to a SET now gets
a `concept_proposals` row carrying that set (`allowed_types`, migration
`034`) with decision `NEEDS_TYPE` and **no concept at all**. A set of
exactly one is knowledge and is used.

Nothing downstream is worse off. A strategy with no canonical concept is
already recorded as an OPEN gap rather than linked to a PROPOSED one to
make a count look right (D8), and a PROPOSED concept is not retrievable
anyway — it was junk in the ontology, not a working answer. `v_concept_needs_type`
(migration `035`) is a READ, not a queue: nothing is blocked on anyone
emptying it, and these rows are not counted against D8's escalation cap.

**And one attempt now leaves one row.** The type-rejection branch wrote a
`LOGGED` proposal and then fell through to `AUTO_CREATE`, so a single
normalization attempt left two rows saying opposite things. The refusal is
carried to the terminal row instead.

### 8.3 An unconfirmed alias resolved through the trigram tier

`_tier_alias` filters `a.confirmed`. `_tier_trigram` joined
`concept_aliases` with no such filter, so an unconfirmed alias equal to the
query contributed `similarity = 1.0` and resolved the phrase through the
back door — the alias tier refusing the row while the tier underneath it
used the same row as an exact match. **"Unconfirmed" meant nothing.**

Measured by reverting the fix: the trigram tier returns
`1.0 ['c3test alias host concept']` off a row marked `confirmed = false`.

This is the hole that made the semantic tier's no-alias rule necessary, and
closing it is what makes an unconfirmed row genuinely inert rather than
inert by convention. Confirming the alias turns the deterministic path back
on, and the suite asserts both directions.

---

## 9. The production-relevant subset

The committed answer key is unchanged and §1–§6 remain the full historical
56. But **the seven `mechanism` phrases are no longer sent to the resolver
at all** after this work, so they are history rather than a measurement of
what the system now does. Reported separately rather than by editing the
sample:

```
full historical 56
  RIGHT 33  PARTIAL 4  PARTIAL_MISS 9  REFUSED_CONFUSABLE 4  MISSED 2  WRONG 4   (n=56)

production-relevant 49  (target + intervention/K11; mechanism excluded)
  RIGHT 33  PARTIAL 0  PARTIAL_MISS 6  REFUSED_CONFUSABLE 4  MISSED 2  WRONG 4   (n=49)

the 7 mechanism propositions, on their own
  RIGHT 0  PARTIAL 4  PARTIAL_MISS 3  REFUSED_CONFUSABLE 0  MISSED 0  WRONG 0   (n=7)
```

**Excluding mechanism removes no RIGHT and no WRONG.** All seven were
PARTIAL or PARTIAL_MISS — sentences whose core idea a seeded concept names
but which no single concept IS. That is the expected shape: a proposition
could never have scored RIGHT, and the four PARTIAL verdicts in the full
set are all of them.

**0.82 is not re-derived from this subset and is not retuned.** The subset
is a narrower view of the same measurement, not a new one, and choosing a
threshold from it after seeing it would be the fitting this whole exercise
is structured to avoid.

---

## 10. The cache is bound to the ontology revision (migration `036`)

§8.1 made the cache re-run its guards over the **stored** candidate set.
That closes a stale confusable pair and a wrong caller type, and it cannot
close the opposite shape: **a concept that did not exist when the row was
written was never a candidate**, so re-checking the stored set can never
surface it. For a system whose design is a continuously growing ontology,
that means every cache entry decays as the library grows.

The case that settles it is not the stale score. It is the **confirmed
alias**: the alias tier runs first and is exact, so a confirmed alias is
the most authoritative mapping in the chain. Reverting the fix reproduces
it exactly —

```
FAIL  THE OLD CACHE DOES NOT OUTRANK A NEWLY CONFIRMED ALIAS
      <RESOLVED cache conf=0.98 n=1 'c3test a phrase whose best answer will change'>
```

— the cache serving a 0.98 cosine guess over a mapping a human had just
confirmed. That is not a stale score, it is overriding a deliberate human
decision.

`ontology_revision` is one row with one counter. A cache row records the
revision it was resolved against; a read at a different revision is a MISS
and the ordinary tiers run. **Nothing is re-embedded on a bump** — the row
is not deleted, it is overwritten when the phrase is next actually
resolved, which keeps the existing cache model and makes invalidation lazy.

### The trigger set, stated rather than assumed

Derived by walking every tier and asking what it reads.

**Advances the revision:**

| table | when |
|---|---|
| `concepts` | INSERT or DELETE of a row with `status IN ('SEEDED','ACTIVE')` |
| `concepts` | UPDATE crossing the SEEDED/ACTIVE boundary, or changing `canonical_name`, `canonical_key`, `concept_type`, `embedding` or `merged_into` on a live row |
| `concept_aliases` | a **confirmed** alias inserted, deleted, un/re-confirmed, or its text or concept changed |
| `concept_relations` | a `CONFUSABLE_DO_NOT_MERGE` relation inserted, deleted, or either end changed |

**Does not, and why it cannot affect a resolution:**

| | why |
|---|---|
| `concepts.retrieval_hits` / `last_retrieved` | telemetry — and **this is the decisive one**: `retrieval.py` writes it on every retrieval read, so a trigger on any write to `concepts` would have every search invalidate the whole cache. That is the opposite of D2, and it is why the trigger set is column-scoped rather than table-scoped. |
| `concepts.definition` | feeds `search_text`, which feeds the FTS index and the embedding TEXT. No tier reads it. A definition edited and not re-embedded has changed no answer; the re-embed writes `embedding` and bumps. |
| `concepts.embedding_model` / `embedding_dim` / `embedding_source_hash` | provenance for the vector, never compared, and only ever written alongside `embedding`. |
| `concepts.parent_concept_id` | read by the normalization TEST generator (sibling pairs), never by the resolver. |
| `origin_method`, `origin_detail`, timestamps | provenance. |
| a concept at `PROPOSED` / `MERGED` / `DEPRECATED` | no tier selects it. **This is the common ingestion write** — `_propose_new` creates PROPOSED concepts by the dozen. Promotion INTO SEEDED/ACTIVE does bump. |
| an **unconfirmed** alias | proven inert in both tiers by §8.3. A record for a human, not an input. |
| `concept_aliases.method` / `confidence` | recorded, never matched on. |
| any other `relation_type` | `confusable_with()` is the resolver's only reader of that table. |

Transition tables rather than `UPDATE OF col`: `UPDATE OF` fires when a
statement *mentions* a column, even setting it to its existing value. The
triggers compare old and new values, so `set status = status` does not bump.

### What it costs, measured

**A global counter invalidates 100% of the cache on any qualifying change.**
That is accepted deliberately. It is affordable because invalidation is
lazy — the bill is *one embedding per distinct phrase actually used after
the change*, not one per cached row.

```
mean embedding call, measured over 67 real calls   $0.0000017
D47 phrases that reach the semantic tier           56 of 56
  -> a full re-walk of that source's vocabulary    $0.000094
a 1,000-phrase library, fully re-walked            ~$0.0017
a 100,000-phrase library, fully re-walked          ~$0.17
```

The last row is the honest worst case and it is still not the real cost,
because nothing re-walks a library — phrases are re-resolved when they are
asked for.

**And the counter barely moves during the work that matters:**

```
test_knowledge_factory  (a full K09 ingestion)   revision 140 -> 140   0 bumps
test_curated            (a curated import)       revision 140 -> 140   0 bumps
seed_ontology           (re-run, all reused)     revision 140 -> 142   2 bumps
```

Zero bumps across an entire source going through ingestion, because the
common write is a PROPOSED concept and no tier can see one. Bumps come from
deliberate acts: seeding, promoting a proposal, confirming an alias,
recording a do-not-merge pair, re-embedding a batch.

### Why global, and not something cleverer

**Per-concept-neighbourhood scoping cannot address the case that motivated
this.** A NEW concept has no prior relationship to any stored
neighbourhood — that is the bug, not an implementation detail of it. Making
it work would mean storing every cached phrase's **query vector** (1536
floats per row) and comparing each new concept against all of them on every
ontology change, to save calls costing fractions of a cent.

One narrowing genuinely is cheap, and is recorded rather than built: a
newly confirmed alias could invalidate only the rows whose `phrase_norm`
equals its `alias_norm`, because that tier is exact. It is not built
because it would leave two invalidation rules to keep in agreement, and the
one it would replace is not expensive. If the numbers ever change, that is
the first thing to reach for.

### Ordering

The alias is now attached **before** the cache row is written. A confirmed
alias advances the revision, so caching first would stamp the row with the
old revision and the next read would miss on a bump that same call caused.
Correct either way — a miss is safe — but one ordering throws away the
entry it just wrote.

### What this does not change

**The threshold is untouched and the sweep is untouched.** 0.82 remains
PROVISIONAL, the committed answer key is unedited, no margin rule was
added, and the production-relevant 49-phrase set still carries **4 known
WRONG resolutions**. This work makes the resolver safer; it does not make
the calibration settled, and nothing here should be read as saying it does.
