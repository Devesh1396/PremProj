-- 001_ops.sql
-- Operational telemetry. Created before any knowledge or client table so
-- that cost is instrumented from the very first extraction batch rather
-- than retrofitted once the curve is already a surprise.

-- ---------------------------------------------------------------------
-- Cost events
-- ---------------------------------------------------------------------
-- One row per billable model call, anywhere in the system. Deliberately
-- narrow: no clinical content, only identifiers, so this table can be
-- queried and exported freely without touching PHI.

CREATE TYPE cost_operation AS ENUM (
    'ENGINE_RUN',        -- engines 1-6
    'NORMALIZATION',     -- phrase -> canonical concept
    'CLAIM_EXTRACTION',
    'EVIDENCE_ANALYSIS',
    'STRATEGY_SYNTHESIS',
    'MERGE_DECISION',    -- the cost that grows with library size
    'CONTROVERSY_PASS',
    'NEGATIVE_KNOWLEDGE_PASS',
    'GAP_ANALYSIS',
    'DOMAIN_MAPPING',
    'LIVE_RESEARCH',
    'EMBEDDING',
    'RERANK',
    'OTHER'
);

CREATE TABLE cost_events (
    cost_event_id   bigserial PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    operation       cost_operation NOT NULL,
    model_role      text,           -- MODEL_ANALYSIS, MODEL_EXTRACTION, ...
    model_name      text,           -- resolved model at call time
    -- What this call was working on. Never free clinical text.
    entity_type     text,           -- 'domain' | 'strategy' | 'client_case' | ...
    entity_id       text,
    batch_id        uuid,           -- groups a foundation batch
    workflow        text,           -- n8n workflow name
    input_tokens    integer,
    output_tokens   integer,
    -- Provider-reported cost where available; otherwise computed later
    -- from a rate table. Nullable on purpose.
    cost_usd        numeric(12,6),
    duration_ms     integer,
    success         boolean NOT NULL DEFAULT true,
    error_class     text
);

CREATE INDEX idx_cost_events_time      ON cost_events (occurred_at DESC);
CREATE INDEX idx_cost_events_operation ON cost_events (operation, occurred_at DESC);
CREATE INDEX idx_cost_events_batch     ON cost_events (batch_id) WHERE batch_id IS NOT NULL;

COMMENT ON TABLE cost_events IS
'Per-call cost telemetry. Contains no clinical content by design. MERGE_DECISION cost per new card is the metric that reveals whether synthesis scales as the library grows.';

-- ---------------------------------------------------------------------
-- Job runs
-- ---------------------------------------------------------------------
-- Resumability spine. Foundation building must survive n8n restarts,
-- machine reboots and interrupted sessions.

CREATE TYPE job_status AS ENUM (
    'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD_LETTER', 'CANCELLED', 'SKIPPED'
);

CREATE TABLE job_runs (
    job_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        text        NOT NULL,   -- 'K01_DOMAIN_MAPPER', 'K09_CLAIM_EXTRACTOR', ...
    entity_type     text,
    entity_id       text,
    batch_id        uuid,
    status          job_status  NOT NULL DEFAULT 'PENDING',
    attempts        integer     NOT NULL DEFAULT 0,
    max_attempts    integer     NOT NULL DEFAULT 3,
    -- Checkpoint for resume. Small JSON only: cursor positions, page
    -- numbers, chapter index. Never accumulated content.
    checkpoint      jsonb,
    error_class     text,
    error_detail    text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    completed_at    timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_job_runs_claim  ON job_runs (job_type, status, created_at)
    WHERE status IN ('PENDING', 'FAILED');
CREATE INDEX idx_job_runs_batch  ON job_runs (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX idx_job_runs_entity ON job_runs (entity_type, entity_id);

-- Prevent the same unit of work being queued twice while live.
CREATE UNIQUE INDEX uq_job_runs_active
    ON job_runs (job_type, entity_type, entity_id)
    WHERE status IN ('PENDING', 'RUNNING');

CREATE TRIGGER trg_job_runs_updated
    BEFORE UPDATE ON job_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- Dead letter
-- ---------------------------------------------------------------------
-- Failures are never silently lost. Malformed structured output never
-- reaches the knowledge tables; it lands here after bounded retries.

CREATE TABLE dead_letter_jobs (
    dead_letter_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          uuid REFERENCES job_runs(job_id) ON DELETE SET NULL,
    job_type        text        NOT NULL,
    entity_type     text,
    entity_id       text,
    failure_reason  text        NOT NULL,
    -- Raw payload retained for diagnosis. May contain source text, so this
    -- table follows the same handling rules as knowledge content.
    raw_payload     jsonb,
    attempts        integer     NOT NULL DEFAULT 0,
    resolved        boolean     NOT NULL DEFAULT false,
    resolution_note text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz
);

CREATE INDEX idx_dead_letter_open ON dead_letter_jobs (job_type, created_at DESC)
    WHERE resolved = false;

-- ---------------------------------------------------------------------
-- Cost rollup
-- ---------------------------------------------------------------------

CREATE VIEW v_cost_by_operation AS
SELECT
    date_trunc('day', occurred_at)          AS day,
    operation,
    model_role,
    count(*)                                AS calls,
    sum(input_tokens)                       AS input_tokens,
    sum(output_tokens)                      AS output_tokens,
    round(sum(cost_usd), 4)                 AS cost_usd,
    round(avg(duration_ms)::numeric, 0)     AS avg_ms,
    count(*) FILTER (WHERE NOT success)     AS failures
FROM cost_events
GROUP BY 1, 2, 3
ORDER BY 1 DESC, cost_usd DESC NULLS LAST;

COMMENT ON VIEW v_cost_by_operation IS
'Daily cost by operation. Watch MERGE_DECISION and STRATEGY_SYNTHESIS: if cost per new card rises with library size, deterministic dedup is not filtering enough before the LLM call.';
