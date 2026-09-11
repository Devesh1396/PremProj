-- =====================================================================
-- 020_mode_client_rule_from_registry.sql
--
-- 015 said this, in its own comment, and then did the opposite:
--
--     -- Engine 7's knowledge-clock modes. Read from the registry rather
--     -- than hard-coded: engine_handoffs is where a mode is defined
--     -- (D19/D24), and a list repeated here would be the second copy
--     -- that drifts.
--     clock_mode := NEW.engine = 'E7'
--                   AND NEW.engine_mode IN ('FOUNDATION', 'UPDATE', 'INBOX');
--
-- That IS the second copy. It was harmless while E7 had exactly four
-- modes and nobody added one; the moment a fifth knowledge-clock mode is
-- registered, the trigger classifies it as a CLIENT run and rejects every
-- correct call to it -- with a message about a case with no case, which
-- names the wrong problem entirely.
--
-- K10 and K11 add exactly such modes, so the rule moves to where a mode is
-- already defined. Adding a mode stays an INSERT (D19).
-- =====================================================================

ALTER TABLE engine_handoffs
    ADD COLUMN IF NOT EXISTS client_required boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN engine_handoffs.client_required IS
'Whether a run in this (engine, mode) is client work. false marks a knowledge-clock mode, which must have NO client and emits CASE_VERSION 0 (D18). trg_engine_run_coherent reads this rather than carrying its own list of modes.';

-- The four that existed when 015 was written, with the rule it hard-coded.
UPDATE engine_handoffs SET client_required = false
 WHERE engine = 'E7' AND mode IN ('FOUNDATION', 'UPDATE', 'INBOX');
UPDATE engine_handoffs SET client_required = true
 WHERE NOT (engine = 'E7' AND mode IN ('FOUNDATION', 'UPDATE', 'INBOX'));


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

    -- From the registry, which is where a mode is defined. An unregistered
    -- (engine, mode) has no rule and cannot be judged -- and it would fail
    -- at the handoff lookup anyway, with a message that says so.
    SELECT bool_and(NOT h.client_required) INTO clock_mode
      FROM engine_handoffs h
     WHERE h.engine = NEW.engine AND h.mode = NEW.engine_mode AND h.active;

    IF clock_mode IS NULL THEN
        RAISE EXCEPTION
            'no active handoff is registered for % in mode %, so there is no '
            'rule for whether it is client work. Register it with '
            'scripts/load_handoffs.py before running it.',
            NEW.engine, NEW.engine_mode
            USING ERRCODE = 'check_violation';
    END IF;

    IF clock_mode AND NEW.client_id IS NOT NULL THEN
        RAISE EXCEPTION
            '% % is a knowledge-clock run and must have no client, but '
            'client_id was supplied. The knowledge clock is not client work '
            'and CASE_VERSION 0 means exactly that (D18).',
            NEW.engine, NEW.engine_mode
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT clock_mode AND NEW.client_id IS NULL THEN
        RAISE EXCEPTION
            '% % is a client run and requires a client_id. Only a mode '
            'registered with client_required=false runs without one; an E7 '
            'CASE run without a client is a case with no case.',
            NEW.engine, NEW.engine_mode
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;


-- The view carried the same hard-coded list. Same fix.
CREATE OR REPLACE VIEW v_engine_run_incoherent
WITH (security_invoker = true) AS
SELECT r.run_id, r.engine, r.engine_mode, r.pass, r.client_id, r.status,
       r.started_at,
       CASE
           WHEN r.engine_mode IS NULL THEN 'mode not recorded (pre-015 row)'
           WHEN h.client_required IS NULL THEN 'mode is not registered'
           WHEN NOT h.client_required AND r.client_id IS NOT NULL
               THEN 'knowledge-clock run carrying a client'
           WHEN h.client_required AND r.client_id IS NULL
               THEN 'client run with no client'
       END AS problem
FROM engine_runs r
LEFT JOIN LATERAL (
    SELECT bool_or(x.client_required) AS client_required
      FROM engine_handoffs x
     WHERE x.engine = r.engine AND x.mode = r.engine_mode AND x.active
) h ON true
WHERE r.engine_mode IS NULL
   OR h.client_required IS NULL
   OR (NOT h.client_required AND r.client_id IS NOT NULL)
   OR (h.client_required AND r.client_id IS NULL);

COMMENT ON VIEW v_engine_run_incoherent IS
'Runs whose client and mode disagree, runs from before 015 whose mode was never recorded, and runs in a mode nobody registered. The client/clock rule comes from engine_handoffs.client_required (020), not from a list repeated here.';

GRANT SELECT ON v_engine_run_incoherent TO phi_runtime, phi_practitioner;
