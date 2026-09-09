-- 003_knowledge.sql
-- The knowledge library.
--
-- Not a folder of disease articles. A connected multidimensional store in
-- which knowledge is retrievable by physiology, biomarker, symptom, driver,
-- outcome, population, geography and season, so that it transfers across
-- conditions rather than sitting in per-disease silos.
--
-- The join that makes this work is strategy_concepts -> concepts (002).
-- Without it, retrieval degrades to disease-name matching.

-- =====================================================================
-- Types
-- =====================================================================

CREATE TYPE domain_type AS ENUM (
    'CONDITION', 'PHYSIOLOGY', 'BIOMARKER', 'SYMPTOM', 'NUTRIENT', 'FOOD',
    'EXERCISE', 'BEHAVIOUR', 'POPULATION', 'OUTCOME', 'INTERVENTION_FAMILY',
    'GEOGRAPHY', 'SEASONALITY', 'SUPPLEMENT', 'TRADITIONAL', 'OTHER'
);

-- No COMPLETE. Health knowledge is never finished.
CREATE TYPE foundation_status AS ENUM (
    'NOT_STARTED', 'DISCOVERY', 'EARLY_FOUNDATION', 'MODERATE_FOUNDATION',
    'FOUNDATION_READY', 'DEEP_COVERAGE', 'REVIEW_DUE'
);

CREATE TYPE creator_type AS ENUM (
    'RESEARCHER', 'CLINICIAN', 'SPECIALIST_CLINICIAN', 'PRACTITIONER',
    'COACH', 'AUTHOR', 'ORGANIZATION', 'RESEARCH_GROUP', 'TRADITIONAL_SOURCE', 'OTHER'
);

CREATE TYPE source_type AS ENUM (
    'JOURNAL', 'PUBMED', 'PREPRINT', 'WEBSITE', 'BLOG', 'BOOK', 'PODCAST',
    'VIDEO_CHANNEL', 'NEWSLETTER', 'GUIDELINE', 'TRADITIONAL_TEXT',
    'CONFERENCE', 'PRACTITIONER_FRAMEWORK', 'OTHER'
);

-- The distinction the whole epistemics rests on. A podcast can introduce an
-- excellent intervention; that does not make the podcast the evidence.
CREATE TYPE source_role AS ENUM (
    'DISCOVERY',        -- may surface an idea worth investigating
    'EVIDENCE',         -- may support an efficacy estimate
    'IMPLEMENTATION',   -- practical execution knowledge
    'DEFINITIONAL',     -- diagnostic criteria, thresholds, safety context
    'TRADITIONAL',      -- longstanding use, recorded as use not as proof
    'FOOD_DATA'         -- composition, availability, seasonality
);

CREATE TYPE ingestion_status AS ENUM (
    'DISCOVERED', 'QUEUED', 'FETCHED', 'NORMALIZED', 'EXTRACTED',
    'FULL_TEXT_NOT_AVAILABLE', 'ACCESS_DENIED', 'FAILED', 'SKIPPED'
);

-- AI_DISCOVERED_CANDIDATE must never silently become VERIFIED.
CREATE TYPE knowledge_status AS ENUM (
    'AI_DISCOVERED_CANDIDATE',
    'EXTRACTED_UNVERIFIED',
    'PRACTITIONER_CLAIM_UNVERIFIED',
    'EVIDENCE_LINKED',
    'VERIFIED',
    'CONTESTED',
    'DEPRECATED'
);

CREATE TYPE evidence_confidence AS ENUM (
    'STRONG', 'MODERATE', 'LIMITED', 'MECHANISTIC_ONLY',
    'CONFLICTING', 'INSUFFICIENT', 'UNKNOWN'
);

CREATE TYPE study_design AS ENUM (
    'SYSTEMATIC_REVIEW', 'META_ANALYSIS', 'RCT', 'CONTROLLED_TRIAL',
    'CROSSOVER', 'PROSPECTIVE_COHORT', 'RETROSPECTIVE_COHORT',
    'CASE_CONTROL', 'CROSS_SECTIONAL', 'CASE_SERIES', 'MECHANISTIC',
    'ANIMAL', 'IN_VITRO', 'GUIDELINE', 'CONSENSUS', 'OTHER'
);

CREATE TYPE strategy_evidence_relation AS ENUM (
    'SUPPORTS', 'PARTIALLY_SUPPORTS', 'LIMITS', 'CONFLICTS', 'NEUTRAL', 'CONTEXTUALIZES'
);

CREATE TYPE concept_link_role AS ENUM (
    'TARGETS',          -- strategy acts on this physiology/biomarker/outcome
    'INDICATED_FOR',    -- relevant condition or symptom
    'POPULATION',       -- applicability
    'MECHANISM',
    'CONTRAINDICATED',
    'REQUIRES_CONTEXT'  -- geography, season, medication context
);

-- =====================================================================
-- Domains
-- =====================================================================

CREATE TABLE knowledge_domains (
    domain_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL,
    domain_key       text NOT NULL,
    parent_domain_id uuid REFERENCES knowledge_domains(domain_id) ON DELETE SET NULL,
    domain_type      domain_type NOT NULL,
    description      text,

    -- Wave-1 processing priority only. Never a boundary on what Engine 7
    -- may discover; autonomous expansion continues regardless.
    wave1_priority   integer NOT NULL DEFAULT 0,
    is_core_domain   boolean NOT NULL DEFAULT false,

    status           foundation_status NOT NULL DEFAULT 'NOT_STARTED',
    -- Set by K01 when it expands a seed area into subdomains.
    discovered_by    text,
    active           boolean NOT NULL DEFAULT true,

    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz,
    next_review      timestamptz,

    CONSTRAINT ck_domain_key CHECK (domain_key ~ '^[A-Z][A-Z0-9_]{2,79}$'),
    CONSTRAINT ck_domain_no_self_parent CHECK (parent_domain_id IS DISTINCT FROM domain_id)
);

CREATE UNIQUE INDEX uq_domain_key ON knowledge_domains (domain_key) WHERE active;
CREATE INDEX idx_domain_parent   ON knowledge_domains (parent_domain_id);
CREATE INDEX idx_domain_priority ON knowledge_domains (wave1_priority DESC, status)
    WHERE active;

CREATE TRIGGER trg_domains_updated BEFORE UPDATE ON knowledge_domains
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The 19 domain-depth dimensions. A domain reaching roughly 14 of 19 is
-- FOUNDATION_READY. Tracked as rows so readiness is computable, not a
-- judgement call.
CREATE TYPE coverage_dimension AS ENUM (
    'PHYSIOLOGY', 'MODIFIABLE_DRIVERS', 'BIOMARKERS', 'SYMPTOMS_FUNCTION',
    'DESIRED_OUTCOMES', 'INTERVENTION_FAMILIES', 'NUTRITION_STRATEGIES',
    'EXERCISE_STRATEGIES', 'BEHAVIOUR_STRATEGIES', 'SUPPLEMENT_STRATEGIES',
    'FOOD_DELIVERY', 'FUNCTIONAL_TRADITIONAL', 'HUMAN_EVIDENCE',
    'CONTROVERSIES', 'NEGATIVE_KNOWLEDGE', 'IMPLEMENTATION',
    'POPULATION_APPLICABILITY', 'MEASUREMENT', 'KNOWLEDGE_GAPS'
);

CREATE TABLE domain_coverage (
    domain_id     uuid NOT NULL REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    dimension     coverage_dimension NOT NULL,
    covered       boolean NOT NULL DEFAULT false,
    item_count    integer NOT NULL DEFAULT 0,
    note          text,
    assessed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_id, dimension)
);

-- =====================================================================
-- Sources
-- =====================================================================

CREATE TABLE source_creators (
    creator_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL,
    creator_type     creator_type NOT NULL,
    background       text,
    primary_domains  text[],
    -- Why this creator entered the library. Popularity is never the reason.
    discovery_reason text,
    notes            text,
    claims_requiring_caution text,
    monitor_status   boolean NOT NULL DEFAULT false,
    discovered_date  timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz
);

CREATE INDEX idx_creators_monitor ON source_creators (monitor_status) WHERE monitor_status;
CREATE INDEX idx_creators_name    ON source_creators (lower(name));

COMMENT ON COLUMN source_creators.discovery_reason IS
'Populated by K02/K03 discovery, e.g. "repeated author across 4 systematic reviews in hepatic fat". Popularity is never a discovery reason and never evidence quality.';

CREATE TABLE knowledge_sources (
    source_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name      text NOT NULL,
    source_type      source_type NOT NULL,
    -- A source may serve several roles: a researcher's blog can be both
    -- DISCOVERY and IMPLEMENTATION without being EVIDENCE.
    source_roles     source_role[] NOT NULL DEFAULT '{DISCOVERY}',
    base_identifier  text,
    creator_id       uuid REFERENCES source_creators(creator_id) ON DELETE SET NULL,
    access_method    text,
    monitor_status   boolean NOT NULL DEFAULT false,
    last_checked     timestamptz,
    -- Set false to retire a source without deleting its history.
    active           boolean NOT NULL DEFAULT true,
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_source_roles_nonempty CHECK (cardinality(source_roles) > 0)
);

CREATE UNIQUE INDEX uq_source_identifier ON knowledge_sources (base_identifier)
    WHERE base_identifier IS NOT NULL AND active;
CREATE INDEX idx_sources_monitor ON knowledge_sources (monitor_status, last_checked)
    WHERE monitor_status AND active;

CREATE TABLE source_items (
    item_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        uuid REFERENCES knowledge_sources(source_id) ON DELETE SET NULL,
    title            text,
    authors          text[],
    publication_date date,
    url              text,
    doi              text,
    pmid             text,
    external_id      text,
    content_hash     text,
    ingestion_status ingestion_status NOT NULL DEFAULT 'DISCOVERED',
    access_note      text,

    -- Evaluation layer B. Held-out items are ingested and extracted but
    -- excluded from strategy synthesis, so retrieval can be measured
    -- against knowledge the library was not tuned around.
    held_out         boolean NOT NULL DEFAULT false,
    held_out_batch   text,

    first_seen       timestamptz NOT NULL DEFAULT now(),
    last_seen        timestamptz NOT NULL DEFAULT now()
);

-- Deduplication signals. Partial unique indexes so nulls do not collide.
CREATE UNIQUE INDEX uq_item_doi  ON source_items (lower(doi))  WHERE doi  IS NOT NULL;
CREATE UNIQUE INDEX uq_item_pmid ON source_items (pmid)        WHERE pmid IS NOT NULL;
CREATE UNIQUE INDEX uq_item_url  ON source_items (url)         WHERE url  IS NOT NULL;
CREATE UNIQUE INDEX uq_item_hash ON source_items (content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX idx_items_status   ON source_items (ingestion_status, first_seen);
CREATE INDEX idx_items_held_out ON source_items (held_out_batch) WHERE held_out;

COMMENT ON COLUMN source_items.held_out IS
'Evaluation layer B. Excluded from strategy synthesis so its strategies form an answer key. Testing against fully synthesised material measures index integrity, not retrieval quality.';

CREATE TABLE source_documents (
    document_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id        uuid NOT NULL REFERENCES source_items(item_id) ON DELETE CASCADE,
    document_type  text,
    text_location  text,           -- chapter, section, timestamp
    content_hash   text,
    language       text DEFAULT 'en',
    word_count     integer,
    -- Derived structured knowledge is the product. Verbatim copyrighted
    -- text is not retained beyond what is necessary.
    excerpt_only   boolean NOT NULL DEFAULT true,
    license_note   text,
    ingestion_date timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_item ON source_documents (item_id);

CREATE TABLE knowledge_chunks (
    chunk_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    text         text NOT NULL,
    metadata     jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_chunks_fts ON knowledge_chunks USING gin (to_tsvector('english', text));

-- =====================================================================
-- Claims and evidence
-- =====================================================================

CREATE TABLE claims (
    claim_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         uuid REFERENCES source_items(item_id) ON DELETE SET NULL,
    creator_id      uuid REFERENCES source_creators(creator_id) ON DELETE SET NULL,
    claim_text      text NOT NULL,
    claim_type      text,
    target          text,
    mechanism       text,
    context         text,
    -- A claim is what someone asserted. It is never merged into evidence.
    evidence_referenced_by_source text,
    independent_evidence_findings text,
    current_interpretation        text,
    areas_supported               text,
    areas_overstated              text,
    areas_uncertain               text,
    extraction_confidence numeric(4,3),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_claims_item    ON claims (item_id);
CREATE INDEX idx_claims_creator ON claims (creator_id);

CREATE TABLE evidence_records (
    evidence_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id          uuid REFERENCES source_items(item_id) ON DELETE SET NULL,
    citation         text,
    publication_year integer,
    design           study_design NOT NULL,
    population       text,
    sample_size      integer,
    intervention     text,
    comparator       text,
    exposure         text,
    duration         text,
    outcomes         text,
    results_summary  text,
    magnitude_summary text,
    limitations      text,
    applicability    text,
    funding_conflict_notes text,
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_pub_year CHECK (
        publication_year IS NULL
        OR publication_year BETWEEN 1800 AND extract(year FROM now())::int + 1
    )
);

CREATE INDEX idx_evidence_design ON evidence_records (design, publication_year DESC);
CREATE INDEX idx_evidence_item   ON evidence_records (item_id);

COMMENT ON CONSTRAINT ck_pub_year ON evidence_records IS
'Quality control: impossible publication dates are a known extraction failure mode.';

-- =====================================================================
-- Strategies — the main intervention library
-- =====================================================================

CREATE TABLE strategies (
    strategy_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL,
    canonical_key    text,
    aliases          text[],
    summary          text,

    intervention_category text,
    mechanism             text,
    practical_implementation text,

    dose_or_exposure  text,
    frequency         text,
    duration          text,
    timeframe         text,

    expected_effect_direction text,
    expected_magnitude_summary text,

    evidence_summary     text,
    evidence_confidence  evidence_confidence NOT NULL DEFAULT 'UNKNOWN',
    limitations          text,
    adverse_effects      text,
    interactions         text,
    contraindication_context text,

    cost_context      text,
    complexity        text,
    adherence_context text,
    geography_context text,
    seasonality_context text,
    alternatives      text,
    outcomes_to_track text,

    knowledge_status  knowledge_status NOT NULL DEFAULT 'AI_DISCOVERED_CANDIDATE',

    -- Provenance is mandatory for anything past candidate status. Enforced
    -- below by ck_provenance_required.
    provenance_note   text,

    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    last_reviewed     timestamptz,
    next_review       timestamptz,

    CONSTRAINT ck_strategy_key CHECK (
        canonical_key IS NULL OR canonical_key ~ '^[A-Z][A-Z0-9_]{2,79}$'
    ),
    -- Unattributed model output cannot become permanent authoritative
    -- library content.
    CONSTRAINT ck_provenance_required CHECK (
        knowledge_status = 'AI_DISCOVERED_CANDIDATE'
        OR (provenance_note IS NOT NULL AND length(btrim(provenance_note)) > 0)
    )
);

CREATE UNIQUE INDEX uq_strategy_key ON strategies (canonical_key)
    WHERE canonical_key IS NOT NULL AND knowledge_status <> 'DEPRECATED';
CREATE INDEX idx_strategies_status ON strategies (knowledge_status);
CREATE INDEX idx_strategies_review ON strategies (next_review)
    WHERE next_review IS NOT NULL;
CREATE INDEX idx_strategies_fts    ON strategies
    USING gin (to_tsvector('english',
        name || ' ' || coalesce(summary,'') || ' ' || coalesce(mechanism,'')));

CREATE TRIGGER trg_strategies_updated BEFORE UPDATE ON strategies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON CONSTRAINT ck_provenance_required ON strategies IS
'A strategy past candidate status must answer: where did this come from? Database-enforced, not prompt-enforced.';

-- ---------------------------------------------------------------------
-- The join to the ontology. This is what makes cross-condition retrieval
-- possible: a strategy is reachable by the physiology it targets, not only
-- by the disease it was filed under.
-- ---------------------------------------------------------------------
CREATE TABLE strategy_concepts (
    strategy_id  uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    concept_id   uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    link_role    concept_link_role NOT NULL,
    weight       numeric(4,3) NOT NULL DEFAULT 1.0,
    note         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, concept_id, link_role),
    CONSTRAINT ck_link_weight CHECK (weight BETWEEN 0 AND 1)
);

CREATE INDEX idx_strategy_concepts_concept ON strategy_concepts (concept_id, link_role);

COMMENT ON TABLE strategy_concepts IS
'The retrieval spine. Engine 1 prose is normalized to concepts (002), then joined here. Without this table retrieval collapses to disease-name matching.';

CREATE TABLE strategy_evidence (
    strategy_id   uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    evidence_id   uuid NOT NULL REFERENCES evidence_records(evidence_id) ON DELETE CASCADE,
    relationship  strategy_evidence_relation NOT NULL,
    note          text,
    PRIMARY KEY (strategy_id, evidence_id, relationship)
);

CREATE INDEX idx_strategy_evidence_ev ON strategy_evidence (evidence_id);

CREATE TABLE strategy_claims (
    strategy_id uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    claim_id    uuid NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    note        text,
    PRIMARY KEY (strategy_id, claim_id)
);

CREATE TABLE strategy_domains (
    strategy_id uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    domain_id   uuid NOT NULL REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    PRIMARY KEY (strategy_id, domain_id)
);

CREATE TABLE implementation_patterns (
    pattern_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id      uuid REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    intervention     text,
    target           text,
    client_context   text,
    practical_method text,
    required_preparation text,
    common_barriers  text,
    behavioural_solutions text,
    low_cost_option  text,
    time_saving_option text,
    cultural_adaptation text,
    travel_version   text,
    failure_modes    text,
    -- Implementation knowledge may legitimately come from experienced
    -- practitioners rather than trials. Source role is always labelled.
    derived_from_role source_role NOT NULL DEFAULT 'IMPLEMENTATION',
    provenance_note  text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz
);

CREATE INDEX idx_impl_strategy ON implementation_patterns (strategy_id);

-- =====================================================================
-- Controversies and negative knowledge
-- =====================================================================

CREATE TABLE controversies (
    controversy_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question         text NOT NULL,
    summary          text,
    why_studies_disagree text,
    population_differences text,
    current_consensus text,
    current_uncertainty text,
    practical_interpretation text,
    domain_id        uuid REFERENCES knowledge_domains(domain_id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz
);

CREATE TABLE controversy_positions (
    position_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    controversy_id  uuid NOT NULL REFERENCES controversies(controversy_id) ON DELETE CASCADE,
    position        text NOT NULL,
    evidence_summary text,
    population_context text,
    held_by         text
);

CREATE INDEX idx_positions_controversy ON controversy_positions (controversy_id);

CREATE TABLE negative_knowledge (
    negative_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_or_strategy text NOT NULL,
    strategy_id      uuid REFERENCES strategies(strategy_id) ON DELETE SET NULL,
    domain_id        uuid REFERENCES knowledge_domains(domain_id) ON DELETE SET NULL,
    why_investigated text,
    evidence_examined text,
    finding          text NOT NULL,
    current_interpretation text,
    revisit_trigger  text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_reviewed    timestamptz
);

COMMENT ON TABLE negative_knowledge IS
'Prevents repeated wasted research. Does not accumulate from ingestion naturally: populated by dedicated per-domain passes (K12) once evidence has accumulated.';

-- =====================================================================
-- Food and supplements
-- =====================================================================

CREATE TABLE foods (
    food_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name  text NOT NULL,
    regional_names  text[],
    food_type       text,
    category        text,
    nutrition_profile jsonb,
    key_compounds   text,
    realistic_serving text,
    potential_purposes text,
    preparation     text,
    bioavailability text,
    substitutes_by_purpose text,
    evidence_note   text,
    limitations     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_reviewed   timestamptz
);

CREATE UNIQUE INDEX uq_food_name ON foods (lower(canonical_name));
CREATE INDEX idx_foods_regional ON foods USING gin (regional_names);

CREATE TABLE food_seasonality (
    seasonality_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    food_id        uuid NOT NULL REFERENCES foods(food_id) ON DELETE CASCADE,
    country        text NOT NULL,
    region         text,
    month_start    integer,
    month_end      integer,
    availability   text,
    -- Availability varies by market and year. Never asserted as exact.
    confidence     text NOT NULL DEFAULT 'APPROXIMATE',
    substitute_purpose text,
    notes          text,

    CONSTRAINT ck_month_start CHECK (month_start IS NULL OR month_start BETWEEN 1 AND 12),
    CONSTRAINT ck_month_end   CHECK (month_end   IS NULL OR month_end   BETWEEN 1 AND 12)
);

CREATE INDEX idx_seasonality_lookup ON food_seasonality (country, region, month_start, month_end);

COMMENT ON COLUMN food_seasonality.confidence IS
'Engine 3 may mark VERIFY LOCALLY. The system does not claim exact market availability unless data supports it.';

CREATE TABLE supplements (
    supplement_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    chemical_forms  text[],
    typical_dietary_exposure text,
    therapeutic_exposure     text,
    mechanism       text,
    evidence_summary text,
    evidence_confidence evidence_confidence NOT NULL DEFAULT 'UNKNOWN',
    adverse_effects text,
    interactions    text,
    contraindications text,
    cost_context    text,
    provenance_note text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_reviewed   timestamptz
);

CREATE UNIQUE INDEX uq_supplement_name ON supplements (lower(name));

COMMENT ON COLUMN supplements.therapeutic_exposure IS
'Deliberately separate from typical_dietary_exposure. Reaching a therapeutic dose is a different intervention from dietary inclusion, and the distinction must survive into Engine 3.';

-- =====================================================================
-- Gaps, versioning, practice experience
-- =====================================================================

CREATE TABLE knowledge_gaps (
    gap_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question     text NOT NULL,
    domain_id    uuid REFERENCES knowledge_domains(domain_id) ON DELETE SET NULL,
    importance   integer NOT NULL DEFAULT 0,
    status       text NOT NULL DEFAULT 'OPEN',
    resolution   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);

CREATE INDEX idx_gaps_open ON knowledge_gaps (importance DESC, created_at)
    WHERE status = 'OPEN';

-- Evidence changes are never silent overwrites.
CREATE TABLE knowledge_updates (
    update_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type  text NOT NULL,
    entity_id    uuid NOT NULL,
    old_state    jsonb,
    new_state    jsonb,
    reason       text NOT NULL,
    triggered_by text,
    changed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_updates_entity ON knowledge_updates (entity_type, entity_id, changed_at DESC);

-- Internal practice experience. Structurally separate from
-- evidence_records: there is no foreign key between them and no view joins
-- them, so aggregated observation can never be presented as trial evidence.
CREATE TABLE practice_strategy_outcomes (
    practice_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id      uuid REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    cohort_criteria  text NOT NULL,
    n_clients        integer NOT NULL,
    adherence_summary text,
    outcome_summary  text,
    outcome_range    text,
    drop_out         text,
    common_side_effects text,
    common_failure_reasons text,
    implementation_acceptance text,
    period_start     date,
    period_end       date,
    created_at       timestamptz NOT NULL DEFAULT now(),

    -- Below this the aggregate is not surfaced at all.
    CONSTRAINT ck_min_cohort CHECK (n_clients >= 5)
);

COMMENT ON TABLE practice_strategy_outcomes IS
'INTERNAL PRACTICE EXPERIENCE. De-identified aggregates only. Never merged with evidence_records and always returned to engines as a separately labelled block. Minimum cohort enforced by ck_min_cohort.';

-- =====================================================================
-- Views
-- =====================================================================

-- Domain readiness, computed. Roughly 14 of 19 dimensions covered.
CREATE VIEW v_domain_readiness AS
SELECT d.domain_id,
       d.domain_key,
       d.name,
       d.is_core_domain,
       d.status,
       count(*) FILTER (WHERE c.covered)              AS dimensions_covered,
       19                                              AS dimensions_total,
       (count(*) FILTER (WHERE c.covered)) >= 14       AS meets_depth_bar,
       -- Cast to text[]: drivers do not know custom enum types and return
       -- an enum array as an unparsed literal string. n8n hits this too.
       array_agg(c.dimension::text ORDER BY c.dimension)
           FILTER (WHERE NOT c.covered)                AS missing_dimensions
FROM knowledge_domains d
LEFT JOIN domain_coverage c ON c.domain_id = d.domain_id
WHERE d.active
GROUP BY d.domain_id, d.domain_key, d.name, d.is_core_domain, d.status;

-- Wave-1 floors as live instrumentation, not targets to hit.
CREATE VIEW v_knowledge_floors AS
SELECT 'strategy_cards' AS metric,
       (SELECT count(*) FROM strategies
         WHERE knowledge_status NOT IN ('AI_DISCOVERED_CANDIDATE','DEPRECATED')) AS current,
       750 AS floor_low, 1500 AS floor_high
UNION ALL SELECT 'evidence_records', (SELECT count(*) FROM evidence_records), 2000, 5000
UNION ALL SELECT 'implementation_patterns', (SELECT count(*) FROM implementation_patterns), 150, NULL
UNION ALL SELECT 'food_records', (SELECT count(*) FROM foods), 300, NULL
UNION ALL SELECT 'seasonality_links', (SELECT count(*) FROM food_seasonality), 150, NULL
UNION ALL SELECT 'source_profiles', (SELECT count(*) FROM source_creators), 50, NULL
UNION ALL SELECT 'controversies', (SELECT count(*) FROM controversies), 25, NULL
UNION ALL SELECT 'negative_knowledge', (SELECT count(*) FROM negative_knowledge), 50, NULL;

-- Provenance acceptance: verified knowledge must be traceable.
CREATE VIEW v_provenance_audit AS
SELECT knowledge_status,
       count(*) AS total,
       count(*) FILTER (WHERE provenance_note IS NOT NULL) AS with_provenance,
       count(*) FILTER (WHERE provenance_note IS NULL)     AS missing_provenance
FROM strategies
GROUP BY knowledge_status;

-- Quality control sweep. Each row is a defect class the maintenance
-- report should surface.
CREATE VIEW v_quality_issues AS
SELECT 'strategy_without_concept_link' AS issue, s.strategy_id AS entity_id, s.name AS detail
FROM strategies s
WHERE s.knowledge_status <> 'AI_DISCOVERED_CANDIDATE'
  AND NOT EXISTS (SELECT 1 FROM strategy_concepts sc WHERE sc.strategy_id = s.strategy_id)
UNION ALL
SELECT 'strategy_without_evidence', s.strategy_id, s.name
FROM strategies s
WHERE s.knowledge_status IN ('EVIDENCE_LINKED','VERIFIED')
  AND NOT EXISTS (SELECT 1 FROM strategy_evidence se WHERE se.strategy_id = s.strategy_id)
UNION ALL
SELECT 'strategy_without_outcomes_to_track', s.strategy_id, s.name
FROM strategies s
WHERE s.knowledge_status = 'VERIFIED' AND coalesce(btrim(s.outcomes_to_track),'') = ''
UNION ALL
SELECT 'evidence_without_source_item', e.evidence_id, coalesce(e.citation,'(no citation)')
FROM evidence_records e WHERE e.item_id IS NULL
UNION ALL
SELECT 'document_without_chunks', d.document_id, d.document_type
FROM source_documents d
WHERE NOT EXISTS (SELECT 1 FROM knowledge_chunks k WHERE k.document_id = d.document_id);

-- =====================================================================
-- Optional vector columns
-- =====================================================================

DO $$
DECLARE
    dim int := 1536;  -- must match EMBEDDING_DIM in .env and 002_concepts.sql
BEGIN
    IF has_capability('vector') THEN
        EXECUTE format('ALTER TABLE strategies ADD COLUMN embedding vector(%s)', dim);
        EXECUTE format('ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(%s)', dim);
        EXECUTE format('ALTER TABLE implementation_patterns ADD COLUMN embedding vector(%s)', dim);
        EXECUTE 'CREATE INDEX idx_strategies_embedding ON strategies USING hnsw (embedding vector_cosine_ops)';
        EXECUTE 'CREATE INDEX idx_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)';
        RAISE NOTICE 'Knowledge embedding columns created (dim=%)', dim;
    ELSE
        RAISE NOTICE 'pgvector absent: knowledge retrieval on metadata + FTS only';
    END IF;
END $$;
