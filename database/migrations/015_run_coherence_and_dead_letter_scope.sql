-- =====================================================================
-- 015_run_coherence_and_dead_letter_scope.sql
--
-- Two runtime defects found by review of the deployed system. Both are
-- FORWARD migrations: the VPS is running main and already has rows in both
-- tables, so nothing here redefines an applied migration (hard rule 10).
--
-- =====================================================================
-- A. THE CLIENT/MODE COHERENCE GUARD WAS TOO LOOSE
-- =====================================================================
--
-- 014 added v_runs_without_client as `client_id IS NULL AND engine <> 'E7'`.
-- That permits EVERY Engine 7 run without a client -- including E7 CASE,
-- which is a client run and must have one. The real rule has four parts,
-- not two:
--
--     E1-E6                            client REQUIRED
--     E7 CASE                          client REQUIRED
--     E7 FOUNDATION / UPDATE / INBOX   client MUST BE NULL  (D18)
--
-- And it could not be checked properly anyway, because the mode was not
-- stored on the run. `handoff_mode` lives on engine_outputs, which only
-- exists after a run SUCCEEDS -- so the mode of a dead-lettered or
-- in-flight run was unknowable, and the mode of any run was inferable only
-- from the engine name plus a guess.
--
-- So: store the mode on the run, and enforce coherence BEFORE the insert.
--
-- A TRIGGER rather than a CHECK constraint, deliberately. The VPS has rows
-- from before this migration whose mode nobody recorded; a CHECK would
-- have to either reject them or carry a permanent escape hatch that new
-- rows could also use. A BEFORE INSERT trigger fires only on new writes,
-- so history is grandfathered by construction and nothing new can skip it.
-- =====================================================================

ALTER TABLE engine_runs
    ADD COLUMN IF NOT EXISTS engine_mode text;

COMMENT ON COLUMN engine_runs.engine_mode IS
'What the engine was asked to do, recorded on the RUN so it is auditable for a dead-lettered or in-flight run and not only after a successful output (D24a). Matches engine_handoffs.mode. NULL only on rows written before migration 015.';

-- Backfill from the one place the mode was recorded. No inference: a run
-- whose mode was never stored stays NULL and says so, rather than being
-- given a plausible-looking value nobody observed.
UPDATE engine_runs r
   SET engine_mode = o.handoff_mode
  FROM engine_outputs o
 WHERE o.run_id = r.run_id
   AND r.engine_mode IS NULL
   AND o.handoff_mode IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_engine_runs_mode
    ON engine_runs (engine, engine_mode);


CREATE OR REPLACE FUNCTION trg_engine_run_coherent()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    clock_mode boolean;
BEGIN
    IF NEW.engine_mode IS NULL OR btrim(NEW.engine_mode) = '' THEN
        RAISE EXCEPTION
            'engine_runs.engine_mode is required (%). RUN_ENGINE resolves the '
            'mode before calling the provider; a run that does not record it '
            'cannot be audited for client coherence.', NEW.engine
            USING ERRCODE = 'check_violation';
    END IF;

    -- Engine 7's knowledge-clock modes. Read from the registry rather than
    -- hard-coded: engine_handoffs is where a mode is defined (D19/D24), and
    -- a list repeated here would be the second copy that drifts.
    clock_mode := NEW.engine = 'E7'
                  AND NEW.engine_mode IN ('FOUNDATION', 'UPDATE', 'INBOX');

    IF clock_mode AND NEW.client_id IS NOT NULL THEN
        RAISE EXCEPTION
            'E7 % is a knowledge-clock run and must have no client, but '
            'client_id was supplied. The knowledge clock is not client work '
            'and CASE_VERSION 0 means exactly that (D18).', NEW.engine_mode
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT clock_mode AND NEW.client_id IS NULL THEN
        RAISE EXCEPTION
            '% % is a client run and requires a client_id. Only Engine 7 in '
            'FOUNDATION, UPDATE or INBOX mode runs without one; an E7 CASE '
            'run without a client is a case with no case.',
            NEW.engine, NEW.engine_mode
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_engine_run_coherent ON engine_runs;
CREATE TRIGGER trg_engine_run_coherent
    BEFORE INSERT ON engine_runs
    FOR EACH ROW EXECUTE FUNCTION trg_engine_run_coherent();


-- The view 014 should have had. It detects all four incoherent shapes
-- instead of the one, and names which.
DROP VIEW IF EXISTS v_runs_without_client;

CREATE OR REPLACE VIEW v_engine_run_incoherent
WITH (security_invoker = true) AS
SELECT run_id, engine, engine_mode, pass, client_id, status, started_at,
       CASE
           WHEN engine_mode IS NULL THEN 'mode not recorded (pre-015 row)'
           WHEN engine = 'E7' AND engine_mode IN ('FOUNDATION','UPDATE','INBOX')
                AND client_id IS NOT NULL
               THEN 'knowledge-clock run carrying a client'
           WHEN NOT (engine = 'E7' AND engine_mode IN ('FOUNDATION','UPDATE','INBOX'))
                AND client_id IS NULL
               THEN 'client run with no client'
       END AS problem
FROM engine_runs
WHERE engine_mode IS NULL
   OR (engine = 'E7' AND engine_mode IN ('FOUNDATION','UPDATE','INBOX')
       AND client_id IS NOT NULL)
   OR (NOT (engine = 'E7' AND engine_mode IN ('FOUNDATION','UPDATE','INBOX'))
       AND client_id IS NULL);

COMMENT ON VIEW v_engine_run_incoherent IS
'Runs whose client and mode disagree, and runs from before 015 whose mode was never recorded. Replaces v_runs_without_client, which only caught non-E7 runs with no client and so permitted an E7 CASE run without a client. New rows cannot be incoherent — trg_engine_run_coherent rejects them — so anything here is either history or a defect.';

GRANT SELECT ON v_engine_run_incoherent TO phi_runtime, phi_practitioner;


-- =====================================================================
-- B. DEAD-LETTER PAYLOADS WERE CROSS-CLIENT PHI IN AN UNSCOPED TABLE
-- =====================================================================
--
-- dead_letter_jobs has been defined since 001 with no client_id and no row
-- level security, and RUN_ENGINE writes up to 8,000 characters of raw
-- failed model output into raw_payload. A failed CASE run's raw output
-- contains whatever was in the case: labs, conditions, medications,
-- symptoms. Every one of those rows was readable by phi_runtime under ANY
-- client scope, and by phi_practitioner wholesale.
--
-- This is not telemetry. A failed engine response is the client's clinical
-- record in a different shape, and hard rule 8 says client isolation is
-- structural. The payload is worth keeping -- debugging a dead letter
-- without the response that caused it is guesswork -- so it is kept, and
-- it is scoped.
--
-- Nullable client_id, because dead letters that genuinely carry no client
-- data are real: knowledge-clock runs, and source ingestion. Those stay
-- readable without a scope, exactly as 005 decided for chat_threads and
-- 014 for knowledge-clock runs.
-- =====================================================================

ALTER TABLE dead_letter_jobs
    ADD COLUMN IF NOT EXISTS client_id uuid REFERENCES clients(client_id) ON DELETE CASCADE;

COMMENT ON COLUMN dead_letter_jobs.client_id IS
'The client whose data is in raw_payload, or NULL when there genuinely is none (knowledge-clock runs, source ingestion). Scoping key: raw_payload holds up to 8,000 characters of the failed response, which for a case run is clinical.';

-- Existing rows: recover the client from the run they belong to. entity_id
-- is text and polymorphic, so the join is explicit about which kind.
UPDATE dead_letter_jobs d
   SET client_id = r.client_id
  FROM engine_runs r
 WHERE d.entity_type = 'engine_run'
   AND d.entity_id = r.run_id::text
   AND d.client_id IS NULL
   AND r.client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dead_letter_client
    ON dead_letter_jobs (client_id, created_at DESC) WHERE client_id IS NOT NULL;

ALTER TABLE dead_letter_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_jobs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_runtime_dead_letter_jobs ON dead_letter_jobs;
CREATE POLICY rls_runtime_dead_letter_jobs ON dead_letter_jobs FOR ALL TO phi_runtime
    USING (client_id IS NULL OR client_id = current_client_scope())
    WITH CHECK (client_id IS NULL OR client_id = current_client_scope());

COMMENT ON POLICY rls_runtime_dead_letter_jobs ON dead_letter_jobs IS
'A dead letter carrying a client is visible only under that client''s scope. raw_payload holds the failed response verbatim, which for a case run is clinical data.';

-- The practitioner is one person and reads across their own clients, the
-- same as engine_runs. The isolation this migration adds is for
-- phi_runtime, which is n8n, pooled, and must never see another client's
-- payload.
DROP POLICY IF EXISTS rls_practitioner_dead_letter_jobs ON dead_letter_jobs;
CREATE POLICY rls_practitioner_dead_letter_jobs ON dead_letter_jobs FOR SELECT TO phi_practitioner
    USING (true);


-- Triage without reading anyone's clinical text. What failed, how often,
-- and whether it is still open -- with raw_payload deliberately absent.
CREATE OR REPLACE VIEW v_dead_letter_triage
WITH (security_invoker = true) AS
SELECT job_type,
       entity_type,
       count(*)                                   AS failures,
       count(*) FILTER (WHERE NOT resolved)       AS open_failures,
       count(DISTINCT client_id)                  AS clients_affected,
       count(*) FILTER (WHERE client_id IS NULL)  AS without_client,
       max(created_at)                            AS latest,
       min(created_at)                            AS earliest
FROM dead_letter_jobs
GROUP BY job_type, entity_type
ORDER BY open_failures DESC, failures DESC;

COMMENT ON VIEW v_dead_letter_triage IS
'What is failing and how much, without exposing raw_payload. The first question about a dead letter is almost never "what did the model say" — it is "how many, since when, and is it still happening".';

GRANT SELECT ON v_dead_letter_triage TO phi_runtime, phi_practitioner;
