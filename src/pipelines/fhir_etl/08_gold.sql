-- ===========================================================================
-- GOLD - chart-ready tables for the dashboard. All data is SYNTHETIC (Synthea).
--
-- Gold does the business logic ONCE, in SQL, so Power BI only counts and sums:
--   age bands, visit class names, clinical vs social conditions, one tidy
--   vitals table, the cost of each visit, pipeline statistics.
--
-- "Today" for ages = 2022-04-12, the last visit date in the data (the source
-- files are a snapshot from 2022-04-15). Using the real current date would
-- age every synthetic patient by years.
-- ===========================================================================

-- ---- Patients --------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_dim_patient
COMMENT 'One row per patient with age band. SYNTHETIC.'
AS
SELECT
    patient_id,
    gender,
    birth_date,
    is_deceased,
    CASE WHEN is_deceased THEN 'Deceased' ELSE 'Alive' END                   AS vital_status,
    year(deceased_at)                                                        AS death_year,
    -- Age at death, or at the data's last date for the living.
    floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'),
                         birth_date) / 12)                                   AS age_years,
    CASE
        WHEN floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'), birth_date) / 12) < 18 THEN '0-17'
        WHEN floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'), birth_date) / 12) < 35 THEN '18-34'
        WHEN floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'), birth_date) / 12) < 50 THEN '35-49'
        WHEN floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'), birth_date) / 12) < 65 THEN '50-64'
        WHEN floor(months_between(COALESCE(CAST(deceased_at AS DATE), DATE'2022-04-12'), birth_date) / 12) < 80 THEN '65-79'
        ELSE '80+'
    END                                                                      AS age_band,
    marital_status,
    city
FROM silver_patient;

-- ---- Visits, with their cost ------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_fact_encounter
COMMENT 'One row per visit with class name, duration and institutional claim cost (USD). SYNTHETIC.'
AS
SELECT
    e.encounter_id,
    e.patient_id,
    e.class_code,
    CASE e.class_code
        WHEN 'AMB'  THEN 'Outpatient'  WHEN 'EMER' THEN 'Emergency'
        WHEN 'IMP'  THEN 'Inpatient'   WHEN 'HH'   THEN 'Home health'
        WHEN 'VR'   THEN 'Virtual'     ELSE e.class_code END                 AS visit_class,
    e.type_text                                                              AS visit_type,
    e.reason_text,
    CAST(e.start_at AS DATE)                                                 AS visit_date,
    year(e.start_at)                                                         AS visit_year,
    round((unix_timestamp(e.end_at) - unix_timestamp(e.start_at)) / 60.0, 1) AS duration_minutes,
    e.organization_id,
    e.practitioner_id,
    e.location_id,
    e.location_match,
    -- Institutional claims carry the visit id on their first line item.
    c.total_amount                                                           AS claim_cost_usd
FROM silver_encounter e
LEFT JOIN (SELECT encounter_id, SUM(total_amount) AS total_amount
           FROM silver_claim WHERE claim_type = 'institutional'
           GROUP BY encounter_id) c
       ON c.encounter_id = e.encounter_id;

-- ---- Conditions: clinical vs social -----------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_fact_condition
COMMENT 'One row per diagnosis or finding, split into clinical vs social/other findings. SYNTHETIC.'
AS
SELECT
    c.condition_id,
    c.patient_id,
    -- SNOMED text ends in its kind, e.g. "Stress (finding)". Findings here are
    -- mostly social: employment, stress, isolation, education.
    CASE WHEN c.code_text LIKE '%(finding)' THEN 'Social / other finding'
         ELSE 'Clinical condition' END                                       AS condition_kind,
    regexp_replace(c.code_text, ' \\((disorder|finding|situation)\\)$', '')  AS condition,
    c.clinical_status,
    CAST(c.onset_at AS DATE)                                                 AS onset_date,
    year(c.onset_at)                                                         AS onset_year,
    c.abatement_at IS NULL                                                   AS is_ongoing
FROM silver_condition c;

-- ---- Medicines, procedures, vaccines ----------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_fact_medication
COMMENT 'One row per prescription. SYNTHETIC.'
AS
SELECT medication_request_id, patient_id, encounter_id, status, rx_text AS medicine,
       CAST(authored_at AS DATE) AS prescribed_date, year(authored_at) AS prescribed_year
FROM silver_medication_request;

CREATE OR REFRESH MATERIALIZED VIEW gold_fact_procedure
COMMENT 'One row per procedure. SYNTHETIC.'
AS
SELECT procedure_id, patient_id, encounter_id,
       regexp_replace(code_text, ' \\((procedure|regime/therapy)\\)$', '') AS procedure,
       CAST(performed_start AS DATE) AS performed_date, year(performed_start) AS performed_year
FROM silver_procedure;

CREATE OR REFRESH MATERIALIZED VIEW gold_fact_immunization
COMMENT 'One row per vaccine given. SYNTHETIC.'
AS
SELECT immunization_id, patient_id, encounter_id, vaccine_text AS vaccine,
       CAST(occurred_at AS DATE) AS vaccine_date, year(occurred_at) AS vaccine_year
FROM silver_immunization;

-- ---- Vital signs and labs: one tidy table ----------------------------------
-- Picks the most common numeric measurements by LOINC code and gives each a
-- short name. Blood pressure's two numbers come from the component table.
CREATE OR REFRESH MATERIALIZED VIEW gold_fact_vitals
COMMENT 'One row per numeric vital sign or lab result, named measures. SYNTHETIC.'
AS
WITH picked AS (
    SELECT patient_id, effective_at, code, value_num, unit FROM silver_observation
    WHERE value_type = 'quantity'
    UNION ALL
    SELECT patient_id, effective_at, code, value_num, unit FROM silver_observation_component
    WHERE code IN ('8480-6', '8462-4')
),
names AS (
    SELECT * FROM VALUES
        ('39156-5', 'BMI',                   'Body'),
        ('29463-7', 'Body weight',           'Body'),
        ('8302-2',  'Body height',           'Body'),
        ('8480-6',  'Systolic BP',           'Heart'),
        ('8462-4',  'Diastolic BP',          'Heart'),
        ('8867-4',  'Heart rate',            'Heart'),
        ('9279-1',  'Respiratory rate',      'Heart'),
        ('4548-4',  'HbA1c',                 'Diabetes'),
        ('2339-0',  'Glucose',               'Diabetes'),
        ('2093-3',  'Total cholesterol',     'Cholesterol'),
        ('2085-9',  'HDL cholesterol',       'Cholesterol'),
        ('18262-6', 'LDL cholesterol',       'Cholesterol'),
        ('2571-8',  'Triglycerides',         'Cholesterol'),
        ('718-7',   'Hemoglobin',            'Blood'),
        ('38483-4', 'Creatinine',            'Kidney'),
        ('72514-3', 'Pain score (0-10)',     'Wellbeing'),
        ('55758-7', 'PHQ-2 depression score','Wellbeing'),
        ('70274-6', 'GAD-7 anxiety score',   'Wellbeing')
    AS t(code, measure, measure_group)
)
SELECT p.patient_id, n.measure, n.measure_group, p.value_num AS value, p.unit,
       CAST(p.effective_at AS DATE) AS measured_date, year(p.effective_at) AS measured_year
FROM picked p JOIN names n ON n.code = p.code
WHERE p.value_num IS NOT NULL;

-- ---- Bills ------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_fact_claim
COMMENT 'One row per claim, USD. SYNTHETIC.'
AS
SELECT claim_id, patient_id, encounter_id, claim_type, total_amount AS amount_usd,
       CAST(billable_start AS DATE) AS billed_date, year(billable_start) AS billed_year
FROM silver_claim;

-- ---- Care providers -----------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_dim_organization
COMMENT 'Hospitals and clinics. SYNTHETIC.'
AS
SELECT organization_id, name AS organization, type_text AS organization_type, city
FROM silver_organization;

-- ---- Pipeline statistics (for the data-quality page) --------------------------
CREATE OR REFRESH MATERIALIZED VIEW gold_pipeline_records
COMMENT 'Records per FHIR resource type, as loaded.'
AS
SELECT resource_type, COUNT(*) AS records, COUNT(DISTINCT file_name) AS files
FROM silver_entries GROUP BY resource_type;

CREATE OR REFRESH MATERIALIZED VIEW gold_pipeline_loads
COMMENT 'Each Auto Loader load: when, how many files and records.'
AS
SELECT date_trunc('minute', ingest_ts) AS loaded_at, COUNT(*) AS files,
       SUM(record_count) AS records, round(SUM(file_size) / 1e6, 1) AS megabytes
FROM bronze_bundles GROUP BY date_trunc('minute', ingest_ts);
