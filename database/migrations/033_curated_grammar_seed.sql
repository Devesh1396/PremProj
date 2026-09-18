-- =====================================================================
-- 033_curated_grammar_seed.sql   The curated heading grammar, as rows
--
-- Separate from `032` because the rules are DATA and will grow by INSERT
-- as later sections of the curated document are met. Every rule states
-- the construct it recognises and why that construct is reusable — not
-- "Video 1 needs this to pass", which `ck_rule_justified` will accept as
-- a string and a reviewer must not.
--
-- DELIBERATELY ABSENT: rules for `Adherence philosophy`, `Adherence
-- intelligence`, `Assessment intelligence`, `How this changes the
-- consultation` and the document's section containers. Those appear in
-- Video 1 and are NOT on the practitioner's list of expected constructs,
-- so a rule for them would be fitted to this fixture. They become
-- REVIEW_REQUIRED, which reports the coverage gap with the text and the
-- byte range needed to close it.
-- =====================================================================

INSERT INTO curated_grammar_rules
 (rule_id, construct, pattern, heading_level, block_kind, field_name,
  example_heading, reusable_justification, expected_elsewhere, priority)
VALUES

-- ---- block-level -----------------------------------------------------
('STRATEGY_FAMILY',
 'A grouping heading that names a FAMILY of strategies, not a strategy',
 '^Strategy\s+family\s*[—–-]\s*(?P<name>.+)$', NULL, 'STRATEGY_FAMILY', NULL,
 'Strategy family — Movement',
 'A family heading collects strategies already defined elsewhere in the section. It must be recognised precisely so it is NOT counted as a strategy: Video 1 has six strategies and three family headings, and a grammar that conflated them would report nine.',
 'Any section that ends with a roll-up of its own strategies; the practitioner named this construct explicitly.',
 10),

('STRATEGY_NUMBERED',
 'A numbered strategy card, the document''s primary unit',
 '^(?:New\s+)?Strategy\s+\d+\s*[—–-]\s*(?P<name>.+)$', NULL, 'STRATEGY', NULL,
 'Strategy 1 — Breakfast restructuring',
 'Numbered strategy cards are the unit the practitioner writes in, and the numbering restarts per section. The optional "New " prefix is part of the same construct in later sections.',
 'Every video section that enumerates strategies, including the "New Strategy N" form the practitioner listed.',
 20),

('STRATEGY_CORE',
 'A strategy named as the section''s central one rather than numbered',
 '^Core\s+Strategy\s*[—–-]\s*(?P<name>.+)$', NULL, 'STRATEGY', NULL,
 'Core Strategy — Meal sequencing',
 'The same card construct with a qualifier instead of a number, for sections built around one dominant strategy rather than a list.',
 'Sections organised around a single central strategy; listed by the practitioner alongside the numbered form.',
 20),

('PRINCIPLE_NAMED',
 'A named practitioner principle heading',
 '^(?:MASTER\s+PRACTITIONER\s+PRINCIPLE|Master\s+principle|Core\s+(?:operating\s+)?principle|E7\s+principle|Practitioner\s+principle|Assessment\s+principle|Behaviour\s+principle|Problem-solving\s+principle|Decision\s+principle)\b.*$',
 NULL, 'PRINCIPLE', NULL,
 'Core operating principle — High-impact change with minimum unnecessary friction',
 'Principles are the second top-level construct in this document and carry the reasoning that governs strategy choice. The practitioner enumerated the naming variants directly, which is what this alternation encodes.',
 'The least-structured later sections are expected to be dominated by these forms rather than by numbered cards.',
 30),

-- ---- subsections of a strategy or principle --------------------------
('SUB_WHAT_MEANS', 'The definition subsection of a strategy card',
 '^What\s+the\s+strategy\s+means$', 3, 'SUBSECTION', 'what_it_means',
 'What the strategy means',
 'The definitional subsection of a card. Named by the practitioner as a standard subsection of the strategy construct.',
 'Every section using the numbered or core strategy-card construct.',
 100),

('SUB_WHY', 'The rationale subsection, phrased as a "Why ..." heading',
 '^Why\b.*$', 3, 'SUBSECTION', 'why_useful',
 'Why this can be useful',
 'Rationale subsections are written as a "Why ..." question or statement, and the tail varies with the strategy — "Why this can be useful", "Why retain it?", "Why this matters". The reusable construct is the leading interrogative, not any one of those strings, which is why this matches morphologically rather than by alternation.',
 'Every section; the rationale subsection is the most consistently present one after the definition.',
 100),

('SUB_DECISION', 'The prioritisation subsection — WHEN to reach for this',
 '^(?:Client\s+)?Decision\s+(?:logic|intelligence)$', 3, 'SUBSECTION',
 'client_decision_logic', 'Client decision logic',
 'The prioritisation layer, and the single most valuable field in the document: it states when a strategy matters, when it does not, which bottleneck it addresses and when another intervention comes first. The practitioner named all three surface forms, which vary by section without changing meaning.',
 'Every section that distinguishes "useful strategy" from "current priority"; the practitioner listed Client decision logic, Decision logic and Decision intelligence together.',
 100),

('SUB_WHEN_USEFUL', 'An explicit positive-indication subsection',
 '^When\s+useful$', 3, 'SUBSECTION', 'when_useful', 'When useful',
 'Some sections split the decision layer into explicit positive and negative indication subsections instead of one prose block.',
 'Sections that tabulate indications; named by the practitioner as a separate construct from Client decision logic.',
 100),

('SUB_WHEN_NOT_USEFUL', 'An explicit negative-indication subsection',
 '^When\s+not\s+useful$', 3, 'SUBSECTION', 'when_not_useful', 'When not useful',
 'The counterpart of the positive-indication subsection. Kept separate because "when this does not apply" is the half most often lost when a decision layer is flattened.',
 'The same sections that use "When useful"; the two appear as a pair.',
 100),

('SUB_ADAPTABILITY', 'How the strategy bends to the individual client',
 '^(?:Adaptability|.*\badaptation)$', 3, 'SUBSECTION', 'adaptability',
 'Adaptability',
 'The individualisation subsection, appearing both as the bare noun and as a qualified form such as "Adherence adaptation". Matching the morphological stem keeps the qualified variants inside one construct instead of needing a rule each.',
 'Sections that separate the reusable strategy from its per-client implementation.',
 100),

('SUB_LEVERAGE', 'How the strategy is used in consultation',
 '^Practitioner\s+leverage$', 3, 'SUBSECTION', 'practitioner_leverage',
 'Practitioner leverage',
 'The consultation-craft subsection: how to put the strategy to a client. Named by the practitioner as a standard subsection.',
 'Sections written for use in a live consultation rather than as reference.',
 100),

('SUB_IMPLEMENTATION', 'How the strategy is actually carried out',
 '^(?:\w+\s+)?[Ii]mplementation$', 3, 'SUBSECTION', 'implementation',
 'Behaviour implementation',
 'The execution subsection, bare or domain-qualified ("Behaviour implementation", "Nutrition implementation"). The qualifier names the domain and does not change the construct.',
 'Sections covering protocols and diet plans, where implementation detail is the bulk of the content.',
 100),

('SUB_ALTERNATIVES', 'Other implementations serving the same objective',
 '^(?:Future\s+)?Alternatives$', 3, 'SUBSECTION', 'alternatives',
 'Future alternatives',
 'The substitution subsection — what else serves the same objective when the preferred implementation is impractical. The "Future" qualifier marks alternatives not yet in the library and does not change the construct.',
 'Any section whose strategy has more than one viable implementation.',
 100),

('SUB_FALLBACKS', 'What to do when the strategy cannot be used',
 '^Fallbacks?$', 3, 'SUBSECTION', 'fallbacks', 'Fallback',
 'The degraded-path subsection, distinct from alternatives: a fallback applies when nothing in the family is workable.',
 'Sections dealing with constrained clients; named by the practitioner.',
 100),

('SUB_MONITORING', 'What to watch to tell whether it is working',
 '^Monitoring$', 3, 'SUBSECTION', 'monitoring', 'Monitoring',
 'The response-tracking subsection. It is what a later follow-up cycle reads to decide whether the assumed bottleneck was right.',
 'Sections that specify outcomes to track; named by the practitioner.',
 100),

('SUB_SAFETY', 'Safety context carried by the strategy itself',
 '^Safety(?:\s+context)?$', 3, 'SUBSECTION', 'safety_context', 'Safety',
 'The safety subsection. It must stay its own field rather than merging into general context, because the deterministic safety rules read named conditions.',
 'Sections covering medicated clients or interventions that shift glucose materially.',
 100),

('SUB_EVIDENCE_REL', 'What the source says about its own evidential standing',
 '^Evidence\s+relationship$', 3, 'SUBSECTION', 'evidence_relationship',
 'Evidence relationship',
 'Where the practitioner states how well evidenced a strategy is. Kept separate from any evidence record: it is a statement BY the practitioner, not a citation, and conflating the two is the D48 failure.',
 'Sections where the practitioner distinguishes well-supported strategies from candidates.',
 100);
