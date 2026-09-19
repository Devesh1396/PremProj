-- =====================================================================
-- 038_curated_retrieval.sql   GATE 3 — the bridge from preserved
--                             curated knowledge to retrieval
--
-- GATE 1 (D50) preserved six Video 1 strategies with per-field, per-byte
-- provenance and did NOT write them into `strategies`. That was correct
-- and it left them unreachable: `retrieval.by_concept()` reads
-- `strategies` and `implementation_patterns`, and neither contains a
-- curated row.
--
-- THE OBVIOUS FIX IS THE WRONG ONE. Copying `curated_fields.text_value`
-- into `strategies.summary` / `.mechanism` produces a SECOND copy of the
-- practitioner's words with no span, no per-field provenance and no
-- verbatim guarantee — and the moment two copies exist, the one retrieval
-- returns is the one nobody verified. `strategies.mechanism` is the exact
-- column D49 measured K09 fabricating. A curated import must never fill
-- it.
--
-- So the curated rows stay where they are and RETRIEVAL LEARNS A SECOND
-- ROW SOURCE. That is the accepted risk, recorded with its alternative in
-- DECISIONS.md D52:
--
--   ACCEPTED  two row sources inside one retrieval function may diverge.
--   REJECTED  one row source, reached by duplicating preserved text into
--             `strategies`, which loses the provenance GATE 1 exists for.
--
-- The divergence risk is bounded on purpose: the new source lives INSIDE
-- `by_concept()` and `by_fts()` — the same channels, the same score
-- normalization, the same merge, the same rerank — exactly as
-- `implementation_patterns` already does. There is no second pipeline and
-- no second ranking.
-- =====================================================================


-- ---------------------------------------------------------------------
-- A. Concept extraction rules are a REGISTRY, like the heading grammar
-- ---------------------------------------------------------------------
--
-- `curated_grammar_rules` (033) says which HEADINGS are a strategy. This
-- says which TEXTUAL UNITS inside a card may be offered to the concept
-- resolver. Same anti-overfitting control and the same reason: a rule
-- written because one fixture needs one phrase is not a rule.
--
-- WHAT A UNIT IS NOT. It is never a summary of a paragraph, never a
-- shorter phrase a model was asked to invent, and never a whole prose
-- block sent to `normalize.resolve()` — that last one is the `mechanism`
-- mistake in a new costume (D51). A unit is a span of the practitioner's
-- own characters, findable in the source at the offsets stored with it.
-- ---------------------------------------------------------------------

CREATE TABLE curated_concept_rules (
    rule_id      text PRIMARY KEY,
    construct    text NOT NULL,
    -- Which delimiter the practitioner used. The extractor dispatches on
    -- this; the `pattern` is how the delimiter is found.
    unit_kind    text NOT NULL,
    pattern      text,
    -- NULL = every field of a card. A non-null list restricts the rule to
    -- named fields, and a rule that needs one has to say why in its
    -- justification.
    applies_to   text[],
    example_unit text NOT NULL,
    reusable_justification text NOT NULL,
    expected_elsewhere     text NOT NULL,
    priority     integer NOT NULL DEFAULT 100,
    active       boolean NOT NULL DEFAULT true,

    CONSTRAINT ck_concept_rule_unit CHECK (
        unit_kind IN ('CARD_NAME', 'BOLD_RUN', 'BULLET_LABEL')),
    CONSTRAINT ck_concept_rule_justified CHECK (
        length(btrim(reusable_justification)) >= 20
        AND length(btrim(expected_elsewhere)) >= 10)
);

COMMENT ON TABLE curated_concept_rules IS
'Which textual units of a curated card may be offered to the concept resolver. Registry data: adding a construct is an INSERT (hard rule 13). Every rule states why the construct is REUSABLE across sections, because a rule fitted to one fixture tests nothing. A field that carries knowledge but contains no unit any rule recognises stays UNLINKED and is reported — it is never summarised into a concept phrase.';

GRANT SELECT ON curated_concept_rules TO phi_runtime, phi_practitioner;


-- ---------------------------------------------------------------------
-- B. The link. Traceable to a byte range, or it is not provenance.
-- ---------------------------------------------------------------------
--
-- D48: "PRESENCE OF A SOURCE LOCATION IS NOT PROVENANCE." Every stored
-- range in the D47 run looked right and six of seven did not contain the
-- statement they cited. So a link carries the phrase AND the span, and
-- two checks stand behind it:
--
--   here        `ck_link_span_is_phrase` — the span's LENGTH is the
--               phrase's length, so a range that cannot possibly contain
--               it is refused at insert;
--   in code     `curated_concepts.verify()` re-reads the preserved raw
--               file and asserts source[start:end] == phrase, exactly as
--               `curated_parser.verify()` does for fields. Nothing is
--               stored until it passes.
--
-- This table deliberately does NOT reuse `strategy_concepts`. That table
-- foreign-keys `strategies`, carries a clinical `link_role` and has no
-- span at all — so a curated link stored there would have to invent a
-- role the source never stated and would lose the byte range that is the
-- whole point of GATE 1.
-- ---------------------------------------------------------------------

CREATE TABLE curated_strategy_concepts (
    link_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    curated_id   uuid NOT NULL REFERENCES curated_strategies(curated_id) ON DELETE CASCADE,
    concept_id   uuid NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    rule_id      text NOT NULL REFERENCES curated_concept_rules(rule_id),

    -- Where in the card the unit came from. `field_name` is
    -- `curated_fields.field_name`, or the sentinel below for the card's
    -- own heading, which is not a field.
    field_name   text NOT NULL,
    source_phrase text NOT NULL,
    source_start integer NOT NULL,
    source_end   integer NOT NULL,

    -- WHICH TIER ANSWERED, AND HOW WELL. A judgement that is computed and
    -- discarded cannot be audited later (D48), and "it resolved" without
    -- the tier is not auditable: an alias hit at 1.0 and a cosine at 0.83
    -- are different kinds of claim.
    resolution_tier text NOT NULL,
    resolution_score numeric,

    -- UNIFORM, and that is a decision. The link is a STRUCTURAL fact —
    -- this phrase occurs in this field of this card — not a graded
    -- clinical association. `strategy_concepts.weight` grades how central
    -- a concept is to a strategy; nothing in a curated document states
    -- that, and a gradient invented here would be a knob that could be
    -- tuned until the acceptance fixture passed. Relevance comes from the
    -- retrieval channels instead.
    weight       numeric NOT NULL DEFAULT 1.0,
    created_at   timestamptz NOT NULL DEFAULT now(),

    UNIQUE (curated_id, concept_id, source_start, source_end),
    CONSTRAINT ck_curated_link_span CHECK (source_end > source_start),
    CONSTRAINT ck_curated_link_weight CHECK (weight BETWEEN 0 AND 1),
    CONSTRAINT ck_link_span_is_phrase CHECK (
        length(source_phrase) = source_end - source_start)
);

COMMENT ON COLUMN curated_strategy_concepts.field_name IS
'curated_fields.field_name, or ''strategy_name'' for the card heading, which is not a field. The span is an offset into the preserved raw source, never into the field text, so the trace resolves the same way for both.';

CREATE INDEX ix_curated_link_concept ON curated_strategy_concepts (concept_id);
CREATE INDEX ix_curated_link_card    ON curated_strategy_concepts (curated_id);


-- A PROPOSED CONCEPT IS NOT A RETRIEVAL ANCHOR (D8).
--
-- K11 is forbidden from linking a strategy to PROPOSED concepts to make a
-- count look right, and the same shortcut is available here: the resolver
-- can be asked to create a concept for any phrase, and every curated unit
-- would then link to something. `curated_concepts.py` runs the resolver
-- `read_only=True` so no concept is ever created — this trigger is the
-- backstop that makes it a property rather than a convention.
CREATE OR REPLACE FUNCTION curated_link_live_concept() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE st concept_status;
BEGIN
    SELECT status INTO st FROM concepts WHERE concept_id = NEW.concept_id;
    IF st NOT IN ('SEEDED', 'ACTIVE') THEN
        RAISE EXCEPTION
          'curated link to a % concept: only a live concept anchors retrieval (D8)', st;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_curated_link_live_concept
    BEFORE INSERT OR UPDATE ON curated_strategy_concepts
    FOR EACH ROW EXECUTE FUNCTION curated_link_live_concept();

GRANT SELECT, INSERT, UPDATE, DELETE ON curated_strategy_concepts TO phi_runtime;
GRANT SELECT ON curated_strategy_concepts TO phi_practitioner;


-- ---------------------------------------------------------------------
-- C. Full text over the PRESERVED rows, in place
-- ---------------------------------------------------------------------
--
-- The full-text channel needs the card's words. It reads them from
-- `curated_fields` where they already are, verbatim, with their spans —
-- it does not copy them anywhere. This index is what makes that cheap.
--
-- `retrieval.by_fts()` ranks the CONCATENATED card, the way it already
-- ranks `strategies` (name + summary + mechanism as one document), so a
-- card matching six terms spread over three fields outranks one matching
-- two in a single field. The index below serves the per-field prefilter.
-- ---------------------------------------------------------------------

CREATE INDEX ix_curated_fields_fts
    ON curated_fields USING gin (to_tsvector('english', text_value));


-- ---------------------------------------------------------------------
-- D. The trace, as a view. One row per link, end to end.
-- ---------------------------------------------------------------------
--
-- query -> concept -> curated strategy -> field -> byte range -> the
-- practitioner's own characters. `raw_location` is where K07 preserved
-- the original, so the last hop is a file read and a slice, and that is
-- deliberately left OUTSIDE the database: the check that matters is
-- against the ORIGINAL document, not against another copy of it.
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_curated_concept_trace AS
SELECT l.link_id,
       c.canonical_key,
       c.canonical_name,
       c.concept_type,
       s.curated_id,
       s.ordinal        AS card_ordinal,
       s.name           AS card_name,
       s.heading_path,
       l.field_name,
       l.source_phrase,
       l.source_start,
       l.source_end,
       l.rule_id,
       r.unit_kind,
       l.resolution_tier,
       l.resolution_score,
       e.envelope_id,
       e.raw_location
  FROM curated_strategy_concepts l
  JOIN concepts c            ON c.concept_id  = l.concept_id
  JOIN curated_strategies s  ON s.curated_id  = l.curated_id
  JOIN curated_concept_rules r ON r.rule_id   = l.rule_id
  JOIN source_envelopes e    ON e.envelope_id = s.envelope_id;

COMMENT ON VIEW v_curated_concept_trace IS
'GATE 3 traceability: every concept link resolved to the card, the field, the byte range and the preserved raw file it came from. A retrieved curated strategy that cannot be traced back to the practitioner''s own characters means GATE 1 bought nothing.';

GRANT SELECT ON v_curated_concept_trace TO phi_runtime, phi_practitioner;
