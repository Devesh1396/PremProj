-- =====================================================================
-- 039_curated_concept_rules_seed.sql
--
-- The concept-unit rules, as rows. Separate from `038` for the same
-- reason `033` is separate from `032`: these grow by INSERT as later
-- sections of the curated document are met, and a rule is data.
--
-- ---------------------------------------------------------------------
-- HOW A UNIT IS TOLD FROM PROSE, AND WHY IT IS NOT A LENGTH KNOB
-- ---------------------------------------------------------------------
-- The practitioner writes bold for two different jobs: NAMING something
-- ("**post-meal muscular activity**", "**Client overwhelmed**") and
-- EMPHASISING a whole statement ("**Restriction should have a reason. It
-- should not be the default measure...**"). Only the first is a concept
-- candidate. The second is a sentence, and sending a sentence to
-- `normalize.resolve()` is exactly the failure D51 names — the
-- `mechanism` mistake in a new costume.
--
-- The discriminator is GRAMMATICAL, not dimensional:
--
--   a unit is a PHRASE — it carries no sentence-ending punctuation
--   (. ? !), no comma, no quotation mark and no arrow, it does not end in
--   a colon (a colon-terminated run introduces what follows: it is a
--   lead-in, not a name), and `to_tsvector('english', ...)` finds at
--   least one lexeme in it (a run of stopwords — "**not**" — names
--   nothing).
--
-- There is no character count anywhere in it. A length threshold would be
-- a number that could be moved until the acceptance fixture passed; "is
-- this a sentence or a name?" cannot be moved, and it is a property of
-- how people write, not of this document.
--
-- ---------------------------------------------------------------------
-- DELIBERATELY ABSENT
-- ---------------------------------------------------------------------
-- * A rule for a whole BULLET ITEM. The bullets in Video 1's
--   `client_decision_logic` are conditional CLAUSES — "sedentary
--   behavior is substantial", "protein/fibre are minimal". They carry
--   real knowledge and they are not names, so under the rule above they
--   are prose and stay unlinked. Turning a clause into a concept phrase
--   needs a claim extractor, and the claim extractor for curated content
--   is K09, which D49 measured fabricating. Reported as a limitation
--   rather than papered over.
--
-- * A rule for SUBSECTION HEADINGS. "What the strategy means", "Why this
--   can be useful" are the GRAMMAR's own vocabulary — they are already
--   `curated_grammar_rules.field_name`, they describe the document's
--   structure and they name nothing clinical.
--
-- * A rule for the SECTION ROOT heading ("T2D / Insulin Resistance —
--   Engine 7 Practitioner Intelligence"). It does name the domain, but
--   splitting it needs a delimiter convention — is "/" a separator or
--   part of a term, as it is in "vegetable/fibre structure"? — and one
--   document cannot establish that. It becomes a rule when a second
--   section shows what the convention is.
-- =====================================================================

INSERT INTO curated_concept_rules
 (rule_id, construct, unit_kind, pattern, applies_to, example_unit,
  reusable_justification, expected_elsewhere, priority)
VALUES

('CARD_NAME',
 'The strategy or principle name, as the practitioner wrote it in the heading',
 'CARD_NAME', NULL, NULL,
 'Meal-linked postprandial movement',
 'The card name is the practitioner''s own naming of the unit of knowledge, already isolated from the numbering and the dash by the heading grammar (033) and already stored as a verbatim slice with its span. It is the one unit every curated card has by construction.',
 'Every curated section, in every naming form the heading grammar recognises — numbered, core, family and principle cards alike.',
 10),

('BOLD_LABEL',
 'A bold run the practitioner used to NAME something, rather than to emphasise a statement',
 'BOLD_RUN', '\*\*(?P<unit>[^*]+?)\*\*', NULL,
 'post-meal muscular activity',
 'Bold is the practitioner''s own emphasis marking, and where the emphasised run is a phrase rather than a sentence it is a name: the normalized knowledge object a strategy should eventually become, or the client situation a routing line keys on. The phrase test in this migration''s header is what separates the two, and it is grammatical rather than dimensional so it cannot be tuned toward a fixture.',
 'Any section where the practitioner names a normalized object or enumerates client situations; both constructs recur throughout the document.',
 20),

('BULLET_LABEL',
 'A bullet whose item begins with an explicit label, delimited from its explanation',
 'BULLET_LABEL',
 '^[ \t]*[-*+][ \t]+(?P<unit>[^:—–\n]+?)[ \t]*[:—–][ \t]+\S',
 NULL,
 'Vegetable starter: a portion of salad or cooked vegetable taken first',
 'A labelled bullet is a definition list written in markdown — the practitioner names a thing and then explains it, and the name is the part before the delimiter. It is the plainest concept-shaped construct there is, and it is the form the less-structured later sections are expected to use where they have no heading hierarchy to carry the names.',
 'Sections written as lists of named options rather than as numbered cards; the practitioner listed labelled bullets among the expected constructs.',
 30);
