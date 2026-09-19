-- =====================================================================
-- 041_curated_object_rules.sql   GATE 4 grammar delta, as registry rows.
--
-- TWO rules. That number is the point of this migration.
--
-- Video 14 sends 60 of 61 blocks to REVIEW_REQUIRED under the Video 1
-- grammar. It would be easy to close most of that by adding a rule per
-- unmatched heading -- `Final E7 status`, `Strategy tier`, `Best use`,
-- `Time horizon`, `Our leverage`, and twenty more. Every one of those
-- would exist because this fixture contains it, which is the definition
-- of a parser fitted to its test.
--
-- So the bar is unchanged from `033`: a rule is added only for a
-- construct that is REUSABLE AUTHORED VOCABULARY, and the row says why.
-- Everything else stays REVIEW_REQUIRED with its heading, its text and
-- its span -- the parser reporting a coverage gap, not failing.
--
-- Deliberately NOT added, and reported instead:
--   `Final E7 status`, `Strategy tier`   -- 2 occurrences each, both in
--       this one section. Prem's own status vocabulary and plausibly
--       reusable, but two hits inside a single fixture is not evidence of
--       that, and neither is on the practitioner's construct list.
--   `When potentially worth considering`, `When not to prioritize`
--       -- these are Q1. A rule would decide whether they are
--       `client_decision_logic` under another name, and that is the
--       practitioner's call. Left REVIEW_REQUIRED on purpose: the
--       decision stays open and reversible, where aliasing would not.
--   `Berberine Safety / Gate`, `ACV Protocol Guardrails`   -- Q3.
--   Every assessment / consultation / problem-solving / market heading.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. The registry has to be able to EXPRESS these rules first.
--
-- Two things `033`'s shape cannot say, and both are extended here rather
-- than worked around in the parser:
--
--   a. a block kind of CURATED_OBJECT
--   b. a subsection whose FIELD NAME comes from the author's own heading
--      instead of from a fixed name in the rule
--
-- and one thing it said implicitly that now has to be explicit:
--
--   c. WHICH block kinds may own a subsection. `033` hard-coded
--      STRATEGY/PRINCIPLE inside `attach()`. Left there, the generic
--      subsection rule below would start matching level-3 headings inside
--      Video 1's strategy cards and change rows GATE 1 proved
--      byte-identical. Making ownership a column keeps the new rule
--      confined to the construct it was written for, by data rather than
--      by a branch someone has to remember.
-- ---------------------------------------------------------------------
ALTER TABLE curated_grammar_rules
    DROP CONSTRAINT ck_rule_kind;
ALTER TABLE curated_grammar_rules
    ADD CONSTRAINT ck_rule_kind CHECK (block_kind = ANY (ARRAY[
        'STRATEGY', 'STRATEGY_FAMILY', 'PRINCIPLE', 'SUBSECTION',
        'CURATED_OBJECT']));

ALTER TABLE curated_grammar_rules
    ADD COLUMN field_name_source text NOT NULL DEFAULT 'FIXED',
    ADD COLUMN owner_kinds text[];

ALTER TABLE curated_grammar_rules
    ADD CONSTRAINT ck_rule_field_name_source
        CHECK (field_name_source IN ('FIXED', 'HEADING'));

-- A subsection rule names its field either with a fixed name or from the
-- heading -- exactly one of the two, never both and never neither. Every
-- non-subsection rule has no field at all.
ALTER TABLE curated_grammar_rules DROP CONSTRAINT ck_rule_field;
ALTER TABLE curated_grammar_rules ADD CONSTRAINT ck_rule_field CHECK (
    CASE WHEN block_kind = 'SUBSECTION'
         THEN (field_name IS NOT NULL) <> (field_name_source = 'HEADING')
         ELSE field_name IS NULL AND field_name_source = 'FIXED'
    END);

-- `owner_kinds` belongs to subsection rules and to nothing else.
ALTER TABLE curated_grammar_rules ADD CONSTRAINT ck_rule_owner_kinds CHECK (
    (block_kind = 'SUBSECTION') OR owner_kinds IS NULL);

COMMENT ON COLUMN curated_grammar_rules.owner_kinds IS
'Which enclosing block kinds may own a subsection matched by this rule. NULL means the original behaviour: a strategy or a principle. It is a column and not a branch in attach() because the alternative is a generic rule leaking into Video 1''s strategy cards and rewriting rows GATE 1 proved byte-identical.';

COMMENT ON COLUMN curated_grammar_rules.field_name_source IS
'FIXED: the field is the rule''s own field_name. HEADING: the author named it, and the field is their heading text slugified, with the heading preserved verbatim and its span recorded. HEADING exists because a directive block subdivides into headings the practitioner invents per block, and a closed field list would either drop the ones it does not know or rename them.';

-- ---------------------------------------------------------------------
-- 2. The two rules.
-- ---------------------------------------------------------------------
INSERT INTO curated_grammar_rules
 (rule_id, construct, pattern, heading_level, block_kind, field_name,
  field_name_source, owner_kinds, example_heading, reusable_justification,
  expected_elsewhere, priority)
VALUES

('CURATION_DIRECTIVE',
 'A block introduced by the curation decision the practitioner made about it',
 '^(?P<directive>ADD\s*/\s*UPGRADE|ADD|MERGE|REINFORCE|SKIP|PROVENANCE\s+ONLY)\s*[—–-]\s*(?P<name>.+)$',
 NULL, 'CURATED_OBJECT', NULL, 'FIXED', NULL,
 'ADD — Berberine as a Practitioner-Gated Supplement Adjunct',
 'ADD / ADD-UPGRADE / MERGE / REINFORCE / SKIP / PROVENANCE ONLY is the editing language the practitioner uses to tell Engine 7 what to DO with a block, and it is the organising unit of every section not written as numbered strategy cards. Video 14 uses it eleven times and uses "Strategy N" zero times. It is also self-describing: the disposition is the literal word the author wrote, so recognising it requires no inference about what the block means. The roll-up at the end of the section repeats the same vocabulary as its own headings, which is the author confirming it is a vocabulary rather than a phrasing.',
 'Every section organised by curation decision rather than by strategy enumeration; on the evidence of Video 14 that is the majority form.',
 15),

('SUB_AUTHORED_SUBHEAD',
 'A subsection of a curated object, named by the author rather than by the grammar',
 '^(?P<name>.+)$', 3, 'SUBSECTION', NULL, 'HEADING',
 ARRAY['CURATED_OBJECT'],
 'Escalation logic',
 'A directive block subdivides into headings the practitioner invents per block: "Escalation logic", "E7 reasoning", "Best use", "Important separation". These are deliberately NOT a closed vocabulary, and forcing them into one would either drop the headings the grammar does not know or rename them -- both of which are the flattening GATE 1 exists to prevent, arriving through the grammar instead of through K09. So the construct this rule recognises is not any particular heading; it is "the author names their own subsection", and the field takes the author''s name. It is last by priority so every specific rule in 033 wins first, and owner_kinds confines it to curated objects so it can never touch a strategy card.',
 'Every directive-organised section. The construct is authorial, not lexical, so it does not go stale when the next section invents different subheadings.',
 900);

-- ---------------------------------------------------------------------
-- 3. The one verification construct, with its counterexample.
-- ---------------------------------------------------------------------
INSERT INTO curated_verification_rules
 (rule_id, construct, pattern, verification_actor, verification_status,
  example_statement, counterexample, reusable_justification)
VALUES
('PRACTITIONER_CHECKED_SOURCE',
 'A first-person statement that the practitioner personally consulted the underlying publication',
 '(?m)^[ \t]*I[ \t]+(?:checked|verified|read|reviewed|pulled|looked[ \t]+up)[ \t]+the[ \t]+(?:(?:underlying|original|actual|published|full)[ \t]+)*(?:report|paper|study|trial|publication|meta-analysis|review)\b[^\n]*$',
 'PRACTITIONER', 'PRACTITIONER_VERIFIED',
 'I checked the underlying published report.',
 'MUST NOT match a statement about someone else, or about something other than the publication: "The source checked the underlying report", "I checked with the client", "I checked the numbers against my own practice", "We should check the underlying report". The pattern requires a line that BEGINS with first-person "I", immediately followed by a checking verb, then "the", then optional qualifiers, then a publication noun -- and none of those four satisfies it.',
 'It is the ONLY textual signal separating D49 state B (practitioner-verified evidence) from state C (an unverified source claim), and once collapsed the two are indistinguishable in the stored row. The practitioner states verification in the first person because they are narrating their own curation work, and that narration recurs wherever they chose to check a citation rather than repeat it. Missing it does not degrade gracefully: it silently discards work a human already did and sends the item back toward an evidence layer that is closed.');
