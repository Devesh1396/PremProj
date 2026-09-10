# Layer A baseline — measured 2026-09-10

The first retrieval-quality number this build has. Recorded because
**layer A found a defect in step 17 on its first run**, and because
"retrieval works" had until now been an assertion about mechanisms rather
than a measurement of results.

## What was measured

`scripts/evaluate.py --run A` over the K1 ontology seed: 26 domains, 269
concepts, 290 concept-domain edges. Fourteen domains have a family large
enough to split.

Each test names **three** of a domain's concepts in the query and expects
the domain's **other** concepts back. The two sets are disjoint by
construction, so nothing here can be answered by returning the query
(V2). `query_concepts` is empty — the spine is not handed the family it
is being asked to find.

The library held **zero strategies**, so this measures the ontology's own
retrievability and nothing else. Layer A on a stocked library is a
different number and must not be compared with this one.

## Result

| | mean recall | tests passing (floor 0.30) |
|---|---|---|
| full text only | **0.1372** | 3 of 14 |
| full text + vector | **0.3255** | 9 of 14 |

Same tests, same queries, same day. The only difference is that 269
concepts were embedded in between.

**The floor was 0.30 before either run.** It was not chosen after seeing
0.3255 — a threshold picked to sit just under the number it judges is not
a threshold.

### Per domain, with vectors

```
0.64  LOCALITY / SEASONALITY        7/11
0.50  REMISSION / RESTORATION       3/6
0.43  EXERCISE & MOVEMENT           6/14
0.38  BODY COMPOSITION              3/8
0.38  LIFE STAGES / POPULATIONS     3/8
0.36  CONDITIONS & CLINICAL STATES  9/25
0.33  MEDICATION / NUTRITION        2/6
0.33  IMPLEMENTATION KNOWLEDGE      2/6
0.32  BIOMARKERS & MEASUREMENTS     7/22
0.27  BEHAVIOUR & ADHERENCE         4/15
0.24  INTERVENTION STRATEGIES       4/17
0.16  PHYSIOLOGY                   11/67
0.12  NUTRIENTS & BIOACTIVE         3/25
0.11  SYMPTOMS                      2/18
```

Recall falls as the family grows — 67 expected concepts cannot fit a page
of 20, so PHYSIOLOGY's ceiling is 20/67 = 0.30 and it scored 0.16 against
it. **The score is recall@20, not recall**, and a large family is
penalised by arithmetic before it is penalised by retrieval. Reading these
as a ranking of how well each domain is indexed would be wrong.

## Cost

283 embedding calls (269 concepts + 14 queries), 1,204 estimated input
tokens, **$0.000234** total, 2m27s for the 269 — about 0.55s per call,
sequential.

That is the first corpus-scale evidence that `gemini-embedding-2` works
through `embedding.embed()`: 269 vectors, every one unit-norm at 1536
dimensions, none rejected by `trg_embedding_coherent`.

## What this does NOT show

- **Nothing about strategy retrieval.** The library had no strategies.
- **Nothing about layers B, C, D or E.** No source has been ingested, so
  there is no held-out answer key and no domain at moderate coverage.
- **Nothing about a real case.** Layer C is the cross-domain test, and it
  needs a library with strategies in more than one domain.
- **Nothing about throughput.** 269 sequential calls is not a rate limit
  test.

## What it did find

Bug 63. On the first run every one of the fourteen tests scored **0.00**,
with no error anywhere. `websearch_to_tsquery` ANDs every term, so
`'CONDITIONS & CLINICAL STATES: acne, adrenal fatigue, alopecia'` became
`'condit' & 'clinic' & 'state' & 'acn' & 'adren' & 'fatigu' & 'alopecia'`
and matched no document in the library — as a realistic clinical query,
which is a paragraph, never could. The full-text channel had been
returning nothing for any query longer than a few words since step 17, and
every step-17 test passed anyway because its fixture queries were short.

That is what an evaluation layer is for.
