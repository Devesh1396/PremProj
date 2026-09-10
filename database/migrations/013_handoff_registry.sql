-- =====================================================================
-- 013_handoff_registry.sql — which substantive handoff each engine owes
--
-- The third instance of the pattern 010 and 012 established, and
-- deliberately not a third bespoke mechanism: the prompts became rows so
-- n8n could read a specification, the control contract became a row so n8n
-- could validate one, and now the expected handoff tags become rows so n8n
-- can tell whether an engine actually produced its reasoning.
--
-- WHAT THIS FIXES. Every prompt in prompts/ defines TWO machine-readable
-- outputs, not one:
--
--   <..._HANDOFF>      the substantive reasoning -- strategies, evidence,
--                      targets, implementation. What the next engine needs
--                      in order to think.
--   <CONTROL_BLOCK>    ~17 typed fields. What n8n routes and gates on.
--
-- RUN_ENGINE parsed only the second, `EngineResult.structured` was always
-- None, and `engine_outputs.structured` was written from the INPUT's
-- `_echo` key -- which nothing sets, so it stored `{}` on every run since
-- the engine layer was built. CLIENT_NEW then passed control blocks
-- downstream as `E7_HANDOFF` and `E1_HANDOFF`. The pipeline executed and
-- almost none of the reasoning flowed.
--
-- The two are not interchangeable and this migration is where that becomes
-- structural rather than a convention: a run whose required handoff is
-- absent cannot be recorded as having produced one.
--
-- MODES. Two engines emit different tags depending on what they were asked
-- to do, and confusing them would be worse than missing them:
--
--   E6  INIT / REBUILD -> <CASE_MEMORY_HANDOFF>   full state
--       UPDATE         -> <CASE_MEMORY_DELTA>     only what changed
--   E7  CASE           -> <RESEARCH_PRACTICE_CASE_HANDOFF>
--       FOUNDATION     -> <RESEARCH_PRACTICE_FOUNDATION_HANDOFF>
--
-- Engine 6 §A1: "Emit the full <CASE_MEMORY_HANDOFF> when establishing or
-- rebuilding state, and the <CASE_MEMORY_DELTA> when recording an
-- incremental change. The delta is the normal path on follow-up. Do not
-- restate unchanged state as though it were new."
--
-- A delta is NOT a state. client_case_versions.canonical_state is
-- documented in 004 as "Full canonical state (CASE_MEMORY_HANDOFF)" and
-- `delta` as "Only what changed (CASE_MEMORY_DELTA)" -- two columns,
-- because they are two things. Storing a delta in the state column would
-- make get_current_client_state() return a description of a change as
-- though it were the case.
--
-- Modes are ROWS, not an enum (D19): adding one is an INSERT.
-- =====================================================================


-- =====================================================================
-- 1. The registry
-- =====================================================================

CREATE TABLE IF NOT EXISTS engine_handoffs (
    handoff_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    engine      engine_id NOT NULL,

    -- What the engine was asked to do. The vocabulary is this table's
    -- contents; a new mode is an INSERT, not a migration and not an enum
    -- edit (D19).
    mode        text NOT NULL,

    -- The tag, without angle brackets: CASE_MEMORY_HANDOFF, not
    -- <CASE_MEMORY_HANDOFF>. Stored bare so a caller cannot half-include
    -- the brackets and produce a tag that never matches.
    tag         text NOT NULL,

    -- REQUIRED means a response without this block is not a successful
    -- run: it goes through the repair retry and then dead-letters, exactly
    -- as an invalid control block does. Optional means "accept it if it is
    -- there" -- E6 may emit a delta alongside a rebuilt state, and
    -- discarding it would lose the only record of what changed.
    required    boolean NOT NULL DEFAULT true,

    -- Which prompt section defines it, so a stored row can be traced back
    -- to the specification the way a strategy is traced to its evidence.
    prompt_ref  text NOT NULL,
    note        text,

    active      boolean NOT NULL DEFAULT true,
    loaded_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_handoff_tag_shape  CHECK (tag ~ '^[A-Z][A-Z0-9_]{2,79}$'),
    CONSTRAINT ck_handoff_mode_shape CHECK (mode ~ '^[A-Z][A-Z0-9_]{1,31}$'),
    -- CONTROL_BLOCK is the other thing entirely. Registering it here would
    -- be the exact conflation this table exists to prevent.
    CONSTRAINT ck_handoff_not_control CHECK (tag <> 'CONTROL_BLOCK')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_engine_handoff
    ON engine_handoffs (engine, mode, tag);

CREATE INDEX IF NOT EXISTS idx_engine_handoffs_lookup
    ON engine_handoffs (engine, mode) WHERE active;

COMMENT ON TABLE engine_handoffs IS
'Which substantive machine-readable handoff each engine owes in each mode (D24). The runtime read path for RUN_ENGINE and for the n8n port, which issues the identical SELECT. Distinct from orchestration_contracts: that governs the CONTROL BLOCK, which is for routing and gating; this governs the handoff, which is what the next engine reasons over. They are never interchangeable.';

COMMENT ON COLUMN engine_handoffs.required IS
'A response missing a required handoff is repaired and then dead-lettered, exactly like an invalid control block. A valid control block is not evidence that an engine did its work.';


-- =====================================================================
-- 2. What was actually extracted
-- =====================================================================
--
-- engine_outputs.structured has existed since 004 and has only ever held
-- `{}`. It now holds the parsed handoff, and these two columns say which
-- block it came from -- otherwise a reader cannot tell a full E6 state
-- from an E6 delta by looking at the row, which is precisely the
-- distinction that matters.

ALTER TABLE engine_outputs
    ADD COLUMN IF NOT EXISTS handoff_tag  text,
    ADD COLUMN IF NOT EXISTS handoff_mode text;

COMMENT ON COLUMN engine_outputs.structured IS
'The parsed substantive handoff — the engine''s reasoning, not its routing fields. Empty object means the engine emitted no handoff block, which is only permissible where the registry marks it optional.';

COMMENT ON COLUMN engine_outputs.handoff_tag IS
'Which block `structured` was parsed from, e.g. CASE_MEMORY_HANDOFF or CASE_MEMORY_DELTA. NULL means none was found. Without this a delta and a full state are indistinguishable in the row.';

-- Every extra block an engine emitted beyond the primary one. E6 rebuilding
-- state may also report what changed, and that delta is the only record of
-- it; dropping it because the primary tag was the state would lose it.
ALTER TABLE engine_outputs
    ADD COLUMN IF NOT EXISTS secondary_handoffs jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE engine_outputs
    DROP CONSTRAINT IF EXISTS ck_secondary_handoffs_object;
ALTER TABLE engine_outputs
    ADD CONSTRAINT ck_secondary_handoffs_object
        CHECK (jsonb_typeof(secondary_handoffs) = 'object');

COMMENT ON COLUMN engine_outputs.secondary_handoffs IS
'Additional registered blocks the same response carried, keyed by tag. E6 in REBUILD mode emits the full state AND the delta; the state is `structured` and the delta lands here rather than being discarded.';


-- =====================================================================
-- 3. Access
-- =====================================================================
--
-- No RLS, same as the other two registries: a specification of what an
-- engine owes is not client data and is identical for every client.

GRANT SELECT ON engine_handoffs TO phi_runtime, phi_practitioner;

CREATE OR REPLACE VIEW v_engine_handoff_registry
WITH (security_invoker = true) AS
SELECT engine, mode,
       array_agg(tag ORDER BY tag) FILTER (WHERE required)       AS required_tags,
       array_agg(tag ORDER BY tag) FILTER (WHERE NOT required)   AS optional_tags,
       count(*)                                                  AS registered_tags
FROM engine_handoffs
WHERE active
GROUP BY engine, mode
ORDER BY engine, mode;

COMMENT ON VIEW v_engine_handoff_registry IS
'What each engine owes in each mode, one row per (engine, mode). The runtime lookup RUN_ENGINE and the n8n port both read.';

GRANT SELECT ON v_engine_handoff_registry TO phi_runtime, phi_practitioner;


-- A run that succeeded without recording the reasoning it was supposed to
-- produce. Should always be empty; if it is not, something is accepting a
-- control block as evidence of work.
CREATE OR REPLACE VIEW v_runs_missing_handoff
WITH (security_invoker = true) AS
SELECT r.run_id, r.client_id, r.cycle_id, r.engine, r.pass,
       r.model_name, r.started_at,
       o.handoff_tag, o.handoff_mode,
       jsonb_typeof(o.structured) AS structured_kind
FROM engine_runs r
JOIN engine_outputs o ON o.run_id = r.run_id
WHERE r.status = 'SUCCEEDED'
  AND (o.handoff_tag IS NULL OR o.structured = '{}'::jsonb);

COMMENT ON VIEW v_runs_missing_handoff IS
'Successful runs that recorded no substantive handoff. Expected to be empty: a required handoff is enforced at run time, so a row here means a registry gap or an engine mode nobody registered.';

GRANT SELECT ON v_runs_missing_handoff TO phi_runtime, phi_practitioner;
