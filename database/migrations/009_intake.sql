-- =====================================================================
-- 009_intake.sql — Core Intake V1 (BUILD_GUIDE step 14)
--
-- Scope and, more importantly, the EXCLUSIONS are settled in DECISIONS.md
-- D22. Read that first: the fields here follow from what intake refuses to
-- ask, not the other way round.
--
-- Three rules this migration exists to make structural rather than
-- aspirational:
--
--   1. INTAKE NEVER BLOCKS A CASE. Nothing here can refuse a submission.
--      Completeness is recorded, gaps are reported, and an incomplete
--      intake still initializes Engine 6 canonical state v1.
--   2. ABSENCE IS NEVER NORMALITY. A field not asked or not answered is
--      UNKNOWN. RHT NOT_ASSESSED never means "RHT was fine".
--   3. INTAKE DATA IS CASE DATA. Lab reports and food logs are client
--      records. They never touch source_envelopes, knowledge_entities or
--      the Knowledge Inbox — the two clocks meet only at E7 case retrieval
--      and de-identified practice aggregation (D12).
--
-- Deliberately NOT created here: any new store for clinical facts.
-- client_labs, client_medications, client_supplements, client_conditions,
-- client_symptoms, client_measurements and client_food_logs already exist
-- in 004 and already carry RLS. Intake EXTRACTS into them, so every view,
-- engine and policy built on those tables works on intake-sourced data
-- with no change. Only the things 004 has no home for are added.
-- =====================================================================


-- =====================================================================
-- 1. Where an intake-detected gap goes
-- =====================================================================
--
-- missing_data_reports already exists (005) with the classification
-- vocabulary this step needs -- ESSENTIAL / USEFUL / CONDITIONAL /
-- ALREADY_COVERED_BY_RHT / OPTIONAL / UNNECESSARY -- and
-- v_missing_data_recurrence already aggregates it. That machinery is
-- extended here, not duplicated.
--
-- One thing blocked it: `engine` is NOT NULL over an E1..E7 enum, and a
-- gap found while validating a submission was reported by no engine. The
-- options were to attribute it to E6 or to say so honestly. Attributing it
-- to E6 would put a fictional engine into v_missing_data_recurrence's
-- `engines` array -- the column that answers "which engine's reasoning was
-- constrained by this" -- so the gap is recorded as what it is.

ALTER TABLE missing_data_reports ALTER COLUMN engine DROP NOT NULL;

ALTER TABLE missing_data_reports
    ADD COLUMN IF NOT EXISTS submission_id uuid;

COMMENT ON COLUMN missing_data_reports.engine IS
'The engine whose reasoning was constrained, NULL when the gap was detected by intake validation rather than by an engine run. Exactly one of engine / submission_id is set (ck_gap_has_a_source).';


-- =====================================================================
-- 2. The submission envelope
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'intake_status') THEN
        CREATE TYPE intake_status AS ENUM (
            'DRAFT',        -- being filled in; not yet a case input
            'SUBMITTED',    -- complete enough to convert, gaps and all
            'CONVERTED',    -- extracted into case tables + E6 state built
            'SUPERSEDED'    -- a later submission replaced it
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'intake_section') THEN
        -- The A-N sections of step 14. An enum rather than a registry
        -- because the SECTION set is the shape of V1 and changing it is a
        -- deliberate redesign; the FIELDS inside them are a registry
        -- (intake_field_catalog) precisely so V2 is a data edit.
        CREATE TYPE intake_section AS ENUM (
            'BASIC_PROFILE',        -- A
            'GOALS',                -- B
            'DIAGNOSES_HISTORY',    -- C
            'MEDICATIONS',          -- D
            'LABS_REPORTS',         -- E
            'SYMPTOMS',             -- F
            'DIET_PATTERN',         -- G
            'FOOD_ENVIRONMENT',     -- H
            'HYDRATION_MOVEMENT',   -- I
            'DIGESTIVE',            -- J
            'REPRODUCTIVE',         -- K
            'PREVIOUS_ATTEMPTS',    -- L
            'FOOD_LOG',             -- M
            'RHT_LINKAGE'           -- N
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS intake_submissions (
    submission_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id          uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    status             intake_status NOT NULL DEFAULT 'DRAFT',
    schema_version     text NOT NULL DEFAULT 'intake.v1',

    -- Provenance: who produced this and how. A practitioner transcribing a
    -- consultation and a client filling a form are different evidentiary
    -- weights, and the engines are entitled to know which they have.
    captured_by        text,
    capture_method     text,
    source             event_source NOT NULL DEFAULT 'CORE_INTAKE',

    submitted_at       timestamptz,
    converted_at       timestamptz,
    case_version_id    uuid REFERENCES client_case_versions(case_version_id) ON DELETE SET NULL,
    superseded_by      uuid REFERENCES intake_submissions(submission_id) ON DELETE SET NULL,

    -- The submission exactly as received, before extraction. Kept for the
    -- same reason 006 keeps a raw source: if extraction is wrong, this is
    -- what it gets re-run against.
    raw_payload        jsonb NOT NULL DEFAULT '{}'::jsonb,

    notes              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),

    -- A converted submission must say what it became. Nothing here can
    -- reject a submission for being incomplete -- only for being
    -- incoherent about its own lifecycle.
    CONSTRAINT ck_converted_has_case
        CHECK (status <> 'CONVERTED' OR (converted_at IS NOT NULL AND case_version_id IS NOT NULL)),
    CONSTRAINT ck_submitted_has_time
        CHECK (status IN ('DRAFT') OR submitted_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_intake_client ON intake_submissions (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intake_status ON intake_submissions (status) WHERE status <> 'SUPERSEDED';

-- One live submission per client. History is retained by superseding, the
-- same shape client_case_versions uses for canonical state.
CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_current
    ON intake_submissions (client_id)
    WHERE status IN ('DRAFT','SUBMITTED');

COMMENT ON TABLE intake_submissions IS
'One Core Intake V1 submission. Incompleteness is never a reason to reject: see DECISIONS.md D22 and BUILD_GUIDE step 14.';


-- =====================================================================
-- 3. Section payloads
-- =====================================================================
--
-- Same shape as assessment_layers: a typed section discriminator plus a
-- jsonb payload. Full per-field typing is deferred with the rest of the
-- output contracts (D14) -- only the CONTROL surface is strict in this
-- system, and intake's control surface is completeness, not prose content.

CREATE TABLE IF NOT EXISTS intake_sections (
    section_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id  uuid NOT NULL REFERENCES intake_submissions(submission_id) ON DELETE CASCADE,
    client_id      uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    section        intake_section NOT NULL,
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- NOT_APPLICABLE is a real answer and must be distinguishable from
    -- unanswered: a male client's REPRODUCTIVE section is not a gap.
    not_applicable boolean NOT NULL DEFAULT false,
    na_reason      text,

    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_section_per_submission UNIQUE (submission_id, section),
    CONSTRAINT ck_na_has_reason CHECK (NOT not_applicable OR na_reason IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_intake_sections_client ON intake_sections (client_id, section);

COMMENT ON COLUMN intake_sections.not_applicable IS
'A section deliberately skipped because it does not apply. Distinct from unanswered: NOT_APPLICABLE is an answer, absence is a gap.';


-- =====================================================================
-- 4. The field registry — conditional logic as DATA
-- =====================================================================
--
-- Which fields exist, what they are worth, and when they are asked. A
-- registry rather than code so that V2 -- which will be driven by
-- v_missing_data_recurrence once real cases have run -- is an INSERT or an
-- UPDATE, not a release. Same principle as source_kinds in D19.

CREATE TABLE IF NOT EXISTS intake_field_catalog (
    field_key       text PRIMARY KEY,
    section         intake_section NOT NULL,
    label           text NOT NULL,

    -- Why this field is worth a client's time. ESSENTIAL fields are the
    -- ones whose absence is reported at HIGH severity; ALREADY_COVERED_BY_RHT
    -- fields are listed so the exclusion is visible and testable rather
    -- than merely absent.
    classification  intake_classification NOT NULL,

    -- Conditional display: this field is asked only when the referenced
    -- field holds one of these values. NULL condition = always asked.
    condition_field text REFERENCES intake_field_catalog(field_key) ON DELETE SET NULL,
    condition_values text[],

    rht_owned       boolean NOT NULL DEFAULT false,
    active          boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_condition_pair
        CHECK ((condition_field IS NULL) = (condition_values IS NULL)),
    -- An RHT-owned field must be classified as such. This is the exclusion
    -- from D22 made structural: a future edit cannot quietly start asking
    -- an RHT question through Core Intake without changing its
    -- classification, which is the thing a test can see.
    CONSTRAINT ck_rht_owned_classified
        CHECK (NOT rht_owned OR classification = 'ALREADY_COVERED_BY_RHT')
);

CREATE INDEX IF NOT EXISTS idx_field_catalog_section
    ON intake_field_catalog (section) WHERE active;

COMMENT ON TABLE intake_field_catalog IS
'The V1 field registry. Adding, removing or reclassifying a field is a data operation. rht_owned marks what Core Intake deliberately does not ask because the Real Health Test owns it (DECISIONS.md D22).';


-- =====================================================================
-- 5. Lab and report references
-- =====================================================================
--
-- CASE DATA, not knowledge. A client's lab PDF is their record; it is not
-- a source for the knowledge library and must never enter source_envelopes
-- (D12, and the constraint restated at the top of this file). The
-- similarity of "a file with content to extract" is exactly the trap.

CREATE TABLE IF NOT EXISTS client_report_files (
    report_file_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    submission_id  uuid REFERENCES intake_submissions(submission_id) ON DELETE SET NULL,

    report_kind    text NOT NULL,          -- LAB_PANEL, IMAGING, DISCHARGE_SUMMARY, OTHER
    report_date    date,
    laboratory     text,
    ordering_clinician text,

    -- A reference, not the bytes. Where the artifact actually lives is a
    -- deployment decision; the case record keeps the pointer and the
    -- provenance so a value can always be traced back to its report.
    storage_ref    text,
    original_filename text,
    content_hash   text,

    transcribed    boolean NOT NULL DEFAULT false,
    provenance_note text,
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_report_locatable
        CHECK (storage_ref IS NOT NULL OR original_filename IS NOT NULL OR provenance_note IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_report_files_client
    ON client_report_files (client_id, report_date DESC NULLS LAST);

-- Bind a transcribed value back to the report it came from, so provenance
-- survives into the table the engines actually read.
ALTER TABLE client_labs
    ADD COLUMN IF NOT EXISTS report_file_id uuid
        REFERENCES client_report_files(report_file_id) ON DELETE SET NULL;

COMMENT ON TABLE client_report_files IS
'Client lab and medical report artifacts. CASE data: never source_envelopes, never knowledge_entities. See DECISIONS.md D12.';


-- =====================================================================
-- 6. Now bind the intake gap source, once submissions exist
-- =====================================================================

ALTER TABLE missing_data_reports
    DROP CONSTRAINT IF EXISTS fk_missing_submission;
ALTER TABLE missing_data_reports
    ADD CONSTRAINT fk_missing_submission
    FOREIGN KEY (submission_id) REFERENCES intake_submissions(submission_id) ON DELETE CASCADE;

ALTER TABLE missing_data_reports
    DROP CONSTRAINT IF EXISTS ck_gap_has_a_source;
ALTER TABLE missing_data_reports
    ADD CONSTRAINT ck_gap_has_a_source
    CHECK (num_nonnulls(engine, submission_id) = 1);

COMMENT ON CONSTRAINT ck_gap_has_a_source ON missing_data_reports IS
'A gap is reported either by an engine run or by intake validation, never by neither and never by both. Prevents an intake gap being laundered into an engine attribution.';


-- =====================================================================
-- 7. RLS — from the first migration, not retrofitted
-- =====================================================================
--
-- Intake is where a real client's name, date of birth and labs first enter
-- the system. Every client-scoped table here gets the same treatment 005
-- gives the rest: RLS ENABLED and FORCED (so even the owner is subject),
-- phi_runtime scoped to the transaction-local client, phi_practitioner
-- read-only across clients.
--
-- intake_field_catalog is deliberately NOT in this list: it is a registry
-- of question definitions and holds no client data.

DO $$
DECLARE
    t text;
    client_scoped text[] := ARRAY[
        'intake_submissions','intake_sections','client_report_files'
    ];
BEGIN
    FOREACH t IN ARRAY client_scoped LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);

        EXECUTE format($p$
            CREATE POLICY %I ON %I FOR ALL TO phi_runtime
            USING (client_id = current_client_scope())
            WITH CHECK (client_id = current_client_scope())
        $p$, 'rls_runtime_' || t, t);

        EXECUTE format($p$
            CREATE POLICY %I ON %I FOR SELECT TO phi_practitioner USING (true)
        $p$, 'rls_practitioner_' || t, t);

        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO phi_runtime', t);
        EXECUTE format('GRANT SELECT ON %I TO phi_practitioner', t);
    END LOOP;
END $$;

-- The catalog is reference data: readable by both roles, written by
-- migrations and by deliberate practitioner classification.
GRANT SELECT ON intake_field_catalog TO phi_runtime, phi_practitioner;


-- =====================================================================
-- 8. The V1 field registry
-- =====================================================================
--
-- Sections A-N of step 14. ESSENTIAL is reserved for fields whose absence
-- genuinely constrains Engine 1 or Engine 3 reasoning; most of intake is
-- USEFUL, which is the honest classification for something worth having
-- and not worth blocking on.

INSERT INTO intake_field_catalog (field_key, section, label, classification, notes) VALUES
  -- A. Basic profile
  ('year_of_birth',       'BASIC_PROFILE', 'Year of birth', 'ESSENTIAL', 'Age changes reference ranges and risk framing'),
  ('biological_sex',      'BASIC_PROFILE', 'Biological sex', 'ESSENTIAL', 'Reference ranges; gates the REPRODUCTIVE section'),
  ('height_cm',           'BASIC_PROFILE', 'Height', 'ESSENTIAL', NULL),
  ('weight_kg',           'BASIC_PROFILE', 'Weight', 'ESSENTIAL', NULL),
  ('waist_cm',            'BASIC_PROFILE', 'Waist circumference', 'USEFUL', 'Central adiposity carries more signal than BMI (E1 s18)'),
  ('body_composition',    'BASIC_PROFILE', 'Body composition, if available', 'OPTIONAL', 'Device-dependent; never required'),
  ('occupation',          'BASIC_PROFILE', 'Occupation', 'USEFUL', 'Daily structure, not employment detail'),
  ('daily_structure',     'BASIC_PROFILE', 'Typical working day', 'USEFUL', 'Meal timing feasibility for E2/E3'),
  ('region',              'BASIC_PROFILE', 'Region', 'USEFUL', 'E3 cannot reason about seasonal or regional availability without it'),

  -- B. Goals
  ('consultation_reason', 'GOALS', 'Main reason for consulting', 'ESSENTIAL', NULL),
  ('health_goals',        'GOALS', 'Health goals', 'ESSENTIAL', NULL),
  ('priority_concerns',   'GOALS', 'What concerns you most', 'USEFUL', NULL),
  ('desired_outcomes',    'GOALS', 'What a good outcome looks like', 'USEFUL', 'Client words; never a request for a hypothesis (D22)'),

  -- C. Diagnoses and history
  ('known_diagnoses',     'DIAGNOSES_HISTORY', 'Diagnosed conditions', 'ESSENTIAL', NULL),
  ('medical_history',     'DIAGNOSES_HISTORY', 'Relevant medical history', 'USEFUL', NULL),
  ('prior_events',        'DIAGNOSES_HISTORY', 'Significant prior events or procedures', 'USEFUL', NULL),
  ('family_history',      'DIAGNOSES_HISTORY', 'First-degree family history', 'USEFUL', 'First-degree only, metabolic/CV/endocrine/autoimmune (D22)'),

  -- D. Medications and supplements
  ('medications',         'MEDICATIONS', 'Current medications', 'ESSENTIAL', 'Safety gate input; unknown dose stays UNKNOWN'),
  ('supplements',         'MEDICATIONS', 'Current supplements', 'USEFUL', NULL),
  ('medication_reasons',  'MEDICATIONS', 'What each is for, if known', 'USEFUL', 'If unknown, records UNKNOWN; never inferred'),

  -- E. Labs and reports
  ('lab_values',          'LABS_REPORTS', 'Key lab values', 'ESSENTIAL', NULL),
  ('lab_reports',         'LABS_REPORTS', 'Lab report files or references', 'USEFUL', 'Preferred over manual transcription (D22)'),
  ('lab_dates',           'LABS_REPORTS', 'When tests were taken', 'ESSENTIAL', 'A lab value without a date cannot be trended'),

  -- F. Symptoms
  ('current_symptoms',    'SYMPTOMS', 'Current symptoms', 'ESSENTIAL', 'Focused, not a checklist (D22)'),
  ('symptom_severity',    'SYMPTOMS', 'How much each affects you', 'USEFUL', NULL),

  -- G. Diet pattern
  ('diet_pattern',        'DIET_PATTERN', 'Dietary pattern', 'ESSENTIAL', 'Vegetarian/vegan/non-veg/other'),
  ('restrictions',        'DIET_PATTERN', 'Restrictions', 'ESSENTIAL', NULL),
  ('allergies',           'DIET_PATTERN', 'Allergies', 'ESSENTIAL', 'Safety-bearing'),
  ('intolerances',        'DIET_PATTERN', 'Known intolerances', 'USEFUL', NULL),
  ('dislikes',            'DIET_PATTERN', 'Strong dislikes', 'USEFUL', 'An unliked plan is an unfollowed plan'),
  ('cultural_constraints','DIET_PATTERN', 'Cultural or religious food constraints', 'USEFUL', NULL),

  -- H. Practical food environment
  ('who_cooks',           'FOOD_ENVIRONMENT', 'Who cooks', 'ESSENTIAL', 'E3 cannot design an executable plan without it'),
  ('cooking_facilities',  'FOOD_ENVIRONMENT', 'Cooking facilities', 'USEFUL', NULL),
  ('eating_out',          'FOOD_ENVIRONMENT', 'Eating out frequency and context', 'USEFUL', NULL),
  ('meal_timing',         'FOOD_ENVIRONMENT', 'Usual meal times', 'ESSENTIAL', NULL),
  ('prep_time',           'FOOD_ENVIRONMENT', 'Realistic preparation time', 'USEFUL', NULL),
  ('food_budget',         'FOOD_ENVIRONMENT', 'Budget constraint', 'USEFUL', 'A coarse band, never itemised finances (D22)'),
  ('travel_constraints',  'FOOD_ENVIRONMENT', 'Regular travel', 'OPTIONAL', NULL),

  -- I. Hydration and movement — BASICS ONLY, RHT owns the depth
  ('hydration',           'HYDRATION_MOVEMENT', 'Typical fluid intake', 'USEFUL', NULL),
  ('activity_basic',      'HYDRATION_MOVEMENT', 'Current activity, broadly', 'USEFUL', 'Basics only; RHT owns the distribution'),
  ('movement_limitations','HYDRATION_MOVEMENT', 'Anything that limits movement', 'CONDITIONAL', NULL),

  -- J. Digestive
  ('bowel_pattern',       'DIGESTIVE', 'Bowel pattern', 'USEFUL', NULL),
  ('gi_symptoms',         'DIGESTIVE', 'Reflux, bloating, other GI symptoms', 'USEFUL', NULL),

  -- K. Reproductive — conditional, and genuinely skipped when not applicable
  ('cycle_context',       'REPRODUCTIVE', 'Menstrual cycle context', 'CONDITIONAL', NULL),
  ('cycle_irregularity',  'REPRODUCTIVE', 'Cycle irregularity', 'CONDITIONAL', NULL),
  ('menopause_status',    'REPRODUCTIVE', 'Menopause or perimenopause', 'CONDITIONAL', NULL),
  ('reproductive_dx',     'REPRODUCTIVE', 'PCOS or other reproductive-metabolic diagnosis', 'CONDITIONAL', NULL),

  -- L. Previous attempts — lightweight; E2 does the real reasoning
  ('previous_attempts',   'PREVIOUS_ATTEMPTS', 'Previous diets or programmes', 'USEFUL', NULL),
  ('what_worked',         'PREVIOUS_ATTEMPTS', 'What worked', 'USEFUL', NULL),
  ('what_failed',         'PREVIOUS_ATTEMPTS', 'What did not, and why', 'USEFUL', 'Lightweight; E2 profiles behaviour properly later (D22)'),

  -- M. Food log
  ('food_log_days',       'FOOD_LOG', '3-day food log', 'ESSENTIAL', 'Descriptive; no calorie counting by the client (D22)'),

  -- N. RHT linkage
  ('rht_status',          'RHT_LINKAGE', 'Real Health Test status', 'ESSENTIAL', 'NOT_ASSESSED means unknown, never normal')
ON CONFLICT (field_key) DO NOTHING;

-- Conditional wiring. Declared as data so the rule is inspectable and
-- testable rather than buried in a form component.
UPDATE intake_field_catalog
   SET condition_field = 'biological_sex', condition_values = ARRAY['F','FEMALE','INTERSEX']
 WHERE section = 'REPRODUCTIVE';

UPDATE intake_field_catalog
   SET condition_field = 'known_diagnoses', condition_values = ARRAY['__ANY_MOBILITY_OR_PAIN__']
 WHERE field_key = 'movement_limitations';

-- What Core Intake does NOT ask, recorded so the exclusion is queryable
-- and a test can assert it stayed excluded. ck_rht_owned_classified means
-- these cannot quietly become askable without changing classification.
INSERT INTO intake_field_catalog (field_key, section, label, classification, rht_owned, active, notes) VALUES
  ('sleep_quality',        'HYDRATION_MOVEMENT', 'Sleep quality',                'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('sleep_pattern',        'HYDRATION_MOVEMENT', 'Sleep pattern and regularity', 'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('stress_load',          'HYDRATION_MOVEMENT', 'Stress',                       'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('recovery_capacity',    'HYDRATION_MOVEMENT', 'Recovery',                     'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('fatigue_body_signals', 'HYDRATION_MOVEMENT', 'Fatigue and body signals',     'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('lifestyle_load',       'HYDRATION_MOVEMENT', 'Work and lifestyle load',      'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)'),
  ('sedentary_distribution','HYDRATION_MOVEMENT','Detailed sedentary/activity distribution', 'ALREADY_COVERED_BY_RHT', true, false, 'RHT owns it (D22)')
ON CONFLICT (field_key) DO NOTHING;


-- =====================================================================
-- 9. Completeness, reported rather than enforced
-- =====================================================================

CREATE OR REPLACE VIEW v_intake_completeness AS
SELECT
    s.submission_id,
    s.client_id,
    s.status,
    count(DISTINCT sec.section)                                        AS sections_present,
    count(DISTINCT sec.section) FILTER (WHERE sec.not_applicable)      AS sections_not_applicable,
    (SELECT count(DISTINCT section) FROM intake_field_catalog
      WHERE active AND NOT rht_owned)                                  AS sections_defined,
    (SELECT count(*) FROM missing_data_reports m
      WHERE m.submission_id = s.submission_id AND NOT m.resolved)      AS open_gaps,
    (SELECT count(*) FROM missing_data_reports m
      WHERE m.submission_id = s.submission_id AND NOT m.resolved
        AND m.severity IN ('CRITICAL','HIGH'))                         AS high_priority_gaps,
    s.submitted_at,
    s.converted_at
FROM intake_submissions s
LEFT JOIN intake_sections sec ON sec.submission_id = s.submission_id
GROUP BY s.submission_id, s.client_id, s.status, s.submitted_at, s.converted_at;

ALTER VIEW v_intake_completeness SET (security_invoker = true);
GRANT SELECT ON v_intake_completeness TO phi_runtime, phi_practitioner;

COMMENT ON VIEW v_intake_completeness IS
'Reports how complete a submission is. Reports only: nothing in this schema refuses a case for incompleteness (BUILD_GUIDE step 14, DECISIONS.md D22).';

CREATE TRIGGER trg_intake_submissions_updated BEFORE UPDATE ON intake_submissions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_intake_sections_updated BEFORE UPDATE ON intake_sections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =====================================================================
-- 10. Rebuild v_missing_data_recurrence for a nullable engine
-- =====================================================================
--
-- The view is from 005 and predates intake-sourced gaps. Its
-- `array_agg(DISTINCT engine::text)` over rows where engine is NULL
-- produces {NULL} -- an array containing a NULL, which renders as one
-- unnamed engine rather than as no engine. The column answers "whose
-- reasoning was constrained by this gap", so an intake gap must show an
-- empty list, not a phantom entry.
--
-- Also adds the split the practitioner actually needs when deciding
-- whether a recurring gap should become a V2 intake question: a field
-- engines keep missing is a different signal from a field clients keep
-- leaving blank.

-- DROP then CREATE, not CREATE OR REPLACE: replacing a view may only
-- append columns, and engine_reports / intake_reports belong beside the
-- engines column they qualify, not bolted onto the end.
DROP VIEW IF EXISTS v_missing_data_recurrence;

CREATE VIEW v_missing_data_recurrence AS
SELECT missing_field,
       count(*)                                              AS reports,
       count(DISTINCT client_id)                             AS distinct_clients,
       count(*) FILTER (WHERE constrained_reasoning)          AS constrained_reasoning_count,
       bool_or(rht_would_supply)                              AS rht_would_supply,
       coalesce(
           array_agg(DISTINCT engine::text ORDER BY engine::text)
               FILTER (WHERE engine IS NOT NULL),
           ARRAY[]::text[])                                   AS engines,
       count(*) FILTER (WHERE engine IS NOT NULL)             AS engine_reports,
       count(*) FILTER (WHERE submission_id IS NOT NULL)      AS intake_reports,
       max(severity::text)                                    AS max_severity,
       (array_agg(DISTINCT classification::text)
            FILTER (WHERE classification IS NOT NULL))[1]     AS classification
  FROM missing_data_reports
 GROUP BY missing_field
 ORDER BY count(DISTINCT client_id) DESC, count(*) DESC;

ALTER VIEW v_missing_data_recurrence SET (security_invoker = true);
GRANT SELECT ON v_missing_data_recurrence TO phi_runtime, phi_practitioner;

COMMENT ON VIEW v_missing_data_recurrence IS
'Recurring gaps, aggregated for deliberate classification (Engine 7 s57, DECISIONS.md D8/D22). engine_reports vs intake_reports separates "engines keep missing this" from "clients keep leaving this blank" -- different signals, different V2 decisions. An engine repeatedly reporting a gap NEVER auto-creates an intake question.';
