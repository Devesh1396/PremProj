-- 004_client.sql
-- Client state and the orchestration spine.
--
-- Engine 6 is the logic around this schema: canonical current state plus
-- retained history, so a follow-up is never treated as a new client.
--
-- Two things are enforced here that prompts cannot guarantee:
--   1. E1 Pass A and Pass B must run the same prompt (trg_enforce_two_pass)
--   2. Client-facing output cannot be released while a HOLD flag is open
--      (trg_block_unapproved_communication)

-- =====================================================================
-- Types
-- =====================================================================

CREATE TYPE engine_id AS ENUM ('E1','E2','E3','E4','E5','E6','E7');

-- Pass A and Pass B are an orchestration method around knowledge
-- retrieval, not two versions of Engine 1. Both load the same prompt file.
CREATE TYPE engine_pass AS ENUM ('SINGLE','A','B');

CREATE TYPE run_status AS ENUM (
    'PENDING','RUNNING','SUCCEEDED','SCHEMA_INVALID','REPAIR_RETRY',
    'FAILED','DEAD_LETTER','CANCELLED'
);

CREATE TYPE client_status AS ENUM ('INTAKE','ACTIVE','PAUSED','COMPLETED','ARCHIVED');

CREATE TYPE intervention_status AS ENUM (
    'PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED','PAUSED',
    'STOPPED','COMPLETED','REJECTED'
);

-- "Stopped" is not "failed". "Not tracked" is not "no change".
CREATE TYPE outcome_direction AS ENUM (
    'IMPROVING','STABLE','LIMITED_RESPONSE','WORSENING','NOT_TRACKED','TOO_EARLY'
);

CREATE TYPE flag_severity AS ENUM ('HOLD','NOTE');

-- Deterministic flags come from SQL rules over labs/medications/conditions.
-- LLM flags are additive. An LLM may add a flag; it may not clear a
-- deterministic one.
CREATE TYPE flag_source AS ENUM ('DETERMINISTIC','LLM','PRACTITIONER');

CREATE TYPE flag_status AS ENUM ('OPEN','ACKNOWLEDGED','RESOLVED','OVERRIDDEN');

CREATE TYPE review_decision AS ENUM (
    'PENDING','APPROVED','APPROVED_WITH_EDITS','REJECTED','RERUN_REQUESTED'
);

CREATE TYPE routing_target AS ENUM (
    'NONE','ENGINE1','ENGINE2','ENGINE3','MULTIPLE','MEDICAL_COORDINATION','MORE_DATA'
);

-- Engine 4 section 48.
CREATE TYPE progress_decision AS ENUM (
    'CONTINUE','PROGRESS','INTENSIFY','SIMPLIFY','MODIFY','REPLACE','REMOVE',
    'INVESTIGATE_FURTHER','ROUTE_TO_ENGINE1','ROUTE_TO_ENGINE2','ROUTE_TO_ENGINE3',
    'MEDICAL_COORDINATION','MORE_DATA_BEFORE_DECISION'
);

CREATE TYPE failure_type AS ENUM (
    'STRATEGY','ADHERENCE','IMPLEMENTATION','MEASUREMENT','INSUFFICIENT_EXPOSURE',
    'WRONG_HYPOTHESIS','NORMAL_VARIABILITY','NONE'
);

-- =====================================================================
-- Clients and case versions
-- =====================================================================

CREATE TABLE clients (
    client_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_ref   text,
    status         client_status NOT NULL DEFAULT 'INTAKE',
    -- Identity/context kept deliberately small here. Evolving detail lives
    -- in the versioned case state.
    display_name   text,
    year_of_birth  integer,
    sex            text,
    country        text,
    region         text,
    locality       text,
    primary_language text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_yob CHECK (
        year_of_birth IS NULL
        OR year_of_birth BETWEEN 1900 AND extract(year FROM now())::int
    )
);

CREATE UNIQUE INDEX uq_client_external ON clients (external_ref) WHERE external_ref IS NOT NULL;
CREATE TRIGGER trg_clients_updated BEFORE UPDATE ON clients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Engine 6 canonical state. Never overwritten: a new version is inserted
-- and the previous one retained.
CREATE TABLE client_case_versions (
    case_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    case_version    integer NOT NULL,
    is_current      boolean NOT NULL DEFAULT true,
    phase           text,
    -- Full canonical state (CASE_MEMORY_HANDOFF).
    canonical_state jsonb NOT NULL,
    -- Only what changed (CASE_MEMORY_DELTA), so n8n updates incrementally.
    delta           jsonb,
    change_reason   text,
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now(),

    UNIQUE (client_id, case_version),
    CONSTRAINT ck_case_version_positive CHECK (case_version >= 1)
);

-- Exactly one current version per client, enforced by index not by
-- application discipline.
CREATE UNIQUE INDEX uq_case_current ON client_case_versions (client_id)
    WHERE is_current;

CREATE INDEX idx_case_versions_client ON client_case_versions (client_id, case_version DESC);

COMMENT ON TABLE client_case_versions IS
'Engine 6. Current truth and history are distinct. Superseding a version sets is_current=false rather than deleting; the partial unique index guarantees one current row.';

-- Cycles bound routing depth so a case cannot loop indefinitely between
-- engines 1/2/3.
CREATE TABLE case_cycles (
    cycle_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    cycle_number   integer NOT NULL,
    cycle_type     text NOT NULL,          -- 'NEW_CLIENT' | 'FOLLOWUP'
    loop_count     integer NOT NULL DEFAULT 0,
    max_loops      integer NOT NULL DEFAULT 3,
    opened_at      timestamptz NOT NULL DEFAULT now(),
    closed_at      timestamptz,

    UNIQUE (client_id, cycle_number),
    CONSTRAINT ck_loop_bound CHECK (loop_count <= max_loops)
);

COMMENT ON CONSTRAINT ck_loop_bound ON case_cycles IS
'Routing depth limit. Prevents Engine 4 -> 1/2/3 -> 4 cycling without bound.';

-- =====================================================================
-- Clinical data
-- =====================================================================

CREATE TABLE client_measurements (
    measurement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    measured_on    date NOT NULL,
    measure        text NOT NULL,          -- weight, waist, systolic_bp, ...
    value          numeric,
    unit           text,
    context        text,
    -- Baselines are never moved. A new phase gets a new baseline row.
    is_baseline    boolean NOT NULL DEFAULT false,
    source         text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_measurements_client ON client_measurements (client_id, measure, measured_on DESC);

CREATE TABLE client_labs (
    lab_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    measured_on    date NOT NULL,
    marker         text NOT NULL,
    -- Resolved against the ontology so retrieval and deterministic rules
    -- work on canonical markers rather than free text.
    concept_id     uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    value          numeric,
    value_text     text,
    unit           text,
    reference_low  numeric,
    reference_high numeric,
    is_baseline    boolean NOT NULL DEFAULT false,
    source         text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_labs_client   ON client_labs (client_id, marker, measured_on DESC);
CREATE INDEX idx_labs_concept  ON client_labs (concept_id) WHERE concept_id IS NOT NULL;

CREATE TABLE client_conditions (
    condition_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    condition     text NOT NULL,
    concept_id    uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    status        text NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE | RESOLVED | UNDER_INVESTIGATION
    diagnosed_on  date,
    source        text,
    -- Inferences must never silently become facts.
    is_inferred   boolean NOT NULL DEFAULT false,
    confidence    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_conditions_client ON client_conditions (client_id, status);

CREATE TABLE client_symptoms (
    symptom_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    symptom      text NOT NULL,
    concept_id   uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    severity     integer,
    status       text NOT NULL DEFAULT 'ACTIVE',
    reported_on  date NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_severity CHECK (severity IS NULL OR severity BETWEEN 0 AND 10)
);

CREATE INDEX idx_symptoms_client ON client_symptoms (client_id, reported_on DESC);

CREATE TABLE client_medications (
    medication_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    name          text NOT NULL,
    -- Links to MEDICATION_CONTEXT concepts, which is what the deterministic
    -- safety rules match on.
    concept_id    uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    dose          text,
    timing        text,
    status        text NOT NULL DEFAULT 'CURRENT',   -- CURRENT | PAST | CHANGED
    started_on    date,
    changed_on    date,
    stopped_on    date,
    prescriber_note text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_medications_client ON client_medications (client_id, status);
CREATE INDEX idx_medications_concept ON client_medications (concept_id) WHERE concept_id IS NOT NULL;

CREATE TABLE client_supplements (
    supplement_entry_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    name          text NOT NULL,
    supplement_id uuid REFERENCES supplements(supplement_id) ON DELETE SET NULL,
    dose          text,
    -- Dietary inclusion and therapeutic dosing are different interventions.
    is_therapeutic_dose boolean NOT NULL DEFAULT false,
    timing        text,
    status        text NOT NULL DEFAULT 'CURRENT',
    started_on    date,
    stopped_on    date,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_client_supplements ON client_supplements (client_id, status);

CREATE TABLE client_food_logs (
    food_log_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    logged_on    date NOT NULL,
    raw_text     text,
    structured   jsonb,
    source       text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_food_logs_client ON client_food_logs (client_id, logged_on DESC);

-- =====================================================================
-- Interventions, exposure, targets
-- =====================================================================

CREATE TABLE client_interventions (
    intervention_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    strategy_id     uuid REFERENCES strategies(strategy_id) ON DELETE SET NULL,
    name            text NOT NULL,
    source_engine   engine_id,
    purpose         text,
    status          intervention_status NOT NULL DEFAULT 'PROPOSED',
    -- "Planned" is not "started". started_on stays null until it actually began.
    proposed_on     date,
    started_on      date,
    ended_on        date,
    stop_reason     text,
    -- Stopped is not failed; failed is not intolerable.
    outcome         outcome_direction NOT NULL DEFAULT 'NOT_TRACKED',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_started_requires_status CHECK (
        started_on IS NULL
        OR status IN ('STARTED','ONGOING','MODIFIED','PAUSED','STOPPED','COMPLETED')
    )
);

CREATE INDEX idx_interventions_client ON client_interventions (client_id, status);
CREATE TRIGGER trg_interventions_updated BEFORE UPDATE ON client_interventions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON CONSTRAINT ck_started_requires_status ON client_interventions IS
'Engine 6 must never confuse a proposed intervention with a started one. A start date on a PROPOSED row is rejected.';

CREATE TABLE client_intervention_exposure (
    exposure_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intervention_id uuid NOT NULL REFERENCES client_interventions(intervention_id) ON DELETE CASCADE,
    period_start    date NOT NULL,
    period_end      date,
    -- Adherence quality, not merely completion.
    adherence_summary text,
    adherence_pct   numeric(5,2),
    exposure_note   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_adherence_pct CHECK (adherence_pct IS NULL OR adherence_pct BETWEEN 0 AND 100)
);

CREATE INDEX idx_exposure_intervention ON client_intervention_exposure (intervention_id, period_start DESC);

CREATE TABLE client_targets (
    target_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    target_kind   text NOT NULL,          -- OBJECTIVE | SYMPTOM | FUNCTION | BEHAVIOUR
    measure       text NOT NULL,
    concept_id    uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    baseline_value text,
    target_value  text,
    phase         text,
    status        text NOT NULL DEFAULT 'ACTIVE',
    -- Internal targets are not exposed to the client; Engine 5 derives
    -- client-facing targets separately.
    is_internal   boolean NOT NULL DEFAULT true,
    set_on        date NOT NULL DEFAULT current_date,
    achieved_on   date,
    rationale     text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_targets_client ON client_targets (client_id, status);

CREATE TABLE client_followups (
    followup_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    cycle_id      uuid REFERENCES case_cycles(cycle_id) ON DELETE SET NULL,
    review_period text,
    submitted_on  date NOT NULL,
    raw_answers   jsonb,
    structured    jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_followups_client ON client_followups (client_id, submitted_on DESC);

-- =====================================================================
-- Engine runs
-- =====================================================================

CREATE TABLE engine_runs (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid REFERENCES clients(client_id) ON DELETE CASCADE,
    case_version_id uuid REFERENCES client_case_versions(case_version_id) ON DELETE SET NULL,
    cycle_id        uuid REFERENCES case_cycles(cycle_id) ON DELETE SET NULL,

    engine          engine_id NOT NULL,
    pass            engine_pass NOT NULL DEFAULT 'SINGLE',

    -- Provenance for the reasoning itself. Without these an output cannot
    -- be interpreted six months later.
    prompt_file     text NOT NULL,
    prompt_hash     text NOT NULL,
    schema_version  text,
    model_role      text NOT NULL,
    model_name      text,
    model_params    jsonb,

    status          run_status NOT NULL DEFAULT 'PENDING',
    attempts        integer NOT NULL DEFAULT 0,
    input_tokens    integer,
    output_tokens   integer,
    duration_ms     integer,
    error_class     text,
    error_detail    text,

    started_at      timestamptz,
    completed_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_pass_only_for_e1 CHECK (pass = 'SINGLE' OR engine = 'E1')
);

CREATE INDEX idx_runs_client ON engine_runs (client_id, engine, created_at DESC);
CREATE INDEX idx_runs_status ON engine_runs (status) WHERE status IN ('PENDING','RUNNING','REPAIR_RETRY');
CREATE INDEX idx_runs_cycle  ON engine_runs (cycle_id, engine);

COMMENT ON COLUMN engine_runs.prompt_hash IS
'SHA-256 of the prompt file content. E1 Pass A and Pass B must record the identical hash: a divergent hash means the master specification was forked.';

-- Pass A and Pass B are the same Engine 1 specification invoked twice.
-- A fork shows up here as a rejected insert rather than drifting silently.
CREATE OR REPLACE FUNCTION enforce_two_pass_same_prompt()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    other_hash text;
    other_file text;
BEGIN
    IF NEW.engine <> 'E1' OR NEW.pass = 'SINGLE' OR NEW.cycle_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT prompt_hash, prompt_file INTO other_hash, other_file
    FROM engine_runs
    WHERE cycle_id = NEW.cycle_id
      AND engine = 'E1'
      AND pass IN ('A','B')
      AND pass <> NEW.pass
      AND run_id <> NEW.run_id
    LIMIT 1;

    IF other_hash IS NOT NULL AND other_hash <> NEW.prompt_hash THEN
        RAISE EXCEPTION
            'E1 pass % uses prompt % (hash %) but the other pass in this cycle used % (hash %). '
            'Pass A and Pass B must run the identical master Engine 1 specification.',
            NEW.pass, NEW.prompt_file, left(NEW.prompt_hash, 12),
            other_file, left(other_hash, 12)
            USING ERRCODE = 'raise_exception';
    END IF;

    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_enforce_two_pass
    BEFORE INSERT OR UPDATE ON engine_runs
    FOR EACH ROW EXECUTE FUNCTION enforce_two_pass_same_prompt();

CREATE TABLE engine_outputs (
    output_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        uuid NOT NULL REFERENCES engine_runs(run_id) ON DELETE CASCADE,
    -- Human-readable report and the validated structured handoff are stored
    -- separately. Report formatting is a later concern; the structured
    -- control fields are not.
    human_output  text,
    structured    jsonb,
    -- The strict control-flow subset, validated against the orchestration
    -- contract before anything routes on it.
    control       jsonb,
    schema_valid  boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_outputs_run ON engine_outputs (run_id);
CREATE INDEX idx_outputs_control ON engine_outputs USING gin (control);

-- =====================================================================
-- Flags and review
-- =====================================================================

CREATE TABLE case_flags (
    flag_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    cycle_id      uuid REFERENCES case_cycles(cycle_id) ON DELETE SET NULL,
    run_id        uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,

    rule_key      text NOT NULL,          -- 'INSULIN_PLUS_GLUCOSE_LOWERING', ...
    severity      flag_severity NOT NULL,
    source        flag_source NOT NULL,
    detail        text NOT NULL,
    status        flag_status NOT NULL DEFAULT 'OPEN',

    resolved_by   text,
    resolution_note text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    resolved_at   timestamptz
);

CREATE INDEX idx_flags_open ON case_flags (client_id, severity)
    WHERE status = 'OPEN';

-- An LLM-sourced update may not clear a deterministic flag.
CREATE OR REPLACE FUNCTION protect_deterministic_flags()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF OLD.source = 'DETERMINISTIC'
       AND OLD.status = 'OPEN'
       AND NEW.status <> 'OPEN'
       AND coalesce(NEW.resolved_by, '') NOT LIKE 'practitioner%' THEN
        RAISE EXCEPTION
            'Deterministic flag % can only be resolved by a practitioner, not by %',
            OLD.rule_key, coalesce(NEW.resolved_by, 'an unattributed actor')
            USING ERRCODE = 'raise_exception';
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_protect_deterministic_flags
    BEFORE UPDATE ON case_flags
    FOR EACH ROW EXECUTE FUNCTION protect_deterministic_flags();

CREATE TABLE practitioner_reviews (
    review_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    cycle_id      uuid REFERENCES case_cycles(cycle_id) ON DELETE SET NULL,
    run_id        uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,
    decision      review_decision NOT NULL DEFAULT 'PENDING',
    notes         text,
    edited_output text,
    reviewed_by   text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz
);

CREATE INDEX idx_reviews_pending ON practitioner_reviews (client_id, created_at)
    WHERE decision = 'PENDING';

-- Engine 5 output. This is the only client-facing artifact.
CREATE TABLE client_communications (
    communication_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    cycle_id      uuid REFERENCES case_cycles(cycle_id) ON DELETE SET NULL,
    run_id        uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,
    comm_type     text NOT NULL,          -- FIRST_ASSESSMENT | PROGRESS | ...
    content       text NOT NULL,
    -- Draft freely; release is gated.
    released      boolean NOT NULL DEFAULT false,
    released_at   timestamptz,
    released_by   text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_comms_client ON client_communications (client_id, created_at DESC);

-- The safety gate. Narrow by design: it blocks release only, never the
-- internal analysis, and only while a HOLD flag is actually open.
CREATE OR REPLACE FUNCTION block_unapproved_communication()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    open_holds int;
    rules text;
BEGIN
    IF NOT NEW.released THEN
        RETURN NEW;                      -- drafting is always permitted
    END IF;

    SELECT count(*), string_agg(rule_key, ', ')
      INTO open_holds, rules
      FROM case_flags
     WHERE client_id = NEW.client_id
       AND severity = 'HOLD'
       AND status = 'OPEN';

    IF open_holds > 0 THEN
        RAISE EXCEPTION
            'Cannot release client communication: % open HOLD flag(s) [%]. '
            'Practitioner must resolve or override before release.',
            open_holds, rules
            USING ERRCODE = 'raise_exception';
    END IF;

    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_block_unapproved_communication
    BEFORE INSERT OR UPDATE ON client_communications
    FOR EACH ROW EXECUTE FUNCTION block_unapproved_communication();

COMMENT ON FUNCTION block_unapproved_communication IS
'Workflow-level gate, not a prompt instruction. Blocks release of client-facing output while a HOLD flag is open. Internal analysis and practitioner view are never gated.';

-- =====================================================================
-- Engine 6 read path
-- =====================================================================

-- Single read path for engines 1-5. No engine reconstructs history itself.
CREATE OR REPLACE FUNCTION get_current_client_state(p_client_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $fn$
    SELECT jsonb_build_object(
        'client_id',      c.client_id,
        'status',         c.status,
        'case_version',   v.case_version,
        'phase',          v.phase,
        'canonical_state', v.canonical_state,
        'open_holds', (
            SELECT count(*) FROM case_flags f
             WHERE f.client_id = c.client_id AND f.severity='HOLD' AND f.status='OPEN'
        ),
        'active_interventions', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'name', i.name, 'status', i.status, 'started_on', i.started_on,
                       'outcome', i.outcome)), '[]'::jsonb)
              FROM client_interventions i
             WHERE i.client_id = c.client_id
               AND i.status IN ('STARTED','ONGOING','MODIFIED')
        ),
        'latest_labs', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'marker', l.marker, 'value', l.value, 'unit', l.unit,
                       'measured_on', l.measured_on)), '[]'::jsonb)
              FROM (
                SELECT DISTINCT ON (marker) marker, value, unit, measured_on
                  FROM client_labs WHERE client_id = c.client_id
                 ORDER BY marker, measured_on DESC
              ) l
        )
    )
    FROM clients c
    JOIN client_case_versions v
      ON v.client_id = c.client_id AND v.is_current
    WHERE c.client_id = p_client_id;
$fn$;

CREATE OR REPLACE FUNCTION get_client_timeline(p_client_id uuid)
RETURNS TABLE (event_date date, event_type text, detail text)
LANGUAGE sql
STABLE
AS $fn$
    SELECT measured_on, 'LAB', marker || ' = ' || coalesce(value::text, value_text, '')
      FROM client_labs WHERE client_id = p_client_id
    UNION ALL
    SELECT measured_on, 'MEASUREMENT', measure || ' = ' || coalesce(value::text,'')
      FROM client_measurements WHERE client_id = p_client_id
    UNION ALL
    SELECT started_on, 'INTERVENTION_STARTED', name
      FROM client_interventions WHERE client_id = p_client_id AND started_on IS NOT NULL
    UNION ALL
    SELECT submitted_on, 'FOLLOWUP', coalesce(review_period, 'follow-up')
      FROM client_followups WHERE client_id = p_client_id
    ORDER BY 1;
$fn$;

-- =====================================================================
-- Views
-- =====================================================================

CREATE VIEW v_review_queue AS
SELECT r.review_id, r.client_id, c.display_name, r.run_id,
       er.engine, er.pass, r.created_at,
       (SELECT count(*) FROM case_flags f
         WHERE f.client_id = r.client_id AND f.severity='HOLD' AND f.status='OPEN') AS open_holds,
       (SELECT count(*) FROM case_flags f
         WHERE f.client_id = r.client_id AND f.severity='NOTE' AND f.status='OPEN') AS open_notes
FROM practitioner_reviews r
JOIN clients c ON c.client_id = r.client_id
LEFT JOIN engine_runs er ON er.run_id = r.run_id
WHERE r.decision = 'PENDING'
ORDER BY open_holds DESC, r.created_at;

CREATE VIEW v_engine_run_health AS
SELECT engine, pass, status, count(*) AS runs,
       round(avg(duration_ms)::numeric, 0) AS avg_ms,
       sum(attempts) AS total_attempts
FROM engine_runs
GROUP BY engine, pass, status
ORDER BY engine, pass, status;
