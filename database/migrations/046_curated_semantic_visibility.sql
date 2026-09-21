-- =====================================================================
-- 046_curated_semantic_visibility.sql
--
-- STRUCTURALLY PRESERVED != SEMANTICALLY CLASSIFIED.
--
-- GATE 4's `SUB_AUTHORED_SUBHEAD` stores a subsection under the author's
-- own heading. That is the right behaviour and it is not being removed:
-- it preserves text a closed field list would drop or rename. But it
-- produces rows that LOOK exactly like rows the grammar understands, and
-- nothing in the schema said otherwise. `Berberine Safety / Gate` is
-- preserved perfectly and the system does not know it is safety.
--
-- Left alone, the first coverage report to count stored fields would say
-- Video 14 is "parsed" at a rate that reads as "understood", and the
-- semantic gap would disappear into a percentage at exactly the scale
-- where it matters most.
--
-- THE CLASSIFICATION KEYS ON HOW THE FIELD WAS NAMED, NEVER ON THE NAME.
-- An author heading `Monitoring` slugifies to `monitoring`, which IS a
-- registered role name (033's SUB_MONITORING). A view that matched
-- strings would promote that author-named field to "semantically
-- registered" on a coincidence of spelling -- the precise failure this
-- exists to prevent. So `curated_fields` records the PROVENANCE of its
-- own name.
--
-- NOTHING HERE INFERS A ROLE. No keyword rule, no heuristic, no model. A
-- role is registered only where the practitioner's grammar already named
-- the construct; everything else is honestly UNREGISTERED.
--
-- Append-only.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Where a field's NAME came from.
-- ---------------------------------------------------------------------
CREATE TYPE curated_field_name_source AS ENUM (
    'RULE',      -- a grammar rule named it, so the construct is recognised
    'HEADING',   -- the AUTHOR named it; the grammar has no idea what it is
    'BODY'       -- the block's own body before its first subsection
);

ALTER TABLE curated_fields
    ADD COLUMN name_source curated_field_name_source;

-- Backfill. Every pre-GATE-4 field came from a 033 rule except the
-- opening body, which has no heading and therefore no rule.
UPDATE curated_fields
   SET name_source = CASE WHEN field_name = 'opening_statement'
                          THEN 'BODY'::curated_field_name_source
                          ELSE 'RULE'::curated_field_name_source END
 WHERE name_source IS NULL;

ALTER TABLE curated_fields ALTER COLUMN name_source SET NOT NULL;

COMMENT ON COLUMN curated_fields.name_source IS
'How this field got its name. RULE: a grammar rule recognised the construct. HEADING: the author named it and the grammar does not know what it holds. BODY: the block body. Recorded because the NAME cannot carry this -- an author heading "Monitoring" slugifies onto a registered role name, and classifying by string would call it understood.';

-- ---------------------------------------------------------------------
-- 2. The registry of roles the system actually knows.
--
-- A row here is a claim that the system can ACT on a field, not merely
-- store it. Seeded from the constructs the practitioner named in `033`
-- and from nothing else.
-- ---------------------------------------------------------------------
CREATE TABLE curated_field_roles (
    field_name      text PRIMARY KEY,
    semantic_role   text NOT NULL,
    registered_by   text NOT NULL,
    note            text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_field_role_note CHECK (length(btrim(note)) >= 20)
);

COMMENT ON TABLE curated_field_roles IS
'Field names whose SEMANTIC ROLE is registered -- what the content is, not merely that it was stored. Adding one is an INSERT (hard rule 13) and is a deliberate act: it asserts the system knows what the field means. An author-named field NEVER appears here by being stored.';

INSERT INTO curated_field_roles (field_name, semantic_role, registered_by, note) VALUES
('what_it_means',        'DEFINITION',        'migration 033', 'The definitional subsection of a strategy card, named by the practitioner.'),
('why_useful',           'RATIONALE',         'migration 033', 'Why the strategy can help; the practitioner named the construct.'),
('client_decision_logic','PRIORITISATION',    'migration 033', 'When to reach for this and when something else comes first.'),
('when_useful',          'INDICATION',        'migration 033', 'Explicit positive indication, where a section splits the decision layer.'),
('when_not_useful',      'CONTRA_INDICATION', 'migration 033', 'Explicit negative indication; the half most often lost when flattened.'),
('adaptability',         'INDIVIDUALISATION', 'migration 033', 'How the strategy bends to the individual client.'),
('practitioner_leverage','CONSULTATION_CRAFT','migration 033', 'How the strategy is put to a client in consultation.'),
('implementation',       'EXECUTION',         'migration 033', 'How the strategy is actually carried out.'),
('alternatives',         'SUBSTITUTION',      'migration 033', 'Other implementations serving the same objective.'),
('fallbacks',            'DEGRADED_PATH',     'migration 033', 'What to do when nothing in the family is workable.'),
('monitoring',           'RESPONSE_TRACKING', 'migration 033', 'What to watch to tell whether the strategy is working.'),
('safety_context',       'SAFETY',            'migration 033', 'Safety context carried by the strategy itself; deterministic rules read named conditions.'),
('evidence_relationship','EVIDENCE_STANDING', 'migration 033', 'The practitioner''s own statement of how well evidenced a strategy is.');

-- ---------------------------------------------------------------------
-- 3. The audit view. Three states, and the third is the point.
-- ---------------------------------------------------------------------
CREATE VIEW v_curated_field_semantics AS
SELECT f.field_id,
       f.curated_id,
       f.principle_id,
       f.object_id,
       f.field_name,
       f.name_source,
       f.heading_path,
       f.source_start,
       f.source_end,
       length(f.text_value) AS chars,
       r.semantic_role,
       CASE
         WHEN f.name_source = 'RULE' AND r.field_name IS NOT NULL
              THEN 'SEMANTIC_ROLE_REGISTERED'
         WHEN f.name_source = 'RULE'
              THEN 'SEMANTIC_ROLE_UNREGISTERED'
         ELSE 'STRUCTURALLY_PRESERVED_ONLY'
       END AS semantic_state
  FROM curated_fields f
  LEFT JOIN curated_field_roles r
         ON r.field_name = f.field_name AND f.name_source = 'RULE';

COMMENT ON VIEW v_curated_field_semantics IS
'Per stored field: SEMANTIC_ROLE_REGISTERED (a rule named it and the role is registered), SEMANTIC_ROLE_UNREGISTERED (a rule named it, role not registered), STRUCTURALLY_PRESERVED_ONLY (the author named it, or it is a block body -- the text is preserved exactly and the system does not know what it is). The join is deliberately restricted to name_source = RULE so a slug colliding with a registered name cannot be reported as understood.';

-- Per envelope, so the gap is visible at corpus scale rather than per row.
CREATE VIEW v_curated_semantic_coverage AS
SELECT e.envelope_id,
       e.source_title,
       count(*) FILTER (WHERE s.semantic_state = 'SEMANTIC_ROLE_REGISTERED')    AS role_registered,
       count(*) FILTER (WHERE s.semantic_state = 'SEMANTIC_ROLE_UNREGISTERED')  AS role_unregistered,
       count(*) FILTER (WHERE s.semantic_state = 'STRUCTURALLY_PRESERVED_ONLY') AS preserved_only,
       count(*)                                                                AS fields_total,
       (SELECT count(*) FROM curated_blocks b
         WHERE b.envelope_id = e.envelope_id
           AND b.status = 'REVIEW_REQUIRED')                                   AS blocks_review_required
  FROM source_envelopes e
  JOIN v_curated_field_semantics s
    ON s.curated_id IN (SELECT curated_id FROM curated_strategies WHERE envelope_id = e.envelope_id)
    OR s.principle_id IN (SELECT principle_id FROM curated_principles WHERE envelope_id = e.envelope_id)
    OR s.object_id IN (SELECT object_id FROM curated_objects WHERE envelope_id = e.envelope_id)
 GROUP BY e.envelope_id, e.source_title;

COMMENT ON VIEW v_curated_semantic_coverage IS
'Structural preservation and semantic understanding, side by side and never added together. `preserved_only` is text stored perfectly that the system cannot act on. A coverage report that quotes fields_total alone, or calls preservation "parsed", is reporting the opposite of what this view exists to show.';

GRANT SELECT ON curated_field_roles, v_curated_field_semantics,
                v_curated_semantic_coverage TO phi_runtime;
