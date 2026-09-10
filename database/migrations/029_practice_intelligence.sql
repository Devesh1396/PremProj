-- =====================================================================
-- 029_practice_intelligence.sql   Step 23 — practice intelligence
--
--   BUILD_GUIDE step 23: "De-identified aggregation into
--   `practice_strategy_outcomes`. Minimum cohort 5. Never merged with
--   evidence."
--
-- `practice_strategy_outcomes` has existed since migration `003` with
-- `ck_min_cohort` on it and NOTHING HAS EVER WRITTEN A ROW. That is the
-- fifth instance of the same shape in this build -- `client_interventions`
-- (D42), `client_interventions.outcome` (D43), `client_followups` (D43)
-- and `KNOWLEDGE_DAILY_TOKEN_BUDGET` (D44) were the first four: a control
-- that exists as a name, over a table nothing populates, so the control
-- passes every time having inspected nothing.
--
-- Step 21 is what changed: `client_interventions` now carries started
-- interventions with recorded outcomes and `intervention_outcome_history`
-- carries what each outcome replaced. There is finally something to
-- aggregate.
--
-- Hard rule 6 and D9: practice experience is NEVER evidence. This
-- migration adds the first two views that touch
-- `practice_strategy_outcomes` and neither may reference
-- `evidence_records`. `testing/test_practice.py` asserts that over the
-- whole schema, not over these two by name -- the rule has to survive the
-- next view somebody adds.
-- =====================================================================


-- ---------------------------------------------------------------------
-- A. An aggregate that cannot say what it left out is not an aggregate
-- ---------------------------------------------------------------------
--
-- `n_clients >= 5` was the whole of the honesty story, and it is not
-- enough on its own. Five clients out of five exposed is a finding; five
-- out of thirty, where twenty-five were never assessed, is a selection
-- effect with a number in front of it. The denominator has to travel with
-- the numerator or the reader cannot tell them apart.
--
-- `n_clients` means DISTINCT CLIENTS WITH A RECORDED OUTCOME. Not rows,
-- not interventions, not clients who were merely offered the strategy.
-- One client contributes exactly ONE observation however many times the
-- strategy was tried with them, which is what makes `outcome_counts` sum
-- to `n_clients` -- and that sum is a CHECK below, so the rule is a
-- database property rather than a convention in the runner.
-- ---------------------------------------------------------------------

ALTER TABLE practice_strategy_outcomes
    ADD COLUMN IF NOT EXISTS n_clients_exposed integer,
    ADD COLUMN IF NOT EXISTS n_interventions   integer,
    ADD COLUMN IF NOT EXISTS outcome_counts    jsonb,
    ADD COLUMN IF NOT EXISTS adherence_counts  jsonb,
    ADD COLUMN IF NOT EXISTS generated_at      timestamptz,
    ADD COLUMN IF NOT EXISTS generation_method text;

COMMENT ON COLUMN practice_strategy_outcomes.n_clients IS
'DISTINCT CLIENTS WITH A RECORDED OUTCOME. Never interventions, never clients merely exposed: one client contributes one observation however many times the strategy was tried with them. ck_min_cohort applies to THIS count.';

COMMENT ON COLUMN practice_strategy_outcomes.n_clients_exposed IS
'Distinct clients who actually started the strategy, assessed or not. n_clients_exposed - n_clients is how many were never looked at, which is the difference between a finding and a selection effect.';

COMMENT ON COLUMN practice_strategy_outcomes.outcome_counts IS
'Latest recorded outcome per client, as {outcome: n}. Sums to n_clients by ck_practice_outcomes_account_for_cohort -- a distribution that does not account for the whole cohort is hiding part of it.';

COMMENT ON COLUMN practice_strategy_outcomes.adherence_counts IS
'{HIGH|PARTIAL|LOW|UNKNOWN: n}, also summing to n_clients. Stored BESIDE the outcome and never folded into it (D43): an intervention nobody carried out has not failed, it has not been tested.';

COMMENT ON COLUMN practice_strategy_outcomes.generation_method IS
'NULL for a practitioner-recorded observation. Set by the deterministic aggregator, which is then held to ck_practice_generated_complete. Also what uq_practice_generated keys on, so re-running replaces rather than accumulates.';


-- A sum over a jsonb object of integers. IMMUTABLE so a CHECK may call it.
CREATE OR REPLACE FUNCTION jsonb_counts_total(j jsonb)
RETURNS bigint
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT coalesce(sum((value)::text::bigint), 0)
      FROM jsonb_each(j)
$$;

COMMENT ON FUNCTION jsonb_counts_total IS
'Total of a {key: integer} object. Exists so "the distribution accounts for the whole cohort" can be a CHECK constraint rather than a promise.';


ALTER TABLE practice_strategy_outcomes
    ADD CONSTRAINT ck_practice_counts_coherent CHECK (
        (n_clients_exposed IS NULL OR n_clients_exposed >= n_clients)
        AND (n_interventions IS NULL OR n_interventions >= n_clients)),

    -- Five ROWS from two clients is one person's record with a count on
    -- it. The cohort minimum only means anything if the number it guards
    -- is a count of people.
    ADD CONSTRAINT ck_practice_outcomes_account_for_cohort CHECK (
        outcome_counts IS NULL
        OR jsonb_counts_total(outcome_counts) = n_clients),

    ADD CONSTRAINT ck_practice_adherence_accounts_for_cohort CHECK (
        adherence_counts IS NULL
        OR jsonb_counts_total(adherence_counts) = n_clients),

    ADD CONSTRAINT ck_practice_period_order CHECK (
        period_start IS NULL OR period_end IS NULL OR period_end >= period_start),

    -- A generated aggregate must be able to answer "out of how many, over
    -- what window, with what distribution". A row that cannot is prose
    -- with a sample size attached.
    ADD CONSTRAINT ck_practice_generated_complete CHECK (
        generation_method IS NULL
        OR (n_clients_exposed IS NOT NULL
            AND n_interventions IS NOT NULL
            AND outcome_counts IS NOT NULL
            AND adherence_counts IS NOT NULL
            AND generated_at IS NOT NULL
            AND period_start IS NOT NULL));

COMMENT ON CONSTRAINT ck_practice_outcomes_account_for_cohort
    ON practice_strategy_outcomes IS
'The distribution must account for every client in the cohort. Without it an aggregate can report the four clients who improved out of a cohort of nine and still satisfy ck_min_cohort.';


-- Re-running the aggregator REPLACES its own row. Partial, so a
-- practitioner-recorded observation (generation_method NULL) is never
-- collided with by a generated one and never overwritten by it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_generated
    ON practice_strategy_outcomes (strategy_id, cohort_criteria)
    WHERE generation_method IS NOT NULL;


-- ---------------------------------------------------------------------
-- B. De-identification is enforced, not claimed
-- ---------------------------------------------------------------------
--
-- Every substantive column on this table is free text, and the table
-- comment has said "de-identified aggregates only" since `003` with
-- nothing checking it. The failure mode is not malice: it is a summary
-- that quotes a client's own words back, or a debugging session that
-- pastes an intervention_id into `cohort_criteria` and never takes it out.
--
-- This is the one place in the schema where client-identifying material
-- could cross from the RLS-protected client layer into the GLOBAL,
-- un-scoped knowledge layer -- so it is checked here, at the boundary,
-- rather than trusted upstream.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION practice_deidentified()
RETURNS trigger
LANGUAGE plpgsql
-- SECURITY DEFINER on purpose: `clients` is RLS-FORCED, so a check that
-- ran with the caller's visibility would compare against the ONE client in
-- scope, find no match, and pass. A check that passes because it could not
-- see the thing it was checking for is worse than no check.
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    blob   text;
    hit    text;
BEGIN
    blob := concat_ws(' ', NEW.cohort_criteria, NEW.adherence_summary,
                      NEW.outcome_summary, NEW.outcome_range, NEW.drop_out,
                      NEW.common_side_effects, NEW.common_failure_reasons,
                      NEW.implementation_acceptance);

    IF blob ~* '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' THEN
        RAISE EXCEPTION
            'practice aggregate carries a UUID. A client_id, intervention_id '
            'or run_id in a de-identified aggregate re-identifies the whole '
            'cohort to anyone holding the client table.'
            USING ERRCODE = 'check_violation';
    END IF;

    IF blob ~* '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' THEN
        RAISE EXCEPTION
            'practice aggregate carries an email address.'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT c.display_name INTO hit
      FROM clients c
     WHERE c.display_name IS NOT NULL
       AND length(btrim(c.display_name)) >= 3
       AND blob ILIKE '%' || btrim(c.display_name) || '%'
     LIMIT 1;
    IF hit IS NOT NULL THEN
        RAISE EXCEPTION
            'practice aggregate names a client. De-identified means the '
            'aggregate cannot be read back onto a person, and a name in the '
            'summary is the shortest path there.'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT c.external_ref INTO hit
      FROM clients c
     WHERE c.external_ref IS NOT NULL
       AND length(btrim(c.external_ref)) >= 3
       AND blob ILIKE '%' || btrim(c.external_ref) || '%'
     LIMIT 1;
    IF hit IS NOT NULL THEN
        RAISE EXCEPTION
            'practice aggregate carries a client external reference.'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END $$;

COMMENT ON FUNCTION practice_deidentified IS
'The de-identification boundary between the RLS-protected client layer and the global knowledge layer. Refuses a UUID, an email address, a client display name or an external reference in any free-text column of a practice aggregate.';

CREATE TRIGGER trg_practice_deidentified
    BEFORE INSERT OR UPDATE ON practice_strategy_outcomes
    FOR EACH ROW EXECUTE FUNCTION practice_deidentified();

-- Only the roles that can write the table need to call it.
REVOKE EXECUTE ON FUNCTION practice_deidentified() FROM PUBLIC;


-- ---------------------------------------------------------------------
-- C. The runtime READS practice aggregates. It never creates one.
-- ---------------------------------------------------------------------
--
-- Migration `005` granted phi_runtime full DML on every "global" table,
-- this one included, before anything wrote to it. But aggregation is a
-- CROSS-CLIENT read and phi_runtime's scope is transaction-local and
-- single-client (hard rule 8): as phi_runtime the cohort is always one
-- person or zero. A path that can only ever produce a wrong answer should
-- not exist, and the engine payload only ever needs SELECT.
-- ---------------------------------------------------------------------

REVOKE INSERT, UPDATE, DELETE ON practice_strategy_outcomes FROM phi_runtime;


-- ---------------------------------------------------------------------
-- D. Adherence bands have ONE definition
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION adherence_band(pct numeric)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN pct IS NULL   THEN 'UNKNOWN'
        WHEN pct >= 80     THEN 'HIGH'
        WHEN pct >= 50     THEN 'PARTIAL'
        ELSE                    'LOW'
    END
$$;

COMMENT ON FUNCTION adherence_band IS
'Presentation bands over client_intervention_exposure.adherence_pct. One definition, so the cohort view and any test measuring it cannot disagree. UNKNOWN is a band, not a default to HIGH: unrecorded adherence is not good adherence.';


-- ---------------------------------------------------------------------
-- E. What a cohort looks like before it is aggregated
-- ---------------------------------------------------------------------
--
-- The queue has to separate three states that all look like "no aggregate
-- exists": nobody has run the aggregator, the cohort is genuinely too
-- small, and the clients are there but nobody assessed them. The third is
-- the one worth acting on and the one an absent row hides.
--
-- A PROPOSED intervention nobody started is NOT practice experience. A
-- plan that was never carried out says nothing about the strategy, and
-- counting it inflates every cohort with proposals.
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_practice_cohort_candidates
WITH (security_invoker = true) AS
WITH exposure AS (
    SELECT i.strategy_id,
           i.client_id,
           i.intervention_id,
           i.started_on,
           i.ended_on,
           EXISTS (SELECT 1 FROM intervention_outcome_history h
                    WHERE h.intervention_id = i.intervention_id) AS assessed
      FROM client_interventions i
     WHERE i.strategy_id IS NOT NULL
       AND i.started_on IS NOT NULL
)
SELECT s.strategy_id,
       s.name                                                    AS strategy_name,
       s.knowledge_status,
       count(DISTINCT e.client_id)                               AS n_clients_exposed,
       count(DISTINCT e.client_id) FILTER (WHERE e.assessed)     AS n_clients_assessed,
       -- count(e.intervention_id), never count(*): this is a LEFT JOIN, so
       -- count(*) counts the strategy row itself and reports one
       -- intervention for every strategy nobody has ever started.
       count(e.intervention_id)                                  AS n_interventions,
       min(e.started_on)                                         AS earliest_start,
       max(coalesce(e.ended_on, current_date))                   AS latest_activity,
       (count(DISTINCT e.client_id) FILTER (WHERE e.assessed)) >= 5
                                                                 AS meets_cohort_minimum,
       EXISTS (SELECT 1 FROM practice_strategy_outcomes p
                WHERE p.strategy_id = s.strategy_id
                  AND p.generation_method IS NOT NULL)           AS aggregate_exists,
       CASE
           WHEN count(DISTINCT e.client_id) FILTER (WHERE e.assessed) >= 5
                THEN NULL
           WHEN count(DISTINCT e.client_id) = 0
                THEN 'no client has started this strategy'
           WHEN count(DISTINCT e.client_id) FILTER (WHERE e.assessed) = 0
                THEN format('%s client(s) started it and NONE has been assessed',
                            count(DISTINCT e.client_id))
           ELSE format('%s of %s exposed client(s) assessed; %s short of the minimum of 5',
                       count(DISTINCT e.client_id) FILTER (WHERE e.assessed),
                       count(DISTINCT e.client_id),
                       5 - (count(DISTINCT e.client_id) FILTER (WHERE e.assessed)))
       END                                                       AS blocked_reason
  FROM strategies s
  LEFT JOIN exposure e ON e.strategy_id = s.strategy_id
 GROUP BY s.strategy_id, s.name, s.knowledge_status;

COMMENT ON VIEW v_practice_cohort_candidates IS
'Per-strategy cohort readiness. `blocked_reason` separates "nobody has run the aggregator" from "the cohort is 3" from "eleven clients started it and nobody has assessed one" -- three states that are otherwise the same absent row, and only the last is a standing failure to look.';

-- Practitioner only, deliberately. This view reads ACROSS clients, and
-- phi_runtime is single-client-scoped: it would read a cohort of one and
-- report every strategy as blocked. The runtime reads the aggregate.
GRANT SELECT ON v_practice_cohort_candidates TO phi_practitioner;


-- ---------------------------------------------------------------------
-- F. The separately labelled block (D9, Engine 7 §A4)
-- ---------------------------------------------------------------------
--
-- "Always returned to engines as a separately labelled block." The label
-- travels IN THE ROW, not in the prose around it, because prose is what
-- gets reformatted on the way to a payload. Engine 1's Pass B section and
-- Engine 7 §A4 already say how to weigh this; nothing has ever produced it.
--
-- This view does not, and may not, reference evidence_records.
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_practice_experience
WITH (security_invoker = true) AS
SELECT p.practice_id,
       p.strategy_id,
       s.name                              AS strategy_name,
       s.knowledge_status,
       'INTERNAL_PRACTICE_OBSERVATION'     AS basis,
       'NOT_EVIDENCE'                      AS evidence_status,
       p.cohort_criteria,
       p.n_clients,
       p.n_clients_exposed,
       p.n_interventions,
       p.outcome_counts,
       p.adherence_counts,
       p.outcome_summary,
       p.outcome_range,
       p.adherence_summary,
       p.drop_out,
       p.common_side_effects,
       p.common_failure_reasons,
       p.implementation_acceptance,
       p.period_start,
       p.period_end,
       p.generated_at,
       p.generation_method
  FROM practice_strategy_outcomes p
  JOIN strategies s ON s.strategy_id = p.strategy_id;

COMMENT ON VIEW v_practice_experience IS
'The separately labelled practice block (D9, hard rule 6, Engine 7 A4). `basis` and `evidence_status` are columns rather than a caption so the label cannot be dropped in reformatting. This view must never reference evidence_records and no view may join the two.';

GRANT SELECT ON v_practice_experience TO phi_runtime, phi_practitioner;
