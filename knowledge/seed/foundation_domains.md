# Foundation Domain Curriculum — Engine 7 seed reference

> **Provenance.** Recovered verbatim from Engine 7 master specification **§7 — FOUNDATION
> KNOWLEDGE DOMAINS**, original source `knowledge.pdf` pages 8–20 (OCR text layer), cleaned only
> for the U+0002-for-hyphen substitution documented in `PROGRESS.md`. **Not reworded, not
> reordered, not summarised.**
>
> **Why it lives here.** This is reference data, not a per-call instruction. Carrying it inside
> `prompts/engine7_research_practice.md` cost ~1,700 words of context on every Engine 7 call —
> including CASE and INBOX runs, where the domain curriculum does nothing. It is loaded as
> additional context only for K1 ontology seeding, domain mapping, and foundation research on a
> domain it actually covers.
>
> **Relationship to Part I §9.** §9 of the master specification sets Wave-1 *queue order* — which
> domains are processed first. This file sets *how deep each area goes*. Neither restricts
> autonomous discovery; §9 says so explicitly and §41/§54 require it.
>
> **Verbatim body hash (sha256, excluding this header):**
> `eba68ddadf9aab614a655d9d05237909a09e614de7a4aff97e548352a2af92de`
>
> `testing/test_prompt_contracts.py` asserts this hash still matches, so the curriculum cannot
> drift silently once the material has left the prompt file.

---

## §7. FOUNDATION KNOWLEDGE DOMAINS

The following are seed dimensions, NOT a closed curriculum.
Discover additional relevant domains autonomously.
DOMAIN A — CONDITIONS & CLINICAL STATES
Build deep knowledge around relevant modifiable chronic/metabolic/nutrition-related health states
including but not limited to:
type 2 diabetes
prediabetes
insulin resistance
obesity
visceral adiposity
metabolic syndrome
fatty liver / MASLD
dyslipidaemia
elevated triglycerides
cholesterol/ApoB-related risk
hypertension
PCOS
thyroid-related conditions
digestive/gut complaints
constipation
reflux
bloating
IBS-pattern symptoms
nutritional deficiencies
iron-related problems
bone-health issues
muscle loss
sarcopenia
sarcopenic obesity
mobility/function issues
menopause/perimenopause
reproductive-metabolic health
sleep-related metabolic problems.
Expand beyond these when relevant.
DOMAIN B — PHYSIOLOGY
Develop deep reusable understanding of physiological targets.
Examples include:
GLUCOSE PHYSIOLOGY
insulin secretion
insulin sensitivity
skeletal-muscle glucose disposal
hepatic glucose production
fasting glucose
postprandial glucose
glycaemic variability
beta-cell function
glucose transport
meal-related glucose dynamics.
ADIPOSE PHYSIOLOGY
visceral adiposity
subcutaneous adiposity
ectopic fat
adipocyte dysfunction
lipolysis
adipose insulin resistance
energy storage
adipokines.
LIVER METABOLISM
hepatic fat
hepatic insulin resistance
de novo lipogenesis
fatty-acid oxidation
VLDL production
liver-energy metabolism.
LIPID PHYSIOLOGY
triglycerides
LDL-related biology
ApoB particle burden
HDL
remnant cholesterol
lipid transport
dietary fat response.
APPETITE / SATIETY
hunger
satiety
protein leverage
food reward
energy density
meal volume
appetite signalling
behavioural appetite factors.
MUSCLE
muscle protein synthesis
hypertrophy
strength
sarcopenia
glucose disposal
recovery
muscle quality
training adaptation.
BLOOD PRESSURE / VASCULAR PHYSIOLOGY
sodium
potassium
vascular tone
endothelial function
autonomic influences
renal contribution
body weight
sleep
physical activity.
GUT / DIGESTIVE PHYSIOLOGY
motility
stool formation
digestion
fermentation
fibre types
bile
microbiome-related processes
gut-brain relationships
food tolerance.
ENDOCRINE / REPRODUCTIVE PHYSIOLOGY
insulin-androgen relationships
ovulation
menstrual regulation
thyroid physiology
menopause-related metabolic changes.
Expand beyond these autonomously.
DOMAIN C — BIOMARKERS & MEASUREMENTS
Build knowledge around:
WHAT THE MARKER MEASURES
WHAT INFLUENCES IT
WHAT CAN CONFUSE IT
WHAT INTERVENTIONS MAY MOVE IT
HOW QUICKLY IT MAY RESPOND
WHAT RELATED MARKERS MATTER.
Examples:
fasting glucose
post-meal glucose
HbA1c
fasting insulin
C-peptide
CGM metrics
triglycerides
LDL-C
HDL-C
non-HDL
ApoB
Lp(a)
ALT
AST
GGT
liver-imaging measures
BP
waist
body weight
body composition
B12
vitamin D
ferritin
iron indices
folate
thyroid markers
creatinine
eGFR
uric acid
other clinically relevant markers.
This list is not exhaustive.
DOMAIN D — SYMPTOMS
Build searchable knowledge from symptoms, not merely diagnoses.
Examples:
fatigue
hunger
cravings
bloating
constipation
reflux
altered bowel habits
sleep difficulty
daytime sleepiness
brain fog
menstrual irregularity
weakness
poor exercise tolerance
pain
stiffness
headaches
low energy.
For each symptom understand:
possible nutritional contributors,
lifestyle contributors,
physiological possibilities,
useful assessment questions,
intervention possibilities,
important uncertainty.
DOMAIN E — NUTRIENTS & BIOACTIVE
COMPOUNDS
Develop more than simple food-source knowledge.
For relevant nutrients understand:
physiological roles,
adequacy,
deficiency,
therapeutic use,
food exposure,
supplementation exposure,
bioavailability,
studied populations,
interactions,
outcome evidence.
Examples include:
protein
fibre
fibre subtypes
omega-3
calcium
magnesium
iron
zinc
selenium
iodine
vitamin D
B12
folate
potassium
choline
inositol
polyphenols
plant sterols
other evidence-relevant compounds.
Discover additional compounds autonomously.
DOMAIN F — FOOD KNOWLEDGE
Develop food intelligence deeper than:
FOOD → NUTRIENTS.
For important foods store where relevant:
FOOD NAME:
REGIONAL NAMES:
FOOD TYPE:
MACROS:
KEY NUTRIENTS:
BIOACTIVE COMPOUNDS:
PRACTICAL SERVING:
ENERGY:
PROTEIN:
FIBRE:
CARBOHYDRATE:
CLINICAL/NUTRITIONAL PURPOSES:
RELEVANT HUMAN RESEARCH:
PREPARATION:
BIOAVAILABILITY:
LOCALITY:
SEASONALITY:
PRICE/ACCESS CONSIDERATIONS:
SUBSTITUTES BY NUTRITIONAL PURPOSE:
PRESERVED/FROZEN/DRIED OPTIONS:
LIMITATIONS.
Do not restrict food knowledge to western foods.
Build deep Indian/regional food knowledge.
DOMAIN G — LOCALITY / SEASONALITY
For food implementation, build knowledge around:
country
state/region
regional cuisine
typical seasonal availability
common market access
traditional preparations
local protein foods
fruits
vegetables
grains
pulses
fermented foods
nuts/seeds
herbs/spices.
Especially build useful Indian regional knowledge.
Seasonal knowledge should describe:
FOOD
→ WHERE AVAILABLE
→ WHEN COMMONLY AVAILABLE
→ NUTRITIONAL JOB
→ OFF-SEASON SUBSTITUTE.
Do not make the library dependent on exact foods when the nutritional function can be replaced.
DOMAIN H — INTERVENTION STRATEGIES
This is one of the most important layers.
Collect interventions, not merely facts.
Examples may include:
meal composition
nutrient distribution
food sequencing
carbohydrate amount
carbohydrate quality
protein distribution
fibre strategies
meal timing
energy restriction
weight-loss strategies
time-restricted eating
post-meal movement
resistance exercise
aerobic exercise
sedentary breaks
sleep strategies
appetite interventions
food substitution
supplement interventions
behavioural/environment interventions.
These examples are not prescriptions.
Discover thousands of other strategies autonomously.
Every strategy should connect to:
TARGET
→ MECHANISM
→ EVIDENCE
→ POPULATION
→ MAGNITUDE
→ IMPLEMENTATION
→ LIMITATIONS
→ CLIENT-FIT FACTORS
→ TRACKING.
DOMAIN I — EXERCISE & MOVEMENT
Develop deep intervention knowledge around:
resistance training
aerobic exercise
interval approaches
walking
post-meal movement
sedentary interruption
exercise timing
exercise intensity
frequency
volume
strength
hypertrophy
mobility
balance
joint-friendly activity
progression
recovery.
Connect exercise to outcomes such as:
glucose
insulin sensitivity
BP
lipids
liver fat
body composition
muscle
bone
function
sleep.
DOMAIN J — BEHAVIOUR & ADHERENCE
Support Engine 2 with broad behavioural knowledge.
Include:
habit formation
environmental design
friction
implementation intentions
defaults
choice architecture
motivation
self-efficacy
readiness
self-monitoring
feedback
accountability
relapse
emotional eating
decision fatigue
family/social influence
meal preparation
behavioural substitution
other relevant implementation-science concepts.
Do not reduce behavioural science to one popular book or framework.
DOMAIN K — SUPPLEMENTS / NUTRACEUTICALS
For important supplements store:
NAME:
FORMS:
PHYSIOLOGICAL ROLE:
WHY CONSIDERED:
POPULATIONS STUDIED:
DOSE/EXPOSURE USED IN HUMAN RESEARCH:
DURATION:
OUTCOMES:
EVIDENCE:
FOOD EXPOSURE COMPARISON:
INTERACTIONS:
TOLERABILITY:
LIMITATIONS:
WHO MAY BENEFIT:
WHO MAY NOT:
WHAT TO TRACK.
Do not automatically recommend a supplement simply because evidence exists.
DOMAIN L — TRADITIONAL / AYURVEDIC
KNOWLEDGE
Investigate rather than automatically accepting or rejecting.
Store separately:
TRADITIONAL USE:
PREPARATION:
INGREDIENTS:
TRADITIONAL RATIONALE:
POSSIBLE MODERN MECHANISM:
HUMAN EVIDENCE:
SAFETY:
INTERACTIONS:
PRACTICALITY:
LIMITATIONS:
CURRENT LEVEL OF UNCERTAINTY.
Do not convert traditional use into established efficacy.
Do not discard potentially useful traditional knowledge solely because it originated outside
conventional medicine.
DOMAIN M — MEDICATION / NUTRITION /
EXERCISE CONTEXT
Build contextual knowledge around:
medication-food interactions
supplement interactions
nutrient implications
hypoglycaemia risk
hypotension risk
GI effects
appetite/weight effects
exercise implications
monitoring implications.
This supports interpretation.
Do not independently prescribe or discontinue prescription medication.
DOMAIN N — LIFE STAGES / POPULATIONS
Knowledge should be indexed by relevant populations such as:
adolescents
young adults
reproductive-age women
pregnancy context where appropriate
perimenopause
menopause
older adults
frailty
athletes
sedentary adults
vegetarian
vegan
different body-composition states.
The same intervention may have different relevance across populations.
DOMAIN O — BODY COMPOSITION
Include:
fat loss
visceral-fat reduction
central adiposity
lean mass
muscle gain
recomposition
sarcopenic obesity
plateaus
appetite during deficits
weight maintenance
regain prevention.
DOMAIN P — IMPLEMENTATION KNOWLEDGE
Do not store only:
“Protein helps.”
Store:
HOW DO WE DELIVER THE PROTEIN?
Examples:
meal combinations
vegetarian options
serving sizes
regional foods
batch preparation
portable options
budget options
supplements where appropriate.
Translate efficacy into execution.
DOMAIN Q — OUTCOME-CENTRIC KNOWLEDGE
The system should answer questions such as:
WHAT MOVES:
fasting glucose?
post-meal glucose?
HbA1c?
insulin sensitivity?
triglycerides?
ApoB?
BP?
hepatic fat?
waist?
appetite?
constipation?
sleep?
strength?
pain/function?
without needing to start from a disease label.
DOMAIN R — REMISSION / RESTORATION /
NORMALIZATION
Because the larger system aims toward maximum modifiable improvement, deeply study interventions/
programs aimed at:
diabetes remission
substantial metabolic improvement
fatty-liver resolution
hypertension normalization where achievable
body-composition restoration
PCOS metabolic/reproductive improvement
improved lipid risk markers
functional restoration
muscle restoration.
For remission/restoration programs extract:
POPULATION:
BASELINE:
INTERVENTION:
INTENSITY:
DURATION:
RESULT:
RESPONSE RATE:
PREDICTORS:
MAINTENANCE:
LIMITATIONS:
ADVERSE EFFECTS:
WHAT APPEARS TO HAVE DRIVEN SUCCESS.
DOMAIN S — PRACTITIONER / COACH /
CLINICIAN INTELLIGENCE
Do not dismiss a useful strategy because it came from:
a clinician,
practitioner,
coach,
educator,
author,
podcast.
Do not accept it because they are popular either.
For important practitioner sources store:
PERSON / ORGANIZATION:
BACKGROUND:
AREA OF FOCUS:
STRATEGIES PROMOTED:
ORIGINAL CLAIM:
PRACTICAL IMPLEMENTATION:
SOURCE:
REFERENCES THEY CITE:
EVIDENCE SUPPORTING CLAIM:
EVIDENCE LIMITING CLAIM:
WHAT THEY DO PARTICULARLY WELL:
WHAT MAY BE OVERSTATED:
USEFUL IDEAS FOR FURTHER INVESTIGATION.
Separate:
PRACTITIONER INSIGHT
from
SCIENTIFIC EVIDENCE.
DOMAIN T — BOOK INTELLIGENCE
For books lawfully provided to the system:
Do NOT simply summarize the book.
Extract:
intervention strategies,
practical frameworks,
claims,
explanations,
case examples,
implementation techniques,
study references,
useful questions,
disagreements with other sources.
For every important book-derived strategy store:
BOOK:
AUTHOR:
CHAPTER/PAGE OR LOCATION WHEN AVAILABLE:
CLAIM:
STRATEGY:
PRACTICAL METHOD:
AUTHOR'S RATIONALE:
REFERENCED EVIDENCE:
INDEPENDENT EVIDENCE CHECK:
LIMITATIONS:
KNOWLEDGE CARD LINKS.
Do not store unnecessary large verbatim copyrighted passages.
Store derived knowledge and precise source references.
DOMAIN U — PODCAST / LONG-FORM
INTERVIEW INTELLIGENCE
For podcast/interview transcripts:
Do not merely summarize 3 hours.
Extract:
new intervention claims,
practical implementation,
researcher interpretation,
clinical observations,
unresolved hypotheses,
cited studies,
disagreements,
emerging ideas.
Distinguish:
WHAT THE PERSON SAID
from
WHAT RESEARCH CURRENTLY SUPPORTS.
If nothing useful/new is present:
do not create unnecessary knowledge cards.
DOMAIN V — VIDEO / LECTURE INTELLIGENCE
Treat accessible transcripts similarly.
Extract only decision-relevant knowledge.
Preserve:
SOURCE
SPEAKER
DATE
TIMESTAMP when available
CLAIM
STRATEGY
EVIDENCE REFERENCES.
Do not treat entertainment/popularity as evidence.
DOMAIN W — BLOG / NEWSLETTER
INTELLIGENCE
Blogs/newsletters may be valuable for:
new ideas,
practical implementation,
commentary,
early discussion of research.
Use them primarily as:
DISCOVERY SOURCES.
Then investigate important claims independently.
DOMAIN X — CONTROVERSIES
Create structured controversy knowledge where legitimate scientific/practitioner disagreement exists.
For each controversy store:
QUESTION:
VIEW A:
EVIDENCE A:
VIEW B:
EVIDENCE B:
OTHER VIEWS:
POPULATIONS WHERE DIFFERENCES MATTER:
WHY RESULTS MAY DIFFER:
CURRENT AREAS OF AGREEMENT:
CURRENT UNCERTAINTY:
WHAT DATA WOULD RESOLVE MORE OF THE QUESTION.
Do not force one ideology onto the system.
DOMAIN Y — NEGATIVE KNOWLEDGE
Store useful knowledge about:
failed interventions,
disproven claims,
overhyped mechanisms,
inconsistent findings,
clinically trivial effects,
important adverse effects,
interventions whose evidence was weaker than expected.
This prevents repeated research waste.
A negative knowledge record should explain:
WHAT WAS CLAIMED:
WHY IT SOUNDED PLAUSIBLE:
WHAT THE EVIDENCE FOUND:
WHY IT IS NOT CURRENTLY PRIORITIZED:
WHAT FUTURE EVIDENCE COULD CHANGE THIS.
DOMAIN Z — PRACTICE-BASED EXPERIENCE
Eventually receive aggregated/de-identified data from Engines 4 and 6.
This layer answers:
WHAT HAVE OUR OWN CLIENTS TAUGHT US?
Possible fields:
CLIENT PHENOTYPE:
INTERVENTION:
NUMBER EXPOSED:
ADHERENCE:
OUTCOME TREND:
COMMON RESPONSE:
COMMON FAILURE:
WHO APPEARED TO RESPOND BETTER:
IMPLEMENTATION LESSONS.
This is:
PRACTICE-BASED EXPERIENCE.
It must remain separate from:
PUBLISHED SCIENTIFIC EVIDENCE.
Do not treat observational internal case data as proof of causality.
