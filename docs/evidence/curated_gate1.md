# GATE 1 — curated practitioner preservation. PASS. 2026-09-18

**Question:** did the existing Knowledge-Inbox path preserve one
human-curated source section without making it worse?

**Answer: YES**, on the mechanical criteria below. What that means is
bounded: preservation only. Concept normalization (GATE 2) and retrieval
(GATE 3) are untouched and still unsolved.

**Source:** the standalone Video 1 section, already a separate file, so no
extraction of a sub-range from a larger document was needed — one source,
one envelope. `testing/fixtures/curated/t2d_video1.md`, 16,516 chars,
548 lines, 42 headings, 6 strategies.

**Run:** K07 → K08 → **extractor dispatch** → deterministic curated parser.
**Zero provider calls of any kind.** K09 and K10 never ran.

## What changed, and what did not

The only architectural change is at dispatch: `source_kinds.extractor`.
An envelope whose kind is registered `CURATED_DETERMINISTIC` goes to the
parser instead of K09. Routing a new kind remains an INSERT (hard rule 13).

Reused unchanged: the Knowledge Inbox, the source envelope, rights, the
content hash and §57 dedup, K08's chunker, the concept registry and
resolver, and the `knowledge_entities` / `envelope_derived_records`
provenance registry (a new derived kind = an enum value + a registration
trigger, hard rule 12 — never a new foreign key).

**No second inbox, envelope system, provenance layer, normalizer or
pipeline was created.**

New, because nothing existing could express it: `curated_fields` carries
**per-field provenance**. Without a per-field span, "the model invented
nothing" stays an opinion instead of a test.

## Two defects this run found

**1. The parser lost `Client decision logic` on Strategies 1 and 4 —
caught by the acceptance criteria, not by inspection.** The grammar
patterns were case-sensitive and the document writes sentence case:
`Client decision logic` has a lowercase `d` and did not match a pattern
written `Decision`. `Future alternatives` was lost the same way. Fixed by
compiling **every** rule case-insensitively — heading capitalisation
carries no meaning here and the next section will not be consistent about
it, so this is a property of heading grammars, not a patch for this
fixture.

**2. A DEDUPED envelope carried `content_hash = NULL`** —
`open_envelope()` returned before the line that writes it. The row that
exists *because* of a hash match could not be found by that hash. This is
the bug class the brief named; it is now fixed in the shared inbox path
and asserted both ways (the hash is present, and it resolves to the
original envelope).

## A. Source envelope

| | |
|---|---|
| envelope_id | `496208d2-9b13-4a96-a8d3-fea88bf37cd9` |
| title | `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence, Video 1` |
| kind | `PRACTITIONER_CURATED` |
| role | `IMPLEMENTATION` |
| rights | `PRIVATE_INTERNAL` |
| status | `EXTRACTED` |
| content_hash | `87a893e8cade99bee31b19b476e70dd364d7df04aec4adfe35346efecc4e3b41` |
| raw_location | `raw/87/87a893e8cade99bee31b19b476e70dd364d7df04aec4adfe35346efecc4e3b41.md` |
| source_type | `PRACTITIONER_FRAMEWORK` |
| extractor | `CURATED_DETERMINISTIC` |

## B. All six strategies


### Breakfast restructuring

`5bc3c4a8-8a63-475b-b885-6bf37903ccee` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 1 — Breakfast restructuring` · source range **1349–3379** · hash `406e167fef2eba23…`

| field | provenance | span | text |
|---|---|---|---|
| `adaptability` | VERBATIM_SOURCE | 2860–3156 | The actual food implementation should later be individualized for:<br><br>vegetarian/non-vegetarian preference\<br>culture\<br>budget\<br>cooking facilities\<br>work schedule\<br>appetite\<br>protein requirement\<br>calorie/weight objective\<br>intolerances and preferences.<br><br>Engine 3 should eventually choose the actual meal. |
| `client_decision_logic` | VERBATIM_SOURCE | 2394–2840 | **Prioritize this strategy when:**<br><br>-   breakfast is clearly one of the client's weakest meals;<br><br>-   it is predominantly refined carbohydrate/sugar;<br><br>-   protein/fibre are minimal;<br><br>-   the client is willing to modify breakfast;<br><br>-   changing one repetitive meal may simplify adherence.<br><br>**Do not pri …[+146 chars] |
| `practitioner_leverage` | VERBATIM_SOURCE | 3185–3377 | For an overwhelmed client, this can become a useful first win:<br><br>**"For now, let's improve one meal that happens every morning."**<br><br>rather than:<br><br>**"Your entire diet must change immediately."** |
| `what_it_means` | VERBATIM_SOURCE | 1419–2067 | When breakfast is predominantly carbohydrate-based and contains little meaningful protein, fibre or other satiating whole-food structure, breakfast becomes a potential intervention point.<br><br>Typical patterns may include:<br><br>toast + jam + juice\<br>sweet cereal\<br>bakery foods\<br>sugary beverages\<br>heavily refin …[+348 chars] |
| `why_useful` | VERBATIM_SOURCE | 2097–2365 | Breakfast is often:<br><br>-   repetitive;<br><br>-   habitual;<br><br>-   relatively easy to identify;<br><br>-   consumed with little day-to-day variation.<br><br>Therefore, changing one repeated breakfast may create a useful intervention without immediately redesigning the client's entire diet. |

Absent (the source supplies none; never filled): `alternatives`, `fallbacks`, `implementation`, `monitoring`, `safety_context`, `when_not_useful`, `when_useful`


### Pre-meal vegetable/fibre structure

`82aced8f-83e6-4917-9f46-81b14df6e0eb` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 2 — Pre-meal vegetable/fibre structure` · source range **3379–4581** · hash `c92e57574398f7c0…`

| field | provenance | span | text |
|---|---|---|---|
| `client_decision_logic` | VERBATIM_SOURCE | 4228–4436 | Potentially useful when:<br><br>familiar lunch/dinner + poor meal structure + low vegetable/fibre exposure.<br><br>Lower priority when the meal is already well structured or another major driver deserves attention first. |
| `practitioner_leverage` | VERBATIM_SOURCE | 4465–4579 | A useful consultation question becomes:<br><br>**"Can we improve this meal before deciding that we need to remove it?"** |
| `what_it_means` | VERBATIM_SOURCE | 3460–3943 | Instead of automatically removing the client's familiar carbohydrate-containing meal, consider whether adding an appropriate vegetable/fibre-rich component before or at the beginning of that meal can improve its structure.<br><br>The source proposes a vegetable starter before lunch or dinner as one of its …[+183 chars] |
| `why_useful` | VERBATIM_SOURCE | 3973–4206 | Potentially useful when:<br><br>-   familiar foods are important for adherence;<br><br>-   vegetable/fibre intake is poor;<br><br>-   the client strongly resists restrictive instructions;<br><br>-   an addition is easier to execute than another prohibition. |

Absent (the source supplies none; never filled): `adaptability`, `alternatives`, `fallbacks`, `implementation`, `monitoring`, `safety_context`, `when_not_useful`, `when_useful`


### Vinegar as a candidate meal-level tool

`617a98c7-f1cc-4c87-84b8-ca65eeeb8124` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 3 — Vinegar as a candidate meal-level tool` · source range **4581–5477** · hash `3bf09b08a733b18b…`

| field | provenance | span | text |
|---|---|---|---|
| `what_it_means` | VERBATIM_SOURCE | 4666–5074 | Vinegar before a meal is introduced as a simple intervention requiring very little restructuring of the person's usual diet.<br><br>From this source alone, retain it as:<br><br>**A candidate low-friction meal-level glucose-management tool.**<br><br>Do not manufacture a complete vinegar protocol from this video becaus …[+108 chars] |
| `why_useful` | VERBATIM_SOURCE | 5096–5475 | It expands the intervention menu.<br><br>There may eventually be a client where:<br><br>-   large diet restructuring is difficult;<br><br>-   the person wants a very small intervention;<br><br>-   meal-level glucose management is relevant;<br><br>-   later knowledge supports appropriate use.<br><br>Future research or practitioner sour …[+79 chars] |

Absent (the source supplies none; never filled): `adaptability`, `alternatives`, `client_decision_logic`, `fallbacks`, `implementation`, `monitoring`, `practitioner_leverage`, `safety_context`, `when_not_useful`, `when_useful`


### Meal-linked postprandial movement

`bb3e57d5-c330-4ab6-927f-0b6a40294977` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 4 — Meal-linked postprandial movement` · source range **5477–7153** · hash `b26ce58a21a2fa51…`

| field | provenance | span | text |
|---|---|---|---|
| `adaptability` | VERBATIM_SOURCE | 6505–6721 | A client does not necessarily need to start with:<br><br>breakfast walk + lunch walk + dinner walk.<br><br>For a low-adherence client:<br><br>choose one meal\<br>→ establish the behavior\<br>→ observe execution/response\<br>→ expand if useful. |
| `alternatives` | VERBATIM_SOURCE | 6748–7151 | The larger Engine 7 knowledge object should eventually become:<br><br>**post-meal muscular activity**<br><br>with walking as one implementation.<br><br>Future sources may enrich it with alternatives such as:<br><br>seated calf activity\<br>household movement\<br>resistance/activity breaks\<br>other physically suitable options.<br><br>Thi …[+103 chars] |
| `client_decision_logic` | VERBATIM_SOURCE | 6201–6477 | Potentially prioritize when:<br><br>-   sedentary behavior is substantial;<br><br>-   post-meal glucose exposure is a relevant issue;<br><br>-   walking is physically appropriate;<br><br>-   the client currently does little post-meal movement;<br><br>-   a meal-linked habit is easier than formal exercise. |
| `what_it_means` | VERBATIM_SOURCE | 5557–5911 | Physical activity does not have to exist only as a separate formal workout.<br><br>Movement can be linked directly to an eating occasion.<br><br>The source uses approximately **10 minutes of walking after one meal per day** as its simple implementation.<br><br>The reusable strategy is:<br><br>**Attach a manageable amount o …[+54 chars] |
| `why_useful` | VERBATIM_SOURCE | 5941–6172 | A client may struggle with:<br><br>"Exercise for 45 minutes every day."<br><br>but may accept:<br><br>"After dinner, take a short walk."<br><br>This turns an abstract exercise recommendation into a behavioral trigger:<br><br>**meal finishes → movement begins.** |

Absent (the source supplies none; never filled): `fallbacks`, `implementation`, `monitoring`, `practitioner_leverage`, `safety_context`, `when_not_useful`, `when_useful`


### Progressive layering instead of intervention overload

`f8faa6c2-8a2a-4028-a57c-a8e0c34f09d5` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 5 — Progressive layering instead of intervention overload` · source range **7153–8508** · hash `b8364c2b221fdd49…`

| field | provenance | span | text |
|---|---|---|---|
| `client_decision_logic` | VERBATIM_SOURCE | 7894–8506 | **Poor adherence history / overwhelmed client**<br><br>fewer actions\<br>→ highest-value/easiest wins\<br>→ establish success.<br><br>**Highly motivated and capable client**<br><br>potentially broader starting intervention.<br><br>**Strong response**<br><br>maintain what works and layer only where needed.<br><br>**Weak or absent response**<br> …[+312 chars] |
| `opening_statement` | VERBATIM_SOURCE | 7224–7668 | This may be one of the most transferable pieces of practitioner intelligence from the source.<br><br>The source packages several relatively simple behaviors into a four-week approach rather than asking for a complete lifestyle overhaul immediately.<br><br>Our normalized principle is:<br><br>**Start with an appropriat …[+144 chars] |
| `why_useful` | VERBATIM_SOURCE | 7692–7872 | Clients differ enormously.<br><br>One client may execute five changes immediately.<br><br>Another may fail with more than one.<br><br>Therefore:<br><br>**Intervention load itself should be personalized.** |

Absent (the source supplies none; never filled): `adaptability`, `alternatives`, `fallbacks`, `implementation`, `monitoring`, `practitioner_leverage`, `safety_context`, `what_it_means`, `when_not_useful`, `when_useful`


### Preserve agency and reduce unnecessary deprivation

`4e331d79-e23c-4e55-b3ab-47f3ca49d551` · heading path `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 6 — Preserve agency and reduce unnecessary deprivation` · source range **8508–10645** · hash `1ed40247e1f7cec0…`

| field | provenance | span | text |
|---|---|---|---|
| `client_decision_logic` | VERBATIM_SOURCE | 9452–10643 | The important value is **not "give everybody the same four hacks."**<br><br>Use the options according to the client's actual bottleneck.<br><br>**High-carb breakfast**\<br>→ breakfast restructuring may be useful.<br><br>**Diet-change resistance**\<br>→ meal-linked movement may be an easier first intervention.<br><br>**Client ove …[+891 chars] |
| `opening_statement` | VERBATIM_SOURCE | 8576–9002 | The source repeatedly emphasizes that improvement does not necessarily mean permanently abandoning every carbohydrate-containing food the client enjoys.<br><br>Our normalized practitioner intelligence is:<br><br>**When clinically reasonable, preserve foods and preferences that matter to the client and modify qu …[+126 chars] |
| `why_useful` | VERBATIM_SOURCE | 9026–9423 | A theoretically excellent plan that the client abandons can produce less value than a good plan that is consistently executed.<br><br>But this principle does **not** mean:<br><br>"Never restrict anything."<br><br>Sometimes substantial change may be appropriate.<br><br>The deeper intelligence is:<br><br>**Restriction should have  …[+97 chars] |

Absent (the source supplies none; never filled): `adaptability`, `alternatives`, `fallbacks`, `implementation`, `monitoring`, `practitioner_leverage`, `safety_context`, `what_it_means`, `when_not_useful`, `when_useful`


## C. The predefined Strategy 6 assertion

The span was fixed in `testing/fixtures/curated/strategy6_routing.json` **before** the importer existed to produce it.

| | |
|---|---|
| expected heading path | `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 6 — Preserve agency and reduce unnecessary deprivation > Decision intelligence` |
| expected source range | **9452–10643** (1191 chars) |
| stored destination field | `client_decision_logic` |
| stored heading path | `T2D / Insulin Resistance — Engine 7 Practitioner Intelligence > Strategy 6 — Preserve agency and reduce unnecessary deprivation > Decision intelligence` |
| stored source range | **9452–10643** (1191 chars) |
| stored provenance | `VERBATIM_SOURCE` |
| path matches | **YES** |
| stored field contains the expected span verbatim | **YES** |
| byte-identical | **YES** |

Every routing row of the bottleneck table, present in the stored field:

- `High-carb breakfast` — present
- `Diet-change resistance` — present
- `Client overwhelmed` — present
- `Client already follows a strategy well` — present
- `Preferred strategy is not practical` — present
- `Client cannot walk comfortably` — present
- `Client does not respond despite good adherence` — present
- `Several options are possible` — present

## D. Unparsed / REVIEW_REQUIRED blocks

| heading | level | span | why no rule applied |
|---|---|---|---|
| T2D / Insulin Resistance — Engine 7 Practitioner Intelligence | 1 | 0–65 | no rule in curated_grammar_rules matches the heading 'T2D / Insulin Resistance — Engine 7 Practitioner Intelligence' at level 1. Adding one is an INSE …[+89 chars] |
| Video 1 distilled knowledge | 2 | 65–345 | no rule in curated_grammar_rules matches the heading 'Video 1 distilled knowledge' at level 2. Adding one is an INSERT, and it must state why the cons …[+55 chars] |
| Adherence philosophy | 3 | 10645–11297 | no rule in curated_grammar_rules matches the heading 'Adherence philosophy' at level 3. Adding one is an INSERT, and it must state why the construct i …[+48 chars] |
| Assessment & Consultation Intelligence | 2 | 11297–13163 | no rule in curated_grammar_rules matches the heading 'Assessment & Consultation Intelligence' at level 2. Adding one is an INSERT, and it must state w …[+66 chars] |
| How this changes the consultation | 3 | 13163–13865 | no rule in curated_grammar_rules matches the heading 'How this changes the consultation' at level 3. Adding one is an INSERT, and it must state why th …[+61 chars] |
| Final Engine 7 intelligence from Video 1 | 2 | 13865–13910 | no rule in curated_grammar_rules matches the heading 'Final Engine 7 intelligence from Video 1' at level 2. Adding one is an INSERT, and it must state …[+68 chars] |
| Behaviour implementation | 3 | 14788–15102 | 'Behaviour implementation' matched a subsection rule but its enclosing block is not a strategy or a principle, so it has no owner. The parser will not …[+11 chars] |
| Decision intelligence | 3 | 15102–15451 | 'Decision intelligence' matched a subsection rule but its enclosing block is not a strategy or a principle, so it has no owner. The parser will not in …[+8 chars] |
| Adherence intelligence | 3 | 15451–15657 | no rule in curated_grammar_rules matches the heading 'Adherence intelligence' at level 3. Adding one is an INSERT, and it must state why the construct …[+50 chars] |
| Assessment intelligence | 3 | 15657–16070 | no rule in curated_grammar_rules matches the heading 'Assessment intelligence' at level 3. Adding one is an INSERT, and it must state why the construc …[+51 chars] |
| One-sentence Engine 7 takeaway | 2 | 16070–16516 | no rule in curated_grammar_rules matches the heading 'One-sentence Engine 7 takeaway' at level 2. Adding one is an INSERT, and it must state why the c …[+58 chars] |

## E–H. Other knowledge kinds

| kind | count | note |
|---|---|---|
| implementation_patterns | 0 | none created — the source has no `Implementation` subsection |
| claims | 0 | K09 not run; a curated strategy is not a claim |
| evidence_records | 0 | K10 CLOSED (D48) |
| practitioner-verified evidence | 0 | **Video 1 contains no such passage** — and `evidence_records` has no `verification_actor`. SCHEMA GAP, reported not faked. |
| unverified source claims | 0 | Video 1 makes no effect claim of its own |
| curated_principles | 2 | Core operating principle; Core principle |

## I. Concept proposals (GATE 2 — read-only, nothing written)

| source phrase | nearest existing | score | method / tier | final status |
|---|---|---|---|---|
| Core operating principle — High-impact change with minimum unnecessary friction | — | — | none | PROPOSED |
| Breakfast restructuring | — | — | none | PROPOSED |
| Pre-meal vegetable/fibre structure | — | — | none | PROPOSED |
| Vinegar as a candidate meal-level tool | — | — | none | PROPOSED |
| Meal-linked postprandial movement | — | — | none | PROPOSED |
| Progressive layering instead of intervention overload | — | — | none | PROPOSED |
| Preserve agency and reduce unnecessary deprivation | — | — | none | PROPOSED |
| Core principle | — | — | none | PROPOSED |

PROPOSED concepts created by this import: **0** — read_only=True writes nothing.


## K. Heading-grammar registry — rules USED in this run

| rule | construct | example | reusable because | expected elsewhere |
|---|---|---|---|---|
| `STRATEGY_FAMILY` | A grouping heading that names a FAMILY of strategies, not a strategy | Strategy family — Movement | A family heading collects strategies already defined elsewhere in the section. It must be recognised precisely so it is NOT counted as a strategy: Video 1 has six strategies and th …[+73 chars] | Any section that ends with a roll-up of its own strategies; the practitioner named this construct explicitly. |
| `STRATEGY_NUMBERED` | A numbered strategy card, the document's primary unit | Strategy 1 — Breakfast restructuring | Numbered strategy cards are the unit the practitioner writes in, and the numbering restarts per section. The optional "New " prefix is part of the same construct in later sections. | Every video section that enumerates strategies, including the "New Strategy N" form the practitioner listed. |
| `PRINCIPLE_NAMED` | A named practitioner principle heading | Core operating principle — High-impact change with minimum unnecessary friction | Principles are the second top-level construct in this document and carry the reasoning that governs strategy choice. The practitioner enumerated the naming variants directly, which …[+34 chars] | The least-structured later sections are expected to be dominated by these forms rather than by numbered cards. |
| `SUB_ADAPTABILITY` | How the strategy bends to the individual client | Adaptability | The individualisation subsection, appearing both as the bare noun and as a qualified form such as "Adherence adaptation". Matching the morphological stem keeps the qualified varian …[+55 chars] | Sections that separate the reusable strategy from its per-client implementation. |
| `SUB_ALTERNATIVES` | Other implementations serving the same objective | Future alternatives | The substitution subsection — what else serves the same objective when the preferred implementation is impractical. The "Future" qualifier marks alternatives not yet in the library …[+35 chars] | Any section whose strategy has more than one viable implementation. |
| `SUB_DECISION` | The prioritisation subsection — WHEN to reach for this | Client decision logic | The prioritisation layer, and the single most valuable field in the document: it states when a strategy matters, when it does not, which bottleneck it addresses and when another in …[+119 chars] | Every section that distinguishes "useful strategy" from "current priority"; the practitioner listed Client decision logi …[+53 chars] |
| `SUB_LEVERAGE` | How the strategy is used in consultation | Practitioner leverage | The consultation-craft subsection: how to put the strategy to a client. Named by the practitioner as a standard subsection. | Sections written for use in a live consultation rather than as reference. |
| `SUB_WHAT_MEANS` | The definition subsection of a strategy card | What the strategy means | The definitional subsection of a card. Named by the practitioner as a standard subsection of the strategy construct. | Every section using the numbered or core strategy-card construct. |
| `SUB_WHY` | The rationale subsection, phrased as a "Why ..." heading | Why this can be useful | Rationale subsections are written as a "Why ..." question or statement, and the tail varies with the strategy — "Why this can be useful", "Why retain it?", "Why this matters". The  …[+148 chars] | Every section; the rationale subsection is the most consistently present one after the definition. |

Rules in the registry NOT needed by Video 1 (the grammar is broader than the fixture): `STRATEGY_CORE`, `SUB_EVIDENCE_REL`, `SUB_FALLBACKS`, `SUB_IMPLEMENTATION`, `SUB_MONITORING`, `SUB_SAFETY`, `SUB_WHEN_NOT_USEFUL`, `SUB_WHEN_USEFUL`


## L. Final counts

```
source strategies           = 6
parsed strategies           = 6
stored strategies           = 6
missing strategies          = 0

verbatim fields             = 24
transformed fields          = 0
unsupported / generated     = 0    (a field not backed by its span cannot be stored)

unparsed blocks             = 11 of 42

practitioner-verified evid. = 0    (none in Video 1; SCHEMA GAP reported)
unverified source claims    = 0    (Video 1 makes no effect claim of its own)

concepts resolved           = 0
concepts proposed           = 0    (read_only: nothing written to the ontology)
concepts review-required    = 0

K09 calls                   = 0
K10 calls                   = 0
provider calls, any kind    = 0
```

## What a PASS does NOT mean

Concept normalization is not solved: **0 of 8 phrases resolved** against
269 seeded concepts, and the resolver was run `read_only=True` so nothing
was written to the ontology. That is GATE 2 and it is blocked on
`normalize._tier_semantic()`, which returns `[], 0.0` unconditionally.
Retrieval quality is GATE 3 and untested here. K10 is still closed.

## Schema gap, reported rather than worked around

`evidence_records` has **no `verification_actor` and no
`verification_status`** — it cannot distinguish practitioner verification
from automated verification, which D49 state B requires. Nothing was
forced into a generic flag, because **Video 1 contains no
practitioner-verified passage** (no "I checked the underlying published
report"), so the count is legitimately zero. **This gap must be closed
before any section that does contain such a passage is imported.**

## Next test, per the brief

Not Video 2. Video 1 is one of the *most* structured sections; the next
preservation test should be one of the **least** structured — a section
dominated by `E7 principle` / `Master principle` / irregular headings —
so the same parser architecture is tried at both ends of the spectrum
without fixture-specific tuning. 11 of 42 blocks here are already
`REVIEW_REQUIRED`, and those headings are the honest starting list.
