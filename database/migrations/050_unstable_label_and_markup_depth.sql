-- =====================================================================
-- 050_unstable_label_and_markup_depth.sql
--
-- Three corrections. Append-only: `033`, `048` and `049` are applied and
-- are not edited.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. A LABEL WHOSE MEANING IS NOT STABLE MUST NOT MAP BY SURFACE FORM.
--
-- `049` let 033's SUB_DECISION be owned by a curated object, so Video
-- 14's `Decision intelligence` block was stored as `client_decision_logic`
-- -- role PRIORITISATION, sent to Engine 1 Pass B as a rule for choosing
-- what to do first.
--
-- Its text is PROGNOSIS, not selection:
--
--     "A short timeline may be more plausible when: diabetes is
--      relatively recent ... glucose begins responding quickly ...
--      sufficient beta-cell capacity remains."
--
-- It says when a fast response is plausible. It says nothing about which
-- intervention to choose. Video 1's STORED `Decision intelligence` (under
-- Strategy 6) IS selection logic -- "use the options according to the
-- client's actual bottleneck" -- so the mapping is right there and wrong
-- here. Same surface form, two meanings, in two kinds of container.
--
-- 033's SUB_DECISION justification says its surface forms "vary by
-- section without changing meaning". THE CORPUS REFUTES THAT PREMISE, and
-- its stated provenance -- "the practitioner listed Client decision logic,
-- Decision logic and Decision intelligence together" -- traces to a
-- prompt that listed headings to RECOGNISE. A list of headings to
-- recognise is not a statement that they are synonyms, and it was read as
-- one.
--
-- Under the flat design a label is the ONLY structural signal, so the
-- rule going forward is: a label whose meaning is not stable across
-- sections must not map to a single field by surface form alone.
--
-- The fix, narrow and evidence-based:
--   * SUB_DECISION goes back to strategy and principle owners ONLY, so
--     every Video 1 row is untouched -- same rule, same field, same text.
--   * SUB_DECISION_LOGIC carries into curated objects ONLY the two forms
--     for which there is no counter-evidence, `Client decision logic` and
--     `Decision logic`. It does NOT match `Decision intelligence`.
--   * Video 14's `Decision intelligence` becomes REVIEW_REQUIRED, text and
--     span preserved.
--
-- Q1 REMAINS THE PRACTITIONER'S. This withdraws an answer the grammar had
-- given to it; it does not give a different one.
-- ---------------------------------------------------------------------
UPDATE curated_grammar_rules
   SET owner_kinds = ARRAY['STRATEGY', 'PRINCIPLE']
 WHERE rule_id = 'SUB_DECISION';

INSERT INTO curated_grammar_rules
 (rule_id, construct, pattern, heading_level, block_kind, field_name,
  field_name_source, owner_kinds, example_heading, reusable_justification,
  expected_elsewhere, priority)
VALUES
('SUB_DECISION_LOGIC',
 'The prioritisation subsection inside a curated object, in the two surface forms with no counter-evidence',
 '^(?:Client\s+)?Decision\s+logic$', NULL, 'SUBSECTION',
 'client_decision_logic', 'FIXED', ARRAY['CURATED_OBJECT'],
 'Client decision logic',
 'Carries 033''s decision construct into curated objects WITHOUT the `Decision intelligence` form. Video 14 showed that form means prognosis in a curated object and selection in a strategy card, so it is excluded here; `Client decision logic` and `Decision logic` have not been observed to mean anything else. If they are, this row is the one to narrow.',
 'Directive-organised sections whose objects carry an explicit prioritisation subsection.',
 101);

COMMENT ON COLUMN curated_grammar_rules.reusable_justification IS
'Why a rule''s construct is reusable. CORRECTION (050): SUB_DECISION''s text claims its surface forms "vary by section without changing meaning". Video 14 refutes that for `Decision intelligence` (prognosis there, selection in Video 1), and the claimed provenance was inferred from a list of headings to recognise, not from a statement that they are synonyms.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM curated_grammar_rules
                WHERE rule_id = 'SUB_DECISION'
                  AND 'CURATED_OBJECT' = ANY(owner_kinds)) THEN
        RAISE EXCEPTION 'SUB_DECISION can still be owned by a curated object';
    END IF;
    IF 'Decision intelligence' ~* (SELECT pattern FROM curated_grammar_rules
                                    WHERE rule_id = 'SUB_DECISION_LOGIC') THEN
        RAISE EXCEPTION 'SUB_DECISION_LOGIC matches Decision intelligence';
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 2. MARKDOWN DEPTH IS SOURCE-MARKUP METADATA, NOT STRUCTURE.
--
-- `curated_blocks.heading_level` is the number of `#` characters the
-- converter emitted. For both fixtures a Claude model chose those depths,
-- and the canonical source states none. It is kept for forensic audit --
-- a reviewer comparing a conversion against its source needs it -- and
-- NOTHING in recognition, containment, heading paths or retrieval reads
-- it (D57). `curated_trace` and `curated_expansion` do not return it.
-- ---------------------------------------------------------------------
COMMENT ON COLUMN curated_blocks.heading_level IS
'SOURCE-MARKUP METADATA, NOT STRUCTURE. The count of Markdown `#` characters the converter emitted -- for the GATE 1 and GATE 4 fixtures, chosen by a Claude model; the canonical .docx states no level. Kept for forensic audit only. Nothing in recognition, containment, heading_path or retrieval reads it, and retrieval does not return it.';

COMMENT ON COLUMN curated_blocks.heading_path IS
'Derived from PARSER STATE since 050/D57: a recognised container''s own heading; an owned subsection''s container heading > its own; an unrecognised block''s own heading with no parent. Never built from Markdown depth.';

-- ---------------------------------------------------------------------
-- 3. A WRONG ATTRIBUTION IN AN APPLIED MIGRATION.
--
-- `048`'s header says the model-assigned hierarchy is something "the
-- practitioner has confirmed". That is wrong. The conversion method was
-- confirmed by the DEVELOPER who generated the fixtures, not by the
-- practitioner. `048` is applied and cannot be edited, so the correct
-- statement is recorded where a schema reader will find it.
-- ---------------------------------------------------------------------
COMMENT ON TYPE curated_structural_provenance IS
'How a block''s STRUCTURE was established. CORRECTION TO 048''s HEADER: it says the practitioner confirmed the fixture conversion. The correct statement is -- TEXT: practitioner-authored, verified verbatim against T2D_V_1.docx. HIERARCHY: model-interpreted. The Markdown fixtures were generated using a Claude model, as confirmed by the developer who produced them. No deterministic converter or manifest records how heading depths were chosen. Not practitioner-authored.';
