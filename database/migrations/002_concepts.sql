-- 002_concepts.sql
-- The canonical concept layer.
--
-- Purpose: engines emit clinical prose. The knowledge library stores rows.
-- Prose does not join to rows. This layer is the join.
--
-- Engine 1 says:
--   "large post-meal glucose excursions associated with refined evening
--    carbohydrate intake and low muscle stimulus"
-- Normalization resolves that to:
--   POSTPRANDIAL_GLUCOSE, REFINED_CARBOHYDRATE_EXPOSURE,
--   SKELETAL_MUSCLE_GLUCOSE_DISPOSAL, LOW_RESISTANCE_ACTIVITY,
--   INSULIN_SENSITIVITY
--
-- Engines are never asked to speak in codes. Normalization sits between
-- reasoning output and knowledge retrieval.

-- ---------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------

CREATE TYPE concept_type AS ENUM (
    'CONDITION',
    'PHYSIOLOGY',
    'DRIVER',
    'BIOMARKER',
    'SYMPTOM',
    'OUTCOME',
    'INTERVENTION',
    'NUTRIENT',
    'FOOD',
    'EXERCISE',
    'BEHAVIOUR',
    'POPULATION',
    'MEDICATION_CONTEXT',
    'GEOGRAPHY',
    'SEASON'
);

CREATE TYPE concept_status AS ENUM (
    'SEEDED',       -- from the pre-extraction ontology seed
    'ACTIVE',       -- promoted from a proposal, in use
    'PROPOSED',     -- awaiting resolution, NOT yet usable for retrieval
    'MERGED',       -- folded into another concept; merged_into is set
    'DEPRECATED'    -- withdrawn, retained for provenance
);

CREATE TYPE concept_relation_type AS ENUM (
    'RELATED_TO',              -- symmetric, soft association
    'TARGETS',                 -- intervention -> physiology/biomarker/outcome
    'MEASURES',                -- biomarker -> physiology
    'DRIVES',                  -- driver -> physiology/condition
    'CONTRAINDICATED_WITH',    -- intervention <-> medication_context/population
    'CONFUSABLE_DO_NOT_MERGE'  -- looks similar, is clinically distinct
);

-- How a mapping was established. Ordered cheapest to most expensive:
-- deterministic lookup first, LLM only when required.
CREATE TYPE resolution_method AS ENUM (
    'SEED',            -- authored in the ontology seed
    'DETERMINISTIC',   -- exact normalized alias hit
    'STRUCTURED',      -- known mapping table (lab codes, food synonyms)
    'TRIGRAM',         -- lexical similarity
    'SEMANTIC',        -- embedding similarity
    'LLM',             -- model reasoning, used only when the above fail
    'PRACTITIONER'     -- escalated and decided by a human
);

CREATE TYPE proposal_decision AS ENUM (
    'AUTO_ALIAS',      -- high confidence: attached as alias to existing concept
    'AUTO_CREATE',     -- clearly novel: promoted to a new ACTIVE concept
    'AUTO_MERGE',      -- duplicate of an existing proposal/concept
    'LOGGED',          -- low-impact ambiguity: recorded, not escalated
    'ESCALATED',       -- high-impact ambiguity: in the capped review queue
    'RESOLVED',        -- escalation decided
    'REJECTED'         -- not a usable concept (noise, fragment, duplicate)
);

-- ---------------------------------------------------------------------
-- concepts
-- ---------------------------------------------------------------------

CREATE TABLE concepts (
    concept_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Stable machine key, e.g. POSTPRANDIAL_GLUCOSE. Immutable once ACTIVE:
    -- strategy tags and retrieval benchmarks reference it.
    canonical_key   text        NOT NULL,
    canonical_name  text        NOT NULL,   -- human label
    concept_type    concept_type NOT NULL,

    -- Short definition. Carries the clinical distinction that stops a
    -- near-neighbour being merged in later.
    definition      text,

    parent_concept_id uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,

    status          concept_status NOT NULL DEFAULT 'PROPOSED',
    merged_into     uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,

    -- Provenance. Every concept answers: where did this come from?
    origin_method   resolution_method NOT NULL DEFAULT 'SEED',
    origin_detail   text,

    -- Retrieval support. FTS is always available; the embedding column is
    -- added conditionally below only when pgvector is present.
    search_text     text GENERATED ALWAYS AS (
                        canonical_name || ' ' || coalesce(definition, '')
                    ) STORED,

    -- Usage telemetry. Concepts never hit by retrieval are candidates for
    -- review; concepts hit constantly are worth deepening.
    retrieval_hits  bigint      NOT NULL DEFAULT 0,
    last_retrieved  timestamptz,

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    last_reviewed   timestamptz,

    CONSTRAINT ck_canonical_key_shape
        CHECK (canonical_key ~ '^[A-Z][A-Z0-9_]{2,79}$'),
    CONSTRAINT ck_merged_into_only_when_merged
        CHECK ((status = 'MERGED') = (merged_into IS NOT NULL)),
    CONSTRAINT ck_no_self_merge
        CHECK (merged_into IS DISTINCT FROM concept_id),
    CONSTRAINT ck_no_self_parent
        CHECK (parent_concept_id IS DISTINCT FROM concept_id)
);

-- Canonical key unique among live concepts only, so a deprecated key can
-- be retired without blocking a corrected replacement.
CREATE UNIQUE INDEX uq_concepts_canonical_key
    ON concepts (canonical_key)
    WHERE status IN ('SEEDED', 'ACTIVE', 'PROPOSED');

CREATE INDEX idx_concepts_type    ON concepts (concept_type)
    WHERE status IN ('SEEDED', 'ACTIVE');
CREATE INDEX idx_concepts_parent  ON concepts (parent_concept_id);
CREATE INDEX idx_concepts_fts     ON concepts
    USING gin (to_tsvector('english', search_text));

-- Trigram index only where pg_trgm exists. Without it, alias matching is
-- exact-normalized and more phrases fall through to LLM resolution.
DO $$
BEGIN
    IF has_capability('pg_trgm') THEN
        EXECUTE 'CREATE INDEX idx_concepts_trgm ON concepts '
                'USING gin (canonical_name gin_trgm_ops)';
    END IF;
END $$;

CREATE TRIGGER trg_concepts_updated
    BEFORE UPDATE ON concepts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN concepts.canonical_key IS
'Immutable once ACTIVE. Referenced by strategy tags, retrieval tests and engine handoffs.';
COMMENT ON COLUMN concepts.definition IS
'Carries the clinical distinction. VISCERAL_ADIPOSE_TISSUE and SUBCUTANEOUS_ADIPOSE_TISSUE are separated here, not by name alone.';

-- ---------------------------------------------------------------------
-- concept_aliases
-- ---------------------------------------------------------------------
-- Many phrases -> one concept. This is the deterministic layer that keeps
-- the LLM out of the normalization path for anything already seen.

CREATE TABLE concept_aliases (
    alias_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id    uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,

    alias_text    text NOT NULL,
    alias_norm    text GENERATED ALWAYS AS (norm_phrase(alias_text)) STORED,

    method        resolution_method NOT NULL,
    confidence    numeric(4,3),
    -- Confirmed aliases short-circuit all downstream resolution.
    confirmed     boolean NOT NULL DEFAULT false,

    hit_count     bigint      NOT NULL DEFAULT 0,
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_alias_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

-- One normalized phrase resolves to a given concept at most once.
CREATE UNIQUE INDEX uq_alias_norm_concept ON concept_aliases (alias_norm, concept_id);
-- Lookup index for the deterministic path. Note: NOT unique on alias_norm
-- alone, because one phrase may legitimately map to several concepts.
CREATE INDEX idx_alias_norm  ON concept_aliases (alias_norm);

DO $$
BEGIN
    IF has_capability('pg_trgm') THEN
        EXECUTE 'CREATE INDEX idx_alias_trgm ON concept_aliases '
                'USING gin (alias_norm gin_trgm_ops)';
    END IF;
END $$;

COMMENT ON TABLE concept_aliases IS
'Deterministic phrase -> concept map. Every LLM normalization writes its result back here so the same phrase never costs a second call.';

-- ---------------------------------------------------------------------
-- concept_relations
-- ---------------------------------------------------------------------
-- Includes CONFUSABLE_DO_NOT_MERGE, the relation that stops semantic
-- similarity collapsing clinically distinct neighbours.

CREATE TABLE concept_relations (
    relation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_concept  uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    to_concept    uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    relation_type concept_relation_type NOT NULL,
    -- Why they are confusable and how they differ. Read by the merge step.
    note          text,
    method        resolution_method NOT NULL DEFAULT 'SEED',
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_relation_not_self CHECK (from_concept <> to_concept)
);

CREATE UNIQUE INDEX uq_concept_relation
    ON concept_relations (from_concept, to_concept, relation_type);
CREATE INDEX idx_relation_from ON concept_relations (from_concept, relation_type);
CREATE INDEX idx_relation_to   ON concept_relations (to_concept, relation_type);

-- Confusable pairs are symmetric. Enforce both directions automatically so
-- a merge check can never miss the pair by querying the wrong way round.
CREATE OR REPLACE FUNCTION mirror_confusable_relation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.relation_type = 'CONFUSABLE_DO_NOT_MERGE' THEN
        INSERT INTO concept_relations (from_concept, to_concept, relation_type, note, method)
        VALUES (NEW.to_concept, NEW.from_concept, NEW.relation_type, NEW.note, NEW.method)
        ON CONFLICT (from_concept, to_concept, relation_type) DO NOTHING;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_mirror_confusable
    AFTER INSERT ON concept_relations
    FOR EACH ROW EXECUTE FUNCTION mirror_confusable_relation();

COMMENT ON TYPE concept_relation_type IS
'CONFUSABLE_DO_NOT_MERGE exists because embedding similarity cannot tell "belly fat" (colloquial, mergeable) from "visceral fat" (distinct compartment, not mergeable).';

-- ---------------------------------------------------------------------
-- concept_proposals
-- ---------------------------------------------------------------------
-- Extraction never writes concepts directly. It proposes. Resolution is
-- automatic wherever confidence allows:
--   AUTOMATE -> AUTO-RESOLVE HIGH CONFIDENCE -> LOG LOW-IMPACT UNCERTAINTY
--   -> ESCALATE ONLY HIGH-IMPACT AMBIGUITY

CREATE TABLE concept_proposals (
    proposal_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    raw_phrase       text NOT NULL,
    raw_phrase_norm  text GENERATED ALWAYS AS (norm_phrase(raw_phrase)) STORED,
    -- Surrounding text that disambiguates. "Fasting insulin" means one
    -- thing in a lab panel and another in a mechanism discussion.
    context          text,
    proposed_type    concept_type,

    -- Where the phrase came from.
    source_kind      text,        -- 'ENGINE1_OUTPUT' | 'CLAIM_EXTRACTION' | ...
    source_ref       text,

    -- Best existing match found during resolution.
    candidate_concept uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    similarity        numeric(4,3),
    method            resolution_method,

    -- Impact drives escalation, not uncertainty alone. An ambiguous concept
    -- touching many strategies matters; an ambiguous one-off does not.
    impact_score      numeric(6,3) NOT NULL DEFAULT 0,

    decision          proposal_decision NOT NULL DEFAULT 'LOGGED',
    resulting_concept uuid REFERENCES concepts(concept_id) ON DELETE SET NULL,
    decision_note     text,

    resolved_by       text,       -- 'system' | practitioner identifier
    created_at        timestamptz NOT NULL DEFAULT now(),
    resolved_at       timestamptz,

    CONSTRAINT ck_similarity CHECK (similarity IS NULL OR similarity BETWEEN 0 AND 1)
);

CREATE INDEX idx_proposals_open ON concept_proposals (decision, impact_score DESC, created_at)
    WHERE decision IN ('ESCALATED', 'LOGGED');
CREATE INDEX idx_proposals_phrase ON concept_proposals (raw_phrase_norm);

COMMENT ON COLUMN concept_proposals.impact_score IS
'Escalation is ranked by impact, not by uncertainty. Computed from how many strategies/domains the phrase touches and whether it appears in a core Wave-1 domain.';

-- ---------------------------------------------------------------------
-- normalization_cache
-- ---------------------------------------------------------------------
-- Phrase-level memo. One phrase may resolve to several concepts, so the
-- cache stores an array. Hit here and no resolution work happens at all.

CREATE TABLE normalization_cache (
    phrase_norm   text PRIMARY KEY,
    concept_ids   uuid[] NOT NULL,
    method        resolution_method NOT NULL,
    confidence    numeric(4,3),
    hit_count     bigint      NOT NULL DEFAULT 1,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_cache_nonempty CHECK (cardinality(concept_ids) > 0)
);

CREATE INDEX idx_norm_cache_concepts ON normalization_cache USING gin (concept_ids);

-- ---------------------------------------------------------------------
-- Normalization test set
-- ---------------------------------------------------------------------
-- Generated automatically: merge cases from alias structure, do-not-merge
-- cases from sibling concepts under a shared parent. Practitioner
-- spot-checks a sample rather than authoring the set.

CREATE TABLE normalization_tests (
    test_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phrase_a       text NOT NULL,
    phrase_b       text NOT NULL,
    -- true  = must resolve to the same concept
    -- false = must NOT be merged (the harder and more important half)
    expect_same    boolean NOT NULL,
    rationale      text,
    generated_from text,      -- 'ALIAS_PAIR' | 'SIBLING_PAIR' | 'CONFUSABLE_PAIR'
    spot_checked   boolean NOT NULL DEFAULT false,
    spot_check_ok  boolean,
    last_run_at    timestamptz,
    last_run_pass  boolean,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_norm_tests_failing ON normalization_tests (last_run_pass, expect_same)
    WHERE last_run_pass = false;

COMMENT ON TABLE normalization_tests IS
'Auto-generated. Negative pairs (expect_same=false) come from siblings under a shared parent and from CONFUSABLE_DO_NOT_MERGE relations, which is where dangerous merges actually occur.';

-- ---------------------------------------------------------------------
-- Optional vector columns
-- ---------------------------------------------------------------------
-- Added only when pgvector is present. Without it, resolution uses
-- deterministic -> structured -> trigram -> LLM and still functions.

DO $$
DECLARE
    dim int := 1536;  -- must match EMBEDDING_DIM in .env
BEGIN
    IF has_capability('vector') THEN
        EXECUTE format('ALTER TABLE concepts ADD COLUMN embedding vector(%s)', dim);
        EXECUTE format('ALTER TABLE concept_aliases ADD COLUMN embedding vector(%s)', dim);
        EXECUTE 'CREATE INDEX idx_concepts_embedding ON concepts '
                'USING hnsw (embedding vector_cosine_ops)';
        EXECUTE 'CREATE INDEX idx_alias_embedding ON concept_aliases '
                'USING hnsw (embedding vector_cosine_ops)';
        RAISE NOTICE 'Concept embedding columns created (dim=%)', dim;
    ELSE
        RAISE NOTICE 'pgvector absent: concept layer running on deterministic + trigram + LLM resolution';
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------

-- Live concepts only. Every retrieval path reads this, never the base
-- table, so PROPOSED and MERGED concepts can never leak into results.
CREATE VIEW v_active_concepts AS
SELECT c.concept_id,
       c.canonical_key,
       c.canonical_name,
       c.concept_type,
       c.definition,
       c.parent_concept_id,
       p.canonical_key AS parent_key,
       c.retrieval_hits,
       c.last_retrieved
FROM concepts c
LEFT JOIN concepts p ON p.concept_id = c.parent_concept_id
WHERE c.status IN ('SEEDED', 'ACTIVE');

-- The practitioner queue. Capped and impact-ranked. Items beyond the cap
-- stay queued and re-rank; they are never dropped.
CREATE VIEW v_concept_escalation_queue AS
SELECT p.proposal_id,
       p.raw_phrase,
       p.context,
       p.proposed_type,
       p.impact_score,
       c.canonical_key AS nearest_concept,
       p.similarity,
       p.created_at
FROM concept_proposals p
LEFT JOIN concepts c ON c.concept_id = p.candidate_concept
WHERE p.decision = 'ESCALATED'
ORDER BY p.impact_score DESC, p.created_at;

-- Concepts a merge step must treat as distinct no matter how similar
-- their embeddings are.
CREATE VIEW v_confusable_pairs AS
SELECT a.canonical_key AS concept_a,
       b.canonical_key AS concept_b,
       r.note
FROM concept_relations r
JOIN concepts a ON a.concept_id = r.from_concept
JOIN concepts b ON b.concept_id = r.to_concept
WHERE r.relation_type = 'CONFUSABLE_DO_NOT_MERGE'
  AND a.canonical_key < b.canonical_key;   -- one row per pair
