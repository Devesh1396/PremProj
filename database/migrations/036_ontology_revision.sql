-- ---------------------------------------------------------------------
-- 036 — the normalization cache is bound to the ontology it resolved against
-- ---------------------------------------------------------------------
-- `034` made the cache re-check its STORED candidate set. That closes a
-- stale confusable pair and a wrong caller type, and it cannot close the
-- opposite shape:
--
--   a concept that did not exist when the row was written was never a
--   candidate, so re-running any guard over the stored candidates can
--   never surface it.
--
-- Two ways that bites, and the second is the worse one:
--
--   1. A better semantic answer is added later. The cache keeps returning
--      the old one, and the entry silently becomes more wrong as the
--      library grows -- which, for a system whose whole design is a
--      continuously growing ontology, means every cache entry decays.
--   2. THE PRACTITIONER CONFIRMS AN ALIAS FOR THAT EXACT PHRASE. A
--      confirmed alias is the most authoritative mapping in the chain: the
--      alias tier runs first and is exact. A cache serving the old concept
--      over it is not serving a stale score, it is overriding a deliberate
--      human decision.
--
-- So cache validity is bound to an ONTOLOGY REVISION. A cached row records
-- the revision it was resolved against; a read at a different revision is a
-- MISS and the ordinary tiers run. Rows are not deleted on a bump -- they
-- are overwritten when the phrase is actually resolved again, which keeps
-- the existing cache model and makes invalidation LAZY. That laziness is
-- what makes a single global counter affordable; see the cost note below.
-- ---------------------------------------------------------------------

CREATE TABLE ontology_revision (
    only_row    boolean     PRIMARY KEY DEFAULT true,
    revision    bigint      NOT NULL DEFAULT 1,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    last_reason text,
    CONSTRAINT ck_ontology_revision_single CHECK (only_row)
);

INSERT INTO ontology_revision (only_row, revision, last_reason)
VALUES (true, 1, 'migration 036: the counter starts here');

COMMENT ON TABLE ontology_revision IS
'One row. Advances whenever the ontology changes in a way that could change what normalize.resolve() returns. normalization_cache rows record the revision they were resolved against, and a read at a different revision is a miss.';

CREATE OR REPLACE FUNCTION current_ontology_revision() RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT revision FROM ontology_revision
$$;

-- SECURITY DEFINER: phi_runtime writes confirmed aliases through the
-- resolver, and that is exactly the change that must advance the counter.
-- Granting the runtime UPDATE on this table directly would let anything
-- holding that role set the revision to whatever it liked; the trigger is
-- the only thing that should ever move it.
CREATE OR REPLACE FUNCTION bump_ontology_revision(reason text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    UPDATE ontology_revision
       SET revision = revision + 1, changed_at = now(), last_reason = reason
$$;

-- ---------------------------------------------------------------------
-- THE TRIGGER SET, STATED
-- ---------------------------------------------------------------------
-- Derived by walking every tier and asking what it reads:
--
--   _tier_alias      concept_aliases.alias_norm WHERE confirmed,
--                    concepts.canonical_name, concepts.status
--   _tier_structured concepts.canonical_key, concepts.status
--   _tier_trigram    concepts.canonical_name, concepts.concept_type,
--                    concepts.status, confirmed concept_aliases
--   _tier_semantic   concepts.embedding, concepts.concept_type,
--                    concepts.status
--   confusable_with  concept_relations WHERE relation_type =
--                    'CONFUSABLE_DO_NOT_MERGE'
--
-- So the columns that advance the revision are exactly: status (across the
-- SEEDED/ACTIVE boundary), canonical_name, canonical_key, concept_type,
-- embedding, merged_into; a confirmed alias appearing, disappearing or
-- changing its text; and a CONFUSABLE_DO_NOT_MERGE relation appearing,
-- disappearing or changing either end.
--
-- WHAT DOES NOT ADVANCE IT, AND WHY IT CANNOT AFFECT A RESOLUTION:
--
--   concepts.retrieval_hits / last_retrieved -- telemetry, and this is the
--       decisive one: `retrieval.py` writes it on EVERY retrieval read. A
--       trigger that fired on any write to `concepts` would have every
--       search invalidate the entire cache, which is the opposite of D2.
--   concepts.definition -- feeds `search_text`, which feeds the FTS index
--       and the EMBEDDING TEXT. No tier reads it. A definition edited and
--       not yet re-embedded has changed no tier's answer; the re-embed
--       itself writes `embedding` and bumps.
--   concepts.embedding_model / embedding_dim / embedding_source_hash --
--       provenance for the vector, never compared by a tier, and they only
--       ever move together with `embedding`, which is covered.
--   concepts.parent_concept_id -- read by the normalization TEST
--       generator (sibling pairs), never by the resolver.
--   concepts.origin_method / origin_detail / created_at / updated_at /
--       last_reviewed -- provenance and timestamps.
--   A concept INSERTED or left at status PROPOSED / MERGED / DEPRECATED --
--       no tier selects it, so it is not a candidate and cannot change an
--       answer. This is the common write: K09 creates PROPOSED concepts by
--       the dozen per source, and none of them touches the counter.
--       Promotion INTO SEEDED/ACTIVE does bump, because that is the moment
--       it becomes reachable.
--   concept_aliases with confirmed = false -- proven inert in both tiers
--       as of the same review that asked for this (`_tier_alias` filters
--       `confirmed`, and `_tier_trigram` now does too). An unconfirmed row
--       is a record for a human, not an input.
--   concept_aliases.method / confidence -- recorded, never matched on.
--   concept_relations of any other relation_type (RELATED_TO, TARGETS,
--       PARENT_OF, ...) -- only CONFUSABLE_DO_NOT_MERGE is read by
--       `confusable_with()`, and nothing else in the resolver reads this
--       table at all.
--
-- Transition tables rather than `UPDATE OF col`: `UPDATE OF` fires when a
-- statement MENTIONS a column, even setting it to its existing value. This
-- compares the values, so `set status = status` does not bump.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION trg_ontology_concepts_ins() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM new_rows WHERE status IN ('SEEDED','ACTIVE')) THEN
        PERFORM bump_ontology_revision('a live concept was inserted');
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_concepts_del() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM old_rows WHERE status IN ('SEEDED','ACTIVE')) THEN
        PERFORM bump_ontology_revision('a live concept was deleted');
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_concepts_upd() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM old_rows o JOIN new_rows n USING (concept_id)
         WHERE (o.status IN ('SEEDED','ACTIVE')) IS DISTINCT FROM
               (n.status IN ('SEEDED','ACTIVE'))
            OR (n.status IN ('SEEDED','ACTIVE') AND (
                   o.canonical_name IS DISTINCT FROM n.canonical_name
                OR o.canonical_key  IS DISTINCT FROM n.canonical_key
                OR o.concept_type   IS DISTINCT FROM n.concept_type
                OR o.merged_into    IS DISTINCT FROM n.merged_into))
    ) THEN
        PERFORM bump_ontology_revision('a live concept changed how it matches');
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_aliases() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM bump_ontology_revision('a confirmed alias changed');
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_relations() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM bump_ontology_revision('a CONFUSABLE_DO_NOT_MERGE relation changed');
    RETURN NULL;
END $$;

CREATE TRIGGER trg_ontology_rev_concepts_ins
    AFTER INSERT ON concepts
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION trg_ontology_concepts_ins();

CREATE TRIGGER trg_ontology_rev_concepts_del
    AFTER DELETE ON concepts
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION trg_ontology_concepts_del();

CREATE TRIGGER trg_ontology_rev_concepts_upd
    AFTER UPDATE ON concepts
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION trg_ontology_concepts_upd();

-- Row-level here, and gated by `confirmed`, because that is the only thing
-- that makes an alias an input. An unconfirmed row may be written freely.
CREATE TRIGGER trg_ontology_rev_alias_ins
    AFTER INSERT ON concept_aliases
    FOR EACH ROW WHEN (NEW.confirmed)
    EXECUTE FUNCTION trg_ontology_aliases();

CREATE TRIGGER trg_ontology_rev_alias_del
    AFTER DELETE ON concept_aliases
    FOR EACH ROW WHEN (OLD.confirmed)
    EXECUTE FUNCTION trg_ontology_aliases();

CREATE TRIGGER trg_ontology_rev_alias_upd
    AFTER UPDATE ON concept_aliases
    FOR EACH ROW WHEN (OLD.confirmed IS DISTINCT FROM NEW.confirmed
                    OR (NEW.confirmed AND OLD.alias_text IS DISTINCT FROM NEW.alias_text)
                    OR (NEW.confirmed AND OLD.concept_id IS DISTINCT FROM NEW.concept_id))
    EXECUTE FUNCTION trg_ontology_aliases();

CREATE TRIGGER trg_ontology_rev_rel_ins
    AFTER INSERT ON concept_relations
    FOR EACH ROW WHEN (NEW.relation_type = 'CONFUSABLE_DO_NOT_MERGE')
    EXECUTE FUNCTION trg_ontology_relations();

CREATE TRIGGER trg_ontology_rev_rel_del
    AFTER DELETE ON concept_relations
    FOR EACH ROW WHEN (OLD.relation_type = 'CONFUSABLE_DO_NOT_MERGE')
    EXECUTE FUNCTION trg_ontology_relations();

CREATE TRIGGER trg_ontology_rev_rel_upd
    AFTER UPDATE ON concept_relations
    FOR EACH ROW WHEN (OLD.relation_type = 'CONFUSABLE_DO_NOT_MERGE'
                    OR NEW.relation_type = 'CONFUSABLE_DO_NOT_MERGE')
    EXECUTE FUNCTION trg_ontology_relations();

-- ---------------------------------------------------------------------
-- The cache records the revision it was resolved against
-- ---------------------------------------------------------------------
ALTER TABLE normalization_cache
    ADD COLUMN IF NOT EXISTS ontology_revision bigint;

COMMENT ON COLUMN normalization_cache.ontology_revision IS
'The ontology_revision this phrase was resolved against. A read at a different revision is a MISS: a concept added since was never in candidate_ids, so no check over the stored candidates could ever surface it. NULL means the row predates migration 036 and is treated as a miss for the same reason 034 treats a NULL candidate set as one.';

GRANT SELECT ON ontology_revision TO phi_runtime, phi_practitioner;

-- ---------------------------------------------------------------------
-- THE COST, stated now rather than discovered in Wave 1
-- ---------------------------------------------------------------------
-- ONE global counter means one confirmed alias invalidates every cached
-- phrase. That is accepted deliberately, and it is affordable for one
-- reason: INVALIDATION IS LAZY. Nothing is re-embedded on a bump. A row
-- costs a provider call only when that phrase is asked for again, so the
-- bill is "one embedding per DISTINCT PHRASE ACTUALLY USED after the
-- change", not "one per cached row".
--
-- At the measured rate (gemini-embedding-2 text, ~$0.0000007 for a clinical
-- phrase), a run touching 60 distinct phrases pays about $0.00004 after a
-- bump. The whole D47 source was 56 distinct phrases. A 1,000-phrase
-- library fully re-walked is about $0.002.
--
-- And in steady state the counter barely moves. The common ingestion write
-- is `_propose_new` creating PROPOSED concepts -- dozens per source, zero
-- bumps, because no tier reads a PROPOSED concept. Bumps come from
-- deliberate acts: seeding, promoting a proposal, confirming an alias,
-- recording a do-not-merge pair, and re-embedding a batch.
--
-- A NARROWER SCOPE WAS CONSIDERED AND REJECTED. Per-concept-neighbourhood
-- scoping cannot work for the case that motivated this: a NEW concept has
-- no prior relationship to any stored neighbourhood, which is the bug. It
-- could be made to work by storing every cached phrase's QUERY VECTOR and
-- comparing each new concept against all of them -- 1536 floats per cache
-- row plus a comparison pass per ontology change, to save calls that cost
-- fractions of a cent. One narrowing IS cheap and is recorded here rather
-- than built: a newly confirmed alias could invalidate only the cache rows
-- whose `phrase_norm` equals its `alias_norm`, because that tier is exact.
-- It is not built because it would leave two invalidation rules to keep in
-- agreement, and the one it replaces is not expensive.
