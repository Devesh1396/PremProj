-- =====================================================================
-- 006_knowledge_inbox.sql
--
-- Structural foundation for Engine 7 §44-§57 and §25-§26.
--
-- Scope: schema only. No UI, no ingestion pipeline, no adapters. This
-- migration exists so K02-K11 can be built later without a schema
-- retrofit, exactly as 005 did for chat and assessments.
--
-- Governing constraint from the specification (§47, §48, §85):
--   "a new source tomorrow should normally be a data operation, not a
--    software-development event"
-- Therefore source_kind is a REGISTRY TABLE, not an enum. Adding
-- YOUTUBE_SHORT or SUBSTACK_POST next month is an INSERT. Enums are used
-- only where the value set is genuinely stable and safety-bearing
-- (rights context, delta classification, evidence-claim support level).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Extensible source-kind registry  (§48)
-- ---------------------------------------------------------------------

CREATE TABLE source_kinds (
    source_kind      text PRIMARY KEY,
    display_name     text NOT NULL,
    description      text,

    -- Default role for this kind. Never a promotion path: a YOUTUBE_VIDEO
    -- defaulting to DISCOVERY can never be queried as EVIDENCE (§9/§10,
    -- enforced in 003 by source_roles).
    default_role     source_role NOT NULL DEFAULT 'DISCOVERY',

    -- Which acquisition adapter family handles it (§49). Advisory only:
    -- acquisition is provider-independent and the adapter is replaceable.
    adapter_hint     text,

    -- Long-form sources justify chapter/segment-level processing (§16, §42).
    long_form        boolean NOT NULL DEFAULT false,

    -- Set false to retire a kind without deleting historical rows.
    active           boolean NOT NULL DEFAULT true,

    -- true only for the seeded set below; false for kinds added later by
    -- the practitioner or by classification. Lets us tell the original
    -- specification's list from organic growth.
    seeded           boolean NOT NULL DEFAULT false,

    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_source_kind_key CHECK (source_kind ~ '^[A-Z][A-Z0-9_]{1,63}$')
);

COMMENT ON TABLE source_kinds IS
'Registry, deliberately not an enum. Engine 7 §48: future source kinds must be addable without redesigning Engine 7, and §85 forbids depending on the coder having known a source existed at build time. Adding a kind is an INSERT.';

INSERT INTO source_kinds (source_kind, display_name, default_role, adapter_hint, long_form, seeded) VALUES
    ('RESEARCH_PAPER',        'Research paper',              'EVIDENCE',       'PUBMED',      false, true),
    ('SYSTEMATIC_REVIEW',     'Systematic review',           'EVIDENCE',       'PUBMED',      false, true),
    ('GUIDELINE',             'Guideline / consensus',       'DEFINITIONAL',   'WEB_HTTP',    false, true),
    ('CLINICAL_TRIAL_RECORD', 'Clinical trial record',       'EVIDENCE',       'CLINICAL_TRIALS', false, true),
    ('YOUTUBE_VIDEO',         'YouTube video',               'DISCOVERY',      'YOUTUBE',     true,  true),
    ('YOUTUBE_PLAYLIST',      'YouTube playlist',            'DISCOVERY',      'YOUTUBE',     true,  true),
    ('PODCAST',               'Podcast',                     'DISCOVERY',      'PODCAST',     true,  true),
    ('BLOG',                  'Blog',                        'DISCOVERY',      'RSS',         false, true),
    ('NEWSLETTER',            'Newsletter',                  'DISCOVERY',      'RSS',         false, true),
    ('WEB_ARTICLE',           'Web article',                 'DISCOVERY',      'WEB_HTTP',    false, true),
    ('FREE_DIET_PLAN',        'Free diet plan',              'IMPLEMENTATION', 'MANUAL_FILE', false, true),
    ('PAID_PRACTITIONER_PLAN','Paid practitioner plan',      'IMPLEMENTATION', 'MANUAL_FILE', false, true),
    ('PRACTITIONER_HANDOUT',  'Practitioner handout',        'IMPLEMENTATION', 'MANUAL_FILE', false, true),
    ('COURSE_NOTES',          'Course notes',                'IMPLEMENTATION', 'MANUAL_FILE', true,  true),
    ('BOOK',                  'Book',                        'DISCOVERY',      'MANUAL_BOOK', true,  true),
    ('EBOOK',                 'Ebook',                       'DISCOVERY',      'MANUAL_BOOK', true,  true),
    ('PDF',                   'PDF document',                'DISCOVERY',      'MANUAL_FILE', false, true),
    ('RECIPE_COLLECTION',     'Recipe collection',           'IMPLEMENTATION', 'MANUAL_FILE', false, true),
    ('CLINICAL_PROTOCOL',     'Clinical protocol',           'IMPLEMENTATION', 'MANUAL_FILE', false, true),
    ('CONFERENCE_MATERIAL',   'Conference material',         'DISCOVERY',      'MANUAL_FILE', false, true),
    ('MANUAL_UPLOAD',         'Manual upload',               'DISCOVERY',      'KNOWLEDGE_INBOX', false, true),
    ('OTHER',                 'Unclassified',                'DISCOVERY',      'KNOWLEDGE_INBOX', false, true);

-- §48: "Unknown source kinds may initially enter OTHER and be classified
-- by the ingestion pipeline." OTHER must therefore always exist.
CREATE OR REPLACE FUNCTION protect_other_source_kind() RETURNS trigger AS $$
BEGIN
    IF OLD.source_kind = 'OTHER' THEN
        RAISE EXCEPTION
          'source_kind OTHER cannot be removed or deactivated: it is the landing state for '
          'previously unseen source types (Engine 7 section 48).';
    END IF;
    RETURN OLD;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_protect_other_kind BEFORE DELETE ON source_kinds
    FOR EACH ROW EXECUTE FUNCTION protect_other_source_kind();

CREATE OR REPLACE FUNCTION protect_other_kind_active() RETURNS trigger AS $$
BEGIN
    IF OLD.source_kind = 'OTHER' AND NEW.active = false THEN
        RAISE EXCEPTION 'source_kind OTHER cannot be deactivated.';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_protect_other_kind_active BEFORE UPDATE ON source_kinds
    FOR EACH ROW EXECUTE FUNCTION protect_other_kind_active();

-- ---------------------------------------------------------------------
-- Stable enums: rights, processing, delta  (§52, §54, §56)
-- ---------------------------------------------------------------------

-- Safety-bearing and stable. §52. Anything not PUBLIC must never reach a
-- client-facing output.
CREATE TYPE rights_context AS ENUM (
    'PUBLIC',
    'PRIVATE_INTERNAL',
    'PAID_LICENSED_TO_PRACTITIONER',
    'RESTRICTED_INTERNAL'
);

CREATE TYPE envelope_status AS ENUM (
    'RECEIVED', 'DEDUPED', 'RIGHTS_BLOCKED', 'RAW_STORED', 'NORMALIZED',
    'CLASSIFIED', 'EXTRACTED', 'COMPARED', 'SYNTHESIZED', 'COMPLETE',
    'FAILED', 'SKIPPED'
);

-- §54. Exactly the eight states in the specification.
CREATE TYPE delta_classification AS ENUM (
    'ALREADY_KNOWN', 'SUPPORTS_EXISTING', 'IMPLEMENTATION_VARIANT',
    'EXTENDS_EXISTING', 'POTENTIAL_NEW_STRATEGY', 'NEW_CLAIM_REQUIRES_RESEARCH',
    'CONTRADICTS_EXISTING', 'LOW_INFORMATION_GAIN'
);

-- §26. Drug-nutrient claims must not silently become facts.
CREATE TYPE drug_claim_support AS ENUM (
    'LABEL_ESTABLISHED', 'STRONG_HUMAN_EVIDENCE', 'MODERATE_HUMAN_EVIDENCE',
    'LIMITED_INDIRECT_EVIDENCE', 'MECHANISTIC_PLAUSIBILITY',
    'PRACTITIONER_CLAIM', 'UNSUPPORTED', 'CONFLICTING'
);

-- ---------------------------------------------------------------------
-- Generic source envelope  (§46)
-- ---------------------------------------------------------------------

CREATE TABLE source_envelopes (
    envelope_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    source_kind      text NOT NULL REFERENCES source_kinds(source_kind),
    source_role      source_role NOT NULL,
    creator_id       uuid REFERENCES source_creators(creator_id) ON DELETE SET NULL,
    source_id        uuid REFERENCES knowledge_sources(source_id) ON DELETE SET NULL,

    source_title     text,
    source_date      date,
    source_url       text,
    file_type        text,
    mime_type        text,

    rights           rights_context NOT NULL DEFAULT 'PUBLIC',
    rights_note      text,

    -- §50: raw source, normalized content and AI-derived knowledge are three
    -- distinct things. This column locates the untouched original only.
    raw_location     text,
    raw_preserved    boolean NOT NULL DEFAULT false,
    content_hash     text,

    -- §56: same raw source, better extraction later. Neither version is lost.
    source_version   integer NOT NULL DEFAULT 1,
    processing_version text,

    status           envelope_status NOT NULL DEFAULT 'RECEIVED',
    failure_reason   text,

    -- §43: a personal save is not automatically professional knowledge.
    send_to_e7       boolean NOT NULL DEFAULT true,
    personal_note    text,
    topics           text[],

    -- §57: set when duplicate detection matched an existing envelope.
    duplicate_of     uuid REFERENCES source_envelopes(envelope_id) ON DELETE SET NULL,

    ingested_at      timestamptz NOT NULL DEFAULT now(),
    ingestion_provider text,
    processed_at     timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_envelope_not_self_dup CHECK (duplicate_of IS DISTINCT FROM envelope_id),
    CONSTRAINT ck_envelope_version_positive CHECK (source_version >= 1),

    -- §50 is a hard requirement, not a warning: derived knowledge may not
    -- exist without the original it was derived from.
    CONSTRAINT ck_raw_before_derived CHECK (
        status IN ('RECEIVED','DEDUPED','RIGHTS_BLOCKED','FAILED','SKIPPED')
        OR raw_preserved = true
    ),
    CONSTRAINT ck_failure_reason CHECK (
        status <> 'FAILED' OR failure_reason IS NOT NULL
    )
);

-- §57: the same content must not be paid for twice. Scoped to non-duplicates
-- so a superseded row can retain its hash.
CREATE UNIQUE INDEX uq_envelope_hash ON source_envelopes (content_hash)
    WHERE content_hash IS NOT NULL AND duplicate_of IS NULL;
CREATE UNIQUE INDEX uq_envelope_url_version ON source_envelopes (source_url, source_version)
    WHERE source_url IS NOT NULL AND duplicate_of IS NULL;
CREATE INDEX idx_envelope_status  ON source_envelopes (status, ingested_at DESC);
CREATE INDEX idx_envelope_kind    ON source_envelopes (source_kind);
CREATE INDEX idx_envelope_creator ON source_envelopes (creator_id);
CREATE INDEX idx_envelope_rights  ON source_envelopes (rights) WHERE rights <> 'PUBLIC';

CREATE TRIGGER trg_envelopes_updated BEFORE UPDATE ON source_envelopes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN source_envelopes.rights IS
'Engine 7 section 52. Raw non-PUBLIC material is internal learning only and is never reproduced in client output. v_client_safe_sources is the only view that filters on this; nothing else should assume it.';

-- ---------------------------------------------------------------------
-- Delta / newness analysis  (§54, §55)
-- ---------------------------------------------------------------------

CREATE TABLE source_delta_analyses (
    delta_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Monotonic ordering key. now() is transaction-scoped in Postgres, so two
    -- analyses written in one transaction share a timestamp and "latest"
    -- becomes non-deterministic. This makes recency total regardless of clock.
    analysis_seq     bigserial NOT NULL,

    envelope_id      uuid NOT NULL REFERENCES source_envelopes(envelope_id) ON DELETE CASCADE,

    classification   delta_classification NOT NULL,
    rationale        text,

    concepts_extracted                integer NOT NULL DEFAULT 0,
    claims_extracted                  integer NOT NULL DEFAULT 0,
    implementation_patterns_extracted integer NOT NULL DEFAULT 0,

    already_known_count      integer NOT NULL DEFAULT 0,
    extended_existing_count  integer NOT NULL DEFAULT 0,
    genuinely_new_count      integer NOT NULL DEFAULT 0,

    strategies_created  integer NOT NULL DEFAULT 0,
    strategies_updated  integer NOT NULL DEFAULT 0,
    research_required_claims text[],

    safety_items_present    boolean NOT NULL DEFAULT false,
    creator_profile_updated boolean NOT NULL DEFAULT false,

    processing_version text,
    analysed_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_delta_counts_nonneg CHECK (
        concepts_extracted >= 0 AND claims_extracted >= 0
        AND implementation_patterns_extracted >= 0 AND already_known_count >= 0
        AND extended_existing_count >= 0 AND genuinely_new_count >= 0
    ),
    -- A verdict of "nothing new" that simultaneously reports new items is a
    -- bug, not a nuance.
    CONSTRAINT ck_delta_known_consistent CHECK (
        classification <> 'ALREADY_KNOWN' OR genuinely_new_count = 0
    )
);

-- §56: reprocessing produces a new analysis; the old one is retained.
CREATE UNIQUE INDEX uq_delta_envelope_version
    ON source_delta_analyses (envelope_id, coalesce(processing_version,''));
CREATE INDEX idx_delta_classification ON source_delta_analyses (classification, analysis_seq DESC);
CREATE INDEX idx_delta_latest ON source_delta_analyses (envelope_id, analysis_seq DESC);

COMMENT ON TABLE source_delta_analyses IS
'Engine 7 sections 54-55. The information-gain record the practitioner sees after adding a source. Rows are appended per processing version, never overwritten.';

-- ---------------------------------------------------------------------
-- Source -> derived knowledge links  (§17 claim pipeline)
-- ---------------------------------------------------------------------

CREATE TYPE derived_kind AS ENUM (
    'CLAIM', 'STRATEGY', 'IMPLEMENTATION_PATTERN', 'EVIDENCE',
    'CONCEPT_PROPOSAL', 'FOOD', 'SUPPLEMENT', 'CONTROVERSY', 'NEGATIVE_KNOWLEDGE'
);

CREATE TABLE envelope_derived_records (
    envelope_id   uuid NOT NULL REFERENCES source_envelopes(envelope_id) ON DELETE CASCADE,
    derived_kind  derived_kind NOT NULL,
    derived_id    uuid NOT NULL,

    -- §17: the source of the idea and the source of the scientific evidence
    -- must remain distinguishable. true means this envelope surfaced the
    -- idea; it does not mean the envelope evidences it.
    discovery_only boolean NOT NULL DEFAULT true,
    processing_version text,
    created_at    timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (envelope_id, derived_kind, derived_id)
);

CREATE INDEX idx_derived_lookup ON envelope_derived_records (derived_kind, derived_id);

COMMENT ON TABLE envelope_derived_records IS
'Polymorphic provenance edge from a source envelope to everything derived from it. Deliberately not a set of typed FKs: derived_kind grows with the knowledge model, and a rigid FK set would make that a migration each time.';

-- ---------------------------------------------------------------------
-- Medication-context knowledge  (§25, §26)
-- ---------------------------------------------------------------------
-- Knowledge-side only. This is the library's understanding of a drug, and
-- is distinct from client_medications in 004, which is what one client
-- actually takes.

CREATE TABLE medication_knowledge (
    medication_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generic_name     text NOT NULL,
    normalized_name  text GENERATED ALWAYS AS (norm_phrase(generic_name)) STORED,
    drug_class       text,
    rxnorm_code      text,
    atc_code         text,

    indication       text,
    mechanism        text,
    monitoring       text,
    important_adverse_effects text,
    contraindications text,

    -- §25: nutrition and exercise implications, and when to involve the
    -- prescriber. Never an instruction to change a prescription.
    nutrition_implications text,
    exercise_implications  text,
    coordination_triggers  text,

    source_name      text,
    source_version   text,
    source_date      date,
    knowledge_status knowledge_status NOT NULL DEFAULT 'EXTRACTED_UNVERIFIED',

    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz,

    CONSTRAINT ck_med_name_nonempty CHECK (length(trim(generic_name)) > 0)
);

CREATE UNIQUE INDEX uq_medication_normalized ON medication_knowledge (normalized_name);
CREATE UNIQUE INDEX uq_medication_rxnorm ON medication_knowledge (rxnorm_code)
    WHERE rxnorm_code IS NOT NULL;

CREATE TRIGGER trg_medication_updated BEFORE UPDATE ON medication_knowledge
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE medication_knowledge IS
'Engine 7 section 25. Library knowledge about a drug, not a client prescription. Exists so Engine 1 can reason about medication context and identify when prescriber coordination is warranted. No engine may ever instruct a client to start, stop, reduce or increase a prescription.';

-- §25: brand aliases only when reliably verified.
CREATE TABLE medication_aliases (
    alias_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_id uuid NOT NULL REFERENCES medication_knowledge(medication_id) ON DELETE CASCADE,
    alias         text NOT NULL,
    normalized_alias text GENERATED ALWAYS AS (norm_phrase(alias)) STORED,
    alias_kind    text NOT NULL DEFAULT 'BRAND',
    verified      boolean NOT NULL DEFAULT false,
    verified_source text,
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_alias_verified_has_source CHECK (verified = false OR verified_source IS NOT NULL)
);

CREATE UNIQUE INDEX uq_med_alias ON medication_aliases (normalized_alias, medication_id);
CREATE INDEX idx_med_alias_lookup ON medication_aliases (normalized_alias) WHERE verified;

-- §26: "Drug X depletes nutrient Y" is a claim with a support level, never
-- an automatic fact.
CREATE TABLE drug_nutrient_claims (
    claim_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_id uuid NOT NULL REFERENCES medication_knowledge(medication_id) ON DELETE CASCADE,
    concept_id    uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    nutrient_name text NOT NULL,
    claim_text    text NOT NULL,

    support_level drug_claim_support NOT NULL,
    evidence_note text,
    provenance    text,

    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),

    -- Anything asserted at or above moderate human evidence must say where
    -- it came from. Mirrors ck_provenance_required in 003.
    CONSTRAINT ck_drug_claim_provenance CHECK (
        support_level IN ('PRACTITIONER_CLAIM','UNSUPPORTED','CONFLICTING',
                          'MECHANISTIC_PLAUSIBILITY','LIMITED_INDIRECT_EVIDENCE')
        OR provenance IS NOT NULL
    )
);

CREATE INDEX idx_drug_nutrient_med ON drug_nutrient_claims (medication_id);
CREATE TRIGGER trg_drug_claim_updated BEFORE UPDATE ON drug_nutrient_claims
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- Run clock coherence  (control contract CASE_VERSION = 0)
-- ---------------------------------------------------------------------
-- A run is either on the case clock (a client and a case) or the knowledge
-- clock (neither). Half-populated rows are the state that would let a
-- knowledge run be read as a case run.

ALTER TABLE engine_runs
    ADD CONSTRAINT ck_run_clock_coherent CHECK (
        (client_id IS NOT NULL)
        OR (case_version_id IS NULL AND cycle_id IS NULL)
    );

COMMENT ON CONSTRAINT ck_run_clock_coherent ON engine_runs IS
'A knowledge-clock run (Engine 7 FOUNDATION/UPDATE/INBOX, control block CASE_VERSION = 0) has no client, and therefore may not carry a case version or cycle. Enforces the two-clock separation at insert.';

CREATE VIEW v_engine_run_clock AS
SELECT
    r.run_id,
    r.engine,
    r.pass,
    r.status,
    r.prompt_file,
    r.prompt_hash,
    r.model_name,
    CASE WHEN r.client_id IS NULL THEN 'KNOWLEDGE' ELSE 'CASE' END AS run_clock,
    r.client_id,
    v.case_version,
    r.created_at,
    r.completed_at
FROM engine_runs r
LEFT JOIN client_case_versions v ON v.case_version_id = r.case_version_id;

COMMENT ON VIEW v_engine_run_clock IS
'Reporting split between the two clocks. case_version is NULL for knowledge-clock runs - never 0, because 0 is a control-block wire value and not a stored case version.';

-- ---------------------------------------------------------------------
-- Practitioner-facing views  (§45, §55)
-- ---------------------------------------------------------------------

CREATE VIEW v_ingestion_status AS
SELECT
    e.envelope_id,
    e.source_title,
    e.source_kind,
    k.display_name  AS source_kind_name,
    e.source_role,
    e.rights,
    e.status,
    e.failure_reason,
    e.duplicate_of IS NOT NULL AS is_duplicate,
    e.raw_preserved,
    e.source_version,
    e.processing_version,
    c.name          AS creator_name,
    d.classification AS delta_classification,
    d.concepts_extracted,
    d.claims_extracted,
    d.implementation_patterns_extracted,
    d.already_known_count,
    d.extended_existing_count,
    d.genuinely_new_count,
    d.safety_items_present,
    e.ingested_at,
    e.processed_at
FROM source_envelopes e
JOIN source_kinds k ON k.source_kind = e.source_kind
LEFT JOIN source_creators c ON c.creator_id = e.creator_id
LEFT JOIN LATERAL (
    SELECT * FROM source_delta_analyses da
    WHERE da.envelope_id = e.envelope_id
    ORDER BY da.analysis_seq DESC LIMIT 1
) d ON true;

COMMENT ON VIEW v_ingestion_status IS
'Engine 7 sections 45 and 55: the practitioner-facing receipt. What arrived, whether it was a duplicate, and what information gain it produced.';

-- §52: the only place rights filtering belongs. Nothing else may assume it.
CREATE VIEW v_client_safe_sources AS
SELECT envelope_id, source_title, source_url, source_kind, source_role
FROM source_envelopes
WHERE rights = 'PUBLIC' AND duplicate_of IS NULL;

COMMENT ON VIEW v_client_safe_sources IS
'Engine 7 section 52. Purchased and private material may be learned from internally but never reproduced or cited in client-facing output. Client-facing paths read this view, not source_envelopes.';
