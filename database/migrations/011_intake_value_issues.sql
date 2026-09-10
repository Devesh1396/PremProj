-- =====================================================================
-- 011_intake_value_issues.sql — where a malformed intake answer goes
--
-- 009 proved COMPLETENESS: which applicable fields have no answer. It said
-- nothing about whether a supplied answer was usable, and the two failures
-- that produced are opposite and both bad:
--
--   height_cm: "about 170"   ->  extract() died with
--                                InvalidTextRepresentation on a numeric
--                                column, hundreds of lines after intake
--                                accepted the submission
--   rht_status: "probably fine" -> flowed through rht_state() into the
--                                Engine 6 payload as RHT_STATUS
--                                "PROBABLY FINE"
--
-- The first is a crash a long way from its cause. The second is worse: a
-- safety-bearing field silently accepting a value that means nothing, in
-- the one place D22 insists NOT_ASSESSED must mean unknown.
--
-- INTAKE STILL NEVER BLOCKS A CASE. Nothing here can refuse a submission.
-- A malformed value becomes an ISSUE plus, where the field matters, a
-- GAP -- so it reads as unknown rather than as an answer.
--
-- Deliberately NOT a schema for intake answers. D22 keeps the field
-- registry as data and V1 explicitly unfinished; a rigid column-per-field
-- table would freeze both. This records what was wrong with what arrived.
-- =====================================================================


-- =====================================================================
-- 1. The issues, alongside the raw submission
-- =====================================================================
--
-- On intake_submissions rather than a table of its own: an issue has no
-- life independent of the submission that carried it, it is always read
-- with it, and it must be deleted with it.
--
-- raw_payload stays RAW. It is the provenance record of what was actually
-- submitted, and nothing sanitizes it in place -- the cleaning happens on
-- the way OUT, at extraction, so the original answer is always recoverable
-- and always comparable against what was made of it.

ALTER TABLE intake_submissions
    ADD COLUMN IF NOT EXISTS validation_issues jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE intake_submissions
    DROP CONSTRAINT IF EXISTS ck_validation_issues_is_array;
ALTER TABLE intake_submissions
    ADD CONSTRAINT ck_validation_issues_is_array
        CHECK (jsonb_typeof(validation_issues) = 'array');

COMMENT ON COLUMN intake_submissions.validation_issues IS
'One object per supplied answer that could not be used: field path, what arrived, what was wrong, and what was done about it (TREATED_AS_UNKNOWN, DROPPED or COERCED). Never a reason to reject a submission — intake never blocks a case (D22). Empty array means every supplied answer was usable, which is NOT the same as complete: absence is tracked as a gap in missing_data_reports.';

-- Finding the submissions that arrived with unusable answers is the
-- practitioner-facing question ("what did the form let through?"), so it
-- should not be a sequential scan once there are years of them.
CREATE INDEX IF NOT EXISTS idx_intake_submissions_with_issues
    ON intake_submissions (client_id, submitted_at DESC)
    WHERE validation_issues <> '[]'::jsonb;


-- =====================================================================
-- 2. The allowed RHT statuses are not a new vocabulary
-- =====================================================================
--
-- assessment_status already exists (005) and already says exactly what an
-- assessment can be: NOT_ASSESSED, NOT_AVAILABLE, IN_PROGRESS, COMPLETED,
-- EXPIRED, SUPERSEDED. Intake validates against THAT rather than against a
-- list in Python, so the two cannot drift and adding a status stays one
-- change in one place.
--
-- A view because scripts/intake.py must read the vocabulary at runtime,
-- and phi_runtime has no business querying pg_enum directly.

CREATE OR REPLACE VIEW v_assessment_status_values
WITH (security_invoker = true) AS
SELECT unnest(enum_range(NULL::assessment_status))::text AS status_value;

COMMENT ON VIEW v_assessment_status_values IS
'The assessment_status vocabulary, readable by phi_runtime. Intake validates a declared RHT status against this rather than a hard-coded list, so a new status is an enum change in one place instead of two.';

GRANT SELECT ON v_assessment_status_values TO phi_runtime, phi_practitioner;
