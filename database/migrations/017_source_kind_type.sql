-- =====================================================================
-- 017_source_kind_type.sql
--
-- K08 needs a `knowledge_sources.source_type` for every envelope it
-- normalizes, and the first draft of the normalizer worked it out with a
-- CASE expression over source_kind names -- BOOK and EBOOK to BOOK, BLOG
-- to BLOG, and so on.
--
-- That is exactly what hard rule 13 and Engine 7 §47 forbid: a source type
-- hard-coded into ingestion logic. Adding a source kind would then be an
-- INSERT *and* a code change, and the code change is the one that gets
-- forgotten -- the new kind would quietly normalize as OTHER with nothing
-- to say it had.
--
-- So the mapping is a column on the registry. Adding a kind stays a single
-- INSERT that carries everything ingestion needs to know about it.
-- =====================================================================

ALTER TABLE source_kinds
    ADD COLUMN IF NOT EXISTS source_type source_type NOT NULL DEFAULT 'OTHER';

COMMENT ON COLUMN source_kinds.source_type IS
'Which knowledge_sources.source_type a source of this kind becomes when it is normalized. Registry data, never a CASE expression in ingestion code (§47, hard rule 13). OTHER is a legitimate answer and the default, so a kind added without one still ingests.';

UPDATE source_kinds SET source_type = v.source_type::source_type
  FROM (VALUES
    ('RESEARCH_PAPER',        'JOURNAL'),
    ('SYSTEMATIC_REVIEW',     'JOURNAL'),
    ('GUIDELINE',             'GUIDELINE'),
    ('CLINICAL_TRIAL_RECORD', 'JOURNAL'),
    ('YOUTUBE_VIDEO',         'VIDEO_CHANNEL'),
    ('YOUTUBE_PLAYLIST',      'VIDEO_CHANNEL'),
    ('PODCAST',               'PODCAST'),
    ('BLOG',                  'BLOG'),
    ('NEWSLETTER',            'NEWSLETTER'),
    ('WEB_ARTICLE',           'WEBSITE'),
    ('FREE_DIET_PLAN',        'PRACTITIONER_FRAMEWORK'),
    ('PAID_PRACTITIONER_PLAN','PRACTITIONER_FRAMEWORK'),
    ('PRACTITIONER_HANDOUT',  'PRACTITIONER_FRAMEWORK'),
    ('COURSE_NOTES',          'PRACTITIONER_FRAMEWORK'),
    ('BOOK',                  'BOOK'),
    ('EBOOK',                 'BOOK'),
    ('PDF',                   'OTHER'),
    ('RECIPE_COLLECTION',     'PRACTITIONER_FRAMEWORK'),
    ('CLINICAL_PROTOCOL',     'PRACTITIONER_FRAMEWORK'),
    ('CONFERENCE_MATERIAL',   'CONFERENCE'),
    ('MANUAL_UPLOAD',         'OTHER'),
    ('OTHER',                 'OTHER')
  ) AS v(source_kind, source_type)
 WHERE source_kinds.source_kind = v.source_kind;
