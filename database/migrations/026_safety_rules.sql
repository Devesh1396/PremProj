-- =====================================================================
-- 026_safety_rules.sql   Step 20 — the deterministic flag rule set
--
-- D6, and hard rule 9. The gate (`trg_block_unapproved_communication`) and
-- the flag table have existed since 004; **nothing ever evaluated a rule**,
-- so no HOLD could ever open and the gate has never had anything to block.
--
-- =====================================================================
-- NARROW IS THE WHOLE POINT
-- =====================================================================
--
-- An early proposal listed antihypertensives, thyroid replacement and
-- diuretics as HOLD triggers. Against this client population that fires on
-- nearly every case, and **a gate that fires constantly is a rubber
-- stamp** — less protection than no gate, plus friction. That proposal was
-- withdrawn (D6).
--
-- So: six rules. **A client on metformin, a statin and an ACE inhibitor
-- passes clean**, and `test_safety.py` asserts exactly that, because it is
-- the acceptance criterion for this step and the failure mode is silent.
--
-- =====================================================================
-- WHAT IS DATA AND WHAT IS CODE
-- =====================================================================
--
-- The rule LOGIC is SQL, deliberately: D6 says these are SQL over
-- `client_labs` / `client_medications` / `client_conditions`, not prompt
-- instructions, because a missed flag is the case you cannot afford.
--
-- The rule's EXISTENCE, its severity, and every drug and intervention name
-- it matches are **rows** (hard rule 13). Adding a sulfonylurea is an
-- INSERT. Hard-coding a list of drug names inside a function is how the
-- next sulfonylurea goes unflagged.
-- =====================================================================


-- ---------------------------------------------------------------------
-- The rule catalogue
-- ---------------------------------------------------------------------

CREATE TABLE safety_rules (
    rule_key      text PRIMARY KEY,
    severity      flag_severity NOT NULL,
    title         text NOT NULL,
    rationale     text NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_safety_rule_key CHECK (rule_key ~ '^[A-Z][A-Z0-9_]{2,59}$')
);

COMMENT ON TABLE safety_rules IS
'What deterministic rules exist and at what severity. Disabling one is an UPDATE; the logic stays SQL (D6). A rule is not a prompt instruction and cannot be added by an engine.';

INSERT INTO safety_rules (rule_key, severity, title, rationale) VALUES
('CRITICAL_LAB', 'HOLD',
 'A configured critical lab threshold is crossed',
 'Thresholds are rows in critical_lab_thresholds, so adding a marker is an INSERT. Only values that need action before a plan is sent are HOLD.'),

('HYPOGLYCAEMIA_RISK', 'HOLD',
 'Insulin or a sulfonylurea alongside a glucose-lowering intervention',
 'A plan that WORKS creates hypoglycaemia risk within days. The danger here is success, not failure, which is why this cannot wait for a follow-up.'),

('ANTICOAGULANT_INTERACTION', 'HOLD',
 'Warfarin with an intervention that plausibly interacts',
 'Vitamin K intake and several supplements move INR. The interaction is with the intervention, so the flag belongs to the plan and not to the medication list.'),

('PREGNANCY_BREASTFEEDING_MINOR', 'HOLD',
 'Pregnancy, breastfeeding, or a client under 18',
 'Different physiology, different evidence base, and different consent. Not a judgment about the plan — a judgment about whether this system should be sending one unreviewed.'),

('RENAL_HEPATIC_IMPAIRMENT', 'HOLD',
 'Significant renal or hepatic impairment',
 'Protein load, supplement clearance and several interventions change meaning entirely. Significant, not any abnormal value: the thresholds are configured.'),

('WORSENING_MARKER', 'NOTE',
 'Engine 4 reported a marker worsening under an active intervention',
 'A NOTE, never a HOLD (hard rule 9): the practitioner must see it, and blocking every plan for a client whose one marker moved the wrong way is the rubber stamp D6 rejected.');


-- Only a REGISTERED rule may be written as a deterministic flag. An
-- unregistered rule_key would be invisible in the catalogue, unexplainable
-- to the practitioner, and impossible to disable.
CREATE OR REPLACE FUNCTION trg_deterministic_flag_registered() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source = 'DETERMINISTIC'
       AND NOT EXISTS (SELECT 1 FROM safety_rules WHERE rule_key = NEW.rule_key) THEN
        RAISE EXCEPTION
            'deterministic flag % is not a registered safety rule. A rule '
            'the catalogue does not know cannot be explained to the '
            'practitioner, cannot be disabled, and cannot be audited.',
            NEW.rule_key
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_flag_rule_registered
    BEFORE INSERT OR UPDATE ON case_flags
    FOR EACH ROW EXECUTE FUNCTION trg_deterministic_flag_registered();

GRANT SELECT ON safety_rules TO phi_runtime, phi_practitioner;


-- ---------------------------------------------------------------------
-- Configured thresholds and name matching — all rows
-- ---------------------------------------------------------------------

CREATE TABLE critical_lab_thresholds (
    marker        text NOT NULL,
    unit          text,
    critical_low  numeric,
    critical_high numeric,
    rule_key      text NOT NULL REFERENCES safety_rules(rule_key),
    note          text,
    active        boolean NOT NULL DEFAULT true,
    PRIMARY KEY (marker, rule_key),

    CONSTRAINT ck_threshold_has_a_bound
        CHECK (critical_low IS NOT NULL OR critical_high IS NOT NULL)
);

COMMENT ON TABLE critical_lab_thresholds IS
'CRITICAL, not merely out of reference range. A value outside the lab reference interval is ordinary in this population; these are the values that need action before a plan is sent.';

-- Deliberately few. Every threshold added here fires on a real client, and
-- the cost of a threshold set too tight is the gate becoming a formality.
INSERT INTO critical_lab_thresholds
    (marker, unit, critical_low, critical_high, rule_key, note) VALUES
('HBA1C',      '%',        NULL, 10.0, 'CRITICAL_LAB',
 'Marked hyperglycaemia; prescriber review before a nutrition plan.'),
('GLUCOSE_FASTING', 'mg/dL', 54,  300,  'CRITICAL_LAB',
 'Hypoglycaemia at the low bound, marked hyperglycaemia at the high.'),
('POTASSIUM',  'mmol/L',   3.0,  6.0,  'CRITICAL_LAB',
 'Arrhythmia risk in both directions; interacts with several dietary changes.'),
('SODIUM',     'mmol/L',   125,  155,  'CRITICAL_LAB',
 'Fluid and electrolyte advice is unsafe outside this band.'),
('EGFR',       'mL/min/1.73m2', 45, NULL, 'RENAL_HEPATIC_IMPAIRMENT',
 'Below 45 changes protein, potassium and supplement advice materially.'),
('CREATININE', 'mg/dL',    NULL, 2.0,  'RENAL_HEPATIC_IMPAIRMENT',
 'Corroborates impaired clearance where eGFR is absent.'),
('ALT',        'U/L',      NULL, 120,  'RENAL_HEPATIC_IMPAIRMENT',
 'Roughly 3x the usual upper limit — not mild transaminitis.'),
('AST',        'U/L',      NULL, 120,  'RENAL_HEPATIC_IMPAIRMENT',
 'As ALT.');

GRANT SELECT ON critical_lab_thresholds TO phi_runtime, phi_practitioner;


-- Which medications and interventions matter, by CLASS. Rows, so the next
-- sulfonylurea is an INSERT (hard rule 13). Matching is on norm_phrase(),
-- the same normalizer the concept layer uses.
CREATE TABLE safety_match_patterns (
    pattern_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    match_class  text NOT NULL,
    applies_to   text NOT NULL,      -- MEDICATION | INTERVENTION | CONDITION
    pattern      text NOT NULL,
    note         text,
    active       boolean NOT NULL DEFAULT true,

    CONSTRAINT ck_pattern_target
        CHECK (applies_to IN ('MEDICATION', 'INTERVENTION', 'CONDITION')),
    CONSTRAINT ck_pattern_nonempty CHECK (length(btrim(pattern)) >= 3)
);

CREATE UNIQUE INDEX uq_safety_pattern
    ON safety_match_patterns (match_class, applies_to, pattern);
CREATE INDEX idx_safety_pattern_class
    ON safety_match_patterns (match_class, applies_to) WHERE active;

COMMENT ON TABLE safety_match_patterns IS
'Substring patterns matched against norm_phrase() of a medication, intervention or condition name. Rows rather than code: a drug list inside a function is how the next drug in the class goes unflagged (hard rule 13).';

INSERT INTO safety_match_patterns (match_class, applies_to, pattern, note) VALUES
-- Insulins. "insulin" alone is safe here because this matches MEDICATION
-- names only; "insulin resistance" is a condition and is never matched.
('INSULIN', 'MEDICATION', 'insulin', 'any insulin, any regimen'),

-- Sulfonylureas by stem. Metformin matches none of these, which is the
-- point of D6's acceptance case.
('SULFONYLUREA', 'MEDICATION', 'glipizide', NULL),
('SULFONYLUREA', 'MEDICATION', 'gliclazide', NULL),
('SULFONYLUREA', 'MEDICATION', 'glimepiride', NULL),
('SULFONYLUREA', 'MEDICATION', 'glyburide', NULL),
('SULFONYLUREA', 'MEDICATION', 'glibenclamide', NULL),
('SULFONYLUREA', 'MEDICATION', 'repaglinide', 'meglitinide; same hypoglycaemia mechanism'),
('SULFONYLUREA', 'MEDICATION', 'nateglinide', 'meglitinide'),

('WARFARIN', 'MEDICATION', 'warfarin', NULL),
('WARFARIN', 'MEDICATION', 'acenocoumarol', 'same vitamin-K mechanism'),

-- Interventions whose SUCCESS is the hazard when stacked on the above.
('GLUCOSE_LOWERING', 'INTERVENTION', 'carbohydrate reduction', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'low carbohydrate', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'intermittent fasting', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'time restricted eating', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'extended fasting', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'berberine', NULL),
('GLUCOSE_LOWERING', 'INTERVENTION', 'meal sequencing', 'fibre-first and similar'),

('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'vitamin k', NULL),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'leafy green', 'vitamin K load'),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'fish oil', NULL),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'omega 3', NULL),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'turmeric', NULL),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'curcumin', NULL),
('ANTICOAGULANT_INTERACTING', 'INTERVENTION', 'ginkgo', NULL),

('PREGNANCY', 'CONDITION', 'pregnan', 'pregnant / pregnancy'),
('PREGNANCY', 'CONDITION', 'gestation', 'gestational diabetes included'),
('BREASTFEEDING', 'CONDITION', 'breastfeeding', NULL),
('BREASTFEEDING', 'CONDITION', 'lactating', NULL),

('RENAL_IMPAIRMENT', 'CONDITION', 'chronic kidney disease', NULL),
('RENAL_IMPAIRMENT', 'CONDITION', 'renal impairment', NULL),
('RENAL_IMPAIRMENT', 'CONDITION', 'renal failure', NULL),
('RENAL_IMPAIRMENT', 'CONDITION', 'dialysis', NULL),
('HEPATIC_IMPAIRMENT', 'CONDITION', 'cirrhosis', NULL),
('HEPATIC_IMPAIRMENT', 'CONDITION', 'hepatic impairment', NULL),
('HEPATIC_IMPAIRMENT', 'CONDITION', 'liver failure', NULL);

GRANT SELECT ON safety_match_patterns TO phi_runtime, phi_practitioner;


-- ---------------------------------------------------------------------
-- The evaluation itself
-- ---------------------------------------------------------------------
--
-- One function, returning what WOULD be flagged. It writes nothing, so a
-- practitioner view, a test and a dry run all read the same answer, and
-- `apply_safety_rules` is the only thing that opens a flag.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION matches_class(p_name text, p_class text, p_target text)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM safety_match_patterns p
         WHERE p.active AND p.match_class = p_class AND p.applies_to = p_target
           AND norm_phrase(p_name) LIKE '%' || norm_phrase(p.pattern) || '%')
$$;

COMMENT ON FUNCTION matches_class IS
'Substring match on norm_phrase(), against rows. The one place a name becomes a class, so a pattern added anywhere is seen everywhere.';


CREATE OR REPLACE FUNCTION evaluate_safety_rules(p_client_id uuid)
RETURNS TABLE (rule_key text, severity flag_severity, detail text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    on_insulin_or_su boolean;
    on_warfarin      boolean;
BEGIN
    -- Which medication classes this client is on. Computed once: three
    -- rules read them and a repeated scan per rule would be the same
    -- question asked three ways.
    SELECT
        bool_or(matches_class(m.name, 'INSULIN', 'MEDICATION')
                OR matches_class(m.name, 'SULFONYLUREA', 'MEDICATION')),
        bool_or(matches_class(m.name, 'WARFARIN', 'MEDICATION'))
      INTO on_insulin_or_su, on_warfarin
      FROM client_medications m
     WHERE m.client_id = p_client_id AND m.status = 'CURRENT';

    -- ---------------------------------------------------------------
    -- 1. Configured critical lab thresholds. LATEST value per marker
    -- only: a value from two years ago that has since been corrected is
    -- history, not a reason to hold today's plan.
    -- ---------------------------------------------------------------
    RETURN QUERY
    WITH latest AS (
        SELECT DISTINCT ON (l.marker) l.marker, l.value, l.unit, l.measured_on
          FROM client_labs l
         WHERE l.client_id = p_client_id AND l.value IS NOT NULL
         ORDER BY l.marker, l.measured_on DESC
    )
    SELECT t.rule_key, r.severity,
           format('%s = %s %s on %s (critical %s)', latest.marker, latest.value,
                  coalesce(latest.unit, t.unit, ''), latest.measured_on,
                  CASE WHEN t.critical_low IS NOT NULL
                            AND latest.value < t.critical_low
                        THEN format('below %s', t.critical_low)
                        ELSE format('above %s', t.critical_high) END)
      FROM latest
      JOIN critical_lab_thresholds t
        ON upper(btrim(t.marker)) = upper(btrim(latest.marker)) AND t.active
      JOIN safety_rules r ON r.rule_key = t.rule_key AND r.active
     WHERE (t.critical_low  IS NOT NULL AND latest.value < t.critical_low)
        OR (t.critical_high IS NOT NULL AND latest.value > t.critical_high);

    -- ---------------------------------------------------------------
    -- 2. Hypoglycaemia risk. The hazard is the plan WORKING, so it needs
    -- both halves: the medication and a live glucose-lowering
    -- intervention. Neither alone is a flag -- a client on insulin with
    -- no such intervention is an ordinary client.
    -- ---------------------------------------------------------------
    IF coalesce(on_insulin_or_su, false) THEN
        RETURN QUERY
        SELECT 'HYPOGLYCAEMIA_RISK'::text, r.severity,
               format('on insulin or a sulfonylurea with a glucose-lowering '
                      'intervention: %s. A plan that works lowers glucose '
                      'within days and the dose is unchanged.',
                      string_agg(i.name, '; ' ORDER BY i.name))
          FROM client_interventions i
          JOIN safety_rules r ON r.rule_key = 'HYPOGLYCAEMIA_RISK' AND r.active
         WHERE i.client_id = p_client_id
           AND i.status IN ('PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED')
           AND matches_class(i.name, 'GLUCOSE_LOWERING', 'INTERVENTION')
         GROUP BY r.severity
        HAVING count(*) > 0;
    END IF;

    -- ---------------------------------------------------------------
    -- 3. Warfarin, and only where the intervention plausibly interacts.
    -- ---------------------------------------------------------------
    IF coalesce(on_warfarin, false) THEN
        RETURN QUERY
        SELECT 'ANTICOAGULANT_INTERACTION'::text, r.severity,
               format('on warfarin with an intervention that plausibly '
                      'moves INR: %s. Prescriber coordination before release.',
                      string_agg(i.name, '; ' ORDER BY i.name))
          FROM client_interventions i
          JOIN safety_rules r ON r.rule_key = 'ANTICOAGULANT_INTERACTION' AND r.active
         WHERE i.client_id = p_client_id
           AND i.status IN ('PROPOSED','APPROVED','STARTED','ONGOING','MODIFIED')
           AND matches_class(i.name, 'ANTICOAGULANT_INTERACTING', 'INTERVENTION')
         GROUP BY r.severity
        HAVING count(*) > 0;
    END IF;

    -- ---------------------------------------------------------------
    -- 4. Pregnancy, breastfeeding, minors.
    -- ---------------------------------------------------------------
    RETURN QUERY
    SELECT 'PREGNANCY_BREASTFEEDING_MINOR'::text, r.severity, d.detail
      FROM safety_rules r
      JOIN LATERAL (
          SELECT string_agg(x.detail, '; ') AS detail FROM (
              SELECT format('active condition: %s', c.condition) AS detail
                FROM client_conditions c
               WHERE c.client_id = p_client_id AND c.status = 'ACTIVE'
                 AND (matches_class(c.condition, 'PREGNANCY', 'CONDITION')
                      OR matches_class(c.condition, 'BREASTFEEDING', 'CONDITION'))
              UNION ALL
              -- year_of_birth, not a date: the record holds a year, and
              -- inferring a birthday to compute an exact age would be
              -- precision this system does not have.
              SELECT format('year of birth %s — under 18', cl.year_of_birth)
                FROM clients cl
               WHERE cl.client_id = p_client_id
                 AND cl.year_of_birth IS NOT NULL
                 AND (extract(year FROM current_date) - cl.year_of_birth) < 18
          ) x) d ON d.detail IS NOT NULL
     WHERE r.rule_key = 'PREGNANCY_BREASTFEEDING_MINOR' AND r.active;

    -- ---------------------------------------------------------------
    -- 5. Renal or hepatic impairment, by CONDITION. The lab half of this
    -- rule is already covered above, through critical_lab_thresholds
    -- rows that carry this rule_key -- one rule, two evidence sources,
    -- and no second copy of the thresholds.
    -- ---------------------------------------------------------------
    RETURN QUERY
    SELECT 'RENAL_HEPATIC_IMPAIRMENT'::text, r.severity,
           format('active condition: %s', string_agg(c.condition, '; '))
      FROM client_conditions c
      JOIN safety_rules r ON r.rule_key = 'RENAL_HEPATIC_IMPAIRMENT' AND r.active
     WHERE c.client_id = p_client_id AND c.status = 'ACTIVE'
       AND (matches_class(c.condition, 'RENAL_IMPAIRMENT', 'CONDITION')
            OR matches_class(c.condition, 'HEPATIC_IMPAIRMENT', 'CONDITION'))
     GROUP BY r.severity
    HAVING count(*) > 0;

    -- ---------------------------------------------------------------
    -- 6. A marker worsening under an active intervention. A NOTE, never
    -- a HOLD (hard rule 9): it must be seen, and it must not block.
    -- ---------------------------------------------------------------
    RETURN QUERY
    SELECT 'WORSENING_MARKER'::text, r.severity,
           format('worsening under an active intervention: %s',
                  string_agg(i.name, '; ' ORDER BY i.name))
      FROM client_interventions i
      JOIN safety_rules r ON r.rule_key = 'WORSENING_MARKER' AND r.active
     WHERE i.client_id = p_client_id
       AND i.outcome = 'WORSENING'
       AND i.status IN ('STARTED','ONGOING','MODIFIED')
     GROUP BY r.severity
    HAVING count(*) > 0;
END $$;

COMMENT ON FUNCTION evaluate_safety_rules IS
'What WOULD be flagged, computed and not written. D6: six deterministic rules over labs, medications, conditions and interventions. A client on metformin, a statin and an ACE inhibitor returns nothing.';


-- Writing is separate from evaluating, and re-running is idempotent: a
-- rule already OPEN for this client is not opened twice, and a rule that
-- no longer fires is NOT auto-closed -- only a practitioner resolves or
-- overrides a flag (trg_protect_deterministic_flags).
CREATE OR REPLACE FUNCTION apply_safety_rules(p_client_id uuid, p_cycle_id uuid,
                                              p_run_id uuid DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    opened integer := 0;
BEGIN
    INSERT INTO case_flags (client_id, cycle_id, run_id, rule_key, severity,
                            source, detail)
    SELECT p_client_id, p_cycle_id, p_run_id, e.rule_key, e.severity,
           'DETERMINISTIC', e.detail
      FROM evaluate_safety_rules(p_client_id) e
     WHERE NOT EXISTS (
         SELECT 1 FROM case_flags f
          WHERE f.client_id = p_client_id AND f.rule_key = e.rule_key
            AND f.status = 'OPEN');
    GET DIAGNOSTICS opened = ROW_COUNT;
    RETURN opened;
END $$;

COMMENT ON FUNCTION apply_safety_rules IS
'Opens a flag per firing rule, once. A rule that stops firing is never auto-closed: clearing a deterministic flag is a practitioner act, and trg_protect_deterministic_flags enforces that an engine cannot do it.';


-- ---------------------------------------------------------------------
-- What the gate would do, without touching it
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_release_readiness
WITH (security_invoker = true) AS
SELECT c.client_id,
       c.display_name,
       (SELECT count(*) FROM case_flags f
         WHERE f.client_id = c.client_id AND f.severity='HOLD'
           AND f.status='OPEN')                                AS open_holds,
       (SELECT count(*) FROM case_flags f
         WHERE f.client_id = c.client_id AND f.severity='NOTE'
           AND f.status='OPEN')                                AS open_notes,
       (SELECT count(*) FROM practitioner_reviews r
         WHERE r.client_id = c.client_id AND r.decision = 'PENDING') AS pending_reviews,
       (SELECT count(*) FROM practitioner_reviews r
         WHERE r.client_id = c.client_id
           AND r.decision IN ('APPROVED','APPROVED_WITH_EDITS'))     AS approvals,
       -- Both conditions, and they are different things: the gate stops a
       -- HOLD, the practitioner stops everything else. Neither substitutes
       -- for the other.
       ((SELECT count(*) FROM case_flags f
          WHERE f.client_id = c.client_id AND f.severity='HOLD'
            AND f.status='OPEN') = 0
        AND EXISTS (SELECT 1 FROM practitioner_reviews r
                     WHERE r.client_id = c.client_id
                       AND r.decision IN ('APPROVED','APPROVED_WITH_EDITS')))
                                                               AS releasable
FROM clients c;

COMMENT ON VIEW v_release_readiness IS
'Why a client-facing message can or cannot be released. NOTE flags appear and never block (hard rule 9). Approval and the safety gate are separate conditions and neither substitutes for the other.';

GRANT SELECT ON v_release_readiness TO phi_runtime, phi_practitioner;
