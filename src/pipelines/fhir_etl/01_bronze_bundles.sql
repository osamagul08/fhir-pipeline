-- ===========================================================================
-- BRONZE - bronze_bundles. One row per FILE, exactly as it arrived.
--
-- Each file is one FHIR bundle: one patient's whole history, or one of the two
-- reference files (hospitals, practitioners).
--
-- Two copies of the content, on purpose (design.md §3.1):
--   raw_text  the file's text, untouched - the evidence of what arrived
--   bundle    the same text parsed as VARIANT: JSON of any shape that SQL can
--             still read (bundle:type). No single guessed schema, so the
--             "address is a list here, an object there" problem cannot happen.
--
-- STREAM read_files = Auto Loader: it remembers which files it has loaded, so
-- the next run picks up only the files a new batch added.
-- ===========================================================================

CREATE OR REFRESH STREAMING TABLE bronze_bundles (
    -- Warn only (rule Q1): a file that is not valid JSON, or not a Bundle, is
    -- KEPT here (bundle = NULL) and counted - never silently dropped.
    CONSTRAINT is_valid_bundle EXPECT (bundle_resource_type = 'Bundle')
)
COMMENT 'FHIR R4 bundles, one row per file, raw text + parsed VARIANT. Data is SYNTHETIC (Synthea).'
AS
SELECT
    file_name,
    file_size,
    file_modified,
    current_timestamp()                                          AS ingest_ts,
    raw_text,
    bundle,
    bundle:resourceType::string                                  AS bundle_resource_type,
    -- 'transaction' = a patient file; 'batch' = a reference file.
    bundle:type::string                                          AS bundle_type,
    -- A field taken from a VARIANT is still a VARIANT: CAST it to a list to count.
    array_size(CAST(bundle:entry AS ARRAY<VARIANT>))             AS record_count
FROM (
    SELECT
        _metadata.file_name                   AS file_name,       -- which file
        _metadata.file_size                   AS file_size,       -- bytes, to check against the source
        _metadata.file_modification_time      AS file_modified,   -- when it landed in the volume
        value                                 AS raw_text,
        -- try_parse_json: NULL instead of an error for text that is not valid
        -- JSON, so one bad file cannot stop the whole load.
        try_parse_json(value)                 AS bundle
    -- format text + wholeText: ONE row per file, the whole file as one string
    -- (the JSON reader would guess one schema for everything - see above).
    FROM STREAM read_files('${landing_path}', format => 'text', wholeText => true)
);
