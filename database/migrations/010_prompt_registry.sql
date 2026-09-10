-- =====================================================================
-- 010_prompt_registry.sql — the prompts become rows (DECISIONS.md D23)
--
-- CLAUDE.md: the finished system must keep working on n8n + PostgreSQL +
-- an LLM API alone. Step 11 ports RUN_ENGINE to n8n, and that is the first
-- thing that tests the sentence. It fails at once: run_engine.py loads
-- prompts/engine1_prevention.md off this repository's working tree, and
-- n8n runs in a container that has never seen this repository.
--
-- So the prompt becomes a row. prompts/*.md stays the AUTHORED form —
-- reviewed, diffed, version-controlled — and this table is the RUNTIME
-- form. Exactly the relationship database/migrations/ already has with
-- schema_migrations.
--
-- Two things this must not weaken:
--
--   Hard rule 7 — RUN_ENGINE raises PromptMissing rather than falling back
--   to a stub. No active row for an engine means no run. There is no
--   default prompt, no empty string, no "" NOT NULL escape hatch.
--
--   D4 — both Engine 1 passes record the identical prompt hash. They now
--   read the same row, so the invariant holds by construction instead of
--   by two code paths agreeing. trg_enforce_two_pass stays exactly as it
--   is; this migration removes the only way it could have been tripped
--   legitimately (the working tree changing between Pass A and Pass B).
--
-- Append-only. Content is never rewritten under a recorded hash, because
-- the hash in engine_runs is the provenance link back to the text that
-- produced an output.
-- =====================================================================


-- =====================================================================
-- 1. The registry
-- =====================================================================

CREATE TABLE IF NOT EXISTS engine_prompts (
    prompt_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Which engine this specification IS. Reuses the engine enum from 004
    -- so a typo cannot invent an eighth engine.
    engine        engine_id NOT NULL,

    -- The authored file it came from, carried through so a stored row can
    -- be traced back to a path in the repository.
    prompt_file   text NOT NULL,

    -- The full specification. Not summarised, not trimmed: hard rule 1.
    content       text NOT NULL,

    -- sha256 of content. Computed by the loader from the same bytes
    -- run_engine.py hashed before, so hashes recorded in engine_runs
    -- before this migration still resolve.
    prompt_hash   text NOT NULL,

    -- Exactly one active version per engine; see the partial unique index.
    active        boolean NOT NULL DEFAULT true,

    loaded_at     timestamptz NOT NULL DEFAULT now(),
    loaded_by     text NOT NULL DEFAULT current_user,
    superseded_at timestamptz,

    -- A specification is a long document. An empty or whitespace-only one
    -- is a broken load, and broken loads must not be runnable.
    CONSTRAINT ck_prompt_not_blank      CHECK (length(btrim(content)) > 0),
    CONSTRAINT ck_prompt_hash_shape     CHECK (prompt_hash ~ '^[0-9a-f]{64}$'),
    -- An active row has not been superseded; a superseded row is not active.
    CONSTRAINT ck_prompt_active_coherent
        CHECK ((active AND superseded_at IS NULL) OR (NOT active AND superseded_at IS NOT NULL))
);

-- Append-only identity. Loading the same file twice with the same content
-- is a no-op, not a second row; loading changed content is a NEW row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_engine_prompt_version
    ON engine_prompts (prompt_file, prompt_hash);

-- The rule that makes "which prompt does E1 run" have exactly one answer.
CREATE UNIQUE INDEX IF NOT EXISTS uq_engine_prompt_active
    ON engine_prompts (engine) WHERE active;

CREATE INDEX IF NOT EXISTS idx_engine_prompts_hash
    ON engine_prompts (prompt_hash);

COMMENT ON TABLE engine_prompts IS
'Runtime source of the seven engine specifications (D23). prompts/*.md is the authored form; this is what RUN_ENGINE reads, so n8n needs no filesystem. Append-only: superseding a prompt inserts a new row and deactivates the old one, because engine_runs.prompt_hash is a provenance link to text that must stay readable.';

COMMENT ON COLUMN engine_prompts.prompt_hash IS
'sha256 of content. Both Engine 1 passes read the same active row, so D4''s identical-hash rule holds by construction rather than by agreement between two code paths.';

COMMENT ON COLUMN engine_prompts.active IS
'Exactly one row per engine is active (uq_engine_prompt_active). No active row means RUN_ENGINE raises PromptMissing — there is no stub and no fallback.';


-- =====================================================================
-- 2. Append-only, enforced rather than requested
-- =====================================================================
--
-- Rewriting content under a recorded hash would silently relabel every
-- past run that cites it. The trigger blocks the content and hash columns
-- specifically; activation state and superseded_at must stay writable,
-- since that is how a new version takes over.

CREATE OR REPLACE FUNCTION trg_engine_prompts_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.content <> OLD.content OR NEW.prompt_hash <> OLD.prompt_hash
       OR NEW.engine <> OLD.engine OR NEW.prompt_file <> OLD.prompt_file THEN
        RAISE EXCEPTION
            'engine_prompts is append-only: prompt % (hash %) cannot be rewritten. '
            'engine_runs cites this hash as the text that produced an output. '
            'Insert a new version and deactivate this one.',
            OLD.prompt_file, left(OLD.prompt_hash, 12)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_engine_prompts_append_only ON engine_prompts;
CREATE TRIGGER trg_engine_prompts_append_only
    BEFORE UPDATE ON engine_prompts
    FOR EACH ROW EXECUTE FUNCTION trg_engine_prompts_append_only();

-- Deleting a prompt row orphans every engine_runs.prompt_hash citing it.
CREATE OR REPLACE FUNCTION trg_engine_prompts_no_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM engine_runs WHERE prompt_hash = OLD.prompt_hash) THEN
        RAISE EXCEPTION
            'prompt % (hash %) has produced engine runs and cannot be deleted. '
            'Deactivate it instead: an output that cannot be traced to a '
            'specification is worse than no output.',
            OLD.prompt_file, left(OLD.prompt_hash, 12)
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_engine_prompts_no_delete ON engine_prompts;
CREATE TRIGGER trg_engine_prompts_no_delete
    BEFORE DELETE ON engine_prompts
    FOR EACH ROW EXECUTE FUNCTION trg_engine_prompts_no_delete();


-- =====================================================================
-- 3. Access
-- =====================================================================
--
-- NOT client-scoped and deliberately no RLS: a specification is not client
-- data. It carries no PHI, it is identical for every client, and scoping
-- it would mean n8n could not read it without a client scope set — which
-- is exactly the case for a knowledge-clock run (D18, CASE_VERSION 0).
--
-- phi_runtime reads and never writes. Loading a prompt is an
-- administrative act performed by scripts/load_prompts.py as phi_admin,
-- in the same class as applying a migration.

GRANT SELECT ON engine_prompts TO phi_runtime, phi_practitioner;

CREATE OR REPLACE VIEW v_active_engine_prompts
WITH (security_invoker = true) AS
SELECT engine, prompt_file, prompt_hash, length(content) AS content_chars,
       loaded_at, loaded_by
FROM engine_prompts
WHERE active
ORDER BY engine;

COMMENT ON VIEW v_active_engine_prompts IS
'What each engine will actually run, without dumping seven specifications into the output. Content is deliberately omitted; length is here because a prompt that suddenly got short is worth noticing.';

GRANT SELECT ON v_active_engine_prompts TO phi_runtime, phi_practitioner;
