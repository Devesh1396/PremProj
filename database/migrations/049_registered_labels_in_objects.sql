-- =====================================================================
-- 049_registered_labels_in_objects.sql
--
-- A REGISTERED LABEL MUST BE RECOGNISED WHEREVER IT APPEARS.
--
-- `033`'s subsection rules carry `owner_kinds = NULL`, which means
-- (STRATEGY, PRINCIPLE) -- written before `curated_objects` existed. While
-- SUB_AUTHORED_SUBHEAD was active that was invisible: a registered label
-- inside a curated object failed the ownership check, handed over, and the
-- catch-all picked it up under the author's own wording.
--
-- Measured on Video 14, before 048 retired the catch-all:
--
--   `Decision intelligence`      -> stored as `decision_intelligence`
--   `Why it attracts clients`    -> stored as `why_it_attracts_clients`
--
-- Both are REGISTERED CONSTRUCTS. `033`'s SUB_DECISION pattern is
-- `^(?:Client\s+)?Decision\s+(?:logic|intelligence)$` -- the practitioner
-- enumerated `Decision intelligence` themselves -- and SUB_WHY is
-- `^Why\b.*$`. With the catch-all gone they would fall to
-- REVIEW_REQUIRED, so a construct the practitioner registered would be
-- unrecognised purely because of which container it sat in.
--
-- So the 033 subsection rules become ownable by a curated object as well.
-- This adds NO label and invents NO mapping: every pattern and every
-- field name is exactly the one `033` already seeded.
--
-- WHAT THIS DOES NOT DECIDE. GATE 4's Q1 asks whether `Decision
-- intelligence`, `When potentially worth considering` and `When not to
-- prioritize` are one field under three names. `033` already answers for
-- the first -- the practitioner put it in SUB_DECISION's own alternation.
-- The other two appear in NO rule, are not given one here, and stay
-- REVIEW_REQUIRED. Q1 remains open exactly where it was open.
--
-- SUB_AUTHORED_SUBHEAD stays deactivated. This is not a route back to it:
-- these rules match NAMED constructs, not `^(?P<name>.+)$`.
--
-- Append-only.
-- =====================================================================

UPDATE curated_grammar_rules
   SET owner_kinds = ARRAY['STRATEGY', 'PRINCIPLE', 'CURATED_OBJECT']
 WHERE block_kind = 'SUBSECTION'
   AND active
   AND field_name IS NOT NULL;      -- a FIXED, registered field name only

DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n FROM curated_grammar_rules
     WHERE block_kind = 'SUBSECTION' AND active
       AND (owner_kinds IS NULL OR NOT ('CURATED_OBJECT' = ANY(owner_kinds)));
    IF n > 0 THEN
        RAISE EXCEPTION
            '% active subsection rule(s) still cannot be owned by a curated object', n;
    END IF;
    -- The catch-all must not have been revived by this.
    IF EXISTS (SELECT 1 FROM curated_grammar_rules
                WHERE rule_id = 'SUB_AUTHORED_SUBHEAD' AND active) THEN
        RAISE EXCEPTION 'SUB_AUTHORED_SUBHEAD is active again; 048 retired it';
    END IF;
END $$;
