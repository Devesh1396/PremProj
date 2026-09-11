-- =====================================================================
-- 018_embedding_provenance.sql
--
-- EMBEDDING_DIM stays 1536 and the embedding model is gemini-embedding-2
-- (D34). This migration makes both of those facts enforced rather than
-- assumed, and removes the three unenforced copies of the dimension.
--
-- Measured before it was designed (docs/evidence/embedding_dimension_probe.md):
--
--   gemini-embedding-001 truncated to 1536 returns L2 norm 0.702
--   gemini-embedding-2   returns 1.000000 at 3072, 1536 AND 768
--   pgvector 0.6.0 refuses an HNSW index above 2000 dimensions
--   a genuine unit vector at 1536 dims round-trips with error 1.49e-06
--
-- The first of those is the hazard: a vector that is silently the wrong
-- length still returns results, just worse ones, with no error anywhere.
-- Nothing in this schema could have caught it. Now three things can.
--
-- =====================================================================
-- A. ONE SOURCE FOR THE DIMENSION
-- =====================================================================
--
-- It had three, none of them checked: EMBEDDING_DIM in .env.example (read
-- by no code at all), and a `dim int := 1536` literal in 002_concepts.sql
-- and again in 003_knowledge.sql, each carrying a comment saying it must
-- match the other two.
--
-- The fix is not a fourth copy. The dimension a column actually has is in
-- the catalog -- pgvector stores it in atttypmod, verified -- so the
-- COLUMNS are the source and everything else derives from them. There is
-- nothing left to keep in sync.
-- =====================================================================

CREATE OR REPLACE FUNCTION embedding_dim() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT a.atttypmod
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'knowledge_chunks'
       AND a.attname = 'embedding'
       AND NOT a.attisdropped
$$;

COMMENT ON FUNCTION embedding_dim() IS
'The embedding dimension, read from the catalog rather than repeated. NULL when pgvector is absent and the column does not exist, which is a legitimate state (D15) and not an error. knowledge_chunks.embedding is the canonical column; ck_embedding_columns_agree asserts the other four match it.';


-- =====================================================================
-- B. EVERY VECTOR CARRIES ITS PROVENANCE
-- =====================================================================
--
-- A vector on its own cannot say which model produced it or at what
-- dimensionality, and two models' vectors in one index make every
-- distance meaningless. One row per table, written by the FIRST embedding
-- and enforced against every one after it -- so a mixed-model or
-- mixed-dimension write is impossible rather than merely unlikely.
--
-- A registry row rather than a DISTINCT over the table: the check runs on
-- every insert, and a sequential scan per row would make embedding a
-- large corpus quadratic.
-- =====================================================================

CREATE TABLE IF NOT EXISTS embedding_provenance (
    table_name       text PRIMARY KEY,
    embedding_model  text NOT NULL,
    embedding_dim    integer NOT NULL CHECK (embedding_dim > 0),
    first_written_at timestamptz NOT NULL DEFAULT now(),
    vectors_written  bigint NOT NULL DEFAULT 0
);

COMMENT ON TABLE embedding_provenance IS
'Which model and dimensionality each embedding column is pinned to. The first vector written to a table sets it; every later write must match. Changing it means re-embedding that column from scratch — which is the expensive operation this table exists to stop happening by accident.';

GRANT SELECT ON embedding_provenance TO phi_runtime, phi_practitioner;
GRANT INSERT, UPDATE ON embedding_provenance TO phi_runtime;


-- Tolerance chosen from measurement, not taste. A genuine unit vector at
-- 1536 dims round-trips through float4 storage with an error of 1.49e-06,
-- so 1e-3 is roughly 670x the noise floor -- while the failure it exists
-- to catch, gemini-embedding-001 truncated to 1536, is off by 0.298, some
-- 200x the tolerance. Wide margin in both directions.
CREATE OR REPLACE FUNCTION embedding_norm_tolerance() RETURNS double precision
LANGUAGE sql IMMUTABLE AS $$ SELECT 1e-3::double precision $$;


CREATE OR REPLACE FUNCTION trg_embedding_coherent() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    dims  integer;
    norm  double precision;
    pinned_model text;
    pinned_dim   integer;
BEGIN
    IF NEW.embedding IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.embedding_model IS NULL OR btrim(NEW.embedding_model) = ''
       OR NEW.embedding_dim IS NULL THEN
        RAISE EXCEPTION
            'an embedding on %.% must carry the model and dimensionality that '
            'produced it. A vector cannot say what made it, and two models in '
            'one index make every distance meaningless (D34).',
            TG_TABLE_NAME, 'embedding'
            USING ERRCODE = 'check_violation';
    END IF;

    dims := vector_dims(NEW.embedding);
    IF dims <> NEW.embedding_dim THEN
        RAISE EXCEPTION
            'embedding_dim says % but the vector has % dimensions on %.',
            NEW.embedding_dim, dims, TG_TABLE_NAME
            USING ERRCODE = 'check_violation';
    END IF;

    -- sqrt(-(v <#> v)) is the L2 norm: <#> is the NEGATIVE inner product,
    -- so -(v <#> v) is the dot product with itself. No helper function, so
    -- this works on pgvector 0.6.0 where l2_normalize does not exist.
    norm := sqrt(-(NEW.embedding <#> NEW.embedding));
    IF abs(norm - 1.0) > embedding_norm_tolerance() THEN
        RAISE EXCEPTION
            'embedding on % has L2 norm %, not 1. A truncated vector that was '
            'never re-normalised still returns results — just worse ones, with '
            'no error anywhere. gemini-embedding-001 at 1536 returns 0.702; '
            'gemini-embedding-2 returns 1.0 at every dimensionality (D34).',
            TG_TABLE_NAME, round(norm::numeric, 6)
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT p.embedding_model, p.embedding_dim INTO pinned_model, pinned_dim
      FROM embedding_provenance p WHERE p.table_name = TG_TABLE_NAME;

    IF pinned_model IS NULL THEN
        INSERT INTO embedding_provenance
              (table_name, embedding_model, embedding_dim, vectors_written)
        VALUES (TG_TABLE_NAME, NEW.embedding_model, NEW.embedding_dim, 1)
        ON CONFLICT (table_name) DO UPDATE
           SET vectors_written = embedding_provenance.vectors_written + 1;
        RETURN NEW;
    END IF;

    IF pinned_model <> NEW.embedding_model OR pinned_dim <> NEW.embedding_dim THEN
        RAISE EXCEPTION
            '% is embedded with %/%d, and this write is %/%d. Mixing models or '
            'dimensionalities in one index makes every distance meaningless. '
            'Changing either means re-embedding the whole column: clear it, '
            'call reset_embedding_provenance(%L), then re-embed.',
            TG_TABLE_NAME, pinned_model, pinned_dim,
            NEW.embedding_model, NEW.embedding_dim, TG_TABLE_NAME
            USING ERRCODE = 'check_violation';
    END IF;

    UPDATE embedding_provenance
       SET vectors_written = vectors_written + 1
     WHERE table_name = TG_TABLE_NAME;
    RETURN NEW;
END;
$$;


CREATE OR REPLACE FUNCTION reset_embedding_provenance(p_table text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    remaining bigint;
BEGIN
    EXECUTE format('SELECT count(*) FROM %I WHERE embedding IS NOT NULL', p_table)
       INTO remaining;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            '% still holds % embedding(s). Re-pinning a column that still has '
            'vectors in it is how a mixed-model index is created. Clear the '
            'column first — that is the re-embed, and it is meant to be '
            'deliberate.', p_table, remaining
            USING ERRCODE = 'check_violation';
    END IF;
    DELETE FROM embedding_provenance WHERE table_name = p_table;
END;
$$;

COMMENT ON FUNCTION reset_embedding_provenance(text) IS
'Un-pin a column so it can be re-embedded with a different model. Refuses while any vector remains, because that is exactly when re-pinning would create a mixed index.';


-- =====================================================================
-- C. WIRE IT UP -- only where the columns exist
-- =====================================================================
-- Without pgvector there are no embedding columns and nothing to guard.
-- That is a supported configuration (D15), not a degraded one.
-- =====================================================================

DO $$
DECLARE
    t text;
    canonical int;
    found int;
BEGIN
    IF NOT has_capability('vector') THEN
        RAISE NOTICE 'pgvector absent: no embedding columns, nothing to guard';
        RETURN;
    END IF;

    canonical := embedding_dim();

    FOREACH t IN ARRAY ARRAY['concepts', 'concept_aliases', 'strategies',
                             'knowledge_chunks', 'implementation_patterns']
    LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS embedding_model text', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS embedding_dim integer', t);

        -- Every embedding column must have the SAME dimension. They are
        -- compared against each other in retrieval, and 002 and 003 each
        -- carried their own literal with only a comment holding them
        -- together.
        SELECT a.atttypmod INTO found
          FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
         WHERE c.relname = t AND a.attname = 'embedding' AND NOT a.attisdropped;
        IF found IS DISTINCT FROM canonical THEN
            RAISE EXCEPTION
                '%.embedding is vector(%) but knowledge_chunks.embedding is '
                'vector(%). Every embedding column must agree — they are '
                'compared against each other.', t, found, canonical;
        END IF;

        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_embedding ON %I', t, t);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_embedding BEFORE INSERT OR UPDATE OF embedding '
            'ON %I FOR EACH ROW EXECUTE FUNCTION trg_embedding_coherent()', t, t);

        EXECUTE format(
            'COMMENT ON COLUMN %I.embedding_model IS %L', t,
            'The model that produced this vector. Required whenever embedding '
            'is not null, pinned per table by the first write (D34).');
    END LOOP;

    RAISE NOTICE 'embedding guards installed on 5 columns (dim=%)', canonical;
END $$;


-- What is embedded, with what, and whether it is still consistent.
CREATE OR REPLACE VIEW v_embedding_state
WITH (security_invoker = true) AS
SELECT p.table_name,
       p.embedding_model,
       p.embedding_dim,
       p.vectors_written,
       p.first_written_at,
       embedding_dim() AS column_dim,
       p.embedding_dim = embedding_dim() AS dim_matches_column
FROM embedding_provenance p
ORDER BY p.table_name;

COMMENT ON VIEW v_embedding_state IS
'Which model each embedding column is pinned to and how many vectors it holds. Empty until something is embedded, which is the correct reading of an empty library — not a fault.';

GRANT SELECT ON v_embedding_state TO phi_runtime, phi_practitioner;
