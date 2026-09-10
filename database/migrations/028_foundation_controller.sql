-- =====================================================================
-- 028_foundation_controller.sql   Step 22 — K00_FOUNDATION_CONTROLLER
--
-- BUILD_GUIDE: "Long-running, resumable, batched, cost-capped. Core
-- domains carry higher processing priority only — never a limit on what E7
-- may discover. WAVE1_FOUNDATION_READY is a computed operational state,
-- not a certification and not a meeting."
--
-- =====================================================================
-- THE BUDGET WAS A NAME, NOT A LIMIT
-- =====================================================================
--
-- `KNOWLEDGE_DAILY_TOKEN_BUDGET` has been in `.env.example` since the
-- beginning and **nothing has ever read it**. Every other stage of this
-- build ran on fixtures or one item at a time, so it never mattered.
--
-- K00 is the thing that would matter: a loop that discovers, ingests,
-- extracts, researches and synthesises until a domain is covered, over 26
-- domains, unattended. An unenforced budget on THAT is not an oversight,
-- it is the whole risk.
--
-- So the cap becomes a function over `cost_events` — measured from what
-- was actually spent, not from a counter the controller keeps and could
-- forget to increment — and every batch records the cap it ran under.
-- =====================================================================


CREATE OR REPLACE FUNCTION knowledge_spend_today()
RETURNS TABLE (tokens bigint, cost_usd numeric)
LANGUAGE sql STABLE AS $$
    SELECT coalesce(sum(coalesce(input_tokens, 0)
                        + coalesce(output_tokens, 0)), 0)::bigint,
           coalesce(sum(cost_usd), 0)::numeric
      FROM cost_events
     WHERE occurred_at >= date_trunc('day', now())
       -- Knowledge-clock work only. A client cycle is not knowledge
       -- building and must not eat the foundation budget, nor be blocked
       -- by it: a practitioner with a case in front of them is not waiting
       -- on tomorrow.
       AND (entity_type IS NULL OR entity_type NOT LIKE 'client%')
       AND coalesce(workflow, '') <> 'CLIENT_NEW'
$$;

COMMENT ON FUNCTION knowledge_spend_today() IS
'What the knowledge clock has spent today, from cost_events rather than from a counter the controller keeps. A counter can be forgotten to increment; the rows are what actually happened. Client work is excluded in both directions: it does not consume the foundation budget and is never blocked by it.';


-- ---------------------------------------------------------------------
-- Resumable state: where each domain is in the loop
-- ---------------------------------------------------------------------
--
-- "Resumable" means a restart continues rather than starting over. That
-- needs the cursor to be a row, not a variable — a controller that keeps
-- its position in memory has no position at all after a container
-- restart, and re-running a domain from DISCOVERY is how a bounded build
-- becomes an unbounded one.
-- ---------------------------------------------------------------------

CREATE TYPE foundation_stage AS ENUM (
    'DISCOVER',       -- K02-K06: find sources
    'INGEST',         -- K07/K08: envelope, normalize, chunk
    'EXTRACT',        -- K09: claims
    'RESEARCH',       -- K10: independent evidence
    'SYNTHESIZE',     -- K11: strategies
    'CONTROVERSY',    -- K12: disagreements and negative knowledge
    'GAP',            -- K13: what this domain still cannot answer
    'IDLE'            -- nothing to do right now. NOT "finished" (§70).
);

COMMENT ON TYPE foundation_stage IS
'Where a domain is in the K00 loop. IDLE means nothing is queued for it right now — it is NOT a COMPLETE status, which §70 forbids, and the next source to arrive puts the domain back to work.';


CREATE TABLE foundation_progress (
    domain_id       uuid PRIMARY KEY
                    REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    stage           foundation_stage NOT NULL DEFAULT 'DISCOVER',
    -- What the loop has done for this domain, cumulatively. Instrumentation
    -- and engineering floors, never definitions of quality (A4).
    passes          integer NOT NULL DEFAULT 0,
    items_processed integer NOT NULL DEFAULT 0,
    last_advanced   timestamptz,
    last_error      text,
    consecutive_errors integer NOT NULL DEFAULT 0,
    -- A domain whose stage keeps failing is PAUSED rather than retried
    -- forever: an unattended loop that retries a permanent failure spends
    -- the whole budget on it and covers nothing else.
    paused          boolean NOT NULL DEFAULT false,
    paused_reason   text,
    updated_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_progress_counts CHECK (passes >= 0 AND items_processed >= 0),
    CONSTRAINT ck_paused_has_reason CHECK (
        NOT paused OR (paused_reason IS NOT NULL
                       AND length(btrim(paused_reason)) > 0))
);

COMMENT ON TABLE foundation_progress IS
'K00 resume state, one row per domain. A controller that kept its cursor in memory would restart every domain from DISCOVER after a container restart — which turns a bounded build into an unbounded one.';

GRANT SELECT, INSERT, UPDATE ON foundation_progress TO phi_runtime;
GRANT SELECT ON foundation_progress TO phi_practitioner;


-- ---------------------------------------------------------------------
-- Every batch is recorded, with the cap it ran under
-- ---------------------------------------------------------------------

CREATE TABLE foundation_batches (
    batch_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    domains_touched integer NOT NULL DEFAULT 0,
    items_processed integer NOT NULL DEFAULT 0,
    stages_run      text[] NOT NULL DEFAULT '{}',

    -- The cap IN FORCE for this batch, recorded with the result. A budget
    -- read from the environment at run time and never written down cannot
    -- explain, a week later, why a batch stopped early.
    token_budget    bigint,
    tokens_before   bigint,
    tokens_after    bigint,
    cost_before     numeric(12,6),
    cost_after      numeric(12,6),

    stopped_reason  text,
    dry_run         boolean NOT NULL DEFAULT true
);

CREATE INDEX idx_foundation_batches_recent
    ON foundation_batches (started_at DESC);

COMMENT ON COLUMN foundation_batches.dry_run IS
'TRUE by default, and the controller defaults to it. K00 is the one component that could begin mass ingestion unattended, and the standing instruction is one source through the loop first — so executing is an explicit act, not a default.';

GRANT SELECT, INSERT, UPDATE ON foundation_batches TO phi_runtime;
GRANT SELECT ON foundation_batches TO phi_practitioner;


-- ---------------------------------------------------------------------
-- WAVE1_FOUNDATION_READY — computed, never stored
-- ---------------------------------------------------------------------
--
-- A4's four simultaneous dimensions: domain coverage, knowledge depth,
-- retrieval quality, and data quality / provenance. Counts here are
-- engineering floors and progress instrumentation, NEVER definitions of
-- quality — and there is no COMPLETE state anywhere (§70).
--
-- Computed rather than stored because a stored readiness flag is a claim
-- that outlives the thing it described: the library keeps moving, and a
-- row saying READY from three months ago is worse than no row.
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_wave1_readiness
WITH (security_invoker = true) AS
WITH domains AS (
    SELECT count(*) FILTER (WHERE is_core_domain)          AS core_domains,
           count(*)                                        AS all_domains
      FROM knowledge_domains WHERE active
),
readiness AS (
    SELECT count(*) FILTER (WHERE foundation_ready)        AS ready,
           count(*) FILTER (WHERE meets_depth_bar)         AS at_depth,
           count(*) FILTER (WHERE gap_assessment_complete) AS gap_assessed,
           count(*) FILTER (WHERE open_critical_gaps > 0)  AS with_critical_gaps
      FROM v_domain_readiness
     WHERE is_core_domain
),
depth AS (
    SELECT count(*) FILTER (WHERE knowledge_status <> 'DEPRECATED') AS strategies,
           count(*) FILTER (WHERE knowledge_status = 'AI_DISCOVERED_CANDIDATE')
                                                            AS candidates
      FROM strategies
),
retrieval AS (
    SELECT (SELECT count(*) FROM retrieval_tests WHERE active)      AS tests_defined,
           (SELECT mean_score FROM retrieval_test_runs
             WHERE finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1)
                                                                     AS last_mean_score
),
provenance AS (
    SELECT count(*) FILTER (WHERE knowledge_status <> 'AI_DISCOVERED_CANDIDATE'
                              AND provenance_note IS NULL)          AS unprovenanced,
           count(*) FILTER (WHERE NOT EXISTS (
               SELECT 1 FROM strategy_concepts sc
                WHERE sc.strategy_id = s.strategy_id))              AS unretrievable
      FROM strategies s
     WHERE s.knowledge_status <> 'DEPRECATED'
)
SELECT d.core_domains,
       d.all_domains,
       r.ready                       AS core_domains_ready,
       r.at_depth                    AS core_domains_at_depth,
       r.gap_assessed                AS core_domains_gap_assessed,
       r.with_critical_gaps          AS core_domains_with_critical_gaps,
       k.strategies,
       k.candidates,
       t.tests_defined,
       t.last_mean_score,
       p.unprovenanced,
       -- A strategy with no concepts is a strategy nothing will ever
       -- retrieve (D8). It counts against data quality, not against depth.
       p.unretrievable,
       -- All four dimensions at once, and every one of them a FLOOR.
       (d.core_domains > 0
        AND r.ready = d.core_domains
        AND k.strategies > 0
        AND t.tests_defined > 0
        AND p.unprovenanced = 0
        AND p.unretrievable = 0)     AS wave1_foundation_ready
  FROM domains d, readiness r, depth k, retrieval t, provenance p;

COMMENT ON VIEW v_wave1_readiness IS
'A4''s four dimensions at once: domain coverage, knowledge depth, retrieval quality, provenance. An operational state computed from telemetry the system already collects — not a certification, not a meeting, and never stored: a saved READY outlives the library it described. There is no COMPLETE (§70).';

GRANT SELECT ON v_wave1_readiness TO phi_runtime, phi_practitioner;


CREATE OR REPLACE VIEW v_foundation_queue
WITH (security_invoker = true) AS
SELECT d.domain_id,
       d.domain_key,
       d.name,
       d.is_core_domain,
       d.wave1_priority,
       coalesce(p.stage, 'DISCOVER'::foundation_stage) AS stage,
       coalesce(p.passes, 0)          AS passes,
       coalesce(p.items_processed, 0) AS items_processed,
       coalesce(p.paused, false)      AS paused,
       p.paused_reason,
       p.last_error,
       p.last_advanced
  FROM knowledge_domains d
  LEFT JOIN foundation_progress p ON p.domain_id = d.domain_id
 WHERE d.active
   -- Priority is a WEIGHT ON THIS QUEUE and nothing else. It decides what
   -- is processed first; it never restricts what Engine 7 may discover,
   -- and autonomous domain expansion continues regardless (BUILD_PLAN).
 ORDER BY coalesce(p.paused, false),
          d.is_core_domain DESC,
          d.wave1_priority DESC,
          coalesce(p.last_advanced, '-infinity'::timestamptz),
          d.domain_key;

COMMENT ON VIEW v_foundation_queue IS
'What K00 works on next. is_core_domain and wave1_priority order this queue and nothing else — they are processing priority, never a boundary on discovery.';

GRANT SELECT ON v_foundation_queue TO phi_runtime, phi_practitioner;
