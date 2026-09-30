-- ===========================================================================
-- QUARANTINE - one row per broken rule, with the record, the field, the
-- original value and a reason. Records are NOT removed from their tables:
-- this table explains what is wrong with them (design.md §5).
--
--   Q2  a link INSIDE the file (urn:uuid:...) points to no record
--   Q3  a link to the REFERENCE files finds no doctor / organisation / location
--   Q4  a required field is missing or would not convert
--
-- Location links match on the identifier OR, for 'kind' locations such as
-- "Patient's Home" (no identifier), on the location id - see silver_encounter.
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW quarantine
COMMENT 'Every broken rule, one row each, with the original value and a reason. SYNTHETIC data.'
AS
-- ---- Q3: links to reference data that find nothing -------------------------
SELECT 'Q3' AS rule_id, 'Encounter' AS resource_type, encounter_id AS resource_id, patient_id,
       'practitioner' AS field, practitioner_link AS original_value,
       'No practitioner with this NPI in the reference file' AS reason, file_name
FROM silver_encounter WHERE practitioner_link IS NOT NULL AND practitioner_id IS NULL
UNION ALL
SELECT 'Q3', 'Encounter', encounter_id, patient_id, 'organization', organization_link,
       'No organization with this identifier in the reference file', file_name
FROM silver_encounter WHERE organization_link IS NOT NULL AND organization_id IS NULL
UNION ALL
SELECT 'Q3', 'Encounter', encounter_id, patient_id, 'location', location_link,
       'No location with this identifier in the reference file', file_name
FROM silver_encounter WHERE location_link IS NOT NULL AND location_id IS NULL
UNION ALL
SELECT 'Q3', 'Procedure', procedure_id, patient_id, 'location', location_link,
       'No location with this identifier in the reference file', file_name
FROM silver_procedure p
WHERE location_link IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM silver_location l WHERE split_part(p.location_link, '|', 2) IN (l.link_key, l.location_id))
UNION ALL
SELECT 'Q3', 'Immunization', immunization_id, patient_id, 'location', location_link,
       'No location with this identifier in the reference file', file_name
FROM silver_immunization i
WHERE location_link IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM silver_location l WHERE split_part(i.location_link, '|', 2) IN (l.link_key, l.location_id))
UNION ALL
SELECT 'Q3', 'MedicationRequest', medication_request_id, patient_id, 'requester', requester_link,
       'No practitioner with this NPI in the reference file', file_name
FROM silver_medication_request m
WHERE requester_npi IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM silver_practitioner p WHERE p.npi = m.requester_npi)
UNION ALL
SELECT 'Q3', 'Claim', claim_id, patient_id, 'provider', provider_link,
       'No organization with this identifier in the reference file', file_name
FROM silver_claim c
WHERE provider_link IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM silver_organization o WHERE o.link_key = split_part(c.provider_link, '|', 2))

-- ---- Q2: links inside the file that point to no record ---------------------
-- Every clinical record names a patient and (usually) a visit; both must exist.
UNION ALL
SELECT 'Q2', resource_type, resource_id, patient_id, 'encounter', encounter_id,
       'Visit id not found among this dataset''s encounters', file_name
FROM (
    SELECT 'Condition' AS resource_type, condition_id AS resource_id, patient_id, encounter_id, file_name FROM silver_condition
    UNION ALL SELECT 'Procedure', procedure_id, patient_id, encounter_id, file_name FROM silver_procedure
    UNION ALL SELECT 'Immunization', immunization_id, patient_id, encounter_id, file_name FROM silver_immunization
    UNION ALL SELECT 'MedicationRequest', medication_request_id, patient_id, encounter_id, file_name FROM silver_medication_request
    UNION ALL SELECT 'Observation', observation_id, patient_id, encounter_id, file_name FROM silver_observation
    UNION ALL SELECT 'Claim', claim_id, patient_id, encounter_id, file_name FROM silver_claim
) r
WHERE encounter_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM silver_encounter e WHERE e.encounter_id = r.encounter_id)
UNION ALL
SELECT 'Q2', 'Encounter', encounter_id, patient_id, 'patient', patient_id,
       'Patient id not found among this dataset''s patients', file_name
FROM silver_encounter e
WHERE NOT EXISTS (SELECT 1 FROM silver_patient p WHERE p.patient_id = e.patient_id)

-- ---- Q4: required fields missing or unconvertible --------------------------
UNION ALL
SELECT 'Q4', 'Patient', patient_id, patient_id, 'birth_date', NULL,
       'Birth date missing or not a valid date', file_name
FROM silver_patient WHERE birth_date IS NULL
UNION ALL
SELECT 'Q4', 'Encounter', encounter_id, patient_id, 'start_at', NULL,
       'Visit start missing or not a valid timestamp', file_name
FROM silver_encounter WHERE start_at IS NULL
UNION ALL
SELECT 'Q4', 'Observation', observation_id, patient_id, 'value', NULL,
       'Observation has none of the four known value shapes', file_name
FROM silver_observation WHERE value_type IS NULL;
