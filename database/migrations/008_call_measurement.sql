-- =====================================================================
-- 008_call_measurement.sql
--
-- Step 10b needs to answer, per engine call: how many prompt tokens, how
-- many completion tokens, what it cost, how long it took, how many
-- attempts it needed, and whether the control block parsed.
--
-- cost_events already records tokens, latency and success from batch one,
-- one row per provider attempt. What it cannot do is say WHICH run an
-- attempt belongs to: it carries entity_id = client_id, so the two Engine 1
-- calls in a cycle -- Pass A and Pass B, the exact pair D5 asks us to
-- measure -- are indistinguishable in the cost table.
--
-- A. cost_events.run_id, so an attempt attributes to its run.
-- B. cost_events.price_source, so a cost is never silently a guess.
-- C. v_engine_call_measurement, the per-run measurement report.
--
-- entity_id is deliberately NOT repurposed. It is polymorphic across the
-- system (client, domain, strategy, document ids) and losing the client
-- attribution to gain the run attribution trades one gap for another.
-- =====================================================================


-- =====================================================================
-- A. Attribute a cost event to its engine run
-- =====================================================================
--
-- ON DELETE SET NULL rather than CASCADE: cost is operational telemetry
-- about money and latency, and deleting a client must not silently rewrite
-- what the month cost. The row survives with its tokens intact; only the
-- attribution goes.

ALTER TABLE cost_events
    ADD COLUMN IF NOT EXISTS run_id uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_cost_events_run
    ON cost_events (run_id) WHERE run_id IS NOT NULL;

COMMENT ON COLUMN cost_events.run_id IS
'The engine run this provider attempt belongs to. NULL for non-engine operations and for runs since deleted. Required to separate Engine 1 Pass A from Pass B, which share a client, a cycle and a prompt hash.';


-- =====================================================================
-- B. A cost is measured, priced, or unknown -- never invented
-- =====================================================================
--
-- cost_usd has existed since 001 and nothing has ever written to it. Once
-- something does, the number needs provenance: a rate applied from the
-- price registry is not the same claim as a charge reported by the
-- provider, and neither is the same as no rate being configured at all.
--
-- A registry miss must leave cost_usd NULL. A zero would read as "this
-- call was free", which is the one thing it certainly was not.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cost_price_source') THEN
        CREATE TYPE cost_price_source AS ENUM (
            'PROVIDER_REPORTED',  -- the provider told us what it charged
            'PRICE_REGISTRY',     -- our own rate card, applied to token counts
            'UNPRICED'            -- no rate configured for this model
        );
    END IF;
END $$;

ALTER TABLE cost_events
    ADD COLUMN IF NOT EXISTS price_source cost_price_source;

ALTER TABLE cost_events
    DROP CONSTRAINT IF EXISTS ck_cost_priced;
ALTER TABLE cost_events
    ADD CONSTRAINT ck_cost_priced CHECK (
        (price_source = 'UNPRICED' AND cost_usd IS NULL)
        OR price_source IS DISTINCT FROM 'UNPRICED'
    );

COMMENT ON COLUMN cost_events.price_source IS
'Where cost_usd came from. UNPRICED means no rate is configured for this model and cost_usd is NULL, enforced by ck_cost_priced: an unknown price is reported as unknown, never as zero.';


-- =====================================================================
-- C. The per-run measurement report
-- =====================================================================
--
-- One row per engine run. Tokens, cost and latency are summed across every
-- provider attempt the run made, because a run that needed a repair retry
-- genuinely cost two calls and that is the number worth knowing.
--
-- control_block_parsed reads engine_outputs, which is the only place a
-- validated control block can be: RUN_ENGINE dead-letters malformed output
-- rather than inserting it, so the presence of a schema_valid output row IS
-- the parse result.

CREATE OR REPLACE VIEW v_engine_call_measurement AS
SELECT
    r.run_id,
    r.client_id,
    r.cycle_id,
    r.engine,
    r.pass,
    r.prompt_file,
    -- Short form for reading; the full hash stays on engine_runs. Pass A
    -- and Pass B must show the SAME value here (see trg_enforce_two_pass).
    left(r.prompt_hash, 12)                       AS prompt_hash_short,
    r.model_role,
    r.model_name,
    r.status,
    r.started_at,

    -- Attempts as the cost table saw them: one row per call that actually
    -- reached the provider. engine_runs.attempts counts loop iterations,
    -- which also includes an attempt that failed before the provider
    -- answered. Both are reported; a divergence is informative.
    count(c.cost_event_id)                        AS provider_attempts,
    r.attempts                                    AS recorded_attempts,
    greatest(count(c.cost_event_id) - 1, 0)       AS retries,

    sum(c.input_tokens)                           AS prompt_tokens,
    sum(c.output_tokens)                          AS completion_tokens,
    sum(c.input_tokens) + sum(c.output_tokens)    AS total_tokens,

    -- NULL, not 0, when no attempt on this run had a configured rate.
    sum(c.cost_usd)                               AS cost_usd,
    bool_or(c.price_source = 'UNPRICED')          AS has_unpriced_attempt,

    sum(c.duration_ms)                            AS total_ms,
    max(c.duration_ms)                            AS slowest_attempt_ms,
    count(*) FILTER (WHERE NOT c.success)         AS provider_errors,

    (o.run_id IS NOT NULL AND o.schema_valid)     AS control_block_parsed,
    length(o.human_output)                        AS human_output_chars
FROM engine_runs r
LEFT JOIN cost_events   c ON c.run_id = r.run_id
LEFT JOIN engine_outputs o ON o.run_id = r.run_id
GROUP BY r.run_id, r.client_id, r.cycle_id, r.engine, r.pass, r.prompt_file,
         r.prompt_hash, r.model_role, r.model_name, r.status, r.attempts,
         r.started_at, o.run_id, o.schema_valid, o.human_output;

COMMENT ON VIEW v_engine_call_measurement IS
'Per-run engine call measurement for BUILD_GUIDE step 10b: prompt tokens, completion tokens, cost, latency, retries and control-block parse success. Sums every provider attempt a run made, so a repair retry is counted as the two calls it really was.';

-- Views run as their OWNER unless declared otherwise, which would make this
-- one an RLS bypass: it joins engine_runs and engine_outputs, both
-- row-level secured, and its owner is phi_admin. Same treatment every view
-- in 005 gets, and for the same reason.
ALTER VIEW v_engine_call_measurement SET (security_invoker = true);

GRANT SELECT ON v_engine_call_measurement TO phi_practitioner, phi_runtime;
