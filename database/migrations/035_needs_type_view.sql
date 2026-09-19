-- ---------------------------------------------------------------------
-- 035 — the read over NEEDS_TYPE proposals
-- ---------------------------------------------------------------------
-- Separate from 034 only because PostgreSQL refuses to use an enum label
-- in the same transaction that added it, and scripts/migrate.py runs each
-- migration in its own transaction (which is the property that makes a
-- half-applied migration impossible).

-- ---------------------------------------------------------------------
-- What is waiting on a type, without a queue anybody has to work
-- ---------------------------------------------------------------------
-- Hard rule 3: no milestone may create a recurring manual job. This view
-- is a READ, not a queue -- nothing is blocked on anyone emptying it, and
-- these rows are not counted against D8's escalation cap because they are
-- not escalations. The alternative was not "no work": it was a junk
-- PROPOSED PHYSIOLOGY concept that nobody looked at either, sitting in the
-- ontology where retrieval could eventually reach it.
CREATE OR REPLACE VIEW v_concept_needs_type AS
SELECT p.proposal_id,
       p.raw_phrase,
       p.allowed_types,
       p.context,
       p.method,
       p.similarity,
       p.impact_score,
       p.decision_note,
       p.created_at
  FROM concept_proposals p
 WHERE p.decision = 'NEEDS_TYPE'
   AND p.resolved_at IS NULL
 ORDER BY p.impact_score DESC, p.created_at;

COMMENT ON VIEW v_concept_needs_type IS
'Phrases a caller structurally typed to a SET, that no tier resolved, and that were therefore NOT created as a concept under an invented narrow type. A record, not a work queue.';
