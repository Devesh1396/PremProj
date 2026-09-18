-- =====================================================================
-- 032_curated_practitioner.sql   Curated practitioner knowledge, preserved
--
-- D49. K09 is the wrong extractor for a source that is ALREADY the output
-- of the distillation K09 performs. Measured: six strategies became five
-- claims, Strategy 6 vanished, `Client decision logic` survived nowhere,
-- and all seven `mechanism` fields were fabricated from model knowledge.
--
-- THIS IS NOT A SECOND INGESTION PATH (D37). The Knowledge Inbox, the
-- source envelope, rights, dedup, the chunk store, the concept registry
-- and the provenance registry are all unchanged and all reused. The only
-- architectural change is at EXTRACTOR DISPATCH: `source_kinds.extractor`
-- says which extractor a kind gets, and adding a kind is still an INSERT
-- (hard rule 13).
--
-- What is genuinely new is a place to put per-field provenance. No
-- existing table can express "this exact text came from bytes 9425-10645
-- of the source, verbatim" — and without that, "the model did not invent
-- anything" stays a subjective judgement instead of a test.
-- =====================================================================


-- ---------------------------------------------------------------------
-- A. Dispatch. One column, read by K09's queue.
-- ---------------------------------------------------------------------

ALTER TABLE source_kinds
    ADD COLUMN IF NOT EXISTS extractor text NOT NULL DEFAULT 'K09_MODEL';

COMMENT ON COLUMN source_kinds.extractor IS
'Which extractor this kind dispatches to. K09_MODEL is the model-based Claim Card extractor for RAW sources. CURATED_DETERMINISTIC is the deterministic structural parser for sources a human has already curated (D49). Registry data: routing a new kind is an INSERT, never a branch in ingestion code (hard rule 13, §47).';

-- The kind this build needs, seeded here so a fresh database reproduces
-- the acceptance test. `PRACTITIONER_FRAMEWORK` already existed as a
-- source_type; no near-duplicate type is created.
INSERT INTO source_kinds
    (source_kind, display_name, description, default_role, adapter_hint,
     long_form, seeded, source_type, extractor)
VALUES
    ('PRACTITIONER_CURATED', 'Practitioner-curated intelligence',
     'Normalized practitioner intelligence distilled BY HAND from one or '
     'more underlying sources, already deduplicated and structured. It is '
     'the OUTPUT of the distillation K09 performs, not an input to it.',
     'IMPLEMENTATION', 'MANUAL_FILE', true, true,
     'PRACTITIONER_FRAMEWORK', 'CURATED_DETERMINISTIC')
ON CONFLICT (source_kind) DO UPDATE
   SET extractor = excluded.extractor,
       source_type = excluded.source_type;


-- ---------------------------------------------------------------------
-- B. The heading grammar is a REGISTRY, not regexes buried in a parser
-- ---------------------------------------------------------------------
--
-- The curated document changes format between sections, and Video 1 is
-- one of the most structured. A parser fitted to it is not a parser. So
-- every rule must state what construct it recognises, why that construct
-- is a reusable document pattern rather than a Video 1 accident, and
-- which other section families are expected to use it.
--
-- `ck_rule_justified` is what stops "Video 1 needs this to pass" being a
-- sufficient reason to add a rule.
-- ---------------------------------------------------------------------

CREATE TABLE curated_grammar_rules (
    rule_id        text PRIMARY KEY,
    construct      text NOT NULL,
    pattern        text NOT NULL,
    heading_level  integer,
    block_kind     text NOT NULL,
    field_name     text,
    example_heading text NOT NULL,
    reusable_justification text NOT NULL,
    expected_elsewhere     text NOT NULL,
    priority       integer NOT NULL DEFAULT 100,
    active         boolean NOT NULL DEFAULT true,

    CONSTRAINT ck_rule_kind CHECK (
        block_kind IN ('STRATEGY','STRATEGY_FAMILY','PRINCIPLE','SUBSECTION')),
    CONSTRAINT ck_rule_field CHECK (
        (block_kind = 'SUBSECTION') = (field_name IS NOT NULL)),
    -- A justification has to say something. Twenty characters is not a
    -- quality bar; it is a refusal to accept an empty string.
    CONSTRAINT ck_rule_justified CHECK (
        length(btrim(reusable_justification)) >= 20
        AND length(btrim(expected_elsewhere)) >= 10)
);

COMMENT ON TABLE curated_grammar_rules IS
'The heading grammar for curated practitioner documents. Explicit and extensible by INSERT. Every rule carries the justification that it recognises a REUSABLE construct — the anti-overfitting control, because the acceptance fixture must test the parser and the parser must not be fitted to the fixture.';

GRANT SELECT ON curated_grammar_rules TO phi_runtime, phi_practitioner;


-- ---------------------------------------------------------------------
-- C. Every block of the document, parsed or not
-- ---------------------------------------------------------------------
--
-- A block the grammar does not recognise is REVIEW_REQUIRED and keeps its
-- heading, its full text and its byte range. It is never skipped: a
-- silently dropped block is how Strategy 6 disappeared, and nothing in
-- the output said so.
-- ---------------------------------------------------------------------

CREATE TYPE curated_block_status AS ENUM ('PARSED', 'REVIEW_REQUIRED');

CREATE TABLE curated_blocks (
    block_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    envelope_id   uuid NOT NULL REFERENCES source_envelopes(envelope_id) ON DELETE CASCADE,
    ordinal       integer NOT NULL,
    heading_path  text NOT NULL,
    raw_heading   text NOT NULL,
    heading_level integer NOT NULL,
    rule_id       text REFERENCES curated_grammar_rules(rule_id),
    block_kind    text,
    status        curated_block_status NOT NULL,
    failure_reason text,
    source_start  integer NOT NULL,
    source_end    integer NOT NULL,
    raw_text      text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),

    UNIQUE (envelope_id, ordinal),
    CONSTRAINT ck_block_span CHECK (source_end > source_start),
    -- Parsed means a rule matched. Unparsed means a reason was given.
    -- Neither state may be silent about which it is.
    CONSTRAINT ck_block_resolution CHECK (
        (status = 'PARSED' AND rule_id IS NOT NULL AND block_kind IS NOT NULL)
        OR (status = 'REVIEW_REQUIRED' AND rule_id IS NULL
            AND failure_reason IS NOT NULL))
);

CREATE INDEX idx_curated_blocks_review ON curated_blocks (envelope_id)
    WHERE status = 'REVIEW_REQUIRED';

COMMENT ON TABLE curated_blocks IS
'Every heading block in a curated document, including the ones the grammar could not parse. REVIEW_REQUIRED is a successful fail-closed outcome, not an error: it reports a coverage gap with the text and the byte range needed to close it.';

GRANT SELECT, INSERT, UPDATE, DELETE ON curated_blocks TO phi_runtime;
GRANT SELECT ON curated_blocks TO phi_practitioner;


-- ---------------------------------------------------------------------
-- D. The strategies and principles themselves
-- ---------------------------------------------------------------------

CREATE TABLE curated_strategies (
    curated_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    envelope_id  uuid NOT NULL REFERENCES source_envelopes(envelope_id) ON DELETE CASCADE,
    ordinal      integer NOT NULL,
    name         text NOT NULL,
    strategy_family text,
    heading_path text NOT NULL,
    source_start integer NOT NULL,
    source_end   integer NOT NULL,
    content_hash text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),

    UNIQUE (envelope_id, ordinal),
    UNIQUE (envelope_id, name),
    CONSTRAINT ck_curated_span CHECK (source_end > source_start)
);

COMMENT ON TABLE curated_strategies IS
'One row per strategy the practitioner wrote. Identity is (envelope, name) AND (envelope, ordinal), so a second import of the same source cannot create a second row and a dropped strategy cannot hide behind an unchanged count.';

CREATE TABLE curated_principles (
    principle_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    envelope_id  uuid NOT NULL REFERENCES source_envelopes(envelope_id) ON DELETE CASCADE,
    ordinal      integer NOT NULL,
    name         text NOT NULL,
    heading_path text NOT NULL,
    source_start integer NOT NULL,
    source_end   integer NOT NULL,
    content_hash text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),

    UNIQUE (envelope_id, ordinal),
    CONSTRAINT ck_principle_span CHECK (source_end > source_start)
);

COMMENT ON TABLE curated_principles IS
'Practitioner principles — "Core principle", "E7 principle", "MASTER PRACTITIONER PRINCIPLE". Text phrased as an instruction to the system is DATA here, never an instruction to follow.';


-- ---------------------------------------------------------------------
-- E. Per-field provenance. This is the load-bearing table.
-- ---------------------------------------------------------------------
--
-- Every stored text field is either VERBATIM_SOURCE — findable in the
-- original at the range it names — or TRANSFORMED, in which case it must
-- say by which rule. There is no third option, and that is what makes
-- "no invented mechanism" and "no claim stronger than the source"
-- mechanically testable rather than a matter of opinion.
-- ---------------------------------------------------------------------

CREATE TYPE curated_provenance AS ENUM ('VERBATIM_SOURCE', 'TRANSFORMED');

CREATE TABLE curated_fields (
    field_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    curated_id   uuid REFERENCES curated_strategies(curated_id) ON DELETE CASCADE,
    principle_id uuid REFERENCES curated_principles(principle_id) ON DELETE CASCADE,
    block_id     uuid REFERENCES curated_blocks(block_id) ON DELETE SET NULL,
    field_name   text NOT NULL,
    text_value   text NOT NULL,
    provenance   curated_provenance NOT NULL,
    transformation_type text,
    transformation_rule text,
    source_start integer NOT NULL,
    source_end   integer NOT NULL,
    heading_path text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_field_owner CHECK (
        (curated_id IS NOT NULL)::int + (principle_id IS NOT NULL)::int = 1),
    CONSTRAINT ck_field_span CHECK (source_end > source_start),
    CONSTRAINT ck_field_not_empty CHECK (length(btrim(text_value)) > 0),
    -- A transformation that does not say what it did is a rewrite.
    CONSTRAINT ck_field_transformation_declared CHECK (
        (provenance = 'VERBATIM_SOURCE'
         AND transformation_type IS NULL AND transformation_rule IS NULL)
        OR (provenance = 'TRANSFORMED'
            AND transformation_type IS NOT NULL
            AND transformation_rule IS NOT NULL))
);

CREATE UNIQUE INDEX uq_curated_field_strategy
    ON curated_fields (curated_id, field_name) WHERE curated_id IS NOT NULL;
CREATE UNIQUE INDEX uq_curated_field_principle
    ON curated_fields (principle_id, field_name) WHERE principle_id IS NOT NULL;

COMMENT ON TABLE curated_fields IS
'Per-field text with per-field provenance. VERBATIM_SOURCE must be findable in the original at (source_start, source_end) under the approved normalizations; TRANSFORMED must name the rule. `client_decision_logic` is a field HERE and is never folded into a description, a summary or a note — it is what tells E1 when a strategy matters and when another intervention should come first.';

GRANT SELECT, INSERT, UPDATE, DELETE ON curated_strategies, curated_principles,
      curated_fields TO phi_runtime;
GRANT SELECT ON curated_strategies, curated_principles, curated_fields
      TO phi_practitioner;


-- ---------------------------------------------------------------------
-- F. Reuse the provenance registry (hard rule 12)
-- ---------------------------------------------------------------------
--
-- A new derived kind adds an enum value and a registration trigger. It
-- never adds a foreign key to envelope_derived_records.
-- ---------------------------------------------------------------------

ALTER TYPE derived_kind ADD VALUE IF NOT EXISTS 'CURATED_STRATEGY';
ALTER TYPE derived_kind ADD VALUE IF NOT EXISTS 'CURATED_PRINCIPLE';

CREATE TRIGGER trg_register_curated_strategies AFTER INSERT ON curated_strategies
    FOR EACH ROW EXECUTE FUNCTION register_knowledge_entity('CURATED_STRATEGY', 'curated_id');
CREATE TRIGGER trg_deregister_curated_strategies AFTER DELETE ON curated_strategies
    FOR EACH ROW EXECUTE FUNCTION deregister_knowledge_entity('curated_id');

CREATE TRIGGER trg_register_curated_principles AFTER INSERT ON curated_principles
    FOR EACH ROW EXECUTE FUNCTION register_knowledge_entity('CURATED_PRINCIPLE', 'principle_id');
CREATE TRIGGER trg_deregister_curated_principles AFTER DELETE ON curated_principles
    FOR EACH ROW EXECUTE FUNCTION deregister_knowledge_entity('principle_id');
