-- =====================================================================
-- 016_price_registry.sql
--
-- THE FOURTH INSTANCE OF THE SAME PATTERN (D23).
--
-- Prompts, the orchestration contract and the handoff registry all moved
-- from files to rows for one reason: n8n cannot read this repository. The
-- price registry is the last thing RUN_ENGINE reads from disk, and the
-- consequence showed up the moment the n8n cost node was written -- it had
-- nowhere to get a rate, so the port would have written UNPRICED for every
-- call while the Python reference priced the identical call.
--
-- That is not a cosmetic divergence. n8n is production; the Python path is
-- the reference. D5 was decided on cost numbers, and Step 16 will push
-- thousands of Knowledge Factory calls through the workflow. A production
-- path that cannot price its own calls makes the cost table describe the
-- reference implementation instead of the system.
--
-- config/model_prices.json stays the authored form, exactly as prompts/
-- and schemas/orchestration/ did. scripts/load_prices.py loads it. A fresh
-- deployment now runs FOUR loaders after migrating.
--
-- Resolution order is pricing.price_call()'s, reproduced here rather than
-- reinvented: env override, exact model name, longest matching prefix,
-- else UNPRICED with a NULL cost. Never zero -- a zero reads as "this call
-- was free", and ck_cost_priced exists to stop exactly that.
-- =====================================================================

CREATE TABLE IF NOT EXISTS model_prices (
    model_name           text PRIMARY KEY,
    input_usd_per_mtok   numeric(12,6) NOT NULL CHECK (input_usd_per_mtok >= 0),
    output_usd_per_mtok  numeric(12,6) NOT NULL CHECK (output_usd_per_mtok >= 0),
    source_note          text,
    active               boolean NOT NULL DEFAULT true,
    loaded_at            timestamptz NOT NULL DEFAULT now(),
    source_file          text
);

COMMENT ON TABLE model_prices IS
'What a model costs per million tokens, as ROWS so n8n can price a call it just made. Authored form is config/model_prices.json; scripts/load_prices.py is the loader. Adding a model is a data edit, never a change to run_engine.py and never a model name in logic (D23).';

COMMENT ON COLUMN model_prices.model_name IS
'Matched against cost_events.model_name exactly first, then by longest matching prefix, so a dated snapshot id resolves to its family entry.';

GRANT SELECT ON model_prices TO phi_runtime, phi_practitioner;

-- Not client data. No RLS: a rate card is not PHI and every scope needs it.


CREATE OR REPLACE FUNCTION price_call(
    p_model_name    text,
    p_input_tokens  integer,
    p_output_tokens integer,
    p_override_in   numeric DEFAULT NULL,
    p_override_out  numeric DEFAULT NULL
) RETURNS TABLE (cost_usd numeric, price_source cost_price_source)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    in_rate  numeric;
    out_rate numeric;
BEGIN
    -- The env override first, as in pricing._rates(). It exists so a live
    -- run can carry the rates actually being billed without a commit, and
    -- it only applies when BOTH halves are given -- one rate is not a
    -- price. n8n passes $env.LLM_PRICE_INPUT_PER_MTOK / _OUTPUT_PER_MTOK.
    IF p_override_in IS NOT NULL AND p_override_out IS NOT NULL THEN
        in_rate  := p_override_in;
        out_rate := p_override_out;
    ELSIF coalesce(p_model_name, '') = '' THEN
        RETURN QUERY SELECT NULL::numeric, 'UNPRICED'::cost_price_source;
        RETURN;
    ELSE
        SELECT p.input_usd_per_mtok, p.output_usd_per_mtok
          INTO in_rate, out_rate
          FROM model_prices p
         WHERE p.active
           AND (p.model_name = p_model_name
                OR p_model_name LIKE p.model_name || '%')
         -- Exact wins; otherwise the longest prefix, which is what makes
         -- "claude-sonnet-5-20260101" resolve to "claude-sonnet-5" rather
         -- than to a shorter family key that also matches.
         ORDER BY (p.model_name = p_model_name) DESC, length(p.model_name) DESC
         LIMIT 1;
    END IF;

    IF in_rate IS NULL OR out_rate IS NULL THEN
        RETURN QUERY SELECT NULL::numeric, 'UNPRICED'::cost_price_source;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        round(coalesce(p_input_tokens, 0)::numeric  / 1000000 * in_rate
            + coalesce(p_output_tokens, 0)::numeric / 1000000 * out_rate, 6),
        'PRICE_REGISTRY'::cost_price_source;
END;
$$;

COMMENT ON FUNCTION price_call(text, integer, integer, numeric, numeric) IS
'The SQL half of pricing.price_call(). testing/test_n8n_parity.py compares the two over a corpus; two implementations of one rule is the arrangement that has already caught three real divergences (D26).';

GRANT EXECUTE ON FUNCTION price_call(text, integer, integer, numeric, numeric)
    TO phi_runtime, phi_practitioner;
