-- ===========================================================================
-- CHECK - batch 1 against the profiles. Run by hand after the first pipeline run:
--   python scripts/common/sql_run.py sql/databricks/checks/batch1_vs_profile.sql
--          --param catalog=fhir --param schema=dev_osamagul08_fhir_etl
--
-- Expected counts are GENERATED from docs/profiles/sample_50.json (the 50 patient
-- files) plus the reference-file types in docs/profiles/full_1156.json - never
-- typed by hand. Batch 1 = those exact 52 files, so every count must match.
-- Total expected: 29,120 records.
-- ===========================================================================

WITH expected AS (
    SELECT * FROM VALUES
        ('Observation', 6257),
        ('Claim', 2993),
        ('DiagnosticReport', 2604),
        ('Procedure', 2393),
        ('Encounter', 1713),
        ('DocumentReference', 1713),
        ('ExplanationOfBenefit', 1713),
        ('Condition', 1516),
        ('PractitionerRole', 1377),
        ('Location', 1377),
        ('Practitioner', 1377),
        ('Organization', 1376),
        ('MedicationRequest', 1280),
        ('SupplyDelivery', 545),
        ('Immunization', 389),
        ('CareTeam', 129),
        ('CarePlan', 129),
        ('Device', 57),
        ('Patient', 50),
        ('Provenance', 50),
        ('AllergyIntolerance', 40),
        ('ImagingStudy', 16),
        ('Medication', 13),
        ('MedicationAdministration', 13)
    AS t(resource_type, expected)
),
actual AS (
    SELECT resource_type, COUNT(*) AS actual
    FROM IDENTIFIER(:catalog || '.' || :schema || '.silver_entries')
    GROUP BY resource_type
)
SELECT
    COALESCE(e.resource_type, a.resource_type)      AS resource_type,
    e.expected,
    a.actual,
    CASE WHEN e.expected = a.actual THEN 'MATCH' ELSE 'DIFFERENT' END AS verdict
FROM expected e
FULL OUTER JOIN actual a ON a.resource_type = e.resource_type
ORDER BY e.expected DESC NULLS LAST;
