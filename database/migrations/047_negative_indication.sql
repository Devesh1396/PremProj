-- =====================================================================
-- 047_negative_indication.sql   A ROLE NAME THAT CLAIMED TOO MUCH.
--
-- `046` registered:
--
--     when_not_useful  ->  CONTRA_INDICATION
--
-- The grammar rule it describes does not say that. `033`'s
-- SUB_WHEN_NOT_USEFUL is, verbatim:
--
--     construct:  'An explicit negative-indication subsection'
--     rationale:  'The counterpart of the positive-indication subsection.
--                  Kept separate because "when this does not apply" is the
--                  half most often lost when a decision layer is flattened.'
--
-- "Negative indication" and "does not apply" are prioritisation language.
-- A strategy can be lower priority, not currently useful, or mismatched to
-- the present bottleneck without being clinically contraindicated or
-- unsafe. `CONTRA_INDICATION` reads as the clinical term, and a downstream
-- reader looking for contra-indications would have found a list of
-- sequencing judgements and treated them as safety.
--
-- That is the same failure class as D49's `mechanism`: a field given a
-- meaning the source never carried. It is worse here, because the
-- over-claim is toward SAFETY, and GATE 4 has already recorded that the
-- system does NOT operationally know safety (migration 046, Q3).
--
-- The corrected role is `NEGATIVE_INDICATION`, taken from the practitioner
-- grammar's own words rather than invented here.
--
-- WHAT IS NOT CHANGED: the stored field name `when_not_useful`, any
-- practitioner text, any span, and the separate `safety_context` ->
-- SAFETY row, which IS the safety construct and stays exactly as it is.
--
-- Append-only (hard rule 10): `046` is applied and is not edited, on this
-- branch or anywhere else. Nothing outside `046` referenced the old value
-- -- checked across *.py, *.sql, *.md and *.json -- so this is a data
-- correction with no code to follow it.
-- =====================================================================

UPDATE curated_field_roles
   SET semantic_role = 'NEGATIVE_INDICATION',
       registered_by = 'migration 033, corrected by 047',
       note = 'Explicit negative indication: when the strategy does not apply, is lower priority, or is mismatched to the present bottleneck. NOT a clinical contraindication and NOT safety -- 033 calls the construct "an explicit negative-indication subsection" and nothing in it is about harm.'
 WHERE field_name = 'when_not_useful';

-- The corrected row must exist and must not have drifted back.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM curated_field_roles
                    WHERE field_name = 'when_not_useful'
                      AND semantic_role = 'NEGATIVE_INDICATION') THEN
        RAISE EXCEPTION
            'when_not_useful did not take the corrected role NEGATIVE_INDICATION';
    END IF;
    IF EXISTS (SELECT 1 FROM curated_field_roles
                WHERE semantic_role IN ('CONTRA_INDICATION', 'CONTRAINDICATION')) THEN
        RAISE EXCEPTION
            'a CONTRA_INDICATION role is still registered; 047 exists to remove it';
    END IF;
END $$;
