# Why 71 phrases produced one resolution

**2026-09-11.** Diagnosis before any resolver change, because the LLM is
the last tier by design (D8) and reaching for it first pays a model call
for work the cheap tiers should do free. At 500 sources that is the cost
curve `v_cost_by_operation` exists to catch.

The phrases are the live run's own `concept_proposals` rows, read from
the database that run wrote. The 269 seeded concepts were embedded for
real against `gemini-embedding-2`. **Total cost of this diagnosis:
$0.000301, 328 embedding calls.**

One thing to fix before reading further: **the 71 proposals are the
phrases that FAILED.** A phrase that resolves writes no proposal row —
which is why `insulin resistance`, the one resolution, is not among them.
The sample is the failures, which is the right sample for this question
and the wrong one for a hit rate.

---

## The headline: the semantic tier does not exist

`normalize._tier_semantic()` is a stub. Its last line returns
unconditionally:

```python
def _tier_semantic(conn, phrase_norm: str) -> tuple[list[str], float]:
    # Requires pgvector AND embeddings actually written. Neither is true
    # until K14, so this tier reports "cannot answer" rather than pretending.
    if not _capability(conn, "vector"):
        return [], 0.0
    embedded = conn.execute(
        "select count(*) from concepts where embedding is not null").fetchone()[0]
    if embedded == 0:
        return [], 0.0
    return [], 0.0          # <-- both guards passed, and it still returns nothing
```

Its comment says "neither is true until K14". **K14 is built** — step 17,
`retrieval.by_vector()` runs a real pgvector query. The resolver's tier
was never wired up behind it.

### Proven live, not inferred from reading

pgvector 0.6.0 installed, a database migrated with it present, all 269
seeded concepts embedded with real 1536-dim unit-norm vectors:

```
vector capability : True
concepts embedded : 269

A. normalize._tier_semantic() called directly, both guards satisfied
   Light-to-moderate continuous walking       -> ids=[] confidence=0.0
   Postprandial blood glucose concentration   -> ids=[] confidence=0.0
   Soleus muscle glucose uptake into contra…  -> ids=[] confidence=0.0

B. normalize.resolve(read_only=True) over all 71 phrases
   UNRESOLVED   71
   tier that answered: {'none': 67, 'trigram': 4}
   RESOLVED: 0 of 71
```

**Question 1 is answered, and the answer is not a number.** pgvector was
absent in the original run, so that run said nothing about the semantic
tier — but making it present changes nothing, because the tier returns
empty either way. Embedding the library would have bought exactly zero
resolutions.

---

## What a working semantic tier would have found

The tier is a stub, so this asks the question it would have asked: embed
the phrase, cosine-rank the 269 embedded concepts, take the best. **This
is a measurement, not a proposed implementation.**

The signal is there, and it is not marginal:

```
phrase                                        trigram best          cosine best
postprandial blood glucose concentration   postprandial glucose 0.512   postprandial glucose  0.955
skeletal muscle glucose uptake             skeletal-muscle glu. 0.615   skeletal-muscle glu.  0.897
Soleus muscle glucose uptake into contra…  skeletal-muscle glu. 0.190   skeletal-muscle glu.  0.847
postprandial walking                       postprandial glucose 0.448   post-meal movement    0.833
Light-to-moderate continuous walking       walking              0.216   walking               0.754
```

```
cosine  min 0.613  median 0.799  max 0.955
trigram min 0.068  median 0.267  max 0.778
```

### It is not only length — it is synonymy

`postprandial walking` is **twenty characters**. Trigram's best is
`postprandial glucose` at 0.448 — it matched the wrong word, because
`postprandial` shares trigrams and `walking` does not help it reach
`post-meal movement`. Cosine puts `post-meal movement` first at 0.833.

Two vocabularies for one idea — *postprandial* / *post-meal*, *uptake* /
*disposal* — share almost no trigrams. That is not a length problem and
no threshold change reaches it. It is the thing an embedding is for.

---

## Question 2: the threshold, and why lowering it is not the fix

`ALIAS_THRESHOLD` is **0.92** (`CONCEPT_AUTO_ALIAS_THRESHOLD`).
`CREATE_THRESHOLD` is **0.72**, and it is not a second decision point —
it is the `HAVING` gate inside `_tier_trigram`, so anything scoring under
0.72 **never leaves the query**. That is why 67 of 71 show
`method='none'`: the tier did not return a weak answer, it returned no
answer.

Between the two, `resolve()` writes `LOGGED` or `ESCALATED`. The one
near-match in the whole run sat exactly there: `Postprandial glucose
spike` → `postprandial glucose`, 0.778, LOGGED at impact 0.

### Trigram cannot be rescued by a threshold

```
  cosine >= 0.92:  1 of 56    | trigram >= 0.92:  0
  cosine >= 0.85:  8 of 56    | trigram >= 0.85:  0
  cosine >= 0.80: 28 of 56    | trigram >= 0.80:  0
  cosine >= 0.72: 43 of 56    | trigram >= 0.72:  1
  cosine >= 0.60: 56 of 56    | trigram >= 0.60:  7
```

To admit `Light-to-moderate continuous walking → walking` on trigram you
would need a threshold of 0.216 — below which `Severe Knee Osteoarthritis
→ insulin sensitivity` (0.068) and `soleus pushup → sodium` (0.105) are
also admitted. **0.216 is not a near-miss, it is noise.**

### The cosine sweep, with verdicts

Verdicts are mine, one line of reasoning each, assigned from the meaning
of the pair and **not** from the score — deriving the label from the
number would make the analysis circular. `PARTIAL` means the phrase is
compound or a sentence and the top-1 is one of its parts.

```
   thr  admits  RIGHT  PARTIAL  WRONG   worst thing admitted
  0.92       1      1        0      0   —
  0.88       6      5        0      1   sedentary desk workers -> sedentary adults
  0.85       8      6        1      1   "
  0.84      15     10        4      1   "
  0.82      23     16        6      1   "
  0.80      28     16        8      4   carbohydrate-rich meal -> carbohydrate quality
  0.78      32     18        9      5
  0.76      38     19       10      9   healthy adults -> older adults
  0.72      43     21       11     11
  0.65      50     22       12     16   seated calf raises -> resistance training
  0.60      56     22       12     22   soleus pushup -> sedentary interruption
```

**0.82 is the knee.** 23 admitted, 16 right, 6 partial, 1 wrong. Below
0.80 the wrong merges triple while the right ones stop growing.

At 0.92 — the current threshold — the semantic tier would resolve **1 of
56**. The threshold is calibrated for trigram, where 0.92 means near-identity.
Cosine over a domain-coherent corpus has a much higher floor (min 0.613
here, for `1-deoxynojirimycin` against `HbA1c`, which share nothing).
**The thresholds cannot be shared between the two tiers.** That is a
finding in its own right: `ALIAS_THRESHOLD` is currently one constant
applied to whichever tier answered.

### The wrong merges are a type error, not a near-miss

Every `WRONG` verdict has the same shape — a category crossing:

```
Postprandial Window                        -> postprandial glucose   0.808   a TIME WINDOW mapped to a biomarker
Prescription antihyperglycemic medications -> HbA1c                  0.771   a DRUG CLASS mapped to a biomarker
Alpha-glucosidase inhibition               -> HbA1c                  0.704   a MECHANISM mapped to a biomarker
1-deoxynojirimycin                         -> HbA1c                  0.613   a MOLECULE mapped to a biomarker
Overweight and Obese Adults                -> obesity                0.763   a POPULATION mapped to a CONDITION
healthy adults                             -> older adults           0.763   a different population
Air Squats                                 -> aerobic exercise       0.651   resistance mapped to aerobic
Severe Knee Osteoarthritis                 -> bone-health issues     0.686   a joint disease is not a bone disease
```

`concepts.concept_type` already exists and already distinguishes
`PHYSIOLOGY` / `BIOMARKER` / `CONDITION` / `INTERVENTION` / `EXERCISE` /
`MEDICATION_CONTEXT` / `OUTCOME` / `SYMPTOM`. Most of these merges cross
a type boundary and could be refused without any threshold at all.
**A type check is a cheaper and sharper instrument than a threshold**,
and it does not exist in the resolver today.

### CONFUSABLE_DO_NOT_MERGE: the guard works, but only on a span

`confusable_with()` fires when a resolution's answer set **spans** a pair
— it cannot fire on a single top-1. Four phrases' top-3 spans a pair:

```
Non-Insulin-Dependent Glucose Disposal   [skeletal-muscle glucose disposal 0.840, glucose disposal 0.784, …]
Non-Insulin-Mediated Glucose Disposal    [skeletal-muscle glucose disposal 0.841, glucose disposal 0.786, …]
skeletal muscle glucose uptake           [skeletal-muscle glucose disposal 0.897, glucose transport 0.832, glucose disposal 0.795]
carbohydrate-rich meal                   [carbohydrate quality 0.801, carbohydrate amount 0.785, …]
```

The last one is the single WRONG merge admitted at 0.80 — and the guard
**would** have caught it, because both halves of the pair are in the
top-3. So the tier must return a candidate SET, not a top-1. A top-1
implementation silently defeats a guard that already works.

Twelve phrases have a top-1 that is one half of a do-not-merge pair;
`skeletal-muscle glucose disposal` is the magnet for ten of them, nine of
which are `PARTIAL` sentences. That is the next section.

---

## Question 3: three phrases through every tier

```
PHRASE : Light-to-moderate continuous walking        (36 chars)
  tier 0  cache       : miss
  tier 1  alias/exact : [] — would need a concept literally named this; there is none
  tier 2  structured  : [] — unit/biomarker patterns; not a similarity tier
  tier 3  trigram     : [] — best available ('walking', 0.216); the HAVING gate is
                             CREATE_THRESHOLD=0.72, so it never left the query
  tier 4  semantic    : [] — STUB. Data would have supported ('walking', 0.754)
  tier 5  LLM         : not reached — normalize_claim_concepts() passes llm=None
  OUTCOME             : AUTO_CREATE, a 36-character "concept"

PHRASE : postprandial walking                        (20 chars)
  tier 3  trigram     : [] — best ('postprandial glucose', 0.448). It matched the
                             WRONG WORD: 'postprandial' shares trigrams, 'walking'
                             cannot reach 'post-meal movement'
  tier 4  semantic    : [] — STUB. Would have given ('post-meal movement', 0.833)
  OUTCOME             : AUTO_CREATE

PHRASE : Soleus muscle glucose uptake into contracting muscle fibers
         via mitochondrial ATP demand                (88 chars)
  tier 3  trigram     : [] — best ('skeletal-muscle glucose disposal', 0.189)
  tier 4  semantic    : [] — STUB. Would have given the same concept at 0.847
  OUTCOME             : AUTO_CREATE
```

**The seed vocabulary is not too narrow and the aliases are not the
problem.** For every one of these the right concept is in the seed and
the embedding finds it. Three separate failures stack: trigram cannot
cross a synonym, the tier that can is a stub, and the last-resort tier is
unreachable from this caller.

---

## The long phrases are NOT an extraction-prompt bug

Ten proposals exceed 60 characters. Attributing each back to the Claim
Card field it came from:

```
came_from                 phrases  avg_chars  max_chars  over_60
mechanism                       7         96        117        7
target                          6         54         90        2
intervention / K11-side        43         29         72        1
```

**All seven `mechanism` values are over 60 characters, and all seven of
them are sentences.** That is not the engine misbehaving. The prompt
specifies it:

> | `mechanism` | claimed mechanism | The mechanism the source proposes, if any. |

A mechanism *is* a proposition — "contracting muscle fibers uptake
glucose independently of insulin action". There is no concept-shaped way
to say it, and a prompt change that forced one would be asking the engine
to discard what §39 asks it to capture.

The bug is one layer over, in the caller:

```python
for key in ("target", "intervention", "mechanism"):    # knowledge_extract.py
    ...
    normalize.resolve(conn, value, context="K09 claim extraction")
```

**`mechanism` should never have been sent to a concept resolver.** It is
specified to be a sentence and it is faithfully a sentence. Sending it
produces one junk PROPOSED concept per claim and nine of the twelve
`PARTIAL` verdicts above.

`target` is a different and smaller problem: 54 chars average, and the
two long ones are compound lists — *"Abdominal bloating, energy
stability, sugar cravings, fasting glucose, and fasting insulin"* is five
concepts in one string. That one **is** addressable in the prompt, or by
splitting on the conjunction before resolving.

So: the more upstream fix is real, and it is **not** in the extraction
prompt. Do not touch `prompts/` for this.

---

## What the LLM tier would still be for

Assuming the semantic tier is implemented at ~0.82 with a type check and
a candidate set rather than a top-1, the measured residue is **13 of 56
phrases** below 0.82. Sorted by what they actually are:

1. **Genuinely new concepts the seed does not contain** — `soleus
   push-up`, `mulberry leaf extract`, `1-deoxynojirimycin`,
   `alpha-glucosidase inhibition`, `GLUT4 translocation`. These SHOULD
   become new concepts. `AUTO_CREATE` is the right answer and no tier
   should resolve them. An LLM call here buys nothing.
2. **Compound phrases needing splitting, not resolving** — the five-part
   target above. A splitter is deterministic; an LLM is not needed to see
   a comma.
3. **Genuine type ambiguity** — `Impaired Glucose Tolerance` vs
   `prediabetes` (0.774), `Overweight and Obese Adults` vs `obesity`
   (0.763). A human or a model has to decide whether these are one
   concept. This is the only residue that is actually an LLM question,
   and it is **2 of 56**.

**The LLM tier is worth roughly 2 calls in 56 on this source**, and D8
already caps escalation by impact. That is an argument for implementing
the semantic tier and leaving the LLM tier exactly where it is —
unreachable from K09 is arguably the wrong default, but wiring it in
before the semantic tier exists would pay a model call for work a cosine
query does for $0.000001.

**Recommendation, for decision — not applied here:**

1. Implement `_tier_semantic`. It is the only tier that can span the
   synonym gap, and it is currently dead code behind two working guards.
2. Give it its own threshold. 0.92 is a trigram number; 0.82 is the
   measured knee for cosine. One shared constant is a latent bug.
3. Return a candidate set, not a top-1, so `confusable_with()` can fire.
4. Add a `concept_type` check — most wrong merges are category crossings
   and are refusable without any threshold.
5. Stop sending `mechanism` to the resolver.
6. Only then consider the LLM tier, for a residue measured at 2 in 56.

Items 1–5 are deterministic and cost one embedding per phrase. Item 6 is
a spending decision and belongs to the practitioner.
