-- =====================================================================
-- 007_coverage_and_provenance.sql
--
-- Three corrections, all made while the library still holds foundation
-- data rather than years of production records.
--
-- A. coverage_dimension now carries exactly the 18 questions recovered
--    from Engine 7 section 35, under names that mean what the questions
--    ask. MEASUREMENT and NUTRITION_STRATEGIES were semantic shortcuts
--    taken to force an 18-to-18 mapping; both are corrected.
--    KNOWLEDGE_GAPS is removed: gap identification is a readiness and
--    governance question, not a nineteenth domain of content.
--
-- B. Gap governance modelled in its own right. Foundation readiness may
--    require that a gap assessment was PERFORMED and that no unresolved
--    critical gap blocks use. It must never require zero gaps, and zero
--    currently identified gaps must never imply COMPLETE. Engine 7 never
--    reaches COMPLETE (section 70).
--
-- C. Provenance edges can no longer dangle. envelope_derived_records held
--    a free UUID with no target, so a provenance edge could point at
--    nothing and Postgres would accept it. Fixed with a generic entity
--    registry rather than nine typed foreign keys, so a new derived kind
--    remains a data operation.
-- =====================================================================


-- =====================================================================
-- A. Coverage dimensions: 18 recovered questions, correctly named
-- =====================================================================

-- Renames are in-place and preserve stored rows.
ALTER TYPE coverage_dimension RENAME VALUE 'MEASUREMENT' TO 'EFFECT_MAGNITUDE';
ALTER TYPE coverage_dimension RENAME VALUE 'NUTRITION_STRATEGIES' TO 'ALTERNATIVE_STRATEGIES';

-- Postgres cannot drop an enum value in place, so the type is rebuilt.
-- v_domain_readiness depends on the column and is recreated below.
DROP VIEW IF EXISTS v_domain_readiness;

DELETE FROM domain_coverage WHERE dimension = 'KNOWLEDGE_GAPS';

CREATE TYPE coverage_dimension_new AS ENUM (
    'PHYSIOLOGY',               -- What physiology matters?
    'BIOMARKERS',               -- Which biomarkers matter?
    'SYMPTOMS_FUNCTION',        -- Which symptoms matter?
    'MODIFIABLE_DRIVERS',       -- What modifiable drivers exist?
    'INTERVENTION_FAMILIES',    -- What interventions can target each driver?
    'HUMAN_EVIDENCE',           -- What is the evidence?
    'EFFECT_MAGNITUDE',         -- How large might the effects be?
    'POPULATION_APPLICABILITY', -- Who responds?
    'IMPLEMENTATION',           -- How are interventions implemented?
    'ALTERNATIVE_STRATEGIES',   -- What alternatives exist?
    'CONTROVERSIES',            -- What are the major controversies?
    'NEGATIVE_KNOWLEDGE',       -- What does not work?
    'FUNCTIONAL_TRADITIONAL',   -- Which practitioner strategies deserve consideration?
    'SUPPLEMENT_STRATEGIES',    -- Which supplements exist?
    'EXERCISE_STRATEGIES',      -- Which exercise strategies exist?
    'BEHAVIOUR_STRATEGIES',     -- Which behavioural strategies exist?
    'FOOD_DELIVERY',            -- Which local foods can deliver relevant nutrition?
    'DESIRED_OUTCOMES'          -- What does remission/restoration evidence show?
);

ALTER TABLE domain_coverage
    ALTER COLUMN dimension TYPE coverage_dimension_new
    USING dimension::text::coverage_dimension_new;

DROP TYPE coverage_dimension;
ALTER TYPE coverage_dimension_new RENAME TO coverage_dimension;

COMMENT ON TYPE coverage_dimension IS
'The 18 domain-depth questions recovered verbatim from Engine 7 section 35, one enum value per question, in source order. Every value corresponds to a question in the specification: no value here is a build invention, and gap assessment is deliberately not among them (see domain_gap_assessments).';

COMMENT ON TABLE domain_coverage IS
'One row per domain per recovered coverage question. Content coverage only. Whether the domain has assessed what it does NOT know is tracked separately in domain_gap_assessments, because that is a readiness question rather than a domain of knowledge.';


-- =====================================================================
-- B. Gap governance
-- =====================================================================

CREATE TYPE gap_severity AS ENUM (
    'CRITICAL',   -- the foundation is not usable for this domain until addressed
    'HIGH',
    'MEDIUM',
    'LOW'
);

ALTER TABLE knowledge_gaps
    ADD COLUMN severity gap_severity NOT NULL DEFAULT 'MEDIUM';

-- Only CRITICAL blocks. A domain with open HIGH gaps is still usable; a
-- domain with an open CRITICAL gap is not.
COMMENT ON COLUMN knowledge_gaps.severity IS
'CRITICAL means the foundation is not usable for this domain until the gap is addressed. Everything else is recorded and prioritised but never blocks readiness. Open gaps are the normal state of a living library.';

CREATE INDEX idx_gaps_open_severity ON knowledge_gaps (domain_id, severity)
    WHERE status = 'OPEN';

-- Presence of a row means a dedicated gap pass has been RUN for this
-- domain. It says nothing about how many gaps were found, and finding
-- none is a legitimate outcome.
CREATE TABLE domain_gap_assessments (
    domain_id          uuid PRIMARY KEY
                       REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    assessed_at        timestamptz NOT NULL DEFAULT now(),
    assessed_by        text,
    processing_version text,
    gaps_found         integer NOT NULL DEFAULT 0,
    note               text,

    CONSTRAINT ck_gaps_found_nonneg CHECK (gaps_found >= 0)
);

COMMENT ON TABLE domain_gap_assessments IS
'A row means a dedicated gap-identification pass was performed for this domain (Engine 7 section 49). It is a governance record, not a content-coverage dimension. gaps_found = 0 means "no critical gaps currently identified", which is a valid honest result and explicitly does NOT mean the domain is finished: Engine 7 section 70 forbids a COMPLETE state and science continues to move.';

CREATE VIEW v_domain_readiness AS
SELECT d.domain_id,
       d.domain_key,
       d.name,
       d.is_core_domain,
       d.status,

       count(*) FILTER (WHERE c.covered)                    AS dimensions_covered,
       18                                                    AS dimensions_total,
       (count(*) FILTER (WHERE c.covered)) >= 14             AS meets_depth_bar,

       -- Cast to text[]: drivers do not know custom enum types and return
       -- an enum array as an unparsed literal string. n8n hits this too.
       array_agg(c.dimension::text ORDER BY c.dimension)
           FILTER (WHERE NOT c.covered)                      AS missing_dimensions,

       -- Governance, tracked separately from content coverage.
       (g.domain_id IS NOT NULL)                             AS gap_assessment_complete,
       g.assessed_at                                         AS gap_assessed_at,
       coalesce(og.critical_open, 0)                         AS open_critical_gaps,
       coalesce(og.high_open, 0)                             AS open_high_priority_gaps,

       -- Readiness = enough recovered coverage, a gap pass actually run,
       -- and nothing critical left unresolved. Deliberately NOT "zero
       -- gaps": open non-critical gaps are the normal state of a library
       -- that is still learning.
       ((count(*) FILTER (WHERE c.covered)) >= 14
         AND g.domain_id IS NOT NULL
         AND coalesce(og.critical_open, 0) = 0)              AS foundation_ready
FROM knowledge_domains d
LEFT JOIN domain_coverage c        ON c.domain_id = d.domain_id
LEFT JOIN domain_gap_assessments g ON g.domain_id = d.domain_id
LEFT JOIN LATERAL (
    SELECT count(*) FILTER (WHERE kg.severity = 'CRITICAL') AS critical_open,
           count(*) FILTER (WHERE kg.severity = 'HIGH')     AS high_open
    FROM knowledge_gaps kg
    WHERE kg.domain_id = d.domain_id AND kg.status = 'OPEN'
) og ON true
WHERE d.active
GROUP BY d.domain_id, d.domain_key, d.name, d.is_core_domain, d.status,
         g.domain_id, g.assessed_at, og.critical_open, og.high_open;

COMMENT ON VIEW v_domain_readiness IS
'foundation_ready requires sufficient coverage across the 18 recovered dimensions, a gap assessment actually performed, and no unresolved CRITICAL gap. It does not require zero gaps, and it never yields a COMPLETE state: foundation_status has no COMPLETE value and Engine 7 section 70 forbids one.';


-- =====================================================================
-- C. Provenance integrity without typed foreign keys
-- =====================================================================
-- Every derived knowledge object registers itself in one registry. The
-- provenance edge points at the registry, so it cannot reference an object
-- that does not exist. A new derived kind still needs no schema change to
-- envelope_derived_records: it adds a derived_kind value and a registration
-- trigger, and the integrity guarantee comes along for free.

CREATE TABLE knowledge_entities (
    entity_id    uuid NOT NULL,
    entity_kind  derived_kind NOT NULL,
    source_table text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (entity_id),
    -- The composite key the provenance edge targets. Including the kind
    -- means an edge cannot claim a strategy id is a claim.
    UNIQUE (entity_id, entity_kind)
);

CREATE INDEX idx_knowledge_entities_kind ON knowledge_entities (entity_kind);

COMMENT ON TABLE knowledge_entities IS
'Registry of every derived knowledge object, maintained by trigger. Exists so polymorphic provenance edges can be foreign-keyed without hard-coding one FK per derived type. Never written to by hand.';

-- Generic registration. The trigger argument carries the kind, so one
-- function serves every table.
CREATE OR REPLACE FUNCTION register_knowledge_entity() RETURNS trigger AS $$
DECLARE
    id_value uuid;
BEGIN
    EXECUTE format('SELECT ($1).%I', TG_ARGV[1]) INTO id_value USING NEW;
    INSERT INTO knowledge_entities (entity_id, entity_kind, source_table)
    VALUES (id_value, TG_ARGV[0]::derived_kind, TG_TABLE_NAME)
    ON CONFLICT (entity_id) DO NOTHING;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION deregister_knowledge_entity() RETURNS trigger AS $$
DECLARE
    id_value uuid;
BEGIN
    EXECUTE format('SELECT ($1).%I', TG_ARGV[0]) INTO id_value USING OLD;
    DELETE FROM knowledge_entities WHERE entity_id = id_value;
    RETURN OLD;
END $$ LANGUAGE plpgsql;

-- Register the nine derived kinds that exist today.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('strategies',              'STRATEGY',               'strategy_id'),
            ('claims',                  'CLAIM',                  'claim_id'),
            ('evidence_records',        'EVIDENCE',               'evidence_id'),
            ('implementation_patterns', 'IMPLEMENTATION_PATTERN', 'pattern_id'),
            ('foods',                   'FOOD',                   'food_id'),
            ('supplements',             'SUPPLEMENT',             'supplement_id'),
            ('controversies',           'CONTROVERSY',            'controversy_id'),
            ('negative_knowledge',      'NEGATIVE_KNOWLEDGE',     'negative_id'),
            ('concept_proposals',       'CONCEPT_PROPOSAL',       'proposal_id')
        ) AS t(tbl, kind, pk)
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_register_%1$s AFTER INSERT ON %1$I
             FOR EACH ROW EXECUTE FUNCTION register_knowledge_entity(%2$L, %3$L)',
            r.tbl, r.kind, r.pk);
        EXECUTE format(
            'CREATE TRIGGER trg_deregister_%1$s AFTER DELETE ON %1$I
             FOR EACH ROW EXECUTE FUNCTION deregister_knowledge_entity(%2$L)',
            r.tbl, r.pk);
        -- Backfill anything already present.
        EXECUTE format(
            'INSERT INTO knowledge_entities (entity_id, entity_kind, source_table)
             SELECT %2$I, %3$L::derived_kind, %1$L FROM %1$I
             ON CONFLICT (entity_id) DO NOTHING',
            r.tbl, r.pk, r.kind);
    END LOOP;
END $$;

-- Clear any edge written before the registry existed, then bind the edge
-- to the registry. Composite so the kind must match too.
DELETE FROM envelope_derived_records edr
 WHERE NOT EXISTS (
    SELECT 1 FROM knowledge_entities ke
     WHERE ke.entity_id = edr.derived_id AND ke.entity_kind = edr.derived_kind);

ALTER TABLE envelope_derived_records
    ADD CONSTRAINT fk_derived_entity
    FOREIGN KEY (derived_id, derived_kind)
    REFERENCES knowledge_entities (entity_id, entity_kind)
    ON DELETE CASCADE;

COMMENT ON CONSTRAINT fk_derived_entity ON envelope_derived_records IS
'A provenance edge must point at a registered knowledge entity of the stated kind. Extensibility is preserved: a new derived kind adds an enum value and a registration trigger, not a new foreign key here.';
