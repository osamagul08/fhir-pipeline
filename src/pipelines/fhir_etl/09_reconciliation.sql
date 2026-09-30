-- ===========================================================================
-- RECONCILIATION - the gate. The update FAILS (publishes nothing new) if any
-- rule below is broken. The rules hold for ANY set of loaded batches, so they
-- need no expected numbers typed in (design.md §6).
--
-- One row, one column per check. Each CONSTRAINT tests one column.
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW reconciliation (
    -- Every record in the bronze files reached silver: nothing lost, nothing added.
    CONSTRAINT records_bronze_equals_silver EXPECT (records_in_bronze = rows_in_silver)       ON VIOLATION FAIL UPDATE,
    -- Every file parsed as a FHIR Bundle (rule Q1). A bad file stops the run.
    CONSTRAINT every_file_is_a_bundle       EXPECT (files_not_bundles = 0)                   ON VIOLATION FAIL UPDATE,
    -- Every patient file ('transaction') holds exactly one Patient.
    CONSTRAINT one_patient_per_patient_file EXPECT (patient_files_without_one_patient = 0)   ON VIOLATION FAIL UPDATE,
    -- Profile pattern: every visit has exactly one note and one insurer statement.
    CONSTRAINT visit_note_eob_match         EXPECT (encounters = document_references
                                                    AND encounters = explanations_of_benefit) ON VIOLATION FAIL UPDATE,
    -- Record ids unique within each type (rule Q5). FAIL since 2026-09-30: batch 1
    -- measured 0. Also guards against a RENAMED file, which Auto Loader would
    -- load again as new (it remembers file paths, not contents).
    CONSTRAINT resource_ids_unique          EXPECT (duplicate_resource_ids = 0)              ON VIOLATION FAIL UPDATE,
    -- Every record of the 11 typed record types reached its typed table:
    -- the flattening lost nothing and added nothing.
    CONSTRAINT typed_tables_complete        EXPECT (typed_rows_missing = 0)                  ON VIOLATION FAIL UPDATE
)
COMMENT 'Publication gate for the FHIR pipeline: fails the update if any rule is broken.'
AS
SELECT
    (SELECT COUNT(*)                                FROM bronze_bundles)                 AS files_in_bronze,
    (SELECT COUNT_IF(bundle_resource_type IS DISTINCT FROM 'Bundle') FROM bronze_bundles) AS files_not_bundles,
    (SELECT COALESCE(SUM(record_count), 0)          FROM bronze_bundles)                 AS records_in_bronze,
    (SELECT COUNT(*)                                FROM silver_entries)                 AS rows_in_silver,
    (SELECT COUNT(*) FROM (
        SELECT file_name FROM silver_entries WHERE bundle_type = 'transaction'
        GROUP BY file_name HAVING COUNT_IF(resource_type = 'Patient') <> 1))             AS patient_files_without_one_patient,
    (SELECT COUNT_IF(resource_type = 'Encounter')            FROM silver_entries)        AS encounters,
    (SELECT COUNT_IF(resource_type = 'DocumentReference')    FROM silver_entries)        AS document_references,
    (SELECT COUNT_IF(resource_type = 'ExplanationOfBenefit') FROM silver_entries)        AS explanations_of_benefit,
    (SELECT COUNT(*) FROM (
        SELECT resource_type, resource_id FROM silver_entries
        GROUP BY resource_type, resource_id HAVING COUNT(*) > 1))                        AS duplicate_resource_ids,
    -- For each typed record type: |records in silver_entries - rows in its typed
    -- table|, summed. 0 = every record made it, once.
    (SELECT SUM(abs(e.n - t.n)) FROM (
        SELECT resource_type, COUNT(*) AS n FROM silver_entries
        WHERE resource_type IN ('Patient','Encounter','Condition','Procedure','Immunization',
                                'MedicationRequest','Observation','Claim',
                                'Practitioner','Organization','Location')
        GROUP BY resource_type) e
     JOIN (
        SELECT 'Patient' AS resource_type, COUNT(*) AS n FROM silver_patient
        UNION ALL SELECT 'Encounter', COUNT(*) FROM silver_encounter
        UNION ALL SELECT 'Condition', COUNT(*) FROM silver_condition
        UNION ALL SELECT 'Procedure', COUNT(*) FROM silver_procedure
        UNION ALL SELECT 'Immunization', COUNT(*) FROM silver_immunization
        UNION ALL SELECT 'MedicationRequest', COUNT(*) FROM silver_medication_request
        UNION ALL SELECT 'Observation', COUNT(*) FROM silver_observation
        UNION ALL SELECT 'Claim', COUNT(*) FROM silver_claim
        UNION ALL SELECT 'Practitioner', COUNT(*) FROM silver_practitioner
        UNION ALL SELECT 'Organization', COUNT(*) FROM silver_organization
        UNION ALL SELECT 'Location', COUNT(*) FROM silver_location) t
     ON e.resource_type = t.resource_type)                                              AS typed_rows_missing,
    -- Quarantine, for information (the rows themselves are in `quarantine`).
    (SELECT COUNT(*) FROM quarantine)                                                   AS quarantined_issues,
    current_timestamp()                                                                  AS checked_at;
