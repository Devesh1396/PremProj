-- =====================================================================
-- 025_controversy_and_gaps.sql   Step 19 — K12 and K13
--
-- BUILD_PLAN: "K9 runs per domain once that domain reaches moderate
-- coverage, not at the end of Wave 1. Negative knowledge and controversies
-- do not fall out of ingestion naturally; they need dedicated passes over
-- accumulated evidence."
--
-- The tables have existed since 003 and nothing has ever written to them.
-- What was missing is what makes a written row mean something:
--
--   * a controversy with ONE position is not a controversy
--   * negative knowledge that does not say what was examined cannot stop
--     the next pass re-examining it, which is the only thing it is for
--   * `knowledge_gaps.status` was free text, and `foundation_ready` turns
--     on `status = 'OPEN'`
--   * "no controversies in this domain" and "nobody has ever looked" were
--     the same row: absent
-- =====================================================================


-- =====================================================================
-- A. A controversy needs at least two positions
-- =====================================================================
--
-- §"Do not manufacture controversy where strong consensus genuinely
-- exists." The converse matters as much: a record with a single position
-- is a consensus statement or a gap wearing a controversy's clothes, and
-- it would be retrieved and presented as a live disagreement.
--
-- A CONSTRAINT TRIGGER, deferred to commit, because the positions are
-- inserted after the parent -- an immediate check would make the correct
-- write order impossible. The transaction that creates a controversy must
-- also give it its positions, or none of it lands.
-- =====================================================================

CREATE OR REPLACE FUNCTION trg_controversy_needs_positions() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    n integer;
    target uuid := coalesce(NEW.controversy_id, OLD.controversy_id);
BEGIN
    IF NOT EXISTS (SELECT 1 FROM controversies WHERE controversy_id = target) THEN
        RETURN NULL;   -- deleted in the same transaction; nothing to check
    END IF;

    SELECT count(*) INTO n FROM controversy_positions
     WHERE controversy_id = target;

    IF n < 2 THEN
        RAISE EXCEPTION
            'controversy % has % position(s). A controversy with fewer than '
            'two is a consensus statement or a knowledge gap, and storing it '
            'here would present it to the practitioner as a live '
            'disagreement. Record both sides, or record it as a gap.',
            target, n
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_controversy_positions_at_commit
    AFTER INSERT OR UPDATE ON controversies
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_controversy_needs_positions();

CREATE CONSTRAINT TRIGGER trg_position_removal_at_commit
    AFTER DELETE ON controversy_positions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_controversy_needs_positions();

COMMENT ON FUNCTION trg_controversy_needs_positions() IS
'A controversy with fewer than two positions is not a controversy (K12). Deferred to commit because the positions are written after the parent row.';


-- A position that does not say what evidence it rests on is an opinion
-- with a citation-shaped hole. §12 keeps who-said-it separate from
-- what-the-evidence-shows, so `held_by` is not a substitute.
ALTER TABLE controversy_positions
    ADD CONSTRAINT ck_position_has_evidence CHECK (
        evidence_summary IS NOT NULL AND length(btrim(evidence_summary)) > 0);


-- =====================================================================
-- B. Negative knowledge must be able to stop the next search
-- =====================================================================
--
-- `negative_knowledge` exists to "prevent repeated wasted research" (003).
-- A row that does not say WHY it was investigated, WHAT was examined and
-- WHAT WOULD MAKE US LOOK AGAIN cannot do that: the next pass has no way
-- to tell whether its question was already answered or answered badly.
--
-- `revisit_trigger` is required for the same reason §70 forbids a COMPLETE
-- status. "This does not work" with no revisit condition is a permanent
-- verdict on a moving field.
-- =====================================================================

ALTER TABLE negative_knowledge
    ADD CONSTRAINT ck_negative_is_actionable CHECK (
        why_investigated  IS NOT NULL AND length(btrim(why_investigated))  > 0
    AND evidence_examined IS NOT NULL AND length(btrim(evidence_examined)) > 0
    AND revisit_trigger   IS NOT NULL AND length(btrim(revisit_trigger))   > 0);

COMMENT ON CONSTRAINT ck_negative_is_actionable ON negative_knowledge IS
'Negative knowledge exists to stop the same question being researched twice. Without what was examined and what would change the answer, it cannot — and a verdict with no revisit condition is a COMPLETE status by another name (§70).';


-- =====================================================================
-- C. A gap's status is a closed set
-- =====================================================================
--
-- `status` was free text defaulting to 'OPEN', and `v_domain_readiness`
-- computes `foundation_ready` from `status = 'OPEN'`. A row written as
-- 'open' or 'Open' would make a CRITICAL gap invisible and flip a domain
-- to ready — silently, and in the direction that hides the problem.
-- =====================================================================

ALTER TABLE knowledge_gaps
    ADD CONSTRAINT ck_gap_status CHECK (
        status IN ('OPEN', 'RESEARCHING', 'RESOLVED', 'SUPERSEDED'));

-- A resolved gap says what resolved it and when. An unresolved one carries
-- neither, so "resolved" cannot be a state something drifted into.
ALTER TABLE knowledge_gaps
    ADD CONSTRAINT ck_gap_resolution_coherent CHECK (
        (status IN ('RESOLVED', 'SUPERSEDED'))
        = (resolved_at IS NOT NULL
           AND resolution IS NOT NULL AND length(btrim(resolution)) > 0));

COMMENT ON CONSTRAINT ck_gap_status ON knowledge_gaps IS
'OPEN | RESEARCHING | RESOLVED | SUPERSEDED. foundation_ready turns on status = OPEN (007), so a free-text status could hide a CRITICAL gap and mark a domain ready.';


-- =====================================================================
-- D. "Nobody has looked" is not "there is nothing to find"
-- =====================================================================
--
-- `domain_gap_assessments` already makes that distinction for gaps: a row
-- means the pass RAN, and `gaps_found = 0` is an honest result rather than
-- a claim of completeness (hard rule 11). Controversy and negative
-- knowledge need exactly the same record, for exactly the same reason —
-- a domain with no controversies and a domain nobody examined are
-- indistinguishable without it, and the second is the dangerous one.
-- =====================================================================

CREATE TABLE domain_controversy_assessments (
    domain_id             uuid PRIMARY KEY
                          REFERENCES knowledge_domains(domain_id) ON DELETE CASCADE,
    assessed_at           timestamptz NOT NULL DEFAULT now(),
    assessed_by           text,
    processing_version    text,
    controversies_found   integer NOT NULL DEFAULT 0,
    negative_findings     integer NOT NULL DEFAULT 0,
    evidence_examined     integer NOT NULL DEFAULT 0,
    note                  text,

    CONSTRAINT ck_controversy_counts_nonneg
        CHECK (controversies_found >= 0 AND negative_findings >= 0
               AND evidence_examined >= 0)
);

COMMENT ON TABLE domain_controversy_assessments IS
'A row means a dedicated K12 pass was performed for this domain. controversies_found = 0 is an honest result — it does NOT mean the domain is settled, and it is not the same as the absent row that means nobody has looked (hard rule 11, §70).';

GRANT SELECT, INSERT, UPDATE ON domain_controversy_assessments
    TO phi_runtime;
GRANT SELECT ON domain_controversy_assessments TO phi_practitioner;


-- =====================================================================
-- E. What the passes have and have not covered
-- =====================================================================

CREATE OR REPLACE VIEW v_controversy_state
WITH (security_invoker = true) AS
SELECT d.domain_id,
       d.domain_key,
       d.name,
       (a.domain_id IS NOT NULL)              AS pass_performed,
       a.assessed_at,
       coalesce(c.controversies, 0)           AS controversies,
       coalesce(c.positions, 0)               AS positions,
       coalesce(n.findings, 0)                AS negative_findings,
       -- The count that matters most is the one nobody asks for: a domain
       -- at depth with no pass is where a missing controversy hides.
       (a.domain_id IS NULL
        AND coalesce(cov.covered, 0) >= 6)    AS overdue
  FROM knowledge_domains d
  LEFT JOIN domain_controversy_assessments a ON a.domain_id = d.domain_id
  LEFT JOIN LATERAL (
      SELECT count(*) AS controversies,
             coalesce(sum((SELECT count(*) FROM controversy_positions p
                            WHERE p.controversy_id = k.controversy_id)), 0) AS positions
        FROM controversies k WHERE k.domain_id = d.domain_id) c ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS findings FROM negative_knowledge nk
       WHERE nk.domain_id = d.domain_id) n ON true
  LEFT JOIN LATERAL (
      SELECT count(*) FILTER (WHERE dc.covered) AS covered
        FROM domain_coverage dc WHERE dc.domain_id = d.domain_id) cov ON true
 WHERE d.active;

COMMENT ON VIEW v_controversy_state IS
'K12 per domain. `overdue` is a domain that has reached moderate coverage and has never had a controversy pass — the state in which a missing controversy is invisible rather than absent.';

GRANT SELECT ON v_controversy_state TO phi_runtime, phi_practitioner;


CREATE OR REPLACE VIEW v_knowledge_gap_queue
WITH (security_invoker = true) AS
SELECT g.gap_id,
       g.question,
       d.domain_key,
       g.severity,
       g.status,
       g.importance,
       g.created_at,
       -- Impact, not uncertainty (hard rule 3): a gap in a domain the
       -- library leans on matters more than one in a domain it barely
       -- touches, whatever either gap's own severity says.
       (SELECT count(*) FROM strategy_domains sd
         WHERE sd.domain_id = g.domain_id)  AS strategies_in_domain
  FROM knowledge_gaps g
  LEFT JOIN knowledge_domains d ON d.domain_id = g.domain_id
 WHERE g.status IN ('OPEN', 'RESEARCHING')
 ORDER BY
       CASE g.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                       WHEN 'MEDIUM' THEN 2 ELSE 3 END,
       g.importance DESC,
       g.created_at;

COMMENT ON VIEW v_knowledge_gap_queue IS
'Open and in-flight gaps, ranked by severity then impact. Ordering is deterministic so an escalation cap always takes the same top N.';

GRANT SELECT ON v_knowledge_gap_queue TO phi_runtime, phi_practitioner;
