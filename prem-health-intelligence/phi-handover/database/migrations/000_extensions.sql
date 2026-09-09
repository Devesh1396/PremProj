-- 000_extensions.sql
-- Extensions and shared helpers.
--
-- Every extension here is OPTIONAL. The master specification requires the
-- system to run on structured metadata and full-text search alone, with
-- richer retrieval enabled later without database redesign. So each
-- extension is attempted, its availability recorded in system_capabilities,
-- and later migrations branch on that rather than assuming.
--
-- Note: gen_random_uuid() is core Postgres from v13 onward. pgcrypto is
-- deliberately NOT a dependency.

CREATE TABLE IF NOT EXISTS system_capabilities (
    capability   text PRIMARY KEY,
    enabled      boolean     NOT NULL,
    detail       text,
    checked_at   timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION try_enable_extension(ext text, detail text)
RETURNS boolean
LANGUAGE plpgsql
AS $fn$
DECLARE
    ok boolean := false;
BEGIN
    BEGIN
        EXECUTE format('CREATE EXTENSION IF NOT EXISTS %I', ext);
        ok := true;
    EXCEPTION WHEN OTHERS THEN
        ok := false;
        RAISE NOTICE 'extension % unavailable: %', ext, SQLERRM;
    END;

    INSERT INTO system_capabilities (capability, enabled, detail)
    VALUES (ext, ok, detail)
    ON CONFLICT (capability) DO UPDATE
        SET enabled    = EXCLUDED.enabled,
            detail     = EXCLUDED.detail,
            checked_at = now();

    RETURN ok;
END $fn$;

SELECT try_enable_extension(
    'vector',
    'Semantic similarity for hybrid retrieval and concept normalization. When absent, resolution runs deterministic -> structured -> trigram -> LLM.'
);

SELECT try_enable_extension(
    'pg_trgm',
    'Trigram lexical matching for alias lookup. When absent, alias matching is exact-normalized only and more phrases fall through to LLM normalization.'
);

SELECT try_enable_extension(
    'btree_gin',
    'Composite GIN indexes mixing scalar and array columns. When absent, equivalent filtering uses separate indexes.'
);

CREATE OR REPLACE FUNCTION has_capability(cap text)
RETURNS boolean
LANGUAGE sql
STABLE
AS $fn$
    SELECT coalesce((SELECT enabled FROM system_capabilities WHERE capability = cap), false);
$fn$;

-- ---------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $fn$;

-- Deterministic phrase normalization for alias lookup: lowercase, collapse
-- whitespace, strip punctuation that carries no clinical meaning.
--
-- Deliberately conservative. It tidies formatting only. It must never
-- perform semantic merging, because that is exactly how "visceral fat" and
-- "belly fat" end up as one key. Retains % + / - since they appear in
-- clinically meaningful tokens (HbA1c %, omega-3, HDL/LDL).
--
-- IMMUTABLE so it can back a generated column and an index.
--
-- Order matters: strip punctuation, THEN collapse whitespace, THEN trim.
-- Trimming first leaves a trailing space whenever a phrase ends in
-- punctuation ("post-meal glucose excursion!!"), which silently breaks
-- exact-match alias lookup and pushes the phrase to LLM resolution.
--
-- WARNING: concept_aliases.alias_norm and concept_proposals.raw_phrase_norm
-- are STORED generated columns over this function. Changing it does not
-- recompute existing rows. Any future change needs a migration that also
-- rewrites those columns and rebuilds their indexes.
CREATE OR REPLACE FUNCTION norm_phrase(p text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
AS $fn$
    SELECT btrim(
             regexp_replace(
               regexp_replace(lower(p), '[^a-z0-9%+/\- ]', ' ', 'g'),
               '\s+', ' ', 'g'
             )
           );
$fn$;
