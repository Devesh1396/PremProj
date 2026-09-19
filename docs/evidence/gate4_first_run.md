# GATE 4 — FIRST IMPLEMENTED RUN. It is a MISS.

**Never replaced by a later, better result.** The implementation it ran
against is commit `0ed2be0`; the fixture, answer key and prediction were
committed before that at `4b897e5`, `ae89182`, `432d0c1`.

## Result: the run did not complete. It aborted on a foreign key.

```
psycopg.errors.ForeignKeyViolation: insert or update on table
"envelope_derived_records" violates foreign key constraint "fk_derived_entity"
DETAIL:  Key (derived_id, derived_kind)=(40434e68-…, CURATED_OBJECT)
         is not present in table "knowledge_entities".
```

## What that means, plainly

Migration `040` added `CURATED_OBJECT` to the `derived_kind` enum and **did
not add the registration trigger that hard rule 12 requires**:

> *A new derived kind adds an enum value and a registration trigger — never a
> new foreign key on the provenance table.*

The migration's own header comment cites hard rule 12 and then does half of
what it says. `curated_strategies` and `curated_principles` each carry a
`trg_register_*` trigger; `curated_objects` was created without one, so no
row ever entered `knowledge_entities`, and the provenance edge had nothing to
point at.

**The constraint caught it on the first attempt to store a real object.**
That is `envelope_derived_records` doing exactly the job D-12 gives it —
provenance edges cannot dangle — and it is the reason the failure is a
crash at import rather than a library full of unregistered objects.

## Why this is recorded rather than quietly fixed

The brief's ordering exists for this. Had the fix been folded into `040`
before running, the evidence would have shown a clean first run and the
defect would never have been visible. The honest record is that the first
implemented run of GATE 4 hit a defect in GATE 4's own migration.

Nothing about the grammar, the disposition model or the verification model
was exercised past this point on this run. The counts below the abort are
NOT results; they are the last checks that ran before it.

## Verbatim output

```

the fixture is the one the answer key was written against
  PASS  fixture sha256 matches the frozen key

K11 — Video 1's stored rows, captured before and after
  PASS  Video 1 still imports as strategy cards, not objects

the curated source runs the ORDINARY inbox path (D37)
  PASS  K07/K08 normalize it
  PASS  K09's queue does NOT contain it (K12/A3, D49)
  PASS  the curated extractor's queue does
Traceback (most recent call last):
  File "/home/user/PremProj/testing/test_gate4_acceptance.py", line 376, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "/home/user/PremProj/testing/test_gate4_acceptance.py", line 130, in main
    result = CI.import_one(conn, next(e for e in CI.pending(conn)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/PremProj/scripts/curated_import.py", line 381, in import_one
    counts = store(conn, str(envelope_id), text, blocks, cards, objects,
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/PremProj/scripts/curated_import.py", line 290, in store
    conn.execute(
  File "/usr/local/lib/python3.11/dist-packages/psycopg/connection.py", line 300, in execute
    raise ex.with_traceback(None)
psycopg.errors.ForeignKeyViolation: insert or update on table "envelope_derived_records" violates foreign key constraint "fk_derived_entity"
DETAIL:  Key (derived_id, derived_kind)=(f8a24480-7349-4581-8f6a-d768ab9337e9, CURATED_OBJECT) is not present in table "knowledge_entities".
```

## Fix (post-first-run, migration `042`)

Append-only: `040` is applied and is not edited. `042` adds the registration
and deregistration triggers `040` should have carried, and the acceptance
suite gains a check that every curated object is registered — so the next
derived kind cannot repeat this by passing a suite that never looked.

---
---

# POST-FIRST-RUN (migrations `042`, `043`)

Everything below happened AFTER the MISS above and is reported as a later
result, not as the first one.

Two changes, both append-only:

- `042` adds the registration/deregistration triggers `040` omitted.
- `043` carries a CORRECTION to `041`'s header, which claimed four headings
  would be left REVIEW_REQUIRED. They are not: they get no rule of their
  own, as intended, but the generic authored-subhead rule stores them as
  fields named by the author. The intent — not aliasing them to
  `client_decision_logic` or `safety_context`, so Q1 and Q3 stay open — is
  intact; the header described an outcome the parser does not produce.

One test defect was also fixed: a Python tuple comma had leaked into the
suite's SQL (`field_name in ('mechanism',)`). That was the test, not the
implementation.

## Result of the completed run

```

the fixture is the one the answer key was written against
  PASS  fixture sha256 matches the frozen key

K11 — Video 1's stored rows, captured before and after
  PASS  Video 1 still imports as strategy cards, not objects

the curated source runs the ORDINARY inbox path (D37)
  PASS  K07/K08 normalize it
  PASS  K09's queue does NOT contain it (K12/A3, D49)
  PASS  the curated extractor's queue does

  IMPORT RESULT: 11 object(s), 0 strategy, 1 principle, 31 field, 61 block(s), 29 REVIEW_REQUIRED, 1 verification(s)

K12 — the deterministic parse costs nothing
  PASS  zero provider calls billed during import
  PASS  curated_parser.py contains no provider

K1 — ADD / ADD_UPGRADE / MERGE / REINFORCE / SKIP are distinct
        {'ADD': 3, 'ADD_UPGRADE': 1, 'MERGE': 4, 'REINFORCE': 1, 'SKIP': 2}
  PASS  every directive in the source produced its own disposition
  PASS  ADD and ADD_UPGRADE did not collapse
  PASS  MERGE is four and SKIP is two
  PASS  every disposition is re-derivable from its own stored span (D48)

K5 — explicitly rejected and reinforcement material is not active
        NOT ACTIVE: "Underground Vegetables Should Be Restricted"
        NOT ACTIVE: Earlier Energy Distribution / Late Eating
        NOT ACTIVE: Mechanism Overload Around ACV
  PASS  three objects are non-active by the database's own predicate
  PASS  no SKIP block became a curated STRATEGY row
  PASS    rejected claim stays inactive: 'underground vegetables should generally be a'

K2/K3 — the practitioner's verification, and where it stops
        [539:581] 'I checked the underlying published report.'
          -> PRACTITIONER / PRACTITIONER_VERIFIED  on  'Rapid Improvement Is Possible, but Timeline ≠ Biological Guarantee'
  PASS  exactly one practitioner verification is recorded
  PASS  it is PRACTITIONER / PRACTITIONER_VERIFIED
  PASS  its span CONTAINS the statement it names (D48)
  PASS  it attaches to the Rapid Improvement object, not the document
  PASS  berberine and ACV did NOT inherit PRACTITIONER_VERIFIED
  PASS  no SYSTEM_VERIFIED value exists to fall into

K9 — every authored byte is owned or loudly unknown
        61 blocks, 29 REVIEW_REQUIRED
  PASS  every block is stored, parsed or not
  PASS  every REVIEW_REQUIRED block says why
  PASS  every block keeps its raw text

K10 — preservation
  PASS  every stored object field IS its claimed slice
  PASS  no field was TRANSFORMED
  PASS  no `mechanism` field was invented (D49)

K7 — berberine and ACV keep their nuance as SEPARATE fields
        Berberine: ['berberine_safety_gate', 'final_e7_status', 'opening_statement', 'strategy_tier', 'when_not_to_prioritize', 'when_potentially_worth_considering']
  PASS    Berberine keeps more than one field
        Vinegar: ['acv_does_not_replace_meal_structure', 'acv_protocol_guardrails', 'best_use', 'final_e7_status', 'opening_statement', 'strategy_tier']
  PASS    Vinegar keeps more than one field

K11 — Video 1's rows, compared row by row
  PASS  Video 1's stored rows are byte-identical after GATE 4 ran

====================================================================
Q1  'Decision intelligence' vs 'When potentially worth considering'
    vs 'When not to prioritize' — REPORTED, NOT ALIASED
====================================================================

  'Decision intelligence'   [1318:1809]   PARSED
      A short timeline may be more plausible when:
      
      diabetes is relatively recent;\
      there is substantial modifiable adiposity/metabolic load;\
      intervention intensity and adherence are high;\
      glucose begins responding quickly;\
      sufficient beta-cell capacity remains.
      

  'When potentially worth considering'   [9204:9476]   PARSED
      Especially when:
      
      major lifestyle drivers are already being addressed;\
      client specifically wants a supplement adjunct;\
      glucose control remains suboptimal;\
      cost/burden is acceptable;\
      medication/safety context has been reviewed.

  'When not to prioritize'   [9476:9771]   PARSED
      If the client still has obvious major untreated bottlenecks such as:
      
      high refined-carbohydrate exposure\
      major excess energy intake\
      very low activity\
      poor adherence to foundational plan.
      
      Do not let:

  Reported, not decided. None of the three was aliased to the
  others and none was given a rule, so the practitioner's answer
  remains free either way.

====================================================================
Q2  where SKIP material lives — OPTIONS, NOT A CHOICE
====================================================================
  It currently lives in curated_objects with disposition SKIP, its
  full text preserved and curated_disposition_is_active() false.
  The alternatives the existing schema offers, none selected:
    negative_knowledge  — has why_investigated / evidence_examined /
        revisit_trigger, and is for a question EXAMINED AND FOUND
        WANTING (D41). Video 14's SKIPs are not that: Prem is
        refusing the SOURCE's simplification, not reporting a
        failed investigation, and there is no revisit trigger in
        the text to satisfy the NOT NULL columns without inventing
        one.
    knowledge_gaps      — 'nobody has looked'. Wrong: somebody did.
    curated_blocks REVIEW_REQUIRED — text and span preserved, but it
        would say the PARSER did not understand, which is false.

====================================================================
Q3  is there a non-flattening home for safety? — REPORTED
====================================================================
  'Berberine Safety / Gate'  [9771:10389]  PARSED
  'ACV Protocol Guardrails'  [11943:12741]  PARSED

  033 has SUB_SAFETY -> `safety_context`, but it matches only the
  bare heading `Safety`, and it is a STRATEGY-CARD subsection. The
  deterministic safety layer (safety_rules, safety_match_patterns)
  is a practitioner-curated registry, and D42 says adding a rule is
  an INSERT a human makes -- a curated import writing into it would
  be an ingestion path authoring clinical gates.
  ASSESSMENT: a GAP. Video 14's safety content is preserved with its
  span, and is NOT reachable as safety. Reported, not closed.

====================================================================
CONCEPT AUDIT
====================================================================
  units 0  linked 0  refused-as-prose 0
  SKIP  semantic recomputation not authoritative is not available — pgvector absent (D15): the semantic tier cannot run
        This is a supported configuration, not a failure.

============================================================
GATE 4 ACCEPTANCE: every checked expectation met
```
