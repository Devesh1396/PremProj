-- ---------------------------------------------------------------------
-- 034 — the normalization cache must not outrank the guards it skipped
-- ---------------------------------------------------------------------
-- GATE 2 (D51) put a concept_type guard and a candidate-set confusable
-- guard in front of every resolution. `normalization_cache` sat IN FRONT
-- OF BOTH: `resolve()` returned a hit keyed on `phrase_norm` alone, before
-- allowed_types, before the type rejection, before the candidate set was
-- built and before confusable_with() ever ran.
--
-- Two ways that is a bypass, and they are different:
--
--   1. CONTEXT. A phrase first resolved with no caller type knowledge is
--      cached, and then served unchanged to a caller that DOES know the
--      phrase is a target or an intervention. The guard never runs. The
--      cache key carries no type, so nothing in the row could have said no.
--
--   2. STALENESS. A semantic resolution is the top-1 of a candidate set,
--      and the confusable guard fires on the SET. Add a
--      CONFUSABLE_DO_NOT_MERGE pair afterwards and a live run refuses the
--      phrase while the cache keeps serving the old answer -- and
--      re-checking the cached concept cannot catch it, because the
--      objection was never in the answer. It was in the candidates.
--
-- The fix is to store what the guards need and re-run them on READ.
-- Disabling the cache would be the wrong trade: D2 exists so a phrase
-- never costs a second call, and after GATE 2 a miss is a paid embedding.
-- ---------------------------------------------------------------------

-- What the tier CONSIDERED, so confusable_with() can be re-run over the
-- same set on every read. NULL means the row predates this column and
-- cannot be validated -- the resolver treats that as a miss rather than
-- assuming it is safe, because "we cannot check" and "we checked" are not
-- the same answer.
ALTER TABLE normalization_cache
    ADD COLUMN IF NOT EXISTS candidate_ids uuid[];

-- The caller's allowed concept_type set AT WRITE TIME.
--
-- NULL here means TYPE WAS UNKNOWN WHEN THIS WAS WRITTEN. It does NOT mean
-- "valid for every type", and the distinction is the whole point of the
-- column: a resolution produced with nobody claiming to know what kind of
-- thing the phrase was is a weaker record than one produced under a stated
-- constraint, and erasing that difference is how a cache launders an
-- unchecked answer into a checked one.
--
-- It is provenance, not the check. The CHECK on read is against the
-- concept's own `concept_type` and the READER's allowed set, because that
-- is what actually has to hold. This column says what the entry was made
-- under, so an audit can tell the two apart.
ALTER TABLE normalization_cache
    ADD COLUMN IF NOT EXISTS resolved_under_types text[];

COMMENT ON COLUMN normalization_cache.candidate_ids IS
'What the tier considered, not what it resolved to. Stored so the CONFUSABLE_DO_NOT_MERGE guard can be re-run on every cache read: the guard fires on a SPAN, and a single-concept answer can never span anything, so re-checking concept_ids alone would silently pass.';

COMMENT ON COLUMN normalization_cache.resolved_under_types IS
'The caller''s allowed concept_type set at WRITE time. NULL = the type was unknown when this was written, which is NOT the same as valid for all types. Provenance for audit; the safety check on read is the concept''s own type against the READER''s allowed set.';

-- ---------------------------------------------------------------------
-- An unresolved phrase whose type is known only as a SET
-- ---------------------------------------------------------------------
-- `_propose_new` created every unmatched phrase as PHYSIOLOGY, a literal
-- default in the resolver. Once a caller structurally knows the phrase is
-- an INTERVENTION that is not a default, it is a contradiction: `soleus
-- push-up` arrives from a Claim Card `intervention` field and becomes a
-- PROPOSED PHYSIOLOGY concept, and the type work GATE 2 added is undone by
-- the fall-through underneath it.
--
-- There is no honest narrow type to write. §R11 tells the caller the
-- phrase is "what is being done or taken"; it does not say whether that is
-- EXERCISE, FOOD, BEHAVIOUR or INTERVENTION, and picking one from the
-- phrase's wording is the resolver deciding what it wants the answer to be.
-- `concepts.concept_type` is NOT NULL and the enum has no UNKNOWN, so the
-- honest record is a PROPOSAL and no concept at all.
ALTER TYPE proposal_decision ADD VALUE IF NOT EXISTS 'NEEDS_TYPE';

-- The set the caller could honestly vouch for. `proposed_type` is one
-- value and cannot hold "one of these six", so preserving the uncertainty
-- needs its own column rather than a narrowing of it.
ALTER TABLE concept_proposals
    ADD COLUMN IF NOT EXISTS allowed_types text[];

COMMENT ON COLUMN concept_proposals.allowed_types IS
'The concept_type set the CALLER structurally knew the phrase belonged to, from the field it came out of (§R11) and never from its wording. Carried because proposed_type is a single value and narrowing a set to one member to fit it would invent the answer.';

-- The view over these rows is migration 035, not this file: PostgreSQL
-- refuses to USE a new enum label in the transaction that added it, and
-- each migration runs in its own transaction by design.
