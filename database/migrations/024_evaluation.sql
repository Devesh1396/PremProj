-- =====================================================================
-- 024_evaluation.sql   Step 18 — evaluation layers A–E
--
-- D7 settled that there is NO practitioner-authored gold benchmark. Engine
-- 7 exists because the practitioner cannot personally author, read and
-- remember the whole knowledge universe, so a benchmark whose answers come
-- from practitioner recall makes practitioner recall the ceiling on
-- measured success. Five layers replace it:
--
--   A  automated retrieval tests from the seeded domain structure   no human
--   B  source-grounded recovery on HELD-OUT sources                 no human
--   C  cross-domain synthetic cases, per domain, from moderate cover no human
--   D  practitioner spot check, small sample                        QC only
--   E  UNEXPECTED_USEFUL_STRATEGIES_FOUND as a RATE                 via D
--
-- Nothing here is client-scoped. Spot checks are performed on LIBRARY
-- strategies, never on a client's retrieval, so no table below carries a
-- client_id and none needs RLS. That is a deliberate boundary: a QC sample
-- that quoted a real case would make evaluation a PHI surface.
-- =====================================================================


-- =====================================================================
-- A. The seeded structure layer A scores against
-- =====================================================================
--
-- `strategy_domains` has existed since 003; the symmetric edge for
-- concepts never did. The domain a concept was seeded under lived only
-- inside `concepts.origin_detail` -- prose, of the form
-- '... DOMAIN A (CONDITIONS & CLINICAL STATES); also DOMAIN B'.
--
-- Layer A cannot score a family it has to parse out of a sentence, for the
-- same reason n8n does not route on prose (hard rule 5). So the edge
-- becomes a row. `seed_ontology.py` writes it from here on; the backfill
-- below reconciles concepts already seeded, parsing a string THIS BUILD
-- generated in a fixed format, once.
-- =====================================================================

CREATE TABLE IF NOT EXISTS concept_domains (
    concept_id uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    domain_id  uuid NOT NULL REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    -- 'K1_SEED' | 'K01_DISCOVERY' | 'PRACTITIONER'. A registry value, not
    -- an enum: a new way for the edge to arise is data (hard rule 13).
    source     text NOT NULL DEFAULT 'K1_SEED',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (concept_id, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_concept_domains_domain
    ON concept_domains (domain_id);

COMMENT ON TABLE concept_domains IS
'Which domain(s) a concept belongs to. The seeded family layer A scores against, and the symmetric partner of strategy_domains. One concept may belong to several domains — the A-Z curriculum lists some terms under more than one.';

-- One-time reconciliation of concepts seeded before this table existed.
-- `regexp_matches(..., 'g')` over our own generated provenance string; it
-- is not a general prose parser and nothing reads origin_detail after this.
INSERT INTO concept_domains (concept_id, domain_id, source)
SELECT c.concept_id, d.domain_id, 'K1_SEED'
  FROM concepts c
 CROSS JOIN LATERAL regexp_matches(c.origin_detail, 'DOMAIN ([A-Z])(?![A-Z])', 'g') AS m(letter)
  JOIN knowledge_domains d ON d.domain_key = 'DOMAIN_' || m.letter[1]
 WHERE c.origin_method = 'SEED' AND c.origin_detail IS NOT NULL
ON CONFLICT DO NOTHING;

GRANT SELECT, INSERT, DELETE ON concept_domains TO phi_runtime;
GRANT SELECT ON concept_domains TO phi_practitioner;


-- =====================================================================
-- The automated layers: A, B and C
-- =====================================================================

CREATE TYPE evaluation_layer AS ENUM ('A', 'B', 'C');

COMMENT ON TYPE evaluation_layer IS
'The three layers that need no human. D is a QC sample and E is a rate derived from it; neither is a test, so neither is a value here.';

-- How a test is scored. A COLUMN rather than a branch keyed off the layer,
-- because layer C does not measure the same thing as A and B: A and B ask
-- "did the expected material come back", C asks "did the page span the
-- case's domains, or collapse into three disease folders". Two questions,
-- two metrics, and adding a third is a value rather than an `if`.
CREATE TYPE evaluation_metric AS ENUM ('CONCEPT_RECALL', 'DOMAIN_BREADTH');


CREATE TABLE retrieval_tests (
    test_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer          evaluation_layer NOT NULL,
    metric         evaluation_metric NOT NULL,

    query_text     text NOT NULL,
    -- The concepts handed to retrieval as the case's own (the spine
    -- input), as distinct from what the test expects back. Layer A leaves
    -- this EMPTY on purpose: handing the spine the family it is being
    -- asked to find would be the test answering itself.
    query_concepts uuid[] NOT NULL DEFAULT '{}',

    -- What should come back. Never empty -- see the constraint.
    expected_concepts uuid[] NOT NULL DEFAULT '{}',

    domain_id      uuid REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    item_id        uuid REFERENCES source_items(item_id) ON DELETE CASCADE,

    generated_from text NOT NULL,
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),

    -- The one constraint that matters. Recall over an empty expected set
    -- is not 1.0, it is undefined -- and a suite that records it as 1.0
    -- reports a perfect score for a library that knows nothing. A test
    -- with nothing to expect must not exist.
    CONSTRAINT ck_test_has_expectation
        CHECK (cardinality(expected_concepts) > 0),
    -- Layer B is grounded in a specific held-out source, or it is not
    -- layer B: the whole point is that the answer key came from material
    -- the library was not tuned on.
    CONSTRAINT ck_layer_b_has_item
        CHECK (layer <> 'B' OR item_id IS NOT NULL)
);

CREATE INDEX idx_retrieval_tests_layer ON retrieval_tests (layer, active);
CREATE INDEX idx_retrieval_tests_domain ON retrieval_tests (domain_id);

COMMENT ON TABLE retrieval_tests IS
'Auto-generated retrieval tests (D7 layers A, B, C). No row here is authored by the practitioner. Generation is deterministic so a regenerated set is comparable with the last one.';

COMMENT ON COLUMN retrieval_tests.query_concepts IS
'What the case supplies to the concept spine. Empty for layer A by design: a test that hands retrieval the answer measures nothing.';

GRANT SELECT, INSERT, UPDATE, DELETE ON retrieval_tests TO phi_runtime;
GRANT SELECT ON retrieval_tests TO phi_practitioner;


CREATE TABLE retrieval_test_runs (
    run_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer        evaluation_layer NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    tests_run    integer NOT NULL DEFAULT 0,
    tests_passed integer NOT NULL DEFAULT 0,
    mean_score   numeric(5,4),

    -- Recall with pgvector and recall without it are not the same number
    -- and must never be trended as one line (D15). The configuration is
    -- recorded with the result, not assumed from the reader's machine.
    vector_enabled boolean NOT NULL,
    library_size   integer NOT NULL,
    score_floor    numeric(5,4) NOT NULL,
    note           text
);

CREATE INDEX idx_test_runs_layer ON retrieval_test_runs (layer, started_at DESC);

COMMENT ON COLUMN retrieval_test_runs.score_floor IS
'The pass threshold this run used. An engineering tripwire recorded WITH the result, never a definition of quality (A4) — a floor that moves between runs would otherwise make the history meaningless.';

GRANT SELECT, INSERT, UPDATE ON retrieval_test_runs TO phi_runtime;
GRANT SELECT ON retrieval_test_runs TO phi_practitioner;


CREATE TABLE retrieval_test_results (
    run_id      uuid NOT NULL REFERENCES retrieval_test_runs(run_id) ON DELETE CASCADE,
    test_id     uuid NOT NULL REFERENCES retrieval_tests(test_id) ON DELETE CASCADE,
    expected    integer NOT NULL,
    hit         integer NOT NULL,
    returned    integer NOT NULL,
    score       numeric(5,4) NOT NULL,
    passed      boolean NOT NULL,
    -- Which channels produced the hits. A test that only ever passes on
    -- the concept spine is telling you the text and vector halves are not
    -- working, and a bare score cannot say that.
    channels    text[] NOT NULL DEFAULT '{}',
    note        text,
    PRIMARY KEY (run_id, test_id),

    CONSTRAINT ck_result_hit_le_expected CHECK (hit <= expected),
    CONSTRAINT ck_result_score_range CHECK (score BETWEEN 0 AND 1)
);

GRANT SELECT, INSERT ON retrieval_test_results TO phi_runtime;
GRANT SELECT ON retrieval_test_results TO phi_practitioner;


-- =====================================================================
-- Layer B: the answer key
-- =====================================================================
--
-- A3 and D7 together: a held-out source is extracted SEPARATELY, and what
-- comes out is the answer key. `knowledge_extract.py` refuses to extract
-- it into `claims` -- correctly, because that would put the answers into
-- the library being tested.
--
-- So the answer key lands HERE, in a table with no path into synthesis:
-- no `claims` row, no `strategies` row, no `knowledge_entities`
-- registration, and nothing in K10 or K11 reads it. The separation is
-- structural rather than procedural, which is the only kind that survives
-- a future session in a hurry.
-- =====================================================================

CREATE TABLE holdout_answer_keys (
    key_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id       uuid NOT NULL REFERENCES source_items(item_id) ON DELETE CASCADE,
    claim_text    text NOT NULL,
    claim_type    text,
    target        text,
    -- The concepts this claim normalized to. What layer B expects the
    -- library to be able to reach.
    concept_ids   uuid[] NOT NULL DEFAULT '{}',
    run_id        uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,
    extracted_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_holdout_keys_item ON holdout_answer_keys (item_id);

COMMENT ON TABLE holdout_answer_keys IS
'Layer B (D7, A3). Claims extracted from HELD-OUT sources, kept out of the library on purpose: no claims row, no strategy, no provenance edge, and nothing in K10/K11 reads this table. Testing against fully synthesised material measures index integrity, not retrieval quality.';

GRANT SELECT, INSERT, DELETE ON holdout_answer_keys TO phi_runtime;
GRANT SELECT ON holdout_answer_keys TO phi_practitioner;


-- =====================================================================
-- Layer D: the practitioner spot check
-- =====================================================================
--
-- The ONE place a human appears in evaluation, and it is quality control
-- on a sample -- not knowledge authoring (D7), and not a recurring job the
-- system depends on (hard rule 3). The sample is drawn automatically; the
-- practitioner marks verdicts and may say something important was missing.
-- =====================================================================

CREATE TYPE spot_check_verdict AS ENUM (
    'EXPECTED_USEFUL',      -- right, and the practitioner already knew it
    'UNEXPECTED_USEFUL',    -- right, and they did not. This is layer E
    'IRRELEVANT'            -- should not have been returned
);

CREATE TABLE spot_check_samples (
    sample_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sampled_at      timestamptz NOT NULL DEFAULT now(),
    query_text      text NOT NULL,
    context         text,
    items_presented integer NOT NULL,
    reviewed_at     timestamptz,

    -- The fourth verdict in D7 is about the sample, not about any row in
    -- it: "important item missing" names something that did NOT come back.
    -- There is no item to attach it to, so it lives here.
    important_item_missing boolean,
    missing_note    text,

    CONSTRAINT ck_sample_nonempty CHECK (items_presented > 0),
    CONSTRAINT ck_missing_needs_note CHECK (
        important_item_missing IS NOT TRUE
        OR (missing_note IS NOT NULL AND length(btrim(missing_note)) > 0)
    )
);

COMMENT ON CONSTRAINT ck_missing_needs_note ON spot_check_samples IS
'"Something important was missing" with no note is an unactionable signal — it cannot become a knowledge gap, a query fix or a normalization correction.';

GRANT SELECT, INSERT, UPDATE ON spot_check_samples TO phi_runtime, phi_practitioner;


CREATE TABLE spot_check_items (
    sample_id   uuid NOT NULL REFERENCES spot_check_samples(sample_id) ON DELETE CASCADE,
    strategy_id uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    position    integer NOT NULL,
    verdict     spot_check_verdict,
    note        text,
    decided_at  timestamptz,
    PRIMARY KEY (sample_id, strategy_id),

    CONSTRAINT ck_verdict_timestamped CHECK ((verdict IS NULL) = (decided_at IS NULL))
);

CREATE INDEX idx_spot_check_pending ON spot_check_items (sample_id)
    WHERE verdict IS NULL;

GRANT SELECT, INSERT, UPDATE ON spot_check_items TO phi_runtime, phi_practitioner;


-- =====================================================================
-- Layer E: discovery value, as a RATE
-- =====================================================================
--
-- D7 is explicit: never a raw count. Raw counts rise with library size
-- regardless of quality, so a growing library would report improving
-- discovery while getting worse. The rate is per spot-check sample, and
-- the denominator is what was actually REVIEWED -- not what was presented,
-- because a half-reviewed sample would otherwise report half the rate.
-- =====================================================================

CREATE OR REPLACE VIEW v_discovery_value
WITH (security_invoker = true) AS
SELECT s.sample_id,
       s.sampled_at,
       s.items_presented,
       count(i.verdict)                                                   AS items_reviewed,
       count(*) FILTER (WHERE i.verdict = 'UNEXPECTED_USEFUL')            AS unexpected_useful,
       count(*) FILTER (WHERE i.verdict = 'EXPECTED_USEFUL')              AS expected_useful,
       count(*) FILTER (WHERE i.verdict = 'IRRELEVANT')                   AS irrelevant,
       round(count(*) FILTER (WHERE i.verdict = 'UNEXPECTED_USEFUL')::numeric
             / nullif(count(i.verdict), 0), 4)                            AS unexpected_useful_rate,
       round(count(*) FILTER (WHERE i.verdict = 'IRRELEVANT')::numeric
             / nullif(count(i.verdict), 0), 4)                            AS irrelevant_rate,
       s.important_item_missing,
       s.reviewed_at
  FROM spot_check_samples s
  LEFT JOIN spot_check_items i ON i.sample_id = s.sample_id
 GROUP BY s.sample_id, s.sampled_at, s.items_presented,
          s.important_item_missing, s.reviewed_at;

COMMENT ON VIEW v_discovery_value IS
'Layer E. UNEXPECTED_USEFUL_STRATEGIES_FOUND as a RATE per spot-check sample, never a raw count (D7): raw counts rise with library size regardless of quality. Expect the rate to DECLINE as the practitioner absorbs what the system surfaces; a near-zero rate early is the warning sign, not a success.';

GRANT SELECT ON v_discovery_value TO phi_runtime, phi_practitioner;


-- The trend, which is the only form in which layer E means anything: one
-- sample's rate is a small-sample number, and D7's expectation is about
-- the direction over time.
CREATE OR REPLACE VIEW v_discovery_value_trend
WITH (security_invoker = true) AS
SELECT date_trunc('month', sampled_at)::date AS month,
       count(*)                              AS samples,
       sum(items_reviewed)                   AS items_reviewed,
       round(sum(unexpected_useful)::numeric
             / nullif(sum(items_reviewed), 0), 4) AS unexpected_useful_rate,
       round(sum(irrelevant)::numeric
             / nullif(sum(items_reviewed), 0), 4) AS irrelevant_rate,
       count(*) FILTER (WHERE important_item_missing) AS samples_with_a_gap
  FROM v_discovery_value
 GROUP BY 1
 ORDER BY 1 DESC;

COMMENT ON VIEW v_discovery_value_trend IS
'Layer E over time. Pooled across samples rather than averaging per-sample rates, so a three-item sample does not weigh as much as a thirty-item one.';

GRANT SELECT ON v_discovery_value_trend TO phi_runtime, phi_practitioner;


-- =====================================================================
-- What the evaluation layers currently say
-- =====================================================================

CREATE OR REPLACE VIEW v_evaluation_state
WITH (security_invoker = true) AS
WITH latest AS (
    SELECT DISTINCT ON (layer) layer, run_id, started_at, tests_run,
           tests_passed, mean_score, vector_enabled, library_size
      FROM retrieval_test_runs
     WHERE finished_at IS NOT NULL
     ORDER BY layer, started_at DESC
)
SELECT l.code AS layer,
       l.description,
       (SELECT count(*) FROM retrieval_tests t
         WHERE t.layer::text = l.code AND t.active)      AS tests_defined,
       r.started_at   AS last_run_at,
       r.tests_run,
       r.tests_passed,
       r.mean_score,
       r.vector_enabled,
       r.library_size
  FROM (VALUES
        ('A', 'automated retrieval tests from the seeded domain structure'),
        ('B', 'source-grounded recovery on held-out sources'),
        ('C', 'cross-domain synthetic cases, per domain')
       ) AS l(code, description)
  LEFT JOIN latest r ON r.layer::text = l.code;

COMMENT ON VIEW v_evaluation_state IS
'Layers A-C at a glance. A layer with tests_defined = 0 has nothing to measure yet — normal while the library is young, and never to be reported as passing.';

GRANT SELECT ON v_evaluation_state TO phi_runtime, phi_practitioner;
