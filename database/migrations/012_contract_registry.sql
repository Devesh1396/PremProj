-- =====================================================================
-- 012_contract_registry.sql — the orchestration contract becomes a row
--
-- The second half of D23, and the last thing between here and the n8n
-- RUN_ENGINE port.
--
-- 010 put the seven engine SPECIFICATIONS in the database so n8n could
-- read a prompt without a copy of this repository. The same argument
-- applies with more force to the control contract: run_engine.py loads
-- schemas/orchestration/control_contract.v1.json off the working tree and
-- validates every engine's control block against it, and hard rule 5 says
-- n8n NEVER parses prose to route -- it reads the typed fields this
-- document defines. An n8n port with no access to the contract cannot
-- route at all.
--
-- One document, two validators. Python keeps jsonschema; the n8n Code node
-- uses ajv, which ships inside n8n. Both are implementations of JSON Schema
-- 2020-12 and both read THIS row, so the only thing they can disagree
-- about is the standard itself -- and testing/test_contract_registry.py
-- runs the same payloads through both and asserts identical verdicts.
--
-- That is deliberately different from two hand-written validators. The
-- SPECIFICATION is single-sourced; the libraries are interchangeable.
--
-- Append-only, like 010 and for the same reason: engine_runs.schema_version
-- names the contract an output was judged against, and rewriting a
-- document under a recorded version silently relabels every run that cites
-- it.
-- =====================================================================


-- =====================================================================
-- 1. The registry
-- =====================================================================

CREATE TABLE IF NOT EXISTS orchestration_contracts (
    contract_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Matches engine_runs.schema_version, which has carried
    -- 'control_contract.v1' since 004. That column is the link between a
    -- run and the contract its output was judged against.
    schema_version text NOT NULL,

    -- The authored file it came from.
    source_file   text NOT NULL,

    -- The JSON Schema document itself.
    document      jsonb NOT NULL,

    -- sha256 of the file's bytes, exactly as the loader read them.
    -- Deliberately NOT a hash of the parsed jsonb: jsonb reorders keys and
    -- normalises numbers, so hashing it would make the hash depend on
    -- PostgreSQL's internals rather than on what anyone reviewed.
    document_hash text NOT NULL,

    active        boolean NOT NULL DEFAULT true,

    loaded_at     timestamptz NOT NULL DEFAULT now(),
    loaded_by     text NOT NULL DEFAULT current_user,
    superseded_at timestamptz,

    CONSTRAINT ck_contract_is_object   CHECK (jsonb_typeof(document) = 'object'),
    CONSTRAINT ck_contract_hash_shape  CHECK (document_hash ~ '^[0-9a-f]{64}$'),
    -- A schema with no properties would validate everything, which is the
    -- same as no contract at all and would let a malformed control block
    -- route a case. Written as an inequality rather than a count because a
    -- CHECK constraint cannot contain a subquery, and jsonb_object_keys is
    -- set-returning.
    CONSTRAINT ck_contract_has_properties
        CHECK (jsonb_typeof(document -> 'properties') = 'object'
               AND document -> 'properties' <> '{}'::jsonb),
    CONSTRAINT ck_contract_active_coherent
        CHECK ((active AND superseded_at IS NULL) OR (NOT active AND superseded_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_version
    ON orchestration_contracts (schema_version, document_hash);

-- Exactly one active document per schema_version, so "what was this run
-- judged against" has one answer.
CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_active
    ON orchestration_contracts (schema_version) WHERE active;

COMMENT ON TABLE orchestration_contracts IS
'Runtime source of the orchestration control contract (D23). schemas/orchestration/*.json is the authored form; this is what RUN_ENGINE validates against, so n8n can route without a copy of the repository. Append-only: engine_runs.schema_version cites a contract, and a document rewritten under a recorded version silently relabels every run judged by it.';

COMMENT ON COLUMN orchestration_contracts.document_hash IS
'sha256 of the authored file''s bytes, not of the parsed jsonb. jsonb reorders keys and normalises numbers, so hashing it would tie the hash to PostgreSQL''s storage rather than to the text a human reviewed.';


-- =====================================================================
-- 2. Append-only, enforced
-- =====================================================================

CREATE OR REPLACE FUNCTION trg_contracts_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.document IS DISTINCT FROM OLD.document
       OR NEW.document_hash <> OLD.document_hash
       OR NEW.schema_version <> OLD.schema_version THEN
        RAISE EXCEPTION
            'orchestration_contracts is append-only: % (hash %) cannot be rewritten. '
            'engine_runs cites this schema_version as what an output was judged '
            'against. Insert a new version and deactivate this one.',
            OLD.schema_version, left(OLD.document_hash, 12)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_contracts_append_only ON orchestration_contracts;
CREATE TRIGGER trg_contracts_append_only
    BEFORE UPDATE ON orchestration_contracts
    FOR EACH ROW EXECUTE FUNCTION trg_contracts_append_only();

CREATE OR REPLACE FUNCTION trg_contracts_no_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM engine_runs WHERE schema_version = OLD.schema_version) THEN
        RAISE EXCEPTION
            'contract % has judged engine runs and cannot be deleted. '
            'Deactivate it instead.', OLD.schema_version
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_contracts_no_delete ON orchestration_contracts;
CREATE TRIGGER trg_contracts_no_delete
    BEFORE DELETE ON orchestration_contracts
    FOR EACH ROW EXECUTE FUNCTION trg_contracts_no_delete();


-- =====================================================================
-- 3. Access
-- =====================================================================
--
-- No RLS, for the same reason as engine_prompts: a schema is not client
-- data, it is identical for every client, and scoping it would break
-- knowledge-clock runs, which have no client scope (D18).

GRANT SELECT ON orchestration_contracts TO phi_runtime, phi_practitioner;

CREATE OR REPLACE VIEW v_active_contracts
WITH (security_invoker = true) AS
SELECT schema_version,
       source_file,
       document_hash,
       -- The count n8n and the suites both assert against. A contract that
       -- suddenly has three properties is worth noticing before it routes
       -- anything.
       (SELECT count(*) FROM jsonb_object_keys(document -> 'properties')) AS property_count,
       coalesce(jsonb_array_length(document -> 'required'), 0)            AS required_count,
       document -> '$schema'                                             AS json_schema_dialect,
       loaded_at, loaded_by
FROM orchestration_contracts
WHERE active
ORDER BY schema_version;

COMMENT ON VIEW v_active_contracts IS
'What RUN_ENGINE will actually validate against, without dumping the schema document into the output.';

GRANT SELECT ON v_active_contracts TO phi_runtime, phi_practitioner;
