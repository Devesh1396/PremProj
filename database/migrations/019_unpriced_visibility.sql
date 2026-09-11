-- =====================================================================
-- 019_unpriced_visibility.sql
--
-- UNPRICED is the honest answer when no rate is configured (D30), and
-- ck_cost_priced makes sure it can never be quietly reported as zero. But
-- honest and INVISIBLE are different things: a call recorded UNPRICED
-- costs real money and appears in no cost total, and nothing surfaced that.
--
-- Found while adding gemini-embedding-2 to the registry: the embedding
-- probe that settled D34 recorded 14 UNPRICED calls, which is the
-- mechanism working exactly as designed and still not a state to leave.
--
-- This view is the signal. It is empty when everything that has been
-- called has a rate, and it names the model and the volume when something
-- does not.
-- =====================================================================

CREATE OR REPLACE VIEW v_unpriced_spend AS
SELECT c.model_name,
       c.model_role,
       count(*)                          AS calls,
       sum(coalesce(c.input_tokens, 0))  AS input_tokens,
       sum(coalesce(c.output_tokens, 0)) AS output_tokens,
       min(c.occurred_at)                AS first_call,
       max(c.occurred_at)                AS latest_call,
       EXISTS (SELECT 1 FROM model_prices p
                WHERE p.active AND (p.model_name = c.model_name
                                    OR c.model_name LIKE p.model_name || '%'))
           AS rate_exists_now
FROM cost_events c
WHERE c.price_source = 'UNPRICED'
  AND c.model_name IS NOT NULL
  AND c.model_name NOT LIKE 'fixture:%'
GROUP BY c.model_name, c.model_role
ORDER BY count(*) DESC;

COMMENT ON VIEW v_unpriced_spend IS
'Real calls whose cost could not be computed, because no rate is configured for that model. Empty is the goal. rate_exists_now true means a rate has since been added and these historical rows could be re-priced. Fixture models are excluded — they cost nothing and always will.';

GRANT SELECT ON v_unpriced_spend TO phi_runtime, phi_practitioner;
