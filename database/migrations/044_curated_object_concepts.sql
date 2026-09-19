-- =====================================================================
-- 044_curated_object_concepts.sql
--
-- THE CONCEPT BRIDGE DID NOT SEE CURATED OBJECTS.
--
-- `040`/`041` gave Video 14 eleven objects with 31 preserved fields, and
-- the first complete run's concept audit reported `units 0`. Not because
-- nothing resolved -- because `attach_concepts()` iterates
-- `curated_strategies` and a curated object is not one, so the resolver
-- was never asked. A new knowledge object that nothing can retrieve by
-- concept is the D52a failure again: built, and not connected.
--
-- `curated_strategy_concepts` gains a second owner rather than a parallel
-- link table. `ck_link_span_is_phrase` and `trg_curated_link_live_concept`
-- are the guarantees GATE 3 proved, and a second table would be a second
-- place for them to be enforced differently.
--
-- Append-only. The existing unique constraint on (curated_id, ...) stays
-- exactly as it is, so every Video 1 row and every check that reads them
-- is untouched.
-- =====================================================================

ALTER TABLE curated_strategy_concepts
    ALTER COLUMN curated_id DROP NOT NULL,
    ADD COLUMN object_id uuid REFERENCES curated_objects(object_id)
        ON DELETE CASCADE;

ALTER TABLE curated_strategy_concepts ADD CONSTRAINT ck_curated_link_owner
    CHECK ((curated_id IS NOT NULL)::int + (object_id IS NOT NULL)::int = 1);

CREATE UNIQUE INDEX uq_curated_link_object
    ON curated_strategy_concepts (object_id, concept_id, source_start, source_end)
    WHERE object_id IS NOT NULL;

CREATE INDEX ix_curated_link_object ON curated_strategy_concepts (object_id)
    WHERE object_id IS NOT NULL;

COMMENT ON COLUMN curated_strategy_concepts.object_id IS
'GATE 4. The link''s owner when it is a curated object rather than a strategy card. Exactly one of curated_id / object_id is set. RETRIEVAL DOES NOT YET SURFACE CURATED OBJECTS -- by_concept() and by_fts() read curated_strategies, and widening them is GATE 3 work that GATE 4 was scoped out of. So these links are stored, traceable and unused, and that is stated rather than left to be discovered.';
