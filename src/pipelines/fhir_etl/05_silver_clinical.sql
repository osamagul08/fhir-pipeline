-- ===========================================================================
-- SILVER - what happened to the patient: diagnoses, procedures, vaccines,
-- prescriptions. Same pattern each time: one record type, its own columns, the
-- medical code AND its code system (a code means nothing without its system).
--
--   Condition          SNOMED CT   diagnoses
--   Procedure          SNOMED CT   things done to the patient
--   Immunization       CVX         vaccines
--   MedicationRequest  RxNorm      prescriptions
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW silver_condition (
    CONSTRAINT has_code EXPECT (code IS NOT NULL)                -- rule Q4, warn
)
COMMENT 'One row per diagnosis. SYNTHETIC.'
AS
SELECT
    resource_id                                                    AS condition_id,
    replace(resource:subject:reference::string, 'urn:uuid:', '')   AS patient_id,
    replace(resource:encounter:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:clinicalStatus:coding[0]:code::string                 AS clinical_status,      -- active / resolved
    resource:verificationStatus:coding[0]:code::string             AS verification_status,  -- confirmed ...
    resource:code:coding[0]:system::string                         AS code_system,
    resource:code:coding[0]:code::string                           AS code,
    resource:code:text::string                                     AS code_text,
    try_cast(resource:onsetDateTime::string AS TIMESTAMP)          AS onset_at,
    try_cast(resource:abatementDateTime::string AS TIMESTAMP)      AS abatement_at,          -- NULL = still ongoing
    try_cast(resource:recordedDate::string AS TIMESTAMP)           AS recorded_at,
    file_name
FROM silver_entries
WHERE resource_type = 'Condition';


CREATE OR REFRESH MATERIALIZED VIEW silver_procedure (
    CONSTRAINT has_code EXPECT (code IS NOT NULL)
)
COMMENT 'One row per procedure. SYNTHETIC.'
AS
SELECT
    resource_id                                                    AS procedure_id,
    replace(resource:subject:reference::string, 'urn:uuid:', '')   AS patient_id,
    replace(resource:encounter:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:status::string                                        AS status,
    resource:code:coding[0]:system::string                         AS code_system,
    resource:code:coding[0]:code::string                           AS code,
    resource:code:text::string                                     AS code_text,
    try_cast(resource:performedPeriod:start::string AS TIMESTAMP)  AS performed_start,
    try_cast(resource:performedPeriod:end::string AS TIMESTAMP)    AS performed_end,
    resource:location:reference::string                            AS location_link,
    file_name
FROM silver_entries
WHERE resource_type = 'Procedure';


CREATE OR REFRESH MATERIALIZED VIEW silver_immunization (
    CONSTRAINT has_vaccine_code EXPECT (vaccine_code IS NOT NULL)
)
COMMENT 'One row per vaccine given. SYNTHETIC.'
AS
SELECT
    resource_id                                                    AS immunization_id,
    -- Immunization names the person `patient`, not `subject` like the others.
    replace(resource:patient:reference::string, 'urn:uuid:', '')   AS patient_id,
    replace(resource:encounter:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:status::string                                        AS status,
    resource:vaccineCode:coding[0]:system::string                  AS code_system,   -- CVX
    resource:vaccineCode:coding[0]:code::string                    AS vaccine_code,
    resource:vaccineCode:text::string                              AS vaccine_text,
    try_cast(resource:occurrenceDateTime::string AS TIMESTAMP)     AS occurred_at,
    resource:location:reference::string                            AS location_link,
    file_name
FROM silver_entries
WHERE resource_type = 'Immunization';


CREATE OR REFRESH MATERIALIZED VIEW silver_medication_request (
    -- Warn: most prescriptions carry the drug code directly; some point to a
    -- separate Medication record instead (583 Medication records in the full data).
    CONSTRAINT drug_code_or_reference EXPECT (rx_code IS NOT NULL OR medication_link IS NOT NULL)
)
COMMENT 'One row per prescription. SYNTHETIC.'
AS
SELECT
    resource_id                                                    AS medication_request_id,
    replace(resource:subject:reference::string, 'urn:uuid:', '')   AS patient_id,
    replace(resource:encounter:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:status::string                                        AS status,        -- active / stopped ...
    resource:intent::string                                        AS intent,        -- order ...
    -- The notebook in the listing notes: the drug sits here, not in `medication`.
    resource:medicationCodeableConcept:coding[0]:system::string    AS code_system,   -- RxNorm
    resource:medicationCodeableConcept:coding[0]:code::string      AS rx_code,
    resource:medicationCodeableConcept:text::string                AS rx_text,
    resource:medicationReference:reference::string                 AS medication_link,
    try_cast(resource:authoredOn::string AS TIMESTAMP)             AS authored_at,
    resource:requester:reference::string                           AS requester_link,
    split_part(resource:requester:reference::string, '|', 2)       AS requester_npi,
    file_name
FROM silver_entries
WHERE resource_type = 'MedicationRequest';
