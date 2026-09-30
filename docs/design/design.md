# Design — FHIR R4 pipeline on Databricks

**Status: agreed 2026-09-30 (decisions in §10). Nothing here is built yet.**
Every number comes from the profiles (`docs/design/dataset_profile.md`); anything
not yet measured says so. Decisions still open are marked **DECIDE**.

---

## 1. Goal in one line

Turn 1,156 nested FHIR JSON files (631,630 records) into clean, linked,
analytics-ready tables on Databricks — with nothing silently dropped, every
number verified, and every step explainable.

**What we learn by building it:** loading JSON, flattening nested data, one table
per record type, checking links between records, medical code systems, incremental
loads, and the gates/quarantine/automation already proven on BRFSS.

---

## 2. The shape of the problem

```
 1 file = 1 patient's whole history (a "bundle")          2 reference files
 ┌──────────────────────────────────────────┐            ┌─────────────────────┐
 │ Patient                                   │            │ Practitioner (1,377)│
 │ Encounter ──► Condition, Observation,     │  links by  │ Organization (1,376)│
 │               Procedure, Claim, EOB, note │ ─────────► │ Location     (1,377)│
 │ MedicationRequest, Immunization, ...      │  identifier└─────────────────────┘
 └──────────────────────────────────────────┘
   links inside the file:   urn:uuid:…          (85,670 in the sample, 0 broken)
   links to reference files: Type?identifier=…  (674,456 in total, 246 not found)
```

Three things make this harder than BRFSS:
1. **Nesting.** One row per file holds hundreds of records inside a list.
2. **Different shapes per record type.** `address` is a list in Patient but one
   object in Location; one shared schema breaks (found while profiling).
3. **Links.** Records point to other records; a link can point to nothing.

---

## 3. Layers

```
S3 (public, static)
   │  copy job, in batches (§4)
   ▼
landing volume ── raw JSON files, exactly as downloaded
   │  Auto Loader: only new files
   ▼
BRONZE   bronze_bundles         1 row per FILE       raw text + parsed VARIANT
   │  variant_explode(entry)
   ▼
SILVER   silver_entries         1 row per RECORD     631,630 rows, record kept whole
   │  one query per record type, each with its own columns
   ▼
SILVER   silver_patient, silver_encounter, silver_condition, silver_observation, …
         silver_practitioner, silver_organization, silver_location  (reference data)
         quarantine                                   every broken rule, with a reason
   │
   ▼
GOLD     dim_patient, fact_encounter, fact_condition, fact_observation_vitals, fact_claim_cost
```

### 3.1 Bronze — `bronze_bundles` (one row per file)

| Column | From | Why |
|---|---|---|
| `file_name`, `file_size`, `ingest_ts`, `batch_id` | file metadata | trace every row to its file and load |
| `raw_text` | the file, unchanged (`wholetext`) | the evidence of what arrived |
| `bundle` | `parse_json(raw_text)`, type **VARIANT** | queryable without one fixed schema |
| `bundle_type`, `record_count` | from `bundle` | quick checks: `transaction`/`batch`, size |

**Why VARIANT (new concept):** a column type that stores JSON of *any* shape and
still lets SQL read fields (`bundle:entry`, `resource:gender::string`). It avoids
the problem profiling hit: no single guessed schema for 24 record types, so no
`address`-becomes-text failure.

**Tested 2026-09-30 on the SQL warehouse**, smallest file (62 KB), read with
`format => 'text', wholeText => true`:
- `parse_json` + field access: `Bundle`, `transaction`, 29 records, 62,245 characters.
- `variant_explode(bundle:entry)`: 29 rows (20 Observation, 2 DiagnosticReport,
  1 each of 7 more types) - equal to the profile's count for this file.
- `address[0]:city` on the Patient: `Millis`, state `MA` - no shape conflict.
- One fix needed: a field taken from a VARIANT is still a VARIANT; `array_size`
  needs `CAST(bundle:entry AS ARRAY<VARIANT>)`.
Not yet tested inside the Lakeflow pipeline itself (first build step).

A file that is not valid JSON does not stop the load: it is kept in bronze with
`bundle = NULL` and goes to quarantine (rule Q1).

### 3.2 Silver — `silver_entries` (one row per record)

`variant_explode(bundle:entry)` turns each file's list into rows.

| Column | Meaning |
|---|---|
| `file_name`, `batch_id` | where it came from |
| `patient_id` | the Patient in the same bundle (NULL for the 2 reference files) |
| `full_url` | the record's address inside the bundle (`urn:uuid:…`) |
| `resource_type`, `resource_id` | e.g. `Encounter`, its id |
| `resource` | the whole record, VARIANT — nothing lost |

Expected: **631,630 rows** (full profile). That count is a gate (§6).

### 3.3 Silver — one flat table per record type

Each reads `silver_entries` for one `resource_type` and pulls **its own** fields,
so each type has its own schema. First wave (covers most records):

| Table | Records | Key columns (first cut) |
|---|---|---|
| `silver_patient` | 1,154 | patient_id, gender, birth_date, deceased_date, city, state |
| `silver_encounter` | 46,050 | encounter_id, patient_id, class, type code + text, start, end, practitioner_npi, organization_id, location_id |
| `silver_condition` | 32,076 | condition_id, patient_id, encounter_id, SNOMED code + text, onset, abatement |
| `silver_observation` | 162,313 | observation_id, patient_id, encounter_id, LOINC code + text, effective, **value_type, value_num, unit, value_code, value_text** |
| `silver_observation_component` | NOT MEASURED (474 in the sample) | parent observation_id, LOINC code, value_num, unit — e.g. systolic / diastolic |
| `silver_medication_request` | 44,808 | id, patient_id, encounter_id, RxNorm code + text, status, authored_on |
| `silver_claim` | 90,858 | claim_id, patient_id, encounter_id, type, total amount, billable period |
| `silver_procedure` | 61,275 | id, patient_id, encounter_id, SNOMED code + text, performed |
| `silver_immunization` | 9,577 | id, patient_id, encounter_id, CVX code + text, date |
| `silver_practitioner` / `_organization` / `_location` | 1,377 / 1,376 / 1,377 | id, identifier system + value (NPI), name, address |

**Observation needs special care:** its value comes in four shapes (sample:
number 5,387, components 474, code 366, text 30). One row keeps whichever exists
plus `value_type`; blood pressure's two numbers go to the component table.

Later waves (smaller types): DiagnosticReport, ExplanationOfBenefit,
DocumentReference, CarePlan, CareTeam, AllergyIntolerance, Device, SupplyDelivery,
ImagingStudy, Medication(Administration), Provenance. They stay available in
`silver_entries` until then — nothing is lost by building in waves.

### 3.4 Links

| Link kind | Example | Resolved how |
|---|---|---|
| Inside the file | `"urn:uuid:3b2f…"` | match `full_url` in the same file |
| To reference data | `"Practitioner?identifier=http://hl7.org/fhir/sid/us-npi\|9999…"` | match `silver_practitioner` identifier |

Each silver table stores the resolved id **and** the original link text, so a
failed match can be reviewed.

---

## 4. Loading in batches (the source never changes)

All files are dated 2022-04-15 and never updated (D3). To practise incremental
loading, a copy job moves files from S3 into our landing volume **in batches**;
Auto Loader then loads only what is new.

| Batch | Files | Purpose |
|---|---|---|
| 1 | the same **50** as the local sample + the 2 reference files | small start; results must match `sample_50.json` exactly |
| 2..5 | the remaining 1,104 patients in **4 batches of 276** | practise incremental runs; measure time per batch |

Every batch ends with the gates (§6). A batch that fails a gate publishes nothing.

---

## 5. Quality rules and quarantine

Same principle as BRFSS: nothing silently dropped, nothing silently fixed. One
`quarantine` table: `file_name, resource_type, resource_id, rule_id, detail,
raw_value, found_at`.

| Rule | Checks | Known count | Action |
|---|---|---|---|
| **Q1** | File is valid JSON and a Bundle | 0 failures in 1,156 so far | keep in bronze, quarantine the file |
| **Q2** | Inside-file link points to a record in the same bundle | 0 broken in the sample; full: NOT MEASURED | keep the record, link = NULL, quarantine the link |
| **Q3** | Reference link finds a Practitioner / Organization / Location | **246 Location links not found** | keep the record, id = NULL, quarantine the link with the original text |
| **Q4** | Required field present (Patient: birth_date, gender; Encounter: start; Observation: code) | NOT MEASURED | keep the row, flag, quarantine |
| **Q5** | Record id unique within its type | NOT MEASURED | quarantine duplicates |
| **Q6** | Record type is one we know (24 so far) | 24 known | stays in `silver_entries`, flagged |

**Corrections** (the BRFSS "C" rules): none needed so far — no encoding problems
(0 broken characters), and dates are standard ISO text converted to timestamps.
If a conversion fails, the value goes to quarantine, never guessed.

---

## 6. Gates — the run stops if these fail

Expected values come from the profiles, never typed by hand (like the BRFSS
source manifest).

| Gate | Rule |
|---|---|
| Files | files in bronze = files copied to landing |
| Records | rows in `silver_entries` = sum of `size(entry)` in bronze (631,630 when all loaded) |
| Types | count per resource type = the profile's count, for the batches loaded |
| One patient per bundle | every patient bundle has exactly 1 Patient |
| Visit pattern | Encounter = DocumentReference = ExplanationOfBenefit (46,050 each in full) |
| Links add up | found + quarantined = all links, for each target type |
| Nothing lost | every silver_entries row is in a typed table, or in quarantine, or in a "later wave" type |

---

## 7. Gold — first ideas (all labelled SYNTHETIC)

| Table | One row per | Answers |
|---|---|---|
| `dim_patient` | patient | age band, gender, alive/deceased, city |
| `fact_encounter` | visit | visits by type and year; cost from ExplanationOfBenefit |
| `fact_condition` | patient × condition | most common conditions by age and gender; which occur together |
| `fact_observation_vitals` | patient × vital × date | BMI, blood pressure, glucose trends over life |
| `fact_claim_cost` | claim | cost by visit type, condition, year |

Final list decided after silver exists and its counts are verified.

---

## 8. Where it lives and how it runs

Re-use the BRFSS patterns that already work:

| | Choice |
|---|---|
| Catalog / schemas | catalog **`fhir`**: schema `landing` (volume `raw_bundles`) and schema `fhir_etl` (all tables), like `prod_catalog.brfss_etl` |
| Code | Databricks asset bundle, `dev` and `prod` targets |
| Transform | Lakeflow ETL pipeline: streaming bronze (Auto Loader), materialized views for silver and gold, expectations as gates |
| Orchestration | Job: copy next batch → run pipeline → checks |
| Checks by hand | `sql/databricks/checks/`, run with `scripts/common/sql_run.py` |
| Costs | stated before every run; Databricks cost NOT MEASURED on this trial |

---

## 9. Out of scope for now

- Snowflake (D1). OMOP mapping (the listing notebook's last step): later, optional.
- Comparing our flattening with dbignite: later, as a learning exercise.
- Power BI: after gold, with `docs/learning/powerbi_prompt.md`.
- Clinical notes inside DocumentReference: stored, not analysed.

---

## 10. Decisions (agreed 2026-09-30)

1. **Names:** catalog `fhir`; schemas `landing` and `fhir_etl`.
2. **VARIANT in bronze:** yes, after a 1-file test confirms it works.
3. **Batches:** 50 sample files + 2 reference files first, then 4 × 276.
4. **First-wave silver tables:** all eight in §3.3, plus the three reference tables.

## 11. Build order (after this is agreed)

1. 1-file VARIANT test (tiny cost).
2. Landing volume + copy job, batch 1 (50 + 2 files).
3. Bronze + `silver_entries`; gates; results must equal `sample_50.json`.
4. Reference tables + first typed tables; link checks; quarantine.
5. Remaining batches, one at a time, gates each time.
6. Gold, then Power BI.
