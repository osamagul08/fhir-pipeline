# Dataset profile — FHIR R4 synthetic bundles

Every number below comes from a real run. Nothing is estimated.

| | |
|---|---|
| Source | `s3://hls-eng-data-public/data/synthea/fhir/fhir/` (public; the listing's notebook reads it) |
| Profiled | 2026-09-29 |
| Tools | `scripts/profile/download_sample.py`, `scripts/profile/profile_fhir.py` |
| Raw result | `docs/profiles/sample_50.json` |

---

## 1. The whole source (listed, not downloaded)

| | Measured |
|---|---|
| Files | **1,156**: 1,154 patient files + `hospitalInformation1649789466584.json` + `practitionerInformation1649789466584.json` |
| Total size | **2,078.5 MB** (2.08 GB) |
| File size | min 62 KB · median 1,284 KB · max 39,618 KB |
| Last modified | **all 1,156 on 2022-04-15**: a static snapshot, not a feed |
| Download speed from this laptop | 77.6 MB in 7 min 27 s (~170 KB/s) — the full 2 GB would take ~3.5 hours here |

## 2. The 50-file sample

Files sorted by size and every 23rd taken, so the sample runs from small to large
histories: 62 KB to 6,302 KB, 77.6 MB total.

**Limits of this sample, stated up front:**
- The biggest patients (up to 39.6 MB) are **not** in it.
- The two reference files (hospitals, practitioners) are **not** in it.
- 50 of 1,154 patients: shapes and rules are reliable, **counts are not totals**.

### 2.1 Bundles
- All 50 are `transaction` bundles: one patient, with everything that happened to them.
- Records per patient: min **29**, median **381**, max **1,760**. Total **23,613** records.

### 2.2 What is inside (20 resource types)

| Resource | Total | Patients with it | Per patient min / median / max | What it is |
|---|---|---|---|---|
| Observation | 6,257 | 50 | 12 / 87 / 842 | lab results, vital signs, survey scores |
| Claim | 2,993 | 50 | 1 / 39.5 / 353 | a bill sent to the insurer |
| DiagnosticReport | 2,604 | 50 | 2 / 41.5 / 160 | a report grouping results |
| Procedure | 2,393 | 49 | 2 / 34 / 393 | something done to the patient |
| Encounter | 1,713 | 50 | 1 / 28.5 / 117 | a visit |
| DocumentReference | 1,713 | 50 | 1 / 28.5 / 117 | the visit's clinical note |
| ExplanationOfBenefit | 1,713 | 50 | 1 / 28.5 / 117 | what the insurer paid |
| Condition | 1,516 | 49 | 1 / 25 / 94 | a diagnosis |
| MedicationRequest | 1,280 | 44 | 1 / 9 / 236 | a prescription |
| SupplyDelivery | 545 | 23 | 1 / 19 / 118 | supplies given |
| Immunization | 389 | 50 | 1 / 7 / 26 | a vaccine |
| CareTeam, CarePlan | 129 each | 43 | 1 / 3 / 11 | who cares for a condition, and the plan |
| Device | 57 | 30 | 1 / 1 / 9 | e.g. an implant |
| Patient | 50 | 50 | 1 / 1 / 1 | the person |
| Provenance | 50 | 50 | 1 / 1 / 1 | who created the record |
| AllergyIntolerance | 40 | 7 | 1 / 7 / 9 | an allergy |
| ImagingStudy | 16 | 3 | 1 / 1 / 14 | an X-ray or scan |
| Medication, MedicationAdministration | 13 each | 4 | 1 / 2.5 / 7 | a drug given in hospital |

**Pattern:** Encounter, DocumentReference and ExplanationOfBenefit have identical
counts (1,713) at every level — every visit has exactly one note and one insurer
statement. A rule worth checking on the full data.

### 2.3 Medical codes

| Code system | Coded records | Used for |
|---|---|---|
| LOINC | 10,665 | lab tests and observations |
| SNOMED CT | 3,945 | diagnoses, procedures, clinical terms |
| RxNorm | 1,297 | medicines |
| CVX | 389 | vaccines |

### 2.4 Observation values — one field, four types

| Type | Count | Example |
|---|---|---|
| `valueQuantity` (number + unit) | 5,387 | weight in kg |
| `component` (several values) | 474 | blood pressure = systolic + diastolic |
| `valueCodeableConcept` (a code) | 366 | e.g. a coded answer |
| `valueString` (text) | 30 | free text |

Top units: mg/dL (1,010), {score} (692), mmol/L (616), /min (548), % (430),
cm (291), kg (288), kg/m2 (231).

### 2.5 Dates
- Visits, claims, conditions: **1931-05-25 .. 2022-04-12** (Condition to 2022-04-02).
- Observations and procedures start later: **1982-07-19**. Old visits have no results.
- The newest date (2022-04-12) is 3 days before the files' date (2022-04-15).

### 2.6 Patients
- Gender: 28 female, 22 male.
- Born 1913-03-31 .. 2022-03-23 (the youngest is a baby of a few weeks).
- Deceased: 5 of 50.
- **State: all 50 in Massachusetts (MA)**, 41 different cities. No state-level comparison is possible; city-level is.

### 2.7 Links between records

| Kind | Count | Meaning |
|---|---|---|
| `urn:uuid:…` | 85,670 | points to another record in the **same** file |
| conditional, `Type?identifier=…` | 29,105 | points to a record in the **reference files**: Practitioner by NPI (13,500), Location (7,937), Organization (7,668) |
| `#referral`, `#coverage` | 1,713 each | points to a part inside the same record |

- **Broken inside-file links: 0** of 85,670.
- The conditional links resolve only against `hospitalInformation…` and
  `practitionerInformation…`, which are not in this sample: **NOT MEASURED** yet.

### 2.8 Text
- Unreadable characters (U+FFFD): **0**. Double-encoded text: **0**.
- Accented names are stored correctly (e.g. `Ávila`, `Andrés`). They showed as `�`
  only in the Windows terminal — a display problem, not a data problem.

---

## 3. What this means for the pipeline (to decide, not yet built)

1. **Bronze** keeps each bundle as received (one row per file).
2. **Silver** needs one table per resource, flattened, with the patient id on every
   row. Twenty types; the first eight cover 90%+ of records.
3. **Two reference files are dimensions** (doctors, hospitals, locations), not patients.
   Load them separately, and quarantine any link that finds no match.
4. **Observation needs care**: four value types, and blood pressure hides in `component`.
5. **Geography is one state**: city-level only.
6. **Load in batches** to practise incremental loading: the source itself never changes.

---

## 4. Full profile — all 1,156 files, inside Databricks (2026-09-29)

`scripts/profile/profile_databricks.py`, read-only, straight from S3 on the SQL
warehouse. Raw result: `docs/profiles/full_1156.json`. Query time 188.8 s
(files 55.8, resources 4.5, patients 58.8, encounter dates 6.8, links 62.9).

### 4.1 Files and bundles

| | Measured |
|---|---|
| Files | 1,156 = **1,154 patient bundles** (`transaction`) + **2 reference bundles** (`batch`) |
| Reference files | `practitionerInformation…` 4.4 MB, 2,754 records · `hospitalInformation…` 4.2 MB, 2,753 records |
| Records, all files | **631,630** |
| Records per file | min 29 · median 375 · **max 13,192** |

### 4.2 Record types (24)

| Resource | Total | Files with it |
|---|---|---|
| Observation | 162,313 | 1,153 |
| Claim | 90,858 | 1,154 |
| DiagnosticReport | 67,774 | 1,154 |
| Procedure | 61,275 | 1,152 |
| Encounter / DocumentReference / ExplanationOfBenefit | **46,050 each** | 1,154 |
| MedicationRequest | 44,808 | 1,030 |
| Condition | 32,076 | 1,136 |
| Immunization | 9,577 | 1,152 |
| SupplyDelivery | 7,653 | 360 |
| CareTeam / CarePlan | 2,950 each | 977 |
| Practitioner / PractitionerRole / Location | 1,377 each | 1 (reference file) |
| Organization | 1,376 | 1 (reference file) |
| Patient / Provenance | 1,154 each | 1,154 |
| Device | 931 | 542 |
| AllergyIntolerance | 836 | 178 |
| Medication / MedicationAdministration | 583 each | 103 |
| ImagingStudy | 498 | 133 |

The sample's pattern holds on the full data: every Encounter has exactly one
DocumentReference and one ExplanationOfBenefit (46,050 each).

### 4.3 Patients

| Gender | Alive | Deceased |
|---|---|---|
| female | 514 | 68 |
| male | 486 | 86 |
| **total** | **1,000** | **154** |

- **All 1,154 in Massachusetts** (confirmed on the full data).
- Born 1913-03-31 .. 2022-03-23.
- Visits (Encounter `period.start`): **1920-09-06 .. 2022-04-12**, 46,050 visits.

### 4.4 Links to doctors, hospitals, locations

| Target | Links | Found in reference files | **Not found** | Distinct targets asked |
|---|---|---|---|---|
| Practitioner | 372,416 | 372,416 | 0 | 1,207 |
| Organization | 209,940 | 209,940 | 0 | 1,207 |
| Location | 92,100 | 91,854 | **246** | 1,207 |

**246 Location links point to a location that does not exist** in the reference
file. The first real quarantine case. Which records, and why: NOT MEASURED yet.

### 4.5 Found while profiling: one field name, different shapes

`address` is a **list** in Patient but a **single object** in Location. Read with
one merged schema for all record types, Databricks fell back to typing `address`
as STRING, and `address[0].state` failed (`INVALID_EXTRACT_BASE_FIELD_TYPE`).
**Design rule for silver:** give each resource type its own schema; never flatten
all record types through one merged schema.
