-- ===========================================================================
-- SILVER - silver_entries. One row per RECORD inside a bundle.
--
-- variant_explode turns each file's list of records into rows. The record is
-- kept WHOLE (column `resource`, VARIANT), so nothing is lost; the typed tables
-- (silver_patient, silver_encounter, ...) come next and read from here.
--
-- Expected when all 1,156 files are loaded: 631,630 rows (full profile).
-- For batch 1 (50 sample patients + 2 reference files): 23,613 + 2,754 + 2,753
-- = 29,120 rows.
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW silver_entries (
    -- Fail: every FHIR record must say what type it is. A NULL means the
    -- unpacking is wrong - a bug, not bad data.
    CONSTRAINT has_resource_type EXPECT (resource_type IS NOT NULL) ON VIOLATION FAIL UPDATE,
    -- Fail: every record must have its address inside the bundle, or the
    -- links between records (urn:uuid:...) cannot be resolved later.
    CONSTRAINT has_full_url      EXPECT (full_url IS NOT NULL)      ON VIOLATION FAIL UPDATE
)
COMMENT 'One row per FHIR record, record kept whole as VARIANT. Data is SYNTHETIC (Synthea).'
AS
WITH records AS (
    SELECT
        b.file_name,
        b.bundle_type,
        e.pos                                          AS entry_index,   -- position in the file
        e.value:fullUrl::string                        AS full_url,      -- e.g. urn:uuid:3b2f...
        e.value:resource:resourceType::string          AS resource_type, -- e.g. Encounter
        e.value:resource:id::string                    AS resource_id,
        e.value:resource                               AS resource       -- the whole record
    FROM bronze_bundles b,
         -- One output row per element of the entry list: pos = index, value = element.
         LATERAL variant_explode(b.bundle:entry) AS e
)
SELECT
    file_name,
    bundle_type,
    entry_index,
    full_url,
    resource_type,
    resource_id,
    -- The patient this record belongs to: the one Patient in the same file.
    -- MAX over the file picks it out (NULL in the 2 reference files).
    MAX(CASE WHEN resource_type = 'Patient' THEN resource_id END)
        OVER (PARTITION BY file_name)                  AS patient_id,
    resource
FROM records;
