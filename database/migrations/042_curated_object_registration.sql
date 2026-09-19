-- =====================================================================
-- 042_curated_object_registration.sql
--
-- POST-FIRST-RUN FIX. `040` is applied and is not edited (hard rule 10).
--
-- `040` added CURATED_OBJECT to `derived_kind` and did not add the
-- registration trigger. Hard rule 12:
--
--     Every derived knowledge object registers in `knowledge_entities` by
--     trigger. `envelope_derived_records` foreign-keys
--     (derived_id, derived_kind) to it. A new derived kind adds an enum
--     value AND a registration trigger.
--
-- `040`'s own header cites that rule and then does half of it.
-- `curated_strategies` and `curated_principles` each carry the pair;
-- `curated_objects` carried neither, so nothing entered
-- `knowledge_entities` and the provenance edge had nothing to point at.
--
-- The GATE 4 acceptance suite's FIRST implemented run aborted here, on
-- `fk_derived_entity`, which is that constraint doing its job: a dangling
-- provenance edge was refused at the first real insert instead of a
-- library quietly filling with unregistered objects. Recorded in
-- `docs/evidence/gate4_first_run.md` and not written out of history.
-- =====================================================================

CREATE TRIGGER trg_register_curated_objects
    AFTER INSERT ON curated_objects
    FOR EACH ROW
    EXECUTE FUNCTION register_knowledge_entity('CURATED_OBJECT', 'object_id');

CREATE TRIGGER trg_deregister_curated_objects
    AFTER DELETE ON curated_objects
    FOR EACH ROW
    EXECUTE FUNCTION deregister_knowledge_entity('object_id');
