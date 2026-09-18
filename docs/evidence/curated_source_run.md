# Curated practitioner intelligence through K07–K09 — 2026-09-18

**Source:** `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence,
Video 1` — ~300 lines, hand-curated by the practitioner from the Glucose
Revolution video `zg3GBH6fG2I`, distilled and deduplicated **by hand** into
six strategy cards with consistent subsections. Registered as a new source
kind `PRACTITIONER_CURATED` (`PRACTITIONER_FRAMEWORK` / `IMPLEMENTATION`,
`long_form`), which is an INSERT, not code (hard rule 13).

**Run:** K07 ingest → K08 normalize → K09 extract + concept normalization.
**K10 was NOT run** (D48 — the evidence layer failed its clinical audit).
K11 was not run either, so there are **no `strategies` rows**: strategy
cards are K11's output, and everything below is claims and concepts.

Clean database, migrated from empty, K1 seed loaded (26 domains, 269
concepts). One live call, `gemini-3.8-flash`, **$0.0438**.

---

## The question this run was to answer

*Does the pipeline handle curated practitioner knowledge as well as it
handled a raw transcript, or better?*

**Worse, and in a way that matters more.** Three findings, in order of
severity, then the rows.

### 1. K09 fabricates the `mechanism` field — a NEW instance of D48's failure class

§R11 defines `mechanism` as **"the mechanism the source proposes, if any"**,
`claim_text` as **"what the source actually asserts … in the source's own
terms. Not a paraphrase that improves it"**, and states plainly:
**"Never fill a field the source did not supply. `null` is correct."**

The source proposes **no mechanism anywhere**. It contains no physiology at
all. All seven `mechanism` fields are populated from the model's own
knowledge. Occurrences in the source document:

| term written into `mechanism` | occurrences in the source |
|---|---|
| GLUT4 | **0** |
| incretin | **0** |
| disaccharidase | **0** |
| gastric emptying | **0** |
| beta-cell | **0** |
| acetic acid | **0** |
| euglycemia | **0** |
| self-efficacy | **0** |

This is **the same failure as D48, one layer earlier**: model recall
persisted as though it were a fact about the source. The clinical audit
concluded "K07/K08/K09 are not implicated" — that conclusion was reached by
checking claim *text* against the transcript. It did not check `mechanism`,
and `mechanism` is fabricated on this source in 7 cases out of 7.

### 2. The decision logic did not survive, and Strategy 6 vanished entirely

The source's six strategies produced five claims. **Strategy 6 — "Preserve
agency and reduce unnecessary deprivation" — produced none.** Its
`Decision intelligence` subsection is the single largest chunk in the
document (1,191 chars) and contains the entire bottleneck-routing table:
high-carb breakfast → breakfast restructuring; diet-change resistance →
meal-linked movement; client overwhelmed → one or two changes; client
already doing it well → find the next limiting factor; cannot walk → another
muscular-activity implementation. **None of it is anywhere in the output.**

No claim carries a "when to reach for this" condition. The `context` field,
the only place such a thing could have landed, received *implementation*
context instead — "Consumed as a first course immediately prior to or at
start of lunch or dinner." That is adaptability, not prioritisation.

The tiering signal the practitioner identified as the point of the document
is **not in the database in any form.**

### 3. Conditional heuristics became unconditional effect claims

The source is careful. On vinegar it says: *"Do not manufacture a complete
vinegar protocol from this video because it does not provide enough
information to define ideal client selection, preparation, dose or
limitations."*

K09 wrote: **"Ingesting vinegar prior to a meal acts as a low-friction tool
to reduce postprandial glucose spikes"** — `INTERVENTION_EFFECT`,
confidence 0.900.

Strategy 5 says intervention load *should be personalized*. K09 wrote
**"yields superior adherence and sustained metabolic outcomes compared to
immediate multi-domain lifestyle overhauls"** — a comparative effect claim
the source never made.

**Why this compounds:** K10's triage rule is
`RESEARCH_TYPES = ("SAFETY", "INTERVENTION_EFFECT")`. Five of these claims
are `INTERVENTION_EFFECT` and one is `SAFETY`, so **six of seven would be
sent to K10** — a document that deliberately asserts almost nothing
evidential would generate six research calls manufacturing citations for
claims the practitioner explicitly declined to make.

### What went RIGHT, and it is not small

**Provenance is materially better than the transcript case.** Every claim
carries a heading path — `Strategy 3 — Vinegar as a candidate meal-level
tool` — derived from the document's own structure. A timestamp range can
point at the wrong second, and six of seven did (D48). A heading path
cannot. All 7 claims have a provenance edge, all `discovery_only`.

**Chunking held the structure perfectly.** 36 chunks, one per heading, each
addressable as `Strategy N — Name > Client decision logic`. The decision
logic is *locatable in the chunk store*; it simply did not survive
extraction. That distinction matters: the input to a fix is already there.

---

## A. The 7 claims K09 wrote

| # | type | conf | claim_text | target | mechanism | location |
|---|---|---|---|---|---|---|
| 1 | `INTERVENTION_EFFECT` | 0.950 | Converting a predominantly carbohydrate-delivery breakfast into a meal anchored by protein, fibre, and whole-food structure improves metabolic control and postprandial glycaemia in individuals with insulin resistance or type 2 diabetes. | Postprandial glycaemia and daily metabolic control | Delayed gastric emptying, attenuated glucose absorption kinetics, and reduced acute insulin demand compared to refined carbohydrate intake. | `Strategy 1 — Breakfast restructuring` |
| 2 | `INTERVENTION_EFFECT` | 0.950 | Consuming a vegetable or fibre starter before or at the beginning of a carbohydrate-containing meal attenuates postprandial glucose excursion without requiring complete elimination of familiar carbohydrate foods. | Postprandial glucose excursion and meal satiety | Fibre matrix creates viscous intestinal barrier slowing carbohydrate enzymatic breakdown and glucose absorption, and stimulating early incretin/satiety signaling. | `Strategy 2 — Pre-meal vegetable/fibre structure` |
| 3 | `INTERVENTION_EFFECT` | 0.900 | Ingesting vinegar prior to a meal acts as a low-friction tool to reduce postprandial glucose spikes. | Postprandial glucose excursion | Acetic acid inhibition of disaccharidase activity in small intestine mucosa and delayed gastric emptying. | `Strategy 3 — Vinegar as a candidate meal-level tool` |
| 4 | `INTERVENTION_EFFECT` | 0.950 | Engaging in approximately 10 minutes of walking or muscular activity directly following a meal improves postprandial glucose disposal compared to remaining sedentary. | Postprandial glucose disposal | Insulin-independent contraction-stimulated GLUT4 translocation in active skeletal muscle beds. | `Strategy 4 — Meal-linked postprandial movement` |
| 5 | `IMPLEMENTATION` | 0.950 | Progressively layering a small number of high-value executable lifestyle actions across consecutive weeks yields superior adherence and sustained metabolic outcomes compared to immediate multi-domain lifestyle overhauls. | Intervention adherence, client self-efficacy, and progressive metabolic response | Reduces cognitive burden, builds self-efficacy through early wins, and allows systematic causal attribution of metabolic response. | `Strategy 5 — Progressive layering instead of intervention overload` |
| 6 | `SAFETY` | 0.950 | Introducing meaningful postprandial glucose-attenuating dietary or physical activity changes in medicated diabetic individuals can precipitate hypoglycemia and requires proactive prescriber coordination. | Hypoglycemia prevention and medication safety | Rapid reduction in exogenous/postprandial glucose supply without concomitant down-titration of fixed-dose hypoglycemic agents. | `Assessment & Consultation Intelligence > Medication context` |
| 7 | `ASSOCIATION` | 0.900 | Fasting insulin and early hyperinsulinemia provide diagnostic and physiological signals of metabolic dysfunction prior to the clinical onset of overt fasting hyperglycemia. | Early detection of insulin resistance and compensatory beta-cell stress | Compensatory pancreatic hyperinsulinemia maintains euglycemia for years before beta-cell exhaustion leads to elevated fasting plasma glucose. | `Assessment & Consultation Intelligence > Fasting insulin / earlier hyperinsulinemia` |

## B. All 20 concept proposals

| raw_phrase | tier | score | nearest match | decision |
|---|---|---|---|---|
| Postprandial glucose disposal | TRIGRAM | 0.750 | `POSTPRANDIAL_GLUCOSE` | `LOGGED` |
| Acetic acid inhibition of disaccharidase activity in small intestine mucosa and delayed gastric emptying. | DETERMINISTIC | 0.000 | `ACETIC_ACID_INHIBITION_OF_DISACCHARIDASE_ACTIVITY_IN_SMALL_INTESTINE_MUCOSA_AND_` | `AUTO_CREATE` |
| Breakfast restructuring from refined starch/sugar to protein- and fibre-anchored meal | DETERMINISTIC | 0.000 | `BREAKFAST_RESTRUCTURING_FROM_REFINED_STARCH_SUGAR_TO_PROTEIN_AND_FIBRE_ANCHORED_` | `AUTO_CREATE` |
| Compensatory pancreatic hyperinsulinemia maintains euglycemia for years before beta-cell exhaustion leads to elevated fasting plasma glucose. | DETERMINISTIC | 0.000 | `COMPENSATORY_PANCREATIC_HYPERINSULINEMIA_MAINTAINS_EUGLYCEMIA_FOR_YEARS_BEFORE_B` | `AUTO_CREATE` |
| Delayed gastric emptying, attenuated glucose absorption kinetics, and reduced acute insulin demand compared to refined carbohydrate intake. | DETERMINISTIC | 0.000 | `DELAYED_GASTRIC_EMPTYING_ATTENUATED_GLUCOSE_ABSORPTION_KINETICS_AND_REDUCED_ACUT` | `AUTO_CREATE` |
| Dietary carbohydrate restriction, meal sequencing, or postprandial exercise combined with insulin/secretagogues | DETERMINISTIC | 0.000 | `DIETARY_CARBOHYDRATE_RESTRICTION_MEAL_SEQUENCING_OR_POSTPRANDIAL_EXERCISE_COMBIN` | `AUTO_CREATE` |
| Early detection of insulin resistance and compensatory beta-cell stress | DETERMINISTIC | 0.000 | `EARLY_DETECTION_OF_INSULIN_RESISTANCE_AND_COMPENSATORY_BETA_CELL_STRESS` | `AUTO_CREATE` |
| Fibre matrix creates viscous intestinal barrier slowing carbohydrate enzymatic breakdown and glucose absorption, and stimulating early incretin/satiety signaling. | DETERMINISTIC | 0.000 | `FIBRE_MATRIX_CREATES_VISCOUS_INTESTINAL_BARRIER_SLOWING_CARBOHYDRATE_ENZYMATIC_B` | `AUTO_CREATE` |
| Hypoglycemia prevention and medication safety | DETERMINISTIC | 0.000 | `HYPOGLYCEMIA_PREVENTION_AND_MEDICATION_SAFETY` | `AUTO_CREATE` |
| Insulin-independent contraction-stimulated GLUT4 translocation in active skeletal muscle beds. | DETERMINISTIC | 0.000 | `INSULIN_INDEPENDENT_CONTRACTION_STIMULATED_GLUT4_TRANSLOCATION_IN_ACTIVE_SKELETA` | `AUTO_CREATE` |
| Intervention adherence, client self-efficacy, and progressive metabolic response | DETERMINISTIC | 0.000 | `INTERVENTION_ADHERENCE_CLIENT_SELF_EFFICACY_AND_PROGRESSIVE_METABOLIC_RESPONSE` | `AUTO_CREATE` |
| Meal-linked postprandial walking (approx. 10 minutes) | DETERMINISTIC | 0.000 | `MEAL_LINKED_POSTPRANDIAL_WALKING_APPROX_10_MINUTES` | `AUTO_CREATE` |
| Postprandial glucose excursion | DETERMINISTIC | 0.000 | `POSTPRANDIAL_GLUCOSE_EXCURSION` | `AUTO_CREATE` |
| Postprandial glucose excursion and meal satiety | DETERMINISTIC | 0.000 | `POSTPRANDIAL_GLUCOSE_EXCURSION_AND_MEAL_SATIETY` | `AUTO_CREATE` |
| Postprandial glycaemia and daily metabolic control | DETERMINISTIC | 0.000 | `POSTPRANDIAL_GLYCAEMIA_AND_DAILY_METABOLIC_CONTROL` | `AUTO_CREATE` |
| Pre-meal vegetable/fibre starter | DETERMINISTIC | 0.000 | `PRE_MEAL_VEGETABLE_FIBRE_STARTER` | `AUTO_CREATE` |
| Progressive behavioural layering protocol (starting with 1-2 habit anchors) | DETERMINISTIC | 0.000 | `PROGRESSIVE_BEHAVIOURAL_LAYERING_PROTOCOL_STARTING_WITH_1_2_HABIT_ANCHORS` | `AUTO_CREATE` |
| Rapid reduction in exogenous/postprandial glucose supply without concomitant down-titration of fixed-dose hypoglycemic agents. | DETERMINISTIC | 0.000 | `RAPID_REDUCTION_IN_EXOGENOUS_POSTPRANDIAL_GLUCOSE_SUPPLY_WITHOUT_CONCOMITANT_DOW` | `AUTO_CREATE` |
| Reduces cognitive burden, builds self-efficacy through early wins, and allows systematic causal attribution of metabolic response. | DETERMINISTIC | 0.000 | `REDUCES_COGNITIVE_BURDEN_BUILDS_SELF_EFFICACY_THROUGH_EARLY_WINS_AND_ALLOWS_SYST` | `AUTO_CREATE` |
| Vinegar prior to meal | DETERMINISTIC | 0.000 | `VINEGAR_PRIOR_TO_MEAL` | `AUTO_CREATE` |

## C. Concepts that resolved, and via which tier

**0 of 20.** No proposal resolved to any of the 269 seeded concepts.

The single near-match:

- `Postprandial glucose disposal` -> **TRIGRAM** 0.750 -> `POSTPRANDIAL_GLUCOSE` -> decision `LOGGED` (below the auto-resolve threshold)

## D. Provenance and what was NOT produced

| | |
|---|---|

## D. Provenance and what was NOT produced

| | |
|---|---|
| CLAIM provenance edges (discovery_only) | 7 |
| claims written | 7 |
| chunks | 36 |
| new PROPOSED concepts | 19 |
| strategies (K11 not run) | 0 |
| evidence_records (K10 NOT RUN, deliberately) | 0 |

## E. Cost

`gemini-3.8-flash` - **1 call**, 30,325 in / 5,626 out, **$0.043841**

---

## Conclusion

**Curated practitioner knowledge needs a different ingestion path from a
raw transcript.** K09's job on a transcript is to find the checkable
assertions buried in speech, and it does that well. This document is
already the *output* of that operation, performed by a human with clinical
judgement. Running K09 over it does not improve it — it re-derives a worse
version, discards the prioritisation layer the human added, and invents
mechanistic support the human deliberately withheld.

The structure is already machine-readable: `Strategy N — Name` with fixed
subsections. A curated source wants a **deterministic** reader that maps
those headings onto fields — not a model asked to re-extract claims from
prose that is no longer prose.

**Do not put the other seventeen sections through this path.**
