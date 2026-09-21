-- =====================================================================
-- 048_flat_structure.sql   THE CANONICAL SOURCE IS STRUCTURALLY FLAT.
--
-- Measured on the real T2D_V_1.docx:
--
--     paragraphs                13,763
--     Heading-styled paragraphs      0
--     explicit w:outlineLvl          0
--     paragraphs with w:numPr      351
--     bold-only paragraphs       4,207
--     longest bold-only        838 chars
--
-- There is NO authored multi-level hierarchy. The `##` and `###` levels in
-- the Video 1 and Video 14 markdown fixtures were assigned by a model
-- during conversion -- the practitioner has confirmed this, and the TEXT
-- was independently verified verbatim (0 genuine differences over 218 and
-- 245 content lines). The words are authored. The levels are not.
--
-- And bold is not a reliable heading signal either: in that document
-- section titles, subsection labels and full body sentences carry
-- identical bold formatting, the longest bold run being 838 characters.
--
-- So the grammar stops depending on level. Two changes, both data:
--
--   1. Every SUBSECTION rule loses `heading_level = 3`. A registered
--      LABEL recognises the construct; containment is decided by parser
--      state (the open container), not by comparing numbers that the
--      author never wrote.
--
--   2. SUB_AUTHORED_SUBHEAD is DEACTIVATED, not renamed. Its pattern is
--      `^(?P<name>.+)$` -- it matches any text whatsoever, and LEVEL 3 WAS
--      ITS ONLY DISCRIMINATOR. Freed of the level it would match every
--      line in the document. Keeping it while removing the level
--      dependency would be the worst of both.
--
-- CONSEQUENCE, STATED RATHER THAN HIDDEN: the fields Video 14 recognised
-- only through that rule move to REVIEW_REQUIRED. That includes
-- `Berberine Safety / Gate` and `ACV Protocol Guardrails` -- the first
-- safety content in the corpus. Their text and spans are preserved
-- exactly as before; what is withdrawn is the claim that the parser knew
-- they were fields. That is fail-closed behaviour and it is correct.
--
-- Append-only (hard rule 10). `033` and `041` are applied and unedited.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Level stops being a matching condition for subsections.
-- ---------------------------------------------------------------------
UPDATE curated_grammar_rules
   SET heading_level = NULL
 WHERE block_kind = 'SUBSECTION';

-- ---------------------------------------------------------------------
-- 2. The catch-all rule is retired.
-- ---------------------------------------------------------------------
UPDATE curated_grammar_rules
   SET active = false
 WHERE rule_id = 'SUB_AUTHORED_SUBHEAD';

COMMENT ON COLUMN curated_grammar_rules.heading_level IS
'Historical. NULL everywhere for SUBSECTION rules since 048: the canonical source states no heading level, so the converted markdown levels the fixtures carry are model-assigned and must not gate recognition. A rule recognises its construct by its registered LABEL; containment is parser state.';

-- ---------------------------------------------------------------------
-- 3. STRUCTURAL PROVENANCE, kept separate from text provenance.
--
-- `curated_fields.provenance` answers "is this text the source's own
-- characters?" and must keep answering only that. Whether the STRUCTURE
-- around the text was authored or derived is a different question, and
-- overloading one column with both would make VERBATIM_SOURCE mean two
-- things at once.
--
-- Three states, which is exactly what can honestly be distinguished:
--
--   AUTHORED_STRUCTURAL_SIGNAL      the document itself stated the
--                                   structure (a Word Heading style, an
--                                   explicit outline level). DEFINED AND
--                                   CURRENTLY UNUSED -- no source this
--                                   build ingests carries one, and that
--                                   absence is the finding.
--   GRAMMAR_DERIVED_CLASSIFICATION  a registered rule recognised the
--                                   construct deterministically.
--   NO_HIERARCHY_AVAILABLE          nothing recognised it; no structural
--                                   claim is made.
-- ---------------------------------------------------------------------
CREATE TYPE curated_structural_provenance AS ENUM (
    'AUTHORED_STRUCTURAL_SIGNAL',
    'GRAMMAR_DERIVED_CLASSIFICATION',
    'NO_HIERARCHY_AVAILABLE'
);

ALTER TABLE curated_blocks
    ADD COLUMN structural_provenance curated_structural_provenance;

UPDATE curated_blocks
   SET structural_provenance = CASE
         WHEN rule_id IS NOT NULL
           THEN 'GRAMMAR_DERIVED_CLASSIFICATION'::curated_structural_provenance
           ELSE 'NO_HIERARCHY_AVAILABLE'::curated_structural_provenance END
 WHERE structural_provenance IS NULL;

ALTER TABLE curated_blocks
    ALTER COLUMN structural_provenance SET NOT NULL;

COMMENT ON COLUMN curated_blocks.structural_provenance IS
'How this block''s STRUCTURE was established -- never how its text was obtained, which is curated_fields.provenance. AUTHORED_STRUCTURAL_SIGNAL is defined and unused: no source ingested today carries an authored heading level, and saying so is the point.';

CREATE VIEW v_curated_structural_provenance AS
SELECT b.envelope_id,
       b.structural_provenance,
       count(*) AS blocks
  FROM curated_blocks b
 GROUP BY b.envelope_id, b.structural_provenance;

COMMENT ON VIEW v_curated_structural_provenance IS
'Per envelope: how many blocks had their structure derived by the grammar versus not recognised at all. A column of AUTHORED_STRUCTURAL_SIGNAL would mean a source arrived with its own hierarchy; none has.';

GRANT SELECT ON v_curated_structural_provenance TO phi_runtime;
