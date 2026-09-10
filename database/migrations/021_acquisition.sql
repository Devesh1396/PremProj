-- =====================================================================
-- 021_acquisition.sql   Discovery: K02-K06
--
-- Discovery does NOT ingest. K07 and K08 already turn content into an
-- envelope, a preserved original and heading-located chunks; discovery's
-- job is to FIND things and hand them to that path. Two ingestion
-- pipelines would be two normalizers, two dedup rules and two places for
-- rights handling to be forgotten.
--
-- Three tables, each answering one sentence of the specification.
--
--   K02  "Store query history so expensive searches are not repeated."
--   K04  "Track last processed item; do not reprocess old content."
--   K03  "Not indiscriminate scraping. Respect access restrictions."
--   K06  "Do not build brittle unauthorized scraping as a core dependency."
--
-- The last two are a POLICY, and a policy that lives in an adapter's code
-- is a policy each new adapter gets to reinterpret. It lives in a registry
-- row instead, checked at one chokepoint, so adding an adapter is data
-- (hard rule 13) and the thing it is allowed to do is data too.
-- =====================================================================

-- ---------------------------------------------------------------------
-- What each acquisition adapter family is, and is allowed to do (§49)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS acquisition_adapters (
    adapter          text PRIMARY KEY,
    display_name     text NOT NULL,

    -- §49 "prefer structured over scraping". A structured adapter reads a
    -- documented API or feed; an unstructured one reads a page meant for
    -- humans. The distinction is recorded so "prefer" can be measured
    -- rather than asserted.
    structured       boolean NOT NULL DEFAULT true,

    -- The chokepoint refuses a fetch to a host outside this list. NULL
    -- means "no host restriction", which is only ever correct for adapters
    -- that do not fetch at all.
    allowed_hosts    text[],

    -- Whether this adapter must consult robots.txt before fetching. False
    -- is legitimate for a documented API that publishes its own terms;
    -- it is never legitimate for reading someone's website.
    respect_robots   boolean NOT NULL DEFAULT true,

    -- K06: unauthorized scraping is not a core dependency. An adapter that
    -- would need it is registered with requires_authorization = true and
    -- the chokepoint refuses it until someone records the authorization.
    requires_authorization boolean NOT NULL DEFAULT false,
    authorization_note     text,

    -- Politeness. Seconds between two fetches to the same host.
    min_interval_seconds integer NOT NULL DEFAULT 2
        CHECK (min_interval_seconds >= 0),

    -- Do not repeat an expensive search sooner than this.
    repeat_after_hours   integer NOT NULL DEFAULT 24
        CHECK (repeat_after_hours >= 0),

    active           boolean NOT NULL DEFAULT true,
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_adapter_key CHECK (adapter ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    -- An adapter that fetches must say where it may fetch from. The one
    -- exception is an adapter that fetches nothing, which is how the
    -- transcript families work when no transcript is legitimately
    -- available.
    CONSTRAINT ck_adapter_hosts CHECK (
        allowed_hosts IS NULL OR cardinality(allowed_hosts) > 0)
);

COMMENT ON TABLE acquisition_adapters IS
'Which acquisition families exist and what each may do. A registry, not an enum: §49 says acquisition is provider-independent and the adapter is replaceable, and hard rule 13 says a new source type is data. The access policy lives here so it is checked in one place rather than reinterpreted by each adapter.';

GRANT SELECT ON acquisition_adapters TO phi_runtime, phi_practitioner;

INSERT INTO acquisition_adapters
    (adapter, display_name, structured, allowed_hosts, respect_robots,
     requires_authorization, min_interval_seconds, repeat_after_hours, notes)
VALUES
    ('PUBMED', 'PubMed E-utilities', true,
     ARRAY['eutils.ncbi.nlm.nih.gov'], false, false, 1, 24,
     'K02. A documented API with published usage terms — structured, and preferred over reading the search pages that front it.'),
    ('CLINICAL_TRIALS', 'ClinicalTrials.gov API', true,
     ARRAY['clinicaltrials.gov'], false, false, 1, 24,
     'K02. Registry records, structured.'),
    ('RSS', 'RSS / Atom feed', true, NULL, true, false, 2, 6,
     'K04. A feed is published to be read by machines. The cursor is what stops old items being reprocessed; allowed_hosts is NULL because the practitioner chooses the feeds.'),
    ('WEB_HTTP', 'Web article over HTTP', false, NULL, true, false, 5, 168,
     'K03. Reading a page meant for humans, so robots.txt is respected and the interval is longer. Not indiscriminate: a source has to be registered before it is read.'),
    ('PODCAST', 'Podcast episode', true, NULL, true, false, 2, 24,
     'K05. The FEED is structured. A transcript is used when one is legitimately published; when none is, the item is marked FULL_TEXT_NOT_AVAILABLE and nothing is invented.'),
    ('YOUTUBE', 'Video platform', true, NULL, true, true, 2, 24,
     'K06. requires_authorization: obtaining a transcript generally needs terms nobody here has agreed to, and the specification says do not build brittle unauthorized scraping as a core dependency. Until an authorization_note records otherwise, the chokepoint refuses the fetch and the item is marked ACCESS_DENIED — which is a true statement about our access, not a failure.'),
    ('MANUAL_FILE', 'Practitioner-supplied file', true, NULL, false, false, 0, 0,
     'K07. No network at all. The practitioner hands the file over.'),
    ('MANUAL_BOOK', 'Practitioner-supplied book', true, NULL, false, false, 0, 0,
     'K07. As above, processed chapter by chapter (§16, §42).'),
    ('KNOWLEDGE_INBOX', 'Knowledge Inbox drop', true, NULL, false, false, 0, 0,
     'K07. The inbox directory. No network.')
ON CONFLICT (adapter) DO NOTHING;


-- ---------------------------------------------------------------------
-- K02: expensive searches are not repeated
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_queries (
    query_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    adapter       text NOT NULL REFERENCES acquisition_adapters(adapter),

    -- The query as issued, and its hash. The hash is what dedup keys on,
    -- because two callers phrasing the same search differently should
    -- still not pay for it twice -- so callers normalize before hashing
    -- and the raw text is kept for reading.
    query_text    text NOT NULL,
    query_hash    text NOT NULL,

    source_id     uuid REFERENCES knowledge_sources(source_id) ON DELETE SET NULL,
    domain_id     uuid REFERENCES knowledge_domains(domain_id) ON DELETE SET NULL,

    executed_at   timestamptz NOT NULL DEFAULT now(),
    results_returned integer NOT NULL DEFAULT 0 CHECK (results_returned >= 0),
    items_new        integer NOT NULL DEFAULT 0 CHECK (items_new >= 0),
    outcome       text NOT NULL DEFAULT 'OK',
    detail        text,

    CONSTRAINT ck_query_items_le_results CHECK (items_new <= results_returned)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_query_recent
    ON source_queries (adapter, query_hash, executed_at);
CREATE INDEX IF NOT EXISTS idx_query_lookup
    ON source_queries (adapter, query_hash, executed_at DESC);

COMMENT ON TABLE source_queries IS
'Every discovery search that was issued, and what it returned. K02: "Store query history so expensive searches are not repeated." A search that found nothing is still recorded — that is the result most worth not paying for twice.';

GRANT SELECT, INSERT ON source_queries TO phi_runtime;
GRANT SELECT ON source_queries TO phi_practitioner;


-- ---------------------------------------------------------------------
-- K04: track the last processed item
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_cursors (
    source_id     uuid NOT NULL REFERENCES knowledge_sources(source_id) ON DELETE CASCADE,
    cursor_kind   text NOT NULL,
    cursor_value  text NOT NULL,
    items_seen    bigint NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, cursor_kind),
    CONSTRAINT ck_cursor_kind CHECK (cursor_kind ~ '^[A-Z][A-Z0-9_]{1,31}$')
);

COMMENT ON TABLE source_cursors IS
'Where a monitored source was last read to. K04: "Track last processed item; do not reprocess old content." Keyed by KIND as well as source because a feed identifies its items by guid while an API pages by date, and a cursor that means two things is a cursor that reprocesses.';

GRANT SELECT, INSERT, UPDATE ON source_cursors TO phi_runtime;
GRANT SELECT ON source_cursors TO phi_practitioner;


-- ---------------------------------------------------------------------
-- Politeness and the audit trail for what was actually fetched
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_fetches (
    fetch_id     bigserial PRIMARY KEY,
    adapter      text NOT NULL REFERENCES acquisition_adapters(adapter),
    host         text NOT NULL,
    url          text NOT NULL,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    status_code  integer,
    bytes        integer,
    outcome      text NOT NULL,
    detail       text
);

CREATE INDEX IF NOT EXISTS idx_fetch_host_time ON source_fetches (host, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_fetch_outcome ON source_fetches (outcome, fetched_at DESC);

COMMENT ON TABLE source_fetches IS
'Every request the acquisition layer made or REFUSED to make, with the reason. A refusal is recorded as deliberately as a fetch: "we did not read this because robots.txt disallowed it" is the evidence that the policy is working.';

GRANT SELECT, INSERT ON source_fetches TO phi_runtime;
GRANT SELECT ON source_fetches TO phi_practitioner;


CREATE OR REPLACE VIEW v_discovery_state
WITH (security_invoker = true) AS
SELECT a.adapter,
       a.structured,
       a.requires_authorization,
       count(DISTINCT q.query_id)                             AS searches,
       count(DISTINCT f.fetch_id) FILTER (WHERE f.outcome = 'FETCHED')  AS fetched,
       count(DISTINCT f.fetch_id) FILTER (WHERE f.outcome <> 'FETCHED') AS refused_or_failed,
       coalesce(sum(q.items_new), 0)                          AS items_discovered,
       max(greatest(q.executed_at, f.fetched_at))             AS last_activity
FROM acquisition_adapters a
LEFT JOIN source_queries q ON q.adapter = a.adapter
LEFT JOIN source_fetches f ON f.adapter = a.adapter
WHERE a.active
GROUP BY a.adapter, a.structured, a.requires_authorization
ORDER BY a.adapter;

COMMENT ON VIEW v_discovery_state IS
'What each adapter has actually done. refused_or_failed being non-zero is normal and healthy: it counts robots.txt refusals and unavailable transcripts, which are the policy working rather than the system breaking.';

GRANT SELECT ON v_discovery_state TO phi_runtime, phi_practitioner;
