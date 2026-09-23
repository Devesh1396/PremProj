-- =====================================================================
-- 052_absorbed_body_audit.sql   ABSORPTION MUST BE VISIBLE (D58).
--
-- Since D58 an unrecognised block inside an open container no longer
-- closes it. Its text is kept as body of the field it follows, and the
-- block stays REVIEW_REQUIRED. That changes where text lives, so it has to
-- be on the record: a field that silently grew is the D48 shape -- a
-- populated, plausible, wrong-in-detail location.
--
-- Two facts per block, both written by the parser and neither inferred:
--
--   absorbed_into_ordinal  the field-bearing block whose field now holds
--                          this block's text, or NULL.
--   review_class           WHY a block is not recognised structure:
--                          NO_RULE, REGISTERED_NO_CONTAINER,
--                          REGISTERED_NOT_OWNABLE,
--                          REGISTERED_DUPLICATE_FIELD.
--
-- The second exists because "matches no rule" and "matches a registered
-- label whose container was not there" were reported as the same thing.
-- On the canonical source that hid `Decision logic` appearing 14 times,
-- matching SUB_DECISION, and being reported as unrecognised.
--
-- Append-only.
-- =====================================================================

ALTER TABLE curated_blocks
    ADD COLUMN absorbed_into_ordinal integer,
    ADD COLUMN review_class text;

ALTER TABLE curated_blocks ADD CONSTRAINT ck_block_review_class CHECK (
    review_class IS NULL OR review_class IN (
        'NO_RULE', 'REGISTERED_NO_CONTAINER',
        'REGISTERED_NOT_OWNABLE', 'REGISTERED_DUPLICATE_FIELD'));

-- A parsed block has no review class; a REVIEW_REQUIRED block written
-- after 052 always has one. Pre-052 rows are left NULL rather than guessed.
ALTER TABLE curated_blocks ADD CONSTRAINT ck_block_review_class_status CHECK (
    status = 'REVIEW_REQUIRED' OR review_class IS NULL);

-- Absorption is only ever into a block of the same envelope, and only a
-- REVIEW_REQUIRED block is absorbed: a recognised block owns itself.
ALTER TABLE curated_blocks ADD CONSTRAINT ck_block_absorbed_only_if_unowned
    CHECK (absorbed_into_ordinal IS NULL OR status = 'REVIEW_REQUIRED');

COMMENT ON COLUMN curated_blocks.absorbed_into_ordinal IS
'D58. The ordinal of the field-bearing block (container or owned subsection) whose field text now includes this block. Set when an unrecognised or unownable block appeared inside an open container: it changes no ownership, so its characters stay in place as body of that field. NULL otherwise.';

COMMENT ON COLUMN curated_blocks.review_class IS
'D58. Why a REVIEW_REQUIRED block is not recognised structure: NO_RULE (matches no registered label), REGISTERED_NO_CONTAINER (matches one, but no container was open), REGISTERED_NOT_OWNABLE (matches one this container kind may not own), REGISTERED_DUPLICATE_FIELD (would be a second copy of a field the container holds).';

CREATE VIEW v_curated_absorbed_body AS
SELECT b.envelope_id,
       b.ordinal          AS absorbed_ordinal,
       b.raw_heading      AS absorbed_heading,
       b.review_class,
       t.ordinal          AS into_ordinal,
       t.raw_heading      AS into_heading,
       b.source_start,
       b.source_end,
       length(btrim(b.raw_text)) AS chars
  FROM curated_blocks b
  JOIN curated_blocks t
    ON t.envelope_id = b.envelope_id AND t.ordinal = b.absorbed_into_ordinal
 WHERE b.absorbed_into_ordinal IS NOT NULL;

COMMENT ON VIEW v_curated_absorbed_body IS
'Every unowned block whose text now sits inside a field -- "unowned bold inside a field" when the source is a flat .docx. Absorption is a cost of refusing to tell a label from emphasis by length or punctuation (Option 2); this view is what keeps it visible instead of silent. A long list against one field is a coverage gap for the practitioner to decide, not something the parser may resolve.';

GRANT SELECT ON v_curated_absorbed_body TO phi_runtime;
