-- =====================================================================
-- 022_price_modality.sql
--
-- gemini-embedding-2 is MULTIMODAL and the modalities are priced 60x
-- apart, per the practitioner's own figures (2026-09-10, paid tier):
--
--     TEXT   $0.20 / 1M      AUDIO  $6.50 / 1M
--     IMAGE  $0.45 / 1M      VIDEO $12.00 / 1M
--
-- A registry keyed on model name alone has ONE rate per model, so an
-- audio embedding priced at the text rate under-reports by 32x and a
-- video one by 60x. The cost table would look fine and be wrong, which is
-- the failure D30 exists to prevent -- the same failure as a fabricated
-- rate, arriving through a different door.
--
-- So the key is (model_name, modality), and the lookup NEVER falls back to
-- TEXT. A modality with no configured rate is UNPRICED and visible in
-- v_unpriced_spend; it is never quietly charged at another modality's
-- rate.
-- =====================================================================

-- The provider's billing dimensions, not our domain vocabulary, which is
-- why this is a CHECK rather than a registry table: adding one is a
-- provider event, and it should be a deliberate migration.
ALTER TABLE model_prices
    ADD COLUMN IF NOT EXISTS modality text NOT NULL DEFAULT 'TEXT';

ALTER TABLE model_prices DROP CONSTRAINT IF EXISTS ck_price_modality;
ALTER TABLE model_prices ADD CONSTRAINT ck_price_modality
    CHECK (modality IN ('TEXT', 'IMAGE', 'AUDIO', 'VIDEO'));

COMMENT ON COLUMN model_prices.modality IS
'Which input modality this rate is for. gemini-embedding-2 charges 60x more for video than for text, so a rate that does not say which modality it covers is a rate that will eventually be applied to the wrong one.';

-- Repoint the primary key. A model now has one row PER MODALITY.
ALTER TABLE model_prices DROP CONSTRAINT IF EXISTS model_prices_pkey;
ALTER TABLE model_prices ADD PRIMARY KEY (model_name, modality);


-- What was actually charged for. Without this the cost table cannot say
-- which rate applied, so the registry would key on something the ledger
-- could not express.
ALTER TABLE cost_events
    ADD COLUMN IF NOT EXISTS modality text NOT NULL DEFAULT 'TEXT';

ALTER TABLE cost_events DROP CONSTRAINT IF EXISTS ck_cost_modality;
ALTER TABLE cost_events ADD CONSTRAINT ck_cost_modality
    CHECK (modality IN ('TEXT', 'IMAGE', 'AUDIO', 'VIDEO'));

COMMENT ON COLUMN cost_events.modality IS
'The modality of the input that was charged for. Engine runs are TEXT and default to it; K14 embeddings are TEXT by constraint (ck_embedding_text_only), not by convention.';


-- =====================================================================
-- K14 EMBEDS TEXT ONLY, and that is a constraint rather than a habit
-- =====================================================================
--
-- Transcripts and extracted document text, never the source media. This
-- is a COST decision, not a capability limit: embedding the audio of every
-- podcast at $6.50/1M instead of its transcript at $0.20/1M is a 32x bill
-- for a worse retrieval index. Revisit deliberately -- by dropping this
-- constraint in a migration that says why -- if multimodal embedding is
-- ever actually wanted.
-- =====================================================================

ALTER TABLE cost_events DROP CONSTRAINT IF EXISTS ck_embedding_text_only;
ALTER TABLE cost_events ADD CONSTRAINT ck_embedding_text_only
    CHECK (model_role IS DISTINCT FROM 'MODEL_EMBEDDING' OR modality = 'TEXT');


-- =====================================================================
-- The lookup. It refuses to guess.
-- =====================================================================

DROP FUNCTION IF EXISTS price_call(text, integer, integer, numeric, numeric);

CREATE OR REPLACE FUNCTION price_call(
    p_model_name    text,
    p_input_tokens  integer,
    p_output_tokens integer,
    p_override_in   numeric DEFAULT NULL,
    p_override_out  numeric DEFAULT NULL,
    p_modality      text    DEFAULT NULL
) RETURNS TABLE (cost_usd numeric, price_source cost_price_source)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    in_rate    numeric;
    out_rate   numeric;
    modalities int;
    chosen     text;
BEGIN
    -- The env override first, as in pricing._rates(). It exists so a live
    -- run can carry the rates actually being billed without a commit, and
    -- it only applies when BOTH halves are given -- one rate is not a price.
    IF p_override_in IS NOT NULL AND p_override_out IS NOT NULL THEN
        RETURN QUERY SELECT
            round(coalesce(p_input_tokens, 0)::numeric  / 1000000 * p_override_in
                + coalesce(p_output_tokens, 0)::numeric / 1000000 * p_override_out, 6),
            'PRICE_REGISTRY'::cost_price_source;
        RETURN;
    END IF;

    IF coalesce(p_model_name, '') = '' THEN
        RETURN QUERY SELECT NULL::numeric, 'UNPRICED'::cost_price_source;
        RETURN;
    END IF;

    chosen := p_modality;
    IF chosen IS NULL THEN
        -- No modality given. If the model is priced in exactly one, that
        -- is unambiguous and usable. If it is priced in several, GUESSING
        -- is how an audio embedding gets charged at the text rate, so the
        -- answer is UNPRICED -- visible, and never quietly wrong.
        SELECT count(DISTINCT p.modality), min(p.modality)
          INTO modalities, chosen
          FROM model_prices p
         WHERE p.active
           AND (p.model_name = p_model_name
                OR p_model_name LIKE p.model_name || '%');
        IF coalesce(modalities, 0) <> 1 THEN
            RETURN QUERY SELECT NULL::numeric, 'UNPRICED'::cost_price_source;
            RETURN;
        END IF;
    END IF;

    SELECT p.input_usd_per_mtok, p.output_usd_per_mtok
      INTO in_rate, out_rate
      FROM model_prices p
     WHERE p.active
       AND p.modality = chosen
       AND (p.model_name = p_model_name
            OR p_model_name LIKE p.model_name || '%')
     -- Exact wins; otherwise the longest prefix, which is what makes
     -- "claude-sonnet-5-20260101" resolve to "claude-sonnet-5".
     ORDER BY (p.model_name = p_model_name) DESC, length(p.model_name) DESC
     LIMIT 1;

    IF in_rate IS NULL OR out_rate IS NULL THEN
        -- No rate for THIS modality. Never the rate for another one.
        RETURN QUERY SELECT NULL::numeric, 'UNPRICED'::cost_price_source;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        round(coalesce(p_input_tokens, 0)::numeric  / 1000000 * in_rate
            + coalesce(p_output_tokens, 0)::numeric / 1000000 * out_rate, 6),
        'PRICE_REGISTRY'::cost_price_source;
END;
$$;

COMMENT ON FUNCTION price_call(text, integer, integer, numeric, numeric, text) IS
'The SQL half of pricing.price_call(). Keyed on (model, modality) and it NEVER falls back to another modality''s rate: an unpriced modality is UNPRICED, which is visible, rather than cheap and wrong. testing/test_measurement.py compares the two implementations.';

GRANT EXECUTE ON FUNCTION price_call(text, integer, integer, numeric, numeric, text)
    TO phi_runtime, phi_practitioner;


-- v_unpriced_spend groups by model; with modality it must group by both,
-- or an unpriced audio call hides behind a priced text one. Dropped and
-- recreated rather than replaced: CREATE OR REPLACE cannot insert a column
-- in the middle of an existing view's output.
DROP VIEW IF EXISTS v_unpriced_spend;

CREATE VIEW v_unpriced_spend AS
SELECT c.model_name,
       c.model_role,
       c.modality,
       count(*)                          AS calls,
       sum(coalesce(c.input_tokens, 0))  AS input_tokens,
       sum(coalesce(c.output_tokens, 0)) AS output_tokens,
       min(c.occurred_at)                AS first_call,
       max(c.occurred_at)                AS latest_call,
       EXISTS (SELECT 1 FROM model_prices p
                WHERE p.active AND p.modality = c.modality
                  AND (p.model_name = c.model_name
                       OR c.model_name LIKE p.model_name || '%'))
           AS rate_exists_now
FROM cost_events c
WHERE c.price_source = 'UNPRICED'
  AND c.model_name IS NOT NULL
  AND c.model_name NOT LIKE 'fixture:%'
GROUP BY c.model_name, c.model_role, c.modality
ORDER BY count(*) DESC;

COMMENT ON VIEW v_unpriced_spend IS
'Real calls whose cost could not be computed. Grouped by MODALITY as well as model (022): an unpriced audio call must not hide behind a priced text one for the same model.';

GRANT SELECT ON v_unpriced_spend TO phi_runtime, phi_practitioner;
