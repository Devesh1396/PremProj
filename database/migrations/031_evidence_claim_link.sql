-- =====================================================================
-- 031_evidence_claim_link.sql   Evidence belongs to the CLAIM it was
--                               researched for, not to a time window
--
-- K10 researches ONE claim per run and writes the evidence it finds. The
-- link back to that claim did not exist. `knowledge_synthesize.evidence_for()`
-- reconstructed it as:
--
--     select evidence_id from evidence_records
--      where created_at >= (the claim's created_at)
--      order by created_at desc limit 20
--
-- which is not a provenance edge. It is "everything researched since this
-- claim was written", and it is wrong the moment a second claim is
-- researched.
--
-- Found on the first real source through the loop, 2026-09-11. Seven
-- claims were extracted from one video and six researched in one batch,
-- so under the window join the FIRST claim -- a mechanism statement about
-- skeletal muscle glucose uptake -- collected all 17 evidence records,
-- including three studies of a mulberry-extract supplement researched for
-- a completely different claim. The strategy card built on it would have
-- cited them as its evidence.
--
-- This never showed up in the suites because every fixture researches one
-- claim. With a single claim in the table, "evidence written after this
-- claim" and "evidence written FOR this claim" return the same rows, so
-- the fixture could not tell the right answer from the wrong one (V2).
--
-- Hard rule 12 is about derived objects registering their provenance.
-- This is the same principle one layer over: an evidence record that
-- cannot say which claim it was found for is an evidence record whose
-- provenance is a guess about timing.
-- =====================================================================

ALTER TABLE evidence_records
    ADD COLUMN IF NOT EXISTS claim_id uuid
        REFERENCES claims(claim_id) ON DELETE SET NULL;

COMMENT ON COLUMN evidence_records.claim_id IS
'The claim K10 was researching when it wrote this record. ON DELETE SET NULL, not CASCADE: the study exists independently of the claim that led us to it, which is the whole of D10 -- a video surfacing an idea has not evidenced it, and deleting the claim must not delete the literature.';

CREATE INDEX IF NOT EXISTS idx_evidence_claim
    ON evidence_records (claim_id) WHERE claim_id IS NOT NULL;

-- Existing rows are left NULL rather than back-filled by timestamp. The
-- timestamp is precisely the signal that was proven unreliable, and a
-- guessed link recorded as a real one is worse than an absent one: the
-- next reader cannot tell which rows were guessed.
--
-- NULL therefore means "written before this link existed, provenance not
-- recoverable". `v_evidence_without_claim` makes that visible rather than
-- leaving it to be discovered by someone reading a strategy card.

CREATE OR REPLACE VIEW v_evidence_without_claim AS
 SELECT e.evidence_id,
        e.citation,
        e.design,
        e.created_at,
        CASE WHEN e.created_at < '2026-09-11'::date
             THEN 'predates the claim link (migration 031); provenance not recoverable'
             ELSE 'written after the link existed and still has no claim -- investigate'
        END AS why
   FROM evidence_records e
  WHERE e.claim_id IS NULL;

COMMENT ON VIEW v_evidence_without_claim IS
'Evidence records with no claim behind them. Separates "older than the link" from "the link exists and this row still has none", because the second is a defect and the first is only history.';

GRANT SELECT ON v_evidence_without_claim TO phi_runtime, phi_practitioner;
