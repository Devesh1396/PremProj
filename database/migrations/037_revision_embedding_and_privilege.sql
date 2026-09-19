-- ---------------------------------------------------------------------
-- 037 — two holes in 036, found by review
-- ---------------------------------------------------------------------
-- 036 is append-only and is not edited. Both fixes replace its functions.
--
--   1. 036's comment block says a live concept's `embedding` changing
--      advances the revision. `trg_ontology_concepts_upd()` NEVER COMPARED
--      IT. Documentation and implementation disagreed, and the
--      implementation is what runs.
--
--   2. 036 says "the trigger is the only thing that should ever move it",
--      and then created `bump_ontology_revision()` SECURITY DEFINER with no
--      REVOKE. PostgreSQL grants EXECUTE to PUBLIC by default, so any role
--      could invalidate the entire normalization cache by calling it.
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- 1. A RE-EMBEDDED CONCEPT IS A DIFFERENT SEMANTIC ANSWER
-- ---------------------------------------------------------------------
-- `embed_library.py` updates the vector of an EXISTING row whenever its
-- text changed, and `_tier_semantic` ranks on exactly that vector. So:
--
--     phrase -> A, cached at revision N
--     B already exists, and is re-embedded
--     B is now the better match
--     revision is still N -> the cache still serves A
--
-- No concept was added, no status moved, no alias appeared. Every check
-- 036 had was satisfied and the answer had changed anyway.
--
-- THE BRANCH IS DECIDED HERE, AT MIGRATION TIME, NOT AT TRIGGER-FIRE TIME.
-- `concepts.embedding` exists only where pgvector was present when `002`
-- ran, so the function cannot reference it unconditionally. The obvious fix
-- -- ask `has_capability('vector')` inside the trigger -- puts a table read
-- on the path of EVERY concept UPDATE, including the `retrieval_hits` write
-- that fires on every retrieval. This migration already knows the answer,
-- so it compiles one function or the other and says which.
--
-- WHAT HAPPENS IF A DEPLOYMENT GAINS pgvector LATER. Nothing, and that is
-- consistent rather than lucky: `002` creates the column and
-- `system_capabilities.vector` together, and no migration adds either
-- afterwards, so a database built without pgvector does not use vectors at
-- all even if the extension is installed later -- `_tier_semantic` reads
-- the capability row and skips. Turning that on is a FUTURE MIGRATION that
-- adds the column, updates the capability, and MUST rebuild this function.
-- That obligation is not left to a comment: `test_normalization.py` asserts
-- the two agree -- the function body mentions `embedding` if and only if
-- the column exists -- so a migration that adds one without the other turns
-- the suite red on both floors.
DO $mig$
DECLARE
    has_embedding boolean;
    embed_clause  text := '';
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'public.concepts'::regclass
           AND attname  = 'embedding'
           AND NOT attisdropped
    ) INTO has_embedding;

    IF has_embedding THEN
        embed_clause := E'\n                        OR o.embedding IS DISTINCT FROM n.embedding';
    END IF;

    EXECUTE format($f$
        CREATE OR REPLACE FUNCTION trg_ontology_concepts_upd() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $body$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM old_rows o JOIN new_rows n USING (concept_id)
                 WHERE (o.status IN ('SEEDED','ACTIVE')) IS DISTINCT FROM
                       (n.status IN ('SEEDED','ACTIVE'))
                    OR (n.status IN ('SEEDED','ACTIVE') AND (
                           o.canonical_name IS DISTINCT FROM n.canonical_name
                        OR o.canonical_key  IS DISTINCT FROM n.canonical_key
                        OR o.concept_type   IS DISTINCT FROM n.concept_type
                        OR o.merged_into    IS DISTINCT FROM n.merged_into%s))
            ) THEN
                PERFORM public.bump_ontology_revision(
                    'a live concept changed how it matches');
            END IF;
            RETURN NULL;
        END $body$;
    $f$, embed_clause);

    IF has_embedding THEN
        RAISE NOTICE 'ontology revision: concepts.embedding EXISTS, so a re-embedded live concept advances the revision';
    ELSE
        RAISE NOTICE 'ontology revision: concepts.embedding is ABSENT (no pgvector at 002), so the trigger does not reference it; a migration that adds the column must rebuild trg_ontology_concepts_upd()';
    END IF;
END $mig$;

-- ---------------------------------------------------------------------
-- 2. THE COUNTER IS TRIGGER-ONLY, ENFORCED RATHER THAN ASSERTED
-- ---------------------------------------------------------------------
-- A global cache-invalidation function that any role may call is a cheap
-- way to make every phrase in the library cost a provider call again. 036
-- claimed the triggers were the only writer and did not revoke anything.
--
-- The shape that works: the TRIGGER functions become SECURITY DEFINER and
-- own the privilege, and EXECUTE on the bump itself is revoked from
-- PUBLIC. PostgreSQL checks EXECUTE on a trigger function when the TRIGGER
-- IS CREATED, not each time it fires, so revoking it does not stop the
-- triggers -- and because they run as the owner, the bump they call
-- succeeds where a direct call by the same role is refused.
--
-- Granting phi_runtime EXECUTE on the bump would have been simpler and
-- would have recreated the hole: the runtime is exactly the role that
-- writes confirmed aliases, so it is exactly the role that must be able to
-- cause a bump WITHOUT being able to ask for one.
--
-- search_path is pinned on every one of them. A SECURITY DEFINER function
-- resolving `ontology_revision` through a caller-controlled path is how a
-- definer function gets pointed at somebody else's table; the references
-- are schema-qualified as well, so neither alone is load-bearing.

CREATE OR REPLACE FUNCTION current_ontology_revision() RETURNS bigint
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT revision FROM public.ontology_revision
$$;

CREATE OR REPLACE FUNCTION bump_ontology_revision(reason text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    UPDATE public.ontology_revision
       SET revision = revision + 1, changed_at = now(), last_reason = reason
$$;

CREATE OR REPLACE FUNCTION trg_ontology_concepts_ins() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM new_rows WHERE status IN ('SEEDED','ACTIVE')) THEN
        PERFORM public.bump_ontology_revision('a live concept was inserted');
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_concepts_del() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM old_rows WHERE status IN ('SEEDED','ACTIVE')) THEN
        PERFORM public.bump_ontology_revision('a live concept was deleted');
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_aliases() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM public.bump_ontology_revision('a confirmed alias changed');
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION trg_ontology_relations() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM public.bump_ontology_revision(
        'a CONFUSABLE_DO_NOT_MERGE relation changed');
    RETURN NULL;
END $$;

-- Nobody calls the bump directly. The triggers reach it as their owner.
REVOKE EXECUTE ON FUNCTION bump_ontology_revision(text) FROM PUBLIC;

-- Nor may anything invoke a trigger function by hand; each one bumps.
REVOKE EXECUTE ON FUNCTION trg_ontology_concepts_ins() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION trg_ontology_concepts_del() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION trg_ontology_concepts_upd() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION trg_ontology_aliases() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION trg_ontology_relations() FROM PUBLIC;

-- Reading the revision is not a privilege: the resolver checks it on every
-- cache read, as both roles that resolve phrases.
REVOKE EXECUTE ON FUNCTION current_ontology_revision() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION current_ontology_revision() TO phi_runtime, phi_practitioner;

COMMENT ON FUNCTION bump_ontology_revision(text) IS
'Advances the ontology revision, invalidating every normalization_cache entry lazily. SECURITY DEFINER and REVOKEd from PUBLIC: the ontology triggers reach it as their owner, and no role may call it directly, because a global cache invalidation on demand makes every phrase in the library cost a provider call again.';
