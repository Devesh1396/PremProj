-- =====================================================================
-- 027_followup_cycle.sql   Step 21 — CLIENT_FOLLOWUP and E4
--
--   follow-up -> E6 update -> E4 -> routing -> E1/E2/E3 -> E6 -> review
--
-- `client_followups` has existed since 004 and nothing ever read one;
-- `client_interventions.outcome` has existed just as long and nothing ever
-- wrote one. This migration is what the follow-up cycle needs in order to
-- be re-runnable, auditable, and honest about what it did not observe.
-- =====================================================================


-- ---------------------------------------------------------------------
-- A. A follow-up is processed once
-- ---------------------------------------------------------------------
--
-- Without this the queue is "every follow-up ever submitted", so a second
-- run re-processes the same one, spends another routing hop and writes a
-- second set of outcomes over the first. Processing state belongs on the
-- follow-up because that is the thing that is or is not processed.
-- ---------------------------------------------------------------------

ALTER TABLE client_followups
    ADD COLUMN IF NOT EXISTS processed_at timestamptz,
    ADD COLUMN IF NOT EXISTS processing_note text;

CREATE INDEX IF NOT EXISTS idx_followups_unprocessed
    ON client_followups (client_id, submitted_on)
    WHERE processed_at IS NULL;

COMMENT ON COLUMN client_followups.processed_at IS
'When a CLIENT_FOLLOWUP cycle consumed this. NULL means queued. Re-processing one would spend a routing hop and overwrite the outcomes the first run recorded.';


-- ---------------------------------------------------------------------
-- B. An outcome that changes is history, not an overwrite
-- ---------------------------------------------------------------------
--
-- `client_interventions.outcome` is a single column and Engine 4 writes it
-- every cycle. IMPROVING becoming WORSENING is a clinical fact — arguably
-- the most important one a follow-up produces — and a bare UPDATE loses
-- the fact that it ever improved.
--
-- The knowledge layer has `knowledge_updates` for exactly this reason. The
-- client layer had nothing.
-- ---------------------------------------------------------------------

CREATE TABLE intervention_outcome_history (
    history_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intervention_id uuid NOT NULL
                    REFERENCES client_interventions(intervention_id) ON DELETE CASCADE,
    client_id       uuid NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    followup_id     uuid REFERENCES client_followups(followup_id) ON DELETE SET NULL,
    run_id          uuid REFERENCES engine_runs(run_id) ON DELETE SET NULL,

    old_outcome     outcome_direction,
    new_outcome     outcome_direction NOT NULL,
    old_status      intervention_status,
    new_status      intervention_status,

    -- What the outcome rests on, and what was actually done. Adherence is
    -- recorded SEPARATELY from outcome on purpose: an intervention nobody
    -- carried out has not failed, it has not been tested, and collapsing
    -- the two is how a workable plan gets abandoned.
    adherence       text,
    evidence        text,
    recorded_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_outcome_history_intervention
    ON intervention_outcome_history (intervention_id, recorded_at DESC);
CREATE INDEX idx_outcome_history_client
    ON intervention_outcome_history (client_id, recorded_at DESC);

COMMENT ON TABLE intervention_outcome_history IS
'Every outcome Engine 4 recorded, with what it replaced. IMPROVING becoming WORSENING is a clinical fact and a bare UPDATE loses it. Adherence is stored beside the outcome, never folded into it: "did not work" and "was not done" are different findings.';

ALTER TABLE intervention_outcome_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE intervention_outcome_history FORCE ROW LEVEL SECURITY;

CREATE POLICY rls_runtime_outcome_history ON intervention_outcome_history
    FOR ALL TO phi_runtime
    USING (client_id = current_client_scope())
    WITH CHECK (client_id = current_client_scope());

CREATE POLICY rls_practitioner_outcome_history ON intervention_outcome_history
    FOR SELECT TO phi_practitioner USING (true);

GRANT SELECT, INSERT ON intervention_outcome_history TO phi_runtime;
GRANT SELECT ON intervention_outcome_history TO phi_practitioner;


-- One function, so the history cannot be skipped by writing the column
-- directly from somewhere that forgot.
CREATE OR REPLACE FUNCTION record_intervention_outcome(
    p_intervention_id uuid,
    p_outcome outcome_direction,
    p_status intervention_status DEFAULT NULL,
    p_adherence text DEFAULT NULL,
    p_evidence text DEFAULT NULL,
    p_followup_id uuid DEFAULT NULL,
    p_run_id uuid DEFAULT NULL,
    p_stop_reason text DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    prior     client_interventions%ROWTYPE;
    history   uuid;
BEGIN
    SELECT * INTO prior FROM client_interventions
     WHERE intervention_id = p_intervention_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'intervention % does not exist. Recording an outcome against '
            'something that was never proposed would create a response to a '
            'plan nobody made.', p_intervention_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF p_status = 'STOPPED' AND (p_stop_reason IS NULL
                                 OR length(btrim(p_stop_reason)) = 0) THEN
        RAISE EXCEPTION
            'stopping an intervention requires a reason. "Stopped" with no '
            'reason cannot tell a later cycle whether it failed, was '
            'unworkable, or simply finished.'
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO intervention_outcome_history
        (intervention_id, client_id, followup_id, run_id, old_outcome,
         new_outcome, old_status, new_status, adherence, evidence)
    VALUES (p_intervention_id, prior.client_id, p_followup_id, p_run_id,
            prior.outcome, p_outcome, prior.status,
            coalesce(p_status, prior.status), p_adherence, p_evidence)
    RETURNING history_id INTO history;

    UPDATE client_interventions
       SET outcome = p_outcome,
           status = coalesce(p_status, status),
           stop_reason = coalesce(p_stop_reason, stop_reason),
           ended_on = CASE WHEN p_status IN ('STOPPED','COMPLETED')
                           THEN coalesce(ended_on, current_date)
                           ELSE ended_on END
     WHERE intervention_id = p_intervention_id;

    RETURN history;
END $$;

COMMENT ON FUNCTION record_intervention_outcome IS
'The one way an intervention outcome changes. Writes the history row first, then the column — so an outcome cannot move without leaving what it moved from.';


-- ---------------------------------------------------------------------
-- C. What the follow-up cycle looks like from outside
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_followup_queue
WITH (security_invoker = true) AS
SELECT f.followup_id,
       f.client_id,
       c.display_name,
       f.review_period,
       f.submitted_on,
       (SELECT count(*) FROM client_interventions i
         WHERE i.client_id = f.client_id
           AND i.status IN ('PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED'))
                                                        AS live_interventions,
       (SELECT cy.loop_count FROM case_cycles cy
         WHERE cy.client_id = f.client_id
         ORDER BY cy.opened_at DESC LIMIT 1)             AS last_cycle_hops,
       (SELECT cy.max_loops FROM case_cycles cy
         WHERE cy.client_id = f.client_id
         ORDER BY cy.opened_at DESC LIMIT 1)             AS last_cycle_budget
  FROM client_followups f
  JOIN clients c ON c.client_id = f.client_id
 WHERE f.processed_at IS NULL
 ORDER BY f.submitted_on, f.followup_id;

COMMENT ON VIEW v_followup_queue IS
'Unprocessed follow-ups. `live_interventions` is what Engine 4 will have to report on — zero means the follow-up arrived before any plan did, and there is nothing to learn a response from.';

GRANT SELECT ON v_followup_queue TO phi_runtime, phi_practitioner;


CREATE OR REPLACE VIEW v_intervention_response
WITH (security_invoker = true) AS
SELECT i.client_id,
       i.intervention_id,
       i.name,
       i.source_engine,
       i.status,
       i.outcome,
       i.proposed_on,
       i.started_on,
       (SELECT count(*) FROM intervention_outcome_history h
         WHERE h.intervention_id = i.intervention_id)    AS times_assessed,
       (SELECT h.recorded_at FROM intervention_outcome_history h
         WHERE h.intervention_id = i.intervention_id
         ORDER BY h.recorded_at DESC LIMIT 1)            AS last_assessed_at,
       -- An intervention nobody has assessed is NOT one that is doing
       -- nothing. `NOT_TRACKED` is the default on the column, so without
       -- this distinction "never looked at" and "looked at and found
       -- nothing" are the same value.
       (NOT EXISTS (SELECT 1 FROM intervention_outcome_history h
                     WHERE h.intervention_id = i.intervention_id))
                                                         AS never_assessed
  FROM client_interventions i;

COMMENT ON VIEW v_intervention_response IS
'Per-intervention response, with `never_assessed` separating "no outcome recorded" from "outcome recorded as none". The column default is NOT_TRACKED, so the two are otherwise indistinguishable.';

GRANT SELECT ON v_intervention_response TO phi_runtime, phi_practitioner;
