-- 005_case_events.sql
--
-- Foundational hooks that are cheap now and expensive after E6, chat and
-- state handling are wired. This migration adds no features. It prevents
-- future retrofit.
--
-- Contains:
--   1. Row-Level Security with genuine role separation (default deny)
--   2. Versioned assessment envelope (RHT and any future instrument)
--   3. case_events spine — every future source of client information
--   4. Chat threads scoped by client, candidate facts requiring authorization
--   5. missing_data_reports for the intake refinement loop
--   6. Draft vs delivery distinction on client communications

-- =====================================================================
-- 1. ROLES AND CLIENT SCOPE
-- =====================================================================
--
-- Security model:
--   phi_admin        — owns the schema, runs migrations. Not used at runtime.
--   phi_runtime      — engines and workflows. RLS enforced. DEFAULT DENY:
--                      with no client context set, client-scoped tables
--                      return zero rows, not all rows.
--   phi_practitioner — the review surface. The single deliberate
--                      cross-client read path, still not a superuser.
--
-- Client scope is TRANSACTION-LOCAL (set_config third argument true), so a
-- pooled connection cannot carry Client A's context into Client B's query.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phi_admin') THEN
        CREATE ROLE phi_admin NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phi_runtime') THEN
        -- Explicitly NOSUPERUSER and NOBYPASSRLS. A runtime role that can
        -- bypass RLS makes the whole mechanism cosmetic.
        CREATE ROLE phi_runtime LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phi_practitioner') THEN
        CREATE ROLE phi_practitioner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

-- Returns the client scope for the CURRENT TRANSACTION, or NULL if unset.
-- NULL is the safe value: every policy compares client_id against it, and
-- `client_id = NULL` is never true, so no context means no rows.
CREATE OR REPLACE FUNCTION current_client_scope()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
    raw text;
BEGIN
    raw := current_setting('app.current_client_id', true);
    IF raw IS NULL OR btrim(raw) = '' THEN
        RETURN NULL;
    END IF;
    RETURN raw::uuid;
EXCEPTION WHEN others THEN
    -- A malformed scope value must not silently widen access.
    RETURN NULL;
END $fn$;

-- Set client scope for the current transaction only.
CREATE OR REPLACE FUNCTION set_client_scope(p_client_id uuid)
RETURNS void
LANGUAGE sql
AS $fn$
    SELECT set_config('app.current_client_id', coalesce(p_client_id::text, ''), true);
    SELECT NULL::void;
$fn$;

COMMENT ON FUNCTION set_client_scope IS
'Transaction-local by design (set_config third arg true). Pooled connections cannot leak Client A context into a later Client B query.';

-- ---------------------------------------------------------------------
-- 2. ASSESSMENT ENVELOPE
-- ---------------------------------------------------------------------
-- RHT is modelled as a versioned typed envelope. The exact ~30-signal
-- shape is deliberately NOT frozen: layers carry JSONB payloads under
-- typed, versioned headers. Once specific fields stabilise they can be
-- promoted to columns and indexed without redesigning the model.

CREATE TYPE assessment_instrument AS ENUM (
    'REAL_HEALTH_TEST', 'CORE_INTAKE', 'FOOD_LOG_ANALYSIS', 'OTHER'
);

-- NOT_ASSESSED and NOT_AVAILABLE are first-class states. Absence of an
-- assessment is never a normal or negative finding: not measuring sleep
-- load is not the same as finding sleep load to be fine.
CREATE TYPE assessment_status AS ENUM (
    'NOT_ASSESSED',   -- never administered
    'NOT_AVAILABLE',  -- exists but not accessible to this system
    'IN_PROGRESS',
    'COMPLETED',
    'EXPIRED',        -- too old to represent current state
    'SUPERSEDED'      -- a later assessment replaced it
);

-- The four representations of one assessment.
CREATE TYPE assessment_layer_type AS ENUM (
    'RAW_SIGNALS',    -- the client's actual responses
    'DERIVED_SCORES', -- scores and sub-scores computed by the instrument
    'INTERPRETATION', -- conclusions from the instrument's own logic
    'DIRECTION'       -- priorities and recommended focus areas
);

CREATE TABLE client_assessments (
    assessment_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id            uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,

    instrument           assessment_instrument NOT NULL,
    instrument_version   text,
    scoring_version      text,
    payload_schema_version text NOT NULL DEFAULT 'v0-unfrozen',

    status               assessment_status NOT NULL DEFAULT 'NOT_ASSESSED',
    assessed_on          date,

    source               text NOT NULL DEFAULT 'REAL_HEALTH_TEST',
    provenance_note      text,

    superseded_by        uuid REFERENCES client_assessments(assessment_id) ON DELETE SET NULL,

    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_completed_needs_date CHECK (
        status <> 'COMPLETED' OR assessed_on IS NOT NULL
    ),
    CONSTRAINT ck_superseded_link CHECK (
        (status = 'SUPERSEDED') = (superseded_by IS NOT NULL)
    ),
    CONSTRAINT ck_no_self_supersede CHECK (superseded_by IS DISTINCT FROM assessment_id)
);

CREATE INDEX idx_assessments_client ON client_assessments (client_id, instrument, assessed_on DESC);
CREATE TRIGGER trg_assessments_updated BEFORE UPDATE ON client_assessments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN client_assessments.payload_schema_version IS
'Layer payloads are JSONB under a versioned header. When RHT field definitions stabilise, bump this and promote hot fields to columns; existing rows stay readable under their own version.';

CREATE TABLE assessment_layers (
    layer_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The invariant: raw signal, derived score and interpretation are
    -- three representations of ONE assessment. They share assessment_id
    -- and must never be counted as independent observations.
    assessment_id  uuid NOT NULL REFERENCES client_assessments(assessment_id) ON DELETE CASCADE,
    layer_type     assessment_layer_type NOT NULL,
    payload        jsonb NOT NULL,
    generated_by   text,
    created_at     timestamptz NOT NULL DEFAULT now(),

    UNIQUE (assessment_id, layer_type)
);

CREATE INDEX idx_layers_payload ON assessment_layers USING gin (payload);

COMMENT ON TABLE assessment_layers IS
'One assessment, up to four typed layers. Engines may read all of them, but every read carries assessment_id so the system cannot mistake one assessment for three corroborating sources.';

-- Engines read this, never the layer table directly. It keeps the four
-- layers welded to a single observation with explicit provenance.
CREATE VIEW v_assessment_package AS
SELECT a.assessment_id,
       a.client_id,
       a.instrument,
       a.instrument_version,
       a.scoring_version,
       a.payload_schema_version,
       a.status,
       a.assessed_on,
       a.source,
       jsonb_object_agg(l.layer_type::text, l.payload)
           FILTER (WHERE l.layer_id IS NOT NULL)          AS layers,
       count(l.layer_id)                                   AS layer_count,
       'SINGLE_ASSESSMENT'::text                           AS observation_cardinality
FROM client_assessments a
LEFT JOIN assessment_layers l ON l.assessment_id = a.assessment_id
GROUP BY a.assessment_id;

COMMENT ON VIEW v_assessment_package IS
'observation_cardinality is a constant reminder in the payload: however many layers are present, this is ONE observation.';

-- Status for an instrument the client may never have taken. Returns
-- NOT_ASSESSED rather than nothing, so absence is explicit in engine input.
CREATE OR REPLACE FUNCTION get_assessment_status(p_client_id uuid, p_instrument assessment_instrument)
RETURNS assessment_status
LANGUAGE sql
STABLE
AS $fn$
    SELECT coalesce(
        (SELECT status FROM client_assessments
          WHERE client_id = p_client_id AND instrument = p_instrument
            AND status <> 'SUPERSEDED'
          ORDER BY assessed_on DESC NULLS LAST LIMIT 1),
        'NOT_ASSESSED'::assessment_status
    );
$fn$;

-- ---------------------------------------------------------------------
-- 3. CASE EVENT SPINE
-- ---------------------------------------------------------------------
-- Engine 6 eventually consumes events rather than being coupled to intake
-- form submissions. Every future source lands here.

CREATE TYPE event_source AS ENUM (
    'CORE_INTAKE', 'CONSULTATION', 'PHONE', 'WHATSAPP', 'EMAIL',
    'PRACTITIONER_OBSERVATION', 'LAB_REPORT', 'FOOD_LOG', 'ASSESSMENT',
    'FOLLOWUP', 'CLIENT_MESSAGE', 'ENGINE_OUTPUT', 'CONNECTED_SOURCE', 'OTHER'
);

CREATE TYPE event_confidence AS ENUM ('CONFIRMED', 'REPORTED', 'INFERRED', 'UNCERTAIN');

CREATE TABLE case_events (
    event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,

    source          event_source NOT NULL,
    occurred_at     timestamptz,          -- when the fact was true / stated
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    reported_by     text,                 -- 'client' | 'practitioner:pd' | 'system:E4'

    raw_text        text,
    structured      jsonb,
    confidence      event_confidence NOT NULL DEFAULT 'REPORTED',
    provenance_note text,

    -- Whether this event actually changed canonical state, and into which
    -- version. Most events are recorded without altering canonical truth.
    altered_canonical_state boolean NOT NULL DEFAULT false,
    case_version_id uuid REFERENCES client_case_versions(case_version_id) ON DELETE SET NULL,

    -- Backlinks so an event can point at what produced it.
    assessment_id   uuid REFERENCES client_assessments(assessment_id) ON DELETE SET NULL,
    run_id          uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,

    CONSTRAINT ck_altered_needs_version CHECK (
        NOT altered_canonical_state OR case_version_id IS NOT NULL
    )
);

CREATE INDEX idx_events_client ON case_events (client_id, recorded_at DESC);
CREATE INDEX idx_events_source ON case_events (client_id, source);

COMMENT ON CONSTRAINT ck_altered_needs_version ON case_events IS
'An event claiming to have changed canonical state must name the version it produced. Otherwise the audit trail has a hole.';

-- ---------------------------------------------------------------------
-- 4. CHAT AND CANDIDATE FACTS
-- ---------------------------------------------------------------------
-- Schema only. No chat UI, no intent router.

CREATE TABLE chat_threads (
    thread_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL means the general practitioner chat: no client attached, and
    -- therefore no client data reachable.
    client_id   uuid REFERENCES clients(client_id) ON DELETE CASCADE,
    title       text,
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_threads_client ON chat_threads (client_id, updated_at DESC);
CREATE TRIGGER trg_threads_updated BEFORE UPDATE ON chat_threads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE chat_messages (
    message_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id   uuid NOT NULL REFERENCES chat_threads(thread_id) ON DELETE CASCADE,
    -- Denormalized for RLS: policies must not need a join to decide access.
    client_id   uuid REFERENCES clients(client_id) ON DELETE CASCADE,
    role        text NOT NULL,            -- 'practitioner' | 'agent' | 'system'
    content     text NOT NULL,
    -- Which engine, if any, answered. Chat is a routing layer over the
    -- same engines, not an eighth engine.
    engine      engine_id,
    run_id      uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_thread ON chat_messages (thread_id, created_at);

-- Keep chat_messages.client_id consistent with its thread, since RLS
-- depends on it.
CREATE OR REPLACE FUNCTION sync_message_client()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    t_client uuid;
BEGIN
    SELECT client_id INTO t_client FROM chat_threads WHERE thread_id = NEW.thread_id;
    IF NEW.client_id IS DISTINCT FROM t_client THEN
        NEW.client_id := t_client;
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_sync_message_client
    BEFORE INSERT OR UPDATE ON chat_messages
    FOR EACH ROW EXECUTE FUNCTION sync_message_client();

-- Conversation never silently becomes canonical truth.
--
-- Extraction confidence says the model heard correctly. It does not say
-- the fact is true, and it does not authorize changing the clinical
-- record. Authorization is a separate axis from confidence.
CREATE TYPE fact_authorization AS ENUM (
    'PRACTITIONER_APPROVAL',           -- reviewed and approved individually
    'EXPLICIT_PRACTITIONER_INSTRUCTION', -- "Save this: ..."
    'TRUSTED_STRUCTURED_INGESTION'     -- Core Intake, RHT, parsed labs
);

CREATE TYPE candidate_fact_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'SUPERSEDED');

CREATE TABLE candidate_facts (
    candidate_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    thread_id       uuid REFERENCES chat_threads(thread_id) ON DELETE SET NULL,
    message_id      uuid REFERENCES chat_messages(message_id) ON DELETE SET NULL,

    extracted_text  text NOT NULL,
    structured      jsonb,
    fact_type       text,
    -- Recorded for triage and ranking only. It can never authorize a write.
    extraction_confidence numeric(4,3),

    status          candidate_fact_status NOT NULL DEFAULT 'PENDING',
    authorization_type fact_authorization,
    approved_by     text,
    decided_at      timestamptz,
    rejection_note  text,

    applied_event_id uuid REFERENCES case_events(event_id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_confidence_range CHECK (
        extraction_confidence IS NULL OR extraction_confidence BETWEEN 0 AND 1
    ),
    -- The load-bearing rule: approval requires a named authorization and a
    -- named actor. There is no confidence threshold that auto-approves.
    CONSTRAINT ck_approval_requires_authorization CHECK (
        status <> 'APPROVED'
        OR (authorization_type IS NOT NULL AND coalesce(btrim(approved_by), '') <> '')
    )
);

CREATE INDEX idx_candidates_pending ON candidate_facts (client_id, created_at)
    WHERE status = 'PENDING';

COMMENT ON CONSTRAINT ck_approval_requires_authorization ON candidate_facts IS
'High extraction confidence does NOT authorize changing canonical client truth. Unlike ontology alias resolution, there is no auto-resolve path here. Ordinary conversation must never silently become clinical record.';

-- Belt and braces: block any attempt to approve citing confidence alone.
CREATE OR REPLACE FUNCTION guard_candidate_fact_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF NEW.status = 'APPROVED' AND coalesce(OLD.status, 'PENDING') <> 'APPROVED' THEN
        IF NEW.authorization_type IS NULL THEN
            RAISE EXCEPTION
                'Candidate fact cannot be approved without an explicit authorization. '
                'Extraction confidence (%) is not authorization.',
                coalesce(NEW.extraction_confidence::text, 'null')
                USING ERRCODE = 'raise_exception';
        END IF;
        IF NEW.approved_by IS NULL OR NEW.approved_by NOT LIKE 'practitioner%'
           AND NEW.authorization_type <> 'TRUSTED_STRUCTURED_INGESTION' THEN
            RAISE EXCEPTION
                'Candidate fact approval requires a practitioner actor or trusted structured ingestion, got %',
                coalesce(NEW.approved_by, 'null')
                USING ERRCODE = 'raise_exception';
        END IF;
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_guard_candidate_fact_approval
    BEFORE INSERT OR UPDATE ON candidate_facts
    FOR EACH ROW EXECUTE FUNCTION guard_candidate_fact_approval();

-- ---------------------------------------------------------------------
-- 5. MISSING DATA REPORTS
-- ---------------------------------------------------------------------
-- Feeds the intake refinement loop. Reporting a gap NEVER adds a question
-- to Core Intake; aggregation and classification are separate, deliberate
-- steps.

CREATE TYPE missing_severity AS ENUM ('CRITICAL', 'HIGH', 'MODERATE', 'LOW');

CREATE TYPE intake_classification AS ENUM (
    'ESSENTIAL', 'USEFUL', 'CONDITIONAL', 'ALREADY_COVERED_BY_RHT',
    'OPTIONAL', 'UNNECESSARY'
);

CREATE TABLE missing_data_reports (
    report_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,
    engine           engine_id NOT NULL,
    client_id        uuid REFERENCES clients(client_id) ON DELETE CASCADE,
    case_version_id  uuid REFERENCES client_case_versions(case_version_id) ON DELETE SET NULL,

    missing_field    text NOT NULL,
    concept_id       uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    why_it_mattered  text,
    severity         missing_severity NOT NULL DEFAULT 'MODERATE',
    -- Did the absence actually constrain reasoning, or was it merely noted?
    constrained_reasoning boolean NOT NULL DEFAULT false,
    -- Would RHT normally supply this? If so, Core Intake must not duplicate it.
    rht_would_supply boolean NOT NULL DEFAULT false,

    resolved         boolean NOT NULL DEFAULT false,
    resolved_note    text,

    -- Populated later, by deliberate human triage. NULL until then.
    -- An engine reporting a gap does not classify it.
    classification   intake_classification,
    classified_by    text,
    classified_at    timestamptz,

    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_missing_field ON missing_data_reports (missing_field, severity);
CREATE INDEX idx_missing_unclassified ON missing_data_reports (created_at)
    WHERE classification IS NULL;

-- Recurrence across clients. This is the input to intake refinement, not
-- an instruction to change intake.
CREATE VIEW v_missing_data_recurrence AS
SELECT missing_field,
       count(*)                                        AS reports,
       count(DISTINCT client_id)                       AS distinct_clients,
       count(*) FILTER (WHERE constrained_reasoning)   AS constrained_reasoning_count,
       bool_or(rht_would_supply)                       AS rht_would_supply,
       array_agg(DISTINCT engine::text ORDER BY engine::text) AS engines,
       max(severity::text)                             AS max_severity,
       (array_agg(DISTINCT classification::text)
          FILTER (WHERE classification IS NOT NULL))[1] AS classification
FROM missing_data_reports
GROUP BY missing_field
ORDER BY count(DISTINCT client_id) DESC, count(*) DESC;

COMMENT ON VIEW v_missing_data_recurrence IS
'Turns "what should we add to intake?" into a query. Classification stays NULL until a human triages. Never ask the client for information merely because an engine can analyse it.';

-- ---------------------------------------------------------------------
-- 6. DRAFT VERSUS DELIVERY
-- ---------------------------------------------------------------------
-- Generating and viewing a draft inside Practitioner Chat is not outbound
-- client communication. Sending it is, and that still passes the gate.

CREATE TYPE communication_status AS ENUM (
    'DRAFT',            -- practitioner-visible only, freely generated
    'PENDING_APPROVAL',
    'APPROVED',
    'RELEASED',         -- delivered to the client
    'DISCARDED'
);

ALTER TABLE client_communications
    ADD COLUMN comm_status communication_status NOT NULL DEFAULT 'DRAFT',
    ADD COLUMN origin text NOT NULL DEFAULT 'WORKFLOW';   -- WORKFLOW | PRACTITIONER_CHAT

-- Backfill from the existing flag before constraining, so rows written
-- before this migration remain valid.
UPDATE client_communications
   SET comm_status = CASE WHEN released THEN 'RELEASED' ELSE 'DRAFT' END::communication_status;

-- Keep the two representations in sync automatically. Requiring every
-- caller to remember both is a trap: n8n, RUN_ENGINE and the future chat
-- layer would each have to get it right, and one of them eventually
-- wouldn't. Setting EITHER field updates the other.
CREATE OR REPLACE FUNCTION sync_communication_status()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.released AND NEW.comm_status <> 'RELEASED' THEN
            NEW.comm_status := 'RELEASED';
        ELSIF NOT NEW.released AND NEW.comm_status = 'RELEASED' THEN
            NEW.released := true;   -- explicit RELEASED status wins; gate still applies
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE: whichever field the caller changed drives the other.
    IF NEW.released IS DISTINCT FROM OLD.released THEN
        NEW.comm_status := CASE WHEN NEW.released THEN 'RELEASED'
                                ELSE 'DRAFT' END::communication_status;
    ELSIF NEW.comm_status IS DISTINCT FROM OLD.comm_status THEN
        NEW.released := (NEW.comm_status = 'RELEASED');
    END IF;
    RETURN NEW;
END $fn$;

-- BEFORE the gate trigger alphabetically, so sync runs first and the gate
-- then evaluates the final value.
CREATE TRIGGER trg_a_sync_communication_status
    BEFORE INSERT OR UPDATE ON client_communications
    FOR EACH ROW EXECUTE FUNCTION sync_communication_status();

ALTER TABLE client_communications
    ADD CONSTRAINT ck_released_matches_status CHECK (
        released = (comm_status = 'RELEASED')
    );

COMMENT ON COLUMN client_communications.comm_status IS
'DRAFT is generation and practitioner viewing. RELEASED is delivery to the client and passes trg_block_unapproved_communication. Generating a draft is never gated; sending always is.';

-- =====================================================================
-- 7. ROW-LEVEL SECURITY
-- =====================================================================
-- Applied to every client-scoped table, old and new. FORCE so that even
-- the table owner is subject: RLS that the owner bypasses is cosmetic.

DO $$
DECLARE
    t text;
    -- Tables carrying client_id directly.
    direct text[] := ARRAY[
        'clients','client_case_versions','case_cycles','client_measurements',
        'client_labs','client_conditions','client_symptoms','client_medications',
        'client_supplements','client_food_logs','client_interventions',
        'client_targets','client_followups','engine_runs','case_flags',
        'practitioner_reviews','client_communications','client_assessments',
        'case_events','chat_threads','chat_messages','candidate_facts',
        'missing_data_reports'
    ];
BEGIN
    FOREACH t IN ARRAY direct LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);

        -- Runtime: default deny. current_client_scope() is NULL when no
        -- context is set, and `client_id = NULL` is never true, so a query
        -- that forgets its WHERE clause returns nothing rather than
        -- everything.
        IF t = 'clients' THEN
            EXECUTE format($p$
                CREATE POLICY %I ON %I FOR ALL TO phi_runtime
                USING (client_id = current_client_scope())
                WITH CHECK (client_id = current_client_scope())
            $p$, 'rls_runtime_' || t, t);
        ELSIF t IN ('chat_threads','chat_messages') THEN
            -- General practitioner chat has client_id NULL and carries no
            -- client data, so it stays readable without a client context.
            EXECUTE format($p$
                CREATE POLICY %I ON %I FOR ALL TO phi_runtime
                USING (client_id IS NULL OR client_id = current_client_scope())
                WITH CHECK (client_id IS NULL OR client_id = current_client_scope())
            $p$, 'rls_runtime_' || t, t);
        ELSE
            EXECUTE format($p$
                CREATE POLICY %I ON %I FOR ALL TO phi_runtime
                USING (client_id = current_client_scope())
                WITH CHECK (client_id = current_client_scope())
            $p$, 'rls_runtime_' || t, t);
        END IF;

        -- The review surface: the one deliberate cross-client read path.
        EXECUTE format($p$
            CREATE POLICY %I ON %I FOR SELECT TO phi_practitioner USING (true)
        $p$, 'rls_practitioner_' || t, t);

        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO phi_runtime', t);
        EXECUTE format('GRANT SELECT ON %I TO phi_practitioner', t);
    END LOOP;
END $$;

-- Tables without a direct client_id reach it through a parent.
ALTER TABLE engine_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE engine_outputs FORCE ROW LEVEL SECURITY;
CREATE POLICY rls_runtime_engine_outputs ON engine_outputs FOR ALL TO phi_runtime
    USING (EXISTS (SELECT 1 FROM engine_runs r
                    WHERE r.run_id = engine_outputs.run_id
                      AND r.client_id = current_client_scope()))
    WITH CHECK (EXISTS (SELECT 1 FROM engine_runs r
                         WHERE r.run_id = engine_outputs.run_id
                           AND r.client_id = current_client_scope()));
CREATE POLICY rls_practitioner_engine_outputs ON engine_outputs FOR SELECT TO phi_practitioner USING (true);

ALTER TABLE assessment_layers ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_layers FORCE ROW LEVEL SECURITY;
CREATE POLICY rls_runtime_assessment_layers ON assessment_layers FOR ALL TO phi_runtime
    USING (EXISTS (SELECT 1 FROM client_assessments a
                    WHERE a.assessment_id = assessment_layers.assessment_id
                      AND a.client_id = current_client_scope()))
    WITH CHECK (EXISTS (SELECT 1 FROM client_assessments a
                         WHERE a.assessment_id = assessment_layers.assessment_id
                           AND a.client_id = current_client_scope()));
CREATE POLICY rls_practitioner_assessment_layers ON assessment_layers FOR SELECT TO phi_practitioner USING (true);

ALTER TABLE client_intervention_exposure ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_intervention_exposure FORCE ROW LEVEL SECURITY;
CREATE POLICY rls_runtime_exposure ON client_intervention_exposure FOR ALL TO phi_runtime
    USING (EXISTS (SELECT 1 FROM client_interventions i
                    WHERE i.intervention_id = client_intervention_exposure.intervention_id
                      AND i.client_id = current_client_scope()))
    WITH CHECK (EXISTS (SELECT 1 FROM client_interventions i
                         WHERE i.intervention_id = client_intervention_exposure.intervention_id
                           AND i.client_id = current_client_scope()));
CREATE POLICY rls_practitioner_exposure ON client_intervention_exposure FOR SELECT TO phi_practitioner USING (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON engine_outputs, assessment_layers,
      client_intervention_exposure TO phi_runtime;
GRANT SELECT ON engine_outputs, assessment_layers,
      client_intervention_exposure TO phi_practitioner;

-- Knowledge is GLOBAL and deliberately not client-scoped. No RLS here:
-- the strategy library, evidence and foods are shared by design.
DO $$
DECLARE
    t text;
    global_tables text[] := ARRAY[
        'concepts','concept_aliases','concept_relations','concept_proposals',
        'normalization_cache','normalization_tests','knowledge_domains',
        'domain_coverage','source_creators','knowledge_sources','source_items',
        'source_documents','knowledge_chunks','claims','evidence_records',
        'strategies','strategy_concepts','strategy_evidence','strategy_claims',
        'strategy_domains','implementation_patterns','controversies',
        'controversy_positions','negative_knowledge','foods','food_seasonality',
        'supplements','knowledge_gaps','knowledge_updates',
        'practice_strategy_outcomes','cost_events','job_runs',
        'dead_letter_jobs','system_capabilities'
    ];
BEGIN
    FOREACH t IN ARRAY global_tables LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO phi_runtime', t);
        EXECUTE format('GRANT SELECT ON %I TO phi_practitioner', t);
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO phi_runtime, phi_practitioner;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO phi_runtime, phi_practitioner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO phi_runtime;

-- Views inherit the invoking user's RLS because they are not created with
-- security_invoker off; they run as the view owner unless declared. Force
-- invoker semantics so a view cannot become an RLS bypass.
ALTER VIEW v_assessment_package SET (security_invoker = true);
ALTER VIEW v_missing_data_recurrence SET (security_invoker = true);
ALTER VIEW v_review_queue SET (security_invoker = true);
ALTER VIEW v_engine_run_health SET (security_invoker = true);

GRANT SELECT ON ALL TABLES IN SCHEMA public TO phi_practitioner;
