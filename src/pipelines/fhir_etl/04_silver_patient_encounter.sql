-- ===========================================================================
-- SILVER - patients and visits.
--
-- Helper patterns used from here on:
--   replace(link, 'urn:uuid:', '')   a link INSIDE the file -> the record id.
--       Safe: every record's address is 'urn:uuid:' + its id (checked on all
--       29,120 batch-1 records, 0 exceptions). A gate still checks each link.
--   split_part(link, '|', 2)         a link to the REFERENCE files -> the key
--       after the '|', e.g. the NPI in "Practitioner?identifier=...|9999999995".
--   try_cast(x AS TIMESTAMP)         FHIR dates are ISO text ("2021-06-24T09:34:31+00:00");
--       a value that will not convert becomes NULL (and is counted), never an error.
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW silver_patient (
    CONSTRAINT has_birth_date EXPECT (birth_date IS NOT NULL),   -- rule Q4, warn
    CONSTRAINT has_gender     EXPECT (gender IS NOT NULL)        -- rule Q4, warn
)
COMMENT 'One row per patient. Names, phone and street deliberately NOT copied: treated as private even though SYNTHETIC.'
AS
SELECT
    resource_id                                              AS patient_id,
    resource:gender::string                                  AS gender,
    try_cast(resource:birthDate::string AS DATE)             AS birth_date,
    try_cast(resource:deceasedDateTime::string AS TIMESTAMP) AS deceased_at,
    resource:deceasedDateTime IS NOT NULL                    AS is_deceased,
    resource:maritalStatus:coding[0]:code::string            AS marital_status,
    resource:address[0]:city::string                         AS city,          -- address is a LIST here
    resource:address[0]:state::string                        AS state,
    resource:address[0]:postalCode::string                   AS postal_code,
    file_name
FROM silver_entries
WHERE resource_type = 'Patient';


CREATE OR REFRESH MATERIALIZED VIEW silver_encounter (
    CONSTRAINT has_start EXPECT (start_at IS NOT NULL)           -- rule Q4, warn
)
COMMENT 'One row per visit, with its doctor, organisation and location resolved. SYNTHETIC.'
AS
WITH enc AS (
    SELECT
        resource_id                                                   AS encounter_id,
        replace(resource:subject:reference::string, 'urn:uuid:', '')  AS patient_id,
        resource:status::string                                       AS status,
        -- class: AMB = outpatient, EMER = emergency, IMP = inpatient, WELLNESS...
        resource:class:code::string                                   AS class_code,
        resource:type[0]:coding[0]:code::string                       AS type_code,      -- SNOMED
        resource:type[0]:text::string                                 AS type_text,
        try_cast(resource:period:start::string AS TIMESTAMP)          AS start_at,
        try_cast(resource:period:end::string AS TIMESTAMP)            AS end_at,
        resource:reasonCode[0]:coding[0]:code::string                 AS reason_code,    -- SNOMED
        resource:reasonCode[0]:coding[0]:display::string              AS reason_text,
        -- The original link text, kept so a failed match can be reviewed.
        resource:participant[0]:individual:reference::string          AS practitioner_link,
        resource:serviceProvider:reference::string                    AS organization_link,
        resource:location[0]:location:reference::string               AS location_link,
        file_name
    FROM silver_entries
    WHERE resource_type = 'Encounter'
)
SELECT
    enc.*,
    -- Resolved ids. LEFT JOIN: no match gives NULL (quarantine rule Q3),
    -- the visit itself is never dropped.
    p.practitioner_id,
    o.organization_id,
    COALESCE(l.location_id, lh.location_id)            AS location_id,
    -- HOW the location matched, so the second route is visible, never hidden:
    --   identifier  the normal case: the searched identifier exists
    --   id          home visits: "Patient's Home" is a 'kind' location with NO
    --               identifier; Synthea put its id where the identifier goes
    --               (found on batch 1: 3 links, all to that one location)
    --   NULL        matched neither way -> quarantine
    CASE WHEN l.location_id  IS NOT NULL THEN 'identifier'
         WHEN lh.location_id IS NOT NULL THEN 'id' END  AS location_match
FROM enc
LEFT JOIN silver_practitioner p ON p.npi      = split_part(enc.practitioner_link, '|', 2)
LEFT JOIN silver_organization o ON o.link_key = split_part(enc.organization_link, '|', 2)
LEFT JOIN silver_location     l ON l.link_key = split_part(enc.location_link, '|', 2)
-- Second route, tried only when the identifier found nothing.
LEFT JOIN silver_location    lh ON l.location_id IS NULL
                               AND lh.location_id = split_part(enc.location_link, '|', 2);
