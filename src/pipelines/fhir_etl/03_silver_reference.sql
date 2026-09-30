-- ===========================================================================
-- SILVER - reference data: doctors, organisations, locations.
--
-- These come from the 2 reference files (bundle type 'batch'), not from
-- patients. Patient records point to them with a SEARCH, e.g.
--     "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999999995"
-- so each table keeps the identifier that search looks for (`link_key`):
--     Practitioner -> its NPI number
--     Organization, Location -> the Synthea identifier value
--
-- Each type has its OWN columns: one shared schema breaks (Patient.address is a
-- list, Location.address is one object - found while profiling).
-- `r:field::type` reads one field from the VARIANT record and says its type.
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW silver_practitioner (
    CONSTRAINT has_npi EXPECT (npi IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'Doctors from the practitioner reference file. SYNTHETIC.'
AS
SELECT
    resource_id                                              AS practitioner_id,
    -- NPI = the US doctor licence number patient records search by.
    resource:identifier[0]:value::string                     AS npi,
    resource:identifier[0]:system::string                    AS npi_system,
    concat_ws(' ', resource:name[0]:prefix[0]::string,
                   resource:name[0]:given[0]::string,
                   resource:name[0]:family::string)          AS display_name,
    resource:gender::string                                  AS gender,
    resource:address[0]:city::string                         AS city,
    resource:address[0]:state::string                        AS state,
    file_name
FROM silver_entries
WHERE resource_type = 'Practitioner';


CREATE OR REFRESH MATERIALIZED VIEW silver_organization (
    CONSTRAINT has_key EXPECT (link_key IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'Hospitals and clinics from the hospital reference file. SYNTHETIC.'
AS
SELECT
    resource_id                                              AS organization_id,
    resource:identifier[0]:value::string                     AS link_key,
    resource:name::string                                    AS name,
    resource:type[0]:coding[0]:code::string                  AS type_code,     -- e.g. prov
    resource:type[0]:text::string                            AS type_text,     -- e.g. Healthcare Provider
    resource:address[0]:city::string                         AS city,          -- address is a LIST here
    resource:address[0]:state::string                        AS state,
    file_name
FROM silver_entries
WHERE resource_type = 'Organization';


-- FHIR has two KINDS of location (field `mode`):
--   instance  one specific place: this hospital, this address - has an identifier
--   kind      a TYPE of place, e.g. "Patient's Home" - no identifier, no address,
--             because it is not one particular house.
-- The first run's rule "every location has an identifier" was too strict: it
-- stopped on the 'kind' location "Patient's Home" (2026-09-30). Corrected below.
CREATE OR REFRESH MATERIALIZED VIEW silver_location (
    CONSTRAINT has_key_or_is_kind EXPECT (link_key IS NOT NULL OR mode = 'kind') ON VIOLATION FAIL UPDATE
)
COMMENT 'Places where care happens, from the hospital reference file. SYNTHETIC.'
AS
SELECT
    resource_id                                              AS location_id,
    resource:identifier[0]:value::string                     AS link_key,
    resource:mode::string                                    AS mode,            -- instance / kind
    resource:physicalType:coding[0]:display::string          AS physical_type,   -- e.g. House
    COALESCE(resource:name::string, resource:description::string) AS name,      -- "Patient's Home" has only a description
    resource:address:city::string                            AS city,          -- address is ONE object here
    resource:address:state::string                           AS state,
    resource:address:postalCode::string                      AS postal_code,
    resource:position:latitude::double                       AS latitude,
    resource:position:longitude::double                      AS longitude,
    -- The organisation that runs it, by the same kind of identifier.
    resource:managingOrganization:identifier:value::string   AS organization_link_key,
    file_name
FROM silver_entries
WHERE resource_type = 'Location';
