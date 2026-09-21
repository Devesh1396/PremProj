-- =====================================================================
-- 045_curated_field_block_cascade.sql
--
-- THE TRAP THAT MADE THE RE-IMPORT BUG POSSIBLE.
--
-- `curated_fields.block_id` referenced `curated_blocks` ON DELETE SET
-- NULL. `store()` clears an envelope's blocks on every re-import, so that
-- delete did NOT remove the fields hanging off them -- it nulled their
-- `block_id` and left them in place. For strategy and principle fields
-- that was invisible, because `store()` deletes those explicitly by
-- owner. GATE 4 added a THIRD owner and no third explicit delete, so
-- object-owned fields survived the block delete, kept their rows, and the
-- next insert hit `uq_curated_field_object`.
--
-- Measured before the fix, re-importing the same Video 14 envelope:
--
--     UniqueViolation: duplicate key value violates unique constraint
--                      "uq_curated_field_object"
--     30 object fields left behind, ALL with block_id = NULL
--
-- Those orphans are stale state even where they do not collide: a field
-- whose block is gone can no longer be traced to the heading it was
-- parsed from.
--
-- `046` fixes the importer. THIS migration closes the structural trap, so
-- the next owner kind added without its own explicit delete is removed by
-- the block delete instead of silently orphaned. Defence in depth, not a
-- substitute: a field with a NULL `block_id` is still not reachable by
-- cascade, which is why the importer keeps an explicit delete too.
--
-- NOT a change to any stored row. Video 1's rows, spans, hashes and
-- provenance are untouched; only what happens when a block is deleted
-- changes. Append-only: `032` is not edited.
-- =====================================================================

ALTER TABLE curated_fields
    DROP CONSTRAINT curated_fields_block_id_fkey;

ALTER TABLE curated_fields
    ADD CONSTRAINT curated_fields_block_id_fkey
        FOREIGN KEY (block_id) REFERENCES curated_blocks(block_id)
        ON DELETE CASCADE;

COMMENT ON COLUMN curated_fields.block_id IS
'The parsed block this field was read from. ON DELETE CASCADE since 045: an envelope re-import clears its blocks, and a field whose block is gone can no longer be traced to the heading it came from. It was ON DELETE SET NULL, which left GATE 4 object fields orphaned across a re-import and then colliding on uq_curated_field_object.';
