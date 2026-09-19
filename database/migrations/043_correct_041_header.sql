-- =====================================================================
-- 043_correct_041_header.sql   A CORRECTION, carried as a comment.
--
-- `041`'s header says of `When potentially worth considering`,
-- `When not to prioritize`, `Berberine Safety / Gate` and
-- `ACV Protocol Guardrails`:
--
--     "Left REVIEW_REQUIRED on purpose so the decision stays open"
--
-- THAT IS NOT WHAT HAPPENS, and the first completed GATE 4 run showed it.
-- Those four headings get no rule OF THEIR OWN, which is what was
-- intended and is still true -- but they are level-3 subsections of a
-- curated object, so the GENERIC authored-subhead rule in the same
-- migration picks them up and stores them as fields named by the author:
-- `when_potentially_worth_considering`, `when_not_to_prioritize`,
-- `berberine_safety_gate`, `acv_protocol_guardrails`.
--
-- The intent survives and is arguably better served: the text is
-- preserved as its own field with its own span, and it is NOT aliased to
-- `client_decision_logic` or to `safety_context`. Q1 and Q3 remain the
-- practitioner's to answer, and answering them later is an UPDATE to a
-- registry row rather than a re-import.
--
-- But the header states a behaviour the code does not have, and an
-- applied migration cannot be edited (hard rule 10). So the correction is
-- recorded here, where anyone reading the schema will find it.
-- =====================================================================

COMMENT ON TABLE curated_grammar_rules IS
'The curated heading grammar, as rows. CORRECTION TO MIGRATION 041''S HEADER: it claims `When potentially worth considering`, `When not to prioritize`, `Berberine Safety / Gate` and `ACV Protocol Guardrails` are left REVIEW_REQUIRED. They are not. They receive no rule of their own, as intended, but SUB_AUTHORED_SUBHEAD stores them as fields named by the author''s own heading. They are preserved with their spans and are NOT aliased to client_decision_logic or safety_context, so Q1 and Q3 stay open — but 041 describes an outcome the parser does not produce.';
