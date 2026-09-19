-- =====================================================================
-- 040_curated_objects.sql   GATE 4. A curated object that is not a strategy.
--
-- WHY THIS EXISTS, and why it is not "curated_strategies with a flag".
--
-- Video 1 is organised as `Strategy N — Name`. Video 14 contains that
-- construct ZERO times. It is organised by CURATION DIRECTIVE:
--
--     ADD — Berberine as a Practitioner-Gated Supplement Adjunct
--     MERGE — Carbohydrate Reduction Is a Strategy Spectrum
--     SKIP — "Underground Vegetables Should Be Restricted"
--     REINFORCE — Earlier Energy Distribution / Late Eating
--     ADD / UPGRADE — Vinegar / ACV as a Meal-Targeted Food Adjunct
--
-- Eleven such headings. Writing them into `curated_strategies` would
-- assert that each one IS a strategy, and for the two SKIP blocks that
-- assertion is not merely imprecise, it is the failure the gate exists to
-- prevent: `SKIP — "Underground Vegetables Should Be Restricted"` stored
-- as a strategy is a rejected claim promoted to active knowledge.
--
-- THE DISPOSITION IS NOT INFERRED. It is the literal word the
-- practitioner wrote at the start of the heading, and it is stored
-- alongside the exact span it was read from. Nothing here decides what a
-- block means; it records what the author already declared.
--
-- VIDEO 1 IS NOT MIGRATED. `curated_strategies`, `curated_principles` and
-- their rows are untouched, and no view flattens one into the other. A
-- section written as numbered strategy cards is still parsed into
-- strategy cards. Rewriting Video 1 into the new shape for uniformity
-- would change stored rows GATE 1 proved byte-identical, for aesthetics.
--
-- Append-only (hard rule 10). `032` is not edited.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. The disposition vocabulary, as an enum rather than free text.
--
-- `knowledge_gaps.status` was free text and `foundation_ready` turned on
-- `status = 'OPEN'`, so `'open'` would have hidden a CRITICAL gap (D41).
-- The same argument applies with more force here: a retrieval filter that
-- excludes SKIP material must not be defeated by `'Skip'`.
--
-- Six values, deliberately not five. ADD_UPGRADE is its own disposition
-- because `ADD / UPGRADE — Vinegar / ACV` says something ADD does not:
-- the object already existed as a candidate and its standing is being
-- RAISED. Folding it into ADD loses the fact that there is a prior state;
-- folding it into MERGE loses the fact that its status changed.
-- ---------------------------------------------------------------------
CREATE TYPE curated_disposition AS ENUM (
    'ADD',              -- new knowledge this source establishes
    'ADD_UPGRADE',      -- knowledge that existed as a candidate, now raised
    'MERGE',            -- enriches knowledge that already exists
    'REINFORCE',        -- confirms existing knowledge, creates nothing
    'SKIP',             -- examined and explicitly refused by the practitioner
    'PROVENANCE_ONLY'   -- traceable that the source mentioned it; nothing active
);

-- Which dispositions may ever produce ACTIVE practitioner knowledge.
-- A function rather than a column so the answer cannot drift per row.
CREATE FUNCTION curated_disposition_is_active(d curated_disposition)
RETURNS boolean
LANGUAGE sql IMMUTABLE
SET search_path = public, pg_temp
AS $$ SELECT d IN ('ADD', 'ADD_UPGRADE', 'MERGE') $$;

COMMENT ON FUNCTION curated_disposition_is_active(curated_disposition) IS
'REINFORCE creates nothing by the author''s own instruction ("No new strategy object."). SKIP is an explicit refusal. PROVENANCE_ONLY is a trace. None of the three may become active practitioner knowledge, and that is a property of the disposition, not a decision any caller gets to make.';

-- ---------------------------------------------------------------------
-- 2. The object itself.
--
-- Same shape as `curated_strategies` -- envelope, ordinal, name, heading
-- path, span, content hash -- plus the disposition and the span the
-- disposition word itself was read from. `ck_object_directive_span`
-- keeps that honest: the recorded directive span must be inside the
-- object's own span. D48: a populated provenance field that points
-- somewhere plausible but wrong is the shape that passes review.
-- ---------------------------------------------------------------------
CREATE TABLE curated_objects (
    object_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    envelope_id      uuid NOT NULL REFERENCES source_envelopes(envelope_id)
                          ON DELETE CASCADE,
    ordinal          integer NOT NULL,
    disposition      curated_disposition NOT NULL,
    name             text NOT NULL,
    heading_path     text NOT NULL,
    source_start     integer NOT NULL,
    source_end       integer NOT NULL,
    -- where the directive word itself sits, so "this is a SKIP" is
    -- traceable to characters rather than asserted.
    directive_start  integer NOT NULL,
    directive_end    integer NOT NULL,
    -- the NAME's own span, for the concept resolver (D52/GATE 3).
    name_start       integer NOT NULL,
    name_end         integer NOT NULL,
    content_hash     text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_object_span CHECK (source_end > source_start),
    CONSTRAINT ck_object_name_span CHECK (name_end > name_start),
    CONSTRAINT ck_object_directive_span CHECK (
        directive_end > directive_start
        AND directive_start >= source_start
        AND directive_end   <= source_end),
    CONSTRAINT ck_object_name_within CHECK (
        name_start >= source_start AND name_end <= source_end),
    UNIQUE (envelope_id, ordinal),
    UNIQUE (envelope_id, name)
);

COMMENT ON TABLE curated_objects IS
'A curated block whose primary unit is a curation DIRECTIVE rather than a numbered strategy card (GATE 4, Video 14). Not a superset of curated_strategies and not a replacement for it: a section written as strategy cards is still parsed into curated_strategies, unmigrated.';

CREATE INDEX ix_curated_objects_envelope ON curated_objects (envelope_id);
CREATE INDEX ix_curated_objects_active ON curated_objects (envelope_id)
    WHERE curated_disposition_is_active(disposition);

-- Provenance registry (hard rule 12): a new derived kind is an enum value
-- plus a registration trigger, never a new foreign key on the provenance
-- table.
ALTER TYPE derived_kind ADD VALUE IF NOT EXISTS 'CURATED_OBJECT';

-- ---------------------------------------------------------------------
-- 3. `curated_fields` gains a third owner.
--
-- Rather than a second field table. The per-field provenance contract --
-- VERBATIM_SOURCE or TRANSFORMED with the rule named, and nothing else --
-- is the thing GATE 1 proved, and a parallel table would be a second
-- place for that contract to be enforced differently.
-- ---------------------------------------------------------------------
ALTER TABLE curated_fields
    ADD COLUMN object_id uuid REFERENCES curated_objects(object_id)
        ON DELETE CASCADE;

ALTER TABLE curated_fields DROP CONSTRAINT ck_field_owner;
ALTER TABLE curated_fields ADD CONSTRAINT ck_field_owner CHECK (
    (curated_id IS NOT NULL)::int
  + (principle_id IS NOT NULL)::int
  + (object_id IS NOT NULL)::int = 1);

CREATE UNIQUE INDEX uq_curated_field_object
    ON curated_fields (object_id, field_name) WHERE object_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- 4. Practitioner verification, attached to a SPAN.
--
-- D49 state B. `evidence_records` has no verification_actor /
-- verification_status; D50 reported that gap and deliberately did not
-- force Video 1 into a generic flag because Video 1 contains no such
-- passage. VIDEO 14 DOES:
--
--     "I checked the underlying published report."
--
-- so the gap is now load-bearing and is closed here.
--
-- IT IS ATTACHED TO THE STATEMENT, NOT TO THE DOCUMENT. Video 14 also
-- discusses berberine and ACV evidence that the practitioner did NOT say
-- they personally checked. A verification recorded at document level
-- would silently promote those to PRACTITIONER_VERIFIED -- the exact
-- spreading the gate's negative control tests for. Hence a row per
-- verification statement, carrying its own span, and a foreign key to one
-- object.
--
-- There is no SYSTEM_VERIFIED value here and that is deliberate. This
-- table records what a human stated in a curated document. An automated
-- verification is a different claim, made by a different layer, and K10
-- is closed (D48).
-- ---------------------------------------------------------------------
CREATE TYPE curated_verification_actor AS ENUM ('PRACTITIONER');
CREATE TYPE curated_verification_status AS ENUM (
    'PRACTITIONER_VERIFIED',      -- the practitioner says they checked the source
    'SOURCE_CLAIM_UNVERIFIED'     -- stated by the source; nobody checked it here
);

CREATE TABLE curated_verifications (
    verification_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id           uuid NOT NULL REFERENCES curated_objects(object_id)
                             ON DELETE CASCADE,
    verification_actor  curated_verification_actor NOT NULL,
    verification_status curated_verification_status NOT NULL,
    -- the exact authored sentence, verbatim, and where it is.
    statement_text      text NOT NULL,
    source_start        integer NOT NULL,
    source_end          integer NOT NULL,
    rule_id             text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_verification_span CHECK (source_end > source_start),
    -- D48 again, mechanically: the recorded span must be the right LENGTH
    -- for the statement it claims. The importer additionally re-reads the
    -- preserved raw file and compares the characters; this is the floor
    -- that holds even if the importer is bypassed.
    CONSTRAINT ck_verification_span_is_statement
        CHECK (length(statement_text) = source_end - source_start),
    CONSTRAINT ck_verification_not_empty
        CHECK (length(btrim(statement_text)) > 0),
    UNIQUE (object_id, source_start, source_end)
);

COMMENT ON TABLE curated_verifications IS
'D49 state B. A verification the PRACTITIONER performed during curation, attached to the exact statement span that carries it. Never widened to the document: other evidence passages in the same source do not inherit it. Never re-verified by K10, never downgraded because automation did not confirm it, never converted to a system verification.';

-- ---------------------------------------------------------------------
-- 5. The verification phrase registry.
--
-- Hard rule 13: recognising a new authored construct is data, not code.
-- A phrase pattern lives here with the justification for why the
-- construct is reusable and a counterexample it must NOT match, exactly
-- as `curated_grammar_rules` does for headings.
--
-- `ck_verification_rule_justified` refuses a rule with no justification
-- or no counterexample. A reviewer must still read them; the constraint
-- only stops the field being empty.
-- ---------------------------------------------------------------------
CREATE TABLE curated_verification_rules (
    rule_id                 text PRIMARY KEY,
    construct               text NOT NULL,
    pattern                 text NOT NULL,
    verification_actor      curated_verification_actor NOT NULL,
    verification_status     curated_verification_status NOT NULL,
    example_statement       text NOT NULL,
    counterexample          text NOT NULL,
    reusable_justification  text NOT NULL,
    active                  boolean NOT NULL DEFAULT true,
    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_verification_rule_justified CHECK (
        length(btrim(reusable_justification)) >= 40
        AND length(btrim(counterexample)) > 0)
);

COMMENT ON TABLE curated_verification_rules IS
'Authored verification statements, as registry rows. Adding one is an INSERT (hard rule 13). Every rule must say why its construct is reusable beyond the section that prompted it, and must name text it must NOT match.';

-- ---------------------------------------------------------------------
-- 6. Registration and RLS posture.
--
-- Curated knowledge is library material, not client data: the existing
-- curated tables are not RLS-forced and these follow them rather than
-- inventing a third posture.
-- ---------------------------------------------------------------------
GRANT SELECT ON curated_objects, curated_verifications,
                curated_verification_rules TO phi_runtime;
GRANT INSERT, UPDATE, DELETE ON curated_objects, curated_verifications
    TO phi_runtime;
