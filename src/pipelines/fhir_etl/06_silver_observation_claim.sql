-- ===========================================================================
-- SILVER - measurements (Observation) and bills (Claim).
--
-- Observation is the tricky one: its VALUE comes in four shapes (sample):
--   valueQuantity         a number + unit       e.g. 72.4 kg            (5,387)
--   component             several values        e.g. blood pressure     (474)
--   valueCodeableConcept  a code                 e.g. a coded answer     (366)
--   valueString           text                                         (30)
-- silver_observation keeps whichever exists plus `value_type`; the several
-- values of a `component` go to silver_observation_component (one row each).
-- ===========================================================================

CREATE OR REFRESH MATERIALIZED VIEW silver_observation (
    -- Warn: every observation should have exactly one known value shape.
    CONSTRAINT has_value_type EXPECT (value_type IS NOT NULL)
)
COMMENT 'One row per measurement or test result. SYNTHETIC.'
AS
SELECT
    resource_id                                                    AS observation_id,
    replace(resource:subject:reference::string, 'urn:uuid:', '')   AS patient_id,
    replace(resource:encounter:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:status::string                                        AS status,
    resource:category[0]:coding[0]:code::string                    AS category,       -- vital-signs, laboratory, survey ...
    resource:code:coding[0]:system::string                         AS code_system,    -- LOINC
    resource:code:coding[0]:code::string                           AS code,
    resource:code:text::string                                     AS code_text,
    try_cast(resource:effectiveDateTime::string AS TIMESTAMP)      AS effective_at,
    -- Which of the four shapes this one has.
    CASE
        WHEN resource:valueQuantity        IS NOT NULL THEN 'quantity'
        WHEN resource:component            IS NOT NULL THEN 'component'
        WHEN resource:valueCodeableConcept IS NOT NULL THEN 'code'
        WHEN resource:valueString          IS NOT NULL THEN 'text'
    END                                                            AS value_type,
    resource:valueQuantity:value::double                           AS value_num,
    resource:valueQuantity:unit::string                            AS unit,
    resource:valueCodeableConcept:coding[0]:code::string           AS value_code,
    resource:valueCodeableConcept:text::string                     AS value_code_text,
    resource:valueString::string                                   AS value_text,
    array_size(CAST(resource:component AS ARRAY<VARIANT>))         AS component_count,
    file_name
FROM silver_entries
WHERE resource_type = 'Observation';


CREATE OR REFRESH MATERIALIZED VIEW silver_observation_component (
    CONSTRAINT has_code EXPECT (code IS NOT NULL)
)
COMMENT 'One row per part of a multi-part observation, e.g. systolic and diastolic blood pressure. SYNTHETIC.'
AS
SELECT
    s.resource_id                                                    AS observation_id,
    replace(s.resource:subject:reference::string, 'urn:uuid:', '')   AS patient_id,
    c.pos                                                            AS component_index,
    c.value:code:coding[0]:code::string                              AS code,      -- LOINC, e.g. 8480-6 systolic
    c.value:code:text::string                                        AS code_text,
    c.value:valueQuantity:value::double                              AS value_num,
    c.value:valueQuantity:unit::string                               AS unit,
    c.value:valueCodeableConcept:coding[0]:code::string              AS value_code,
    c.value:valueString::string                                      AS value_text,
    try_cast(s.resource:effectiveDateTime::string AS TIMESTAMP)      AS effective_at
FROM silver_entries s,
     LATERAL variant_explode(s.resource:component) AS c
WHERE s.resource_type = 'Observation';


CREATE OR REFRESH MATERIALIZED VIEW silver_claim (
    CONSTRAINT has_total EXPECT (total_amount IS NOT NULL)
)
COMMENT 'One row per bill sent to the insurer. Amounts in USD. SYNTHETIC.'
AS
SELECT
    resource_id                                                      AS claim_id,
    replace(resource:patient:reference::string, 'urn:uuid:', '')     AS patient_id,
    -- The visit the bill is for sits on the first line item.
    replace(resource:item[0]:encounter[0]:reference::string, 'urn:uuid:', '') AS encounter_id,
    resource:status::string                                          AS status,
    resource:type:coding[0]:code::string                             AS claim_type,   -- institutional / pharmacy
    resource:use::string                                             AS use,
    try_cast(resource:billablePeriod:start::string AS TIMESTAMP)     AS billable_start,
    try_cast(resource:billablePeriod:end::string AS TIMESTAMP)       AS billable_end,
    resource:total:value::double                                     AS total_amount,
    resource:total:currency::string                                  AS currency,
    array_size(CAST(resource:item AS ARRAY<VARIANT>))                AS line_items,
    resource:provider:reference::string                              AS provider_link,
    file_name
FROM silver_entries
WHERE resource_type = 'Claim';
