-- =====================================================================
-- 014_engine_run_scope.sql — make RUN_ENGINE runnable as phi_runtime
--
-- Found while preparing the n8n port, and it is a real blocker rather than
-- a tidy-up. Connecting as phi_runtime and calling run_engine() fails on
-- its FIRST statement, both ways:
--
--   client run       InsufficientPrivilege: new row violates row-level
--   knowledge clock  security policy for table "engine_runs"
--
-- Two independent causes, and the Python reference has never hit either
-- because DATABASE_URL connects as phi_admin, which is SUPERUSER and so
-- bypasses RLS entirely. Every engine run this system has ever made went
-- around the policies rather than through them. n8n connects as
-- phi_runtime (hard rule 8) and would have been the first thing to
-- discover that, in production.
--
-- CAUSE 1 -- nothing ever set the scope. scripts/ never calls
-- set_client_scope(); only testing/test_case_events.py does. Fixed in
-- scripts/run_engine.py, not here: every write now runs inside an explicit
-- transaction that sets transaction-local scope first, and the n8n
-- workflow mirrors that in every Postgres node. See D25.
--
-- CAUSE 2 -- and this is the part that needs a migration. The runtime
-- policy on engine_runs is:
--
--     USING (client_id = current_client_scope())
--
-- A knowledge-clock run has NO client: Engine 7 in FOUNDATION, UPDATE or
-- INBOX mode carries client_id NULL and CASE_VERSION 0 (D18). NULL =
-- anything is NULL, never true, so those runs are unwritable as
-- phi_runtime no matter what scope is set. The knowledge clock is not
-- client data and cannot be made to have a client just to satisfy a
-- policy.
--
-- 005 already made exactly this judgement for chat_threads and
-- chat_messages: "General practitioner chat has client_id NULL and carries
-- no client data, so it stays readable without a client context." The same
-- reasoning applies to a knowledge-clock run, so the same policy shape is
-- used rather than a new mechanism.
--
-- WHAT THIS DOES NOT DO. It does not widen access to client rows. A run
-- WITH a client_id is still visible only under that client's scope, and
-- the pooled-connection leakage test in testing/test_case_events.py proves
-- two consecutive runs for different clients on ONE connection cannot see
-- each other.
-- =====================================================================


-- =====================================================================
-- 1. engine_runs — a run with no client is a knowledge-clock run
-- =====================================================================

DROP POLICY IF EXISTS rls_runtime_engine_runs ON engine_runs;
CREATE POLICY rls_runtime_engine_runs ON engine_runs FOR ALL TO phi_runtime
    USING (client_id IS NULL OR client_id = current_client_scope())
    WITH CHECK (client_id IS NULL OR client_id = current_client_scope());

COMMENT ON POLICY rls_runtime_engine_runs ON engine_runs IS
'A run with a client is visible only under that client''s transaction-local scope. A run with NO client is a knowledge-clock run (Engine 7 FOUNDATION / UPDATE / INBOX, CASE_VERSION 0, D18): it carries no client data and cannot be given a client merely to satisfy a policy. Same judgement 005 made for chat_threads.';


-- =====================================================================
-- 2. engine_outputs — follows its run
-- =====================================================================
--
-- The output of a knowledge-clock run is no more client data than the run
-- is. The join stays: an output is reachable exactly when its run is.

DROP POLICY IF EXISTS rls_runtime_engine_outputs ON engine_outputs;
CREATE POLICY rls_runtime_engine_outputs ON engine_outputs FOR ALL TO phi_runtime
    USING (EXISTS (SELECT 1 FROM engine_runs r
                    WHERE r.run_id = engine_outputs.run_id
                      AND (r.client_id IS NULL
                           OR r.client_id = current_client_scope())))
    WITH CHECK (EXISTS (SELECT 1 FROM engine_runs r
                         WHERE r.run_id = engine_outputs.run_id
                           AND (r.client_id IS NULL
                                OR r.client_id = current_client_scope())));

COMMENT ON POLICY rls_runtime_engine_outputs ON engine_outputs IS
'Reachable exactly when the run it belongs to is reachable. The output of a knowledge-clock run is no more client data than the run.';


-- =====================================================================
-- 3. A view that answers "did anything run unscoped that should not have"
-- =====================================================================
--
-- The policy now tolerates NULL client_id, so a bug that dropped the
-- client from a CASE run would no longer be rejected -- it would be
-- silently filed as a knowledge-clock run. This is the check for that:
-- only Engine 7 has knowledge-clock modes, so any other engine with no
-- client is wrong.

CREATE OR REPLACE VIEW v_runs_without_client
WITH (security_invoker = true) AS
SELECT run_id, engine, pass, model_role, model_name, status, started_at
FROM engine_runs
WHERE client_id IS NULL
  AND engine <> 'E7';

COMMENT ON VIEW v_runs_without_client IS
'Runs with no client that are not Engine 7. Expected to be empty: only Engine 7 has knowledge-clock modes (FOUNDATION / UPDATE / INBOX), so any other engine without a client lost it somewhere rather than never having had one.';

GRANT SELECT ON v_runs_without_client TO phi_runtime, phi_practitioner;
