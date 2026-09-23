-- =====================================================================
-- 051_markup_depth_and_no_rule_level.sql
--
-- Two ways a model-assigned level could still pass as structure. Both
-- found on independent review of 0df47bf. Append-only.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. THE MARKUP DEPTH WAS PERSISTED UNDER A NAME THAT READS AS AUTHORED.
--
-- `curated_blocks.heading_level` holds the number of `#` characters the
-- converter emitted -- for both fixtures, chosen by a Claude model. 050
-- labelled it with a column comment, but a comment is not what a reader
-- of a query result sees: they see `heading_level = 3` and read an
-- authored level. The name itself was the claim.
--
-- Renamed to say what it is. It is kept rather than dropped because a
-- reviewer comparing a conversion against its source needs it, and it
-- reaches no retrieval: `curated_trace` and `curated_expansion` never
-- selected it and do not now.
-- ---------------------------------------------------------------------
ALTER TABLE curated_blocks
    RENAME COLUMN heading_level TO source_markup_depth;

COMMENT ON COLUMN curated_blocks.source_markup_depth IS
'SOURCE-MARKUP METADATA, NOT AUTHORED STRUCTURE. The count of Markdown `#` characters the converter emitted -- for the GATE 1 and GATE 4 fixtures, chosen by a Claude model; the canonical .docx states no level (0 Heading styles, 0 w:outlineLvl). Renamed from heading_level in 051 because that name read as an authored level. Kept for forensic audit only. Nothing in recognition, containment, heading_path or retrieval reads it; structural_provenance on the same row is never AUTHORED_STRUCTURAL_SIGNAL for a source that carries only this.';

-- ---------------------------------------------------------------------
-- 2. LEVEL DEPENDENCY COULD RETURN THROUGH DATA.
--
-- 048 set `heading_level = NULL` on the existing rules and added no
-- constraint. Registering a rule is an INSERT (hard rule 13), so a future
-- row with `heading_level = 3` would have restored level-gated matching
-- with no code change at all -- the same shape as the test teardown that
-- revived SUB_AUTHORED_SUBHEAD. The parser's comparison is also removed
-- (D57); this makes the registry refuse the value regardless of what any
-- code does with it.
-- ---------------------------------------------------------------------
ALTER TABLE curated_grammar_rules
    ADD CONSTRAINT ck_rule_no_heading_level CHECK (heading_level IS NULL);

COMMENT ON COLUMN curated_grammar_rules.heading_level IS
'MUST BE NULL (ck_rule_no_heading_level, 051). The canonical source states no heading level, so a rule gated on one would match on depth a converter invented. A rule recognises its construct by its registered label. The column is kept only so historical rows remain readable.';
