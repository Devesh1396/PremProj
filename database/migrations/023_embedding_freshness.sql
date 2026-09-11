-- =====================================================================
-- 023_embedding_freshness.sql   K14
--
-- BUILD_GUIDE step 17: "Do not regenerate unchanged embeddings."
--
-- That is a cost instruction with teeth. Re-embedding a 40,000-chunk
-- library because a batch job was run twice is a real bill for zero new
-- information, and the only way to know a row is unchanged is to have
-- recorded what was embedded.
--
-- So each embeddable row carries the HASH OF THE TEXT THAT WAS EMBEDDED --
-- not of the row, which changes when a hit counter moves, and not a
-- timestamp, which cannot tell an edit from a touch.
--
-- Everything here is conditional on pgvector for the same reason 002 and
-- 003 are: without it there is no `embedding` column to track, and a view
-- that reads one would fail the migration outright on the D15 floor.
-- =====================================================================

DO $$
DECLARE
    t text;
BEGIN
    IF NOT has_capability('vector') THEN
        RAISE NOTICE 'pgvector absent: no embedding columns, nothing to track';
        RETURN;
    END IF;

    FOREACH t IN ARRAY ARRAY['concepts', 'concept_aliases', 'strategies',
                             'knowledge_chunks', 'implementation_patterns']
    LOOP
        EXECUTE format(
            'ALTER TABLE %I ADD COLUMN IF NOT EXISTS embedding_source_hash text', t);
        EXECUTE format(
            'ALTER TABLE %I ADD COLUMN IF NOT EXISTS embedded_at timestamptz', t);
        -- Finding the unembedded rows is the hot path of every backfill.
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_%s_needs_embedding ON %I (embedded_at) '
            'WHERE embedding IS NULL', t, t);
        EXECUTE format(
            'COMMENT ON COLUMN %I.embedding_source_hash IS %L', t,
            'sha256 of the exact text that was embedded. A row whose text still '
            'hashes to this is not re-embedded (K14). NULL means never embedded.');
    END LOOP;

    RAISE NOTICE 'embedding freshness tracked on 5 tables';
END $$;


-- ---------------------------------------------------------------------
-- Coverage
--
-- How much of the library is embedded. The view exists in BOTH capability
-- configurations, because a caller asking "how much is embedded?" on a
-- database with no pgvector deserves an answer rather than a missing
-- relation -- and the honest answer is NOT zero-embedded-of-N, which reads
-- as a backfill that has not run yet. It is NULL: not applicable, with
-- `vector_capable` saying why.
-- ---------------------------------------------------------------------

DO $$
DECLARE
    t            text;
    parts        text[] := ARRAY[]::text[];
    has_vector   boolean := has_capability('vector');
    embedded_expr text;
    missing_expr  text;
BEGIN
    IF has_vector THEN
        embedded_expr := 'count(*) FILTER (WHERE embedding IS NOT NULL)';
        missing_expr  := 'count(*) FILTER (WHERE embedding IS NULL)';
    ELSE
        embedded_expr := 'NULL::bigint';
        missing_expr  := 'NULL::bigint';
    END IF;

    FOREACH t IN ARRAY ARRAY['concepts', 'concept_aliases', 'strategies',
                             'knowledge_chunks', 'implementation_patterns']
    LOOP
        parts := parts || format(
            'SELECT %L::text AS table_name, count(*)::bigint AS rows_total, '
            '%s AS embedded, %s AS never_embedded, %L::boolean AS vector_capable '
            'FROM %I', t, embedded_expr, missing_expr, has_vector, t);
    END LOOP;

    EXECUTE 'CREATE OR REPLACE VIEW v_embedding_coverage '
            'WITH (security_invoker = true) AS '
            || array_to_string(parts, ' UNION ALL ')
            || ' ORDER BY 1';
END $$;

COMMENT ON VIEW v_embedding_coverage IS
'How much of the library is embedded. never_embedded > 0 is normal while the backfill has not run; it is only a problem if it stops falling. NULL counts mean pgvector is absent (D15) and retrieval runs on metadata + full text.';

GRANT SELECT ON v_embedding_coverage TO phi_runtime, phi_practitioner;
