# Walkthrough — the FHIR pipeline, explained end to end

A learning guide to this project: what was built, why, and what to understand.
Simple English. Every number here comes from a real run (see
`docs/report/scope_and_gaps.md`, D1–D13). The data is **synthetic**.

---

## 1. The whole thing in one picture

```
 Databricks' public S3 bucket (1,156 JSON files, 2.08 GB, never updated)
        │   copy_batch job  — 5 batches (52 + 4 × 276 files)
        ▼
 fhir.<landing>.raw_bundles   (a VOLUME: a governed folder of files)
        │   ETL pipeline fhir_etl — Auto Loader reads only NEW files
        ▼
 BRONZE  bronze_bundles            1 row per FILE      raw text + VARIANT
        ▼
 SILVER  silver_entries            1 row per RECORD    631,630 rows
        ▼
 SILVER  11 typed tables           one per record type, own columns
         (patient, encounter, condition, observation + components, procedure,
          immunization, medication_request, claim, practitioner, organization, location)
         quarantine                every broken rule, with a reason
        ▼
 GOLD    11 chart-ready tables     age bands, visit classes, clinical vs social, vitals, costs
        ▼
 GATE    reconciliation            stops the run if anything is lost, duplicated or broken
        ▼
 Power BI  fhir_dashboard.pbip     7 pages, 55 visuals, generated from code
```

**Real-life picture:** the post room of a hospital.
- *Landing* = the in-tray. Letters (files) arrive and are never altered.
- *Bronze* = a photocopy of each letter, filed as received.
- *Silver* = each letter opened and every document inside sorted into the right
  cabinet (patients, visits, prescriptions…).
- *Quarantine* = a tray of documents with problems, each with a note saying why.
- *Gold* = the summaries management reads.
- *The gate* = the supervisor who refuses to send the summary if anything is missing.

---

## 2. What to read first (in this order)

| # | File | Why | Time |
|---|---|---|---|
| 1 | `docs/design/design.md` | The plan and the reasons behind every layer | 15 min |
| 2 | `docs/report/scope_and_gaps.md` | Every decision and finding, D1–D13, with evidence | 20 min |
| 3 | `docs/design/dataset_profile.md` | What is inside the data (section 4 = full data) | 10 min |
| 4 | `src/pipelines/fhir_etl/01_bronze_bundles.sql` | How files become rows; VARIANT | 5 min |
| 5 | `src/pipelines/fhir_etl/02_silver_entries.sql` | How one row per file becomes one row per record | 5 min |
| 6 | `src/pipelines/fhir_etl/04_silver_patient_encounter.sql` | Links, `LEFT JOIN`, the two-way location match | 10 min |
| 7 | `src/pipelines/fhir_etl/07_quarantine.sql` | How problems are recorded, never dropped | 5 min |
| 8 | `src/pipelines/fhir_etl/09_reconciliation.sql` | The gate: what stops a run | 5 min |
| 9 | `src/landing/copy_batch.py` | Batches, and the serverless-internet lesson | 5 min |
| 10 | the four YAML files (section 3 below) | How Databricks is told what to create | 10 min |

**Must understand** (they come back in every data project): Auto Loader's memory
(§6.1), VARIANT (§6.2), one schema per record type (§5.3), quarantine vs drop (§7),
gates that stop a run (§7), and "prove, don't assume" (§8).

---

## 3. The YAML files, one by one

YAML is just a structured text format: `key: value`, and indentation shows what
belongs to what. Databricks reads these files and creates the real objects.

### 3.1 `databricks.yml` — the bundle (the master file)

| Part | What it says | Why it matters |
|---|---|---|
| `bundle: name: fhir_pipeline` | the project's name | groups everything this bundle creates |
| `include: resources/*.yml` | "also read these files" | one resource per file = easy to find |
| `sync: exclude:` docs, data, scripts | what NOT to upload | only code goes to Databricks, not local data |
| `variables: catalog: default: fhir` | a setting used everywhere as `${var.catalog}` | change the catalog in ONE place |
| `warehouse_id: lookup: warehouse: "Serverless Starter Warehouse"` | find the warehouse by name | no long id hard-coded |
| `targets: dev: mode: development` | dev: names get a `dev_<you>_` prefix, schedules paused | dev can never touch prod or run by surprise |
| `targets: prod: mode: production` + `root_path` | prod code in a folder only the deployer can write | lesson from BRFSS: `/Workspace/Shared` = anyone can edit prod |

**Try:** `databricks bundle validate --strict --target dev --profile trial` checks it
without changing anything.

### 3.2 `resources/fhir.schemas.yml` — where things live

Creates, inside catalog `fhir`: schema `landing`, schema `fhir_etl`, and the volume
`raw_bundles` (in `landing`).

| Line | Meaning |
|---|---|
| `schemas: landing_schema:` | `landing_schema` is the bundle's own **handle** (must be unique); `name: landing` is what Databricks shows |
| `catalog_name: ${var.catalog}` | uses the variable from `databricks.yml` |
| `volumes: raw_bundles: volume_type: MANAGED` | a folder whose storage Databricks manages; path `/Volumes/fhir/<schema>/raw_bundles` |
| `schema_name: ${resources.schemas.landing_schema.name}` | a **reference** to another resource: in dev it becomes `dev_osamagul08_landing` automatically |

### 3.3 `resources/copy_batch.job.yml` — the copy job

| Part | Meaning |
|---|---|
| `parameters: - name: batch, default: "1"` | a value you can change per run: `--params batch=2` |
| `max_concurrent_runs: 1` | two copies at once could race on the same files |
| `timeout_seconds: 3600` | a stuck run stops after 1 hour |
| `email_notifications: on_failure` | you are emailed if it fails |
| `spark_python_task: python_file: ../src/landing/copy_batch.py` | the code it runs |
| `parameters: ["--batch", "{{job.parameters.batch}}", "--target", "/Volumes/..."]` | passed to the script like command-line arguments |
| `environments: … client: "2", dependencies: [requests]` | serverless Python environment; no cluster to manage |

### 3.4 `resources/fhir_etl.pipeline.yml` — the ETL pipeline

| Part | Meaning |
|---|---|
| `catalog:` / `schema: ${resources.schemas.etl_schema.name}` | where every table is published |
| `serverless: true` | Databricks provides and removes the compute |
| `continuous: false` | **triggered**: runs, loads what is new, stops, stops billing |
| `configuration: landing_path: /Volumes/...` | a value the SQL reads as `${landing_path}` |
| `libraries: glob: include: ../src/pipelines/fhir_etl/**` | every SQL file in that folder is part of the pipeline |
| `notifications: on-update-failure` | email on failure |

**Key idea:** the pipeline works out the ORDER of tables itself from the `FROM`
lines in the SQL. The numbers in file names (01, 02…) are for people only.

---

## 4. How the profiling was done (3 levels)

Profiling = measuring the data BEFORE building anything, so the design fits the
data and every later count has something to be checked against.

| Level | How | Cost | What it gave |
|---|---|---|---|
| **1. List the source** | ask S3 for file names, sizes, dates (no download) | free | 1,156 files, 2.08 GB, **all dated 2022-04-15 → static** |
| **2. Sample on the laptop** | download 50 files spread by size; Python script `profile_fhir.py` reads every record | free (7.5 min download, 1.5 s profile) | the SHAPE: 20 types, codes, value shapes, links, dates |
| **3. Full data in Databricks** | SQL over all 1,156 files straight from S3 (`profile_databricks.py`) | ~1 DBU | true TOTALS: 631,630 records, 24 types, patients, links |

**Why a sample first?** Cheap and fast to learn the shape; the full run then only
needs the totals. **Why keep both?** Batch 1 = those exact 50 files, so the
pipeline's first run could be checked against the laptop's numbers (it matched
24 of 24 types).

### 4.1 The most important findings

| Finding | Why it matters |
|---|---|
| **Static source** (all files 2022-04-15) | no real feed → batches simulate arrivals (D3) |
| **1,154 patient files + 2 reference files** (hospitals, doctors) | two kinds of bundle: `transaction` and `batch` |
| **631,630 records, 24 types**; Observation 162,313 is the largest | sizes each table; Observation needs most care |
| **Nested JSON**: one file = one patient's whole history | the core job is unpacking (explode) |
| **Same field, different shape** (`address`: list in Patient, object in Location) | one shared schema breaks → one schema per type, VARIANT in bronze |
| **Links**: `urn:uuid:` inside a file, `Type?identifier=…` to reference files | resolve with joins; unmatched → quarantine |
| **Observation value in 4 shapes** (number, components, code, text) | one column set per shape; blood pressure has 2 numbers |
| **Every visit = 1 note + 1 insurer statement** (46,050 each) | a free rule for the gate |
| **All patients in Massachusetts** | no state maps; city level only |
| **80% of "conditions" are social findings** (employment, stress…) | split clinical vs social in gold |
| **"Kind" locations** ("Patient's Home") have no identifier | explains home-visit links (§7) |
| **Encoding problem → false alarm**: the terminal, not the data | check the bytes, not the screen |

---

## 5. The layers, and the idea behind each

### 5.1 Landing — copy in batches
`copy_batch.py` copies one batch into the volume. Batch 1 = the 50 profiled files
+ 2 reference files; batches 2–5 = 276 each. It skips files already there and
fails loudly if any file is missing.

### 5.2 Bronze — one row per file
`read_files(..., format => 'text', wholeText => true)`: the whole file as ONE
text value. Kept twice: `raw_text` (the evidence) and `bundle` = `try_parse_json(raw_text)`
as **VARIANT**. `try_` = a bad file becomes NULL and is counted, never crashes the load.

### 5.3 Silver — unpack, then one table per type
- `silver_entries`: `variant_explode(bundle:entry)` → one row per record, record kept whole.
- Typed tables: `resource:gender::string` = "read field `gender`, treat it as text".
  Each type reads only its own fields → no shape conflict.
- `replace(link, 'urn:uuid:', '')` turns a link into an id (verified on 29,120 records).
- `split_part(link, '|', 2)` takes the key out of `Practitioner?identifier=…|9999…`.
- `try_cast(x AS TIMESTAMP)`: a date that will not convert becomes NULL, counted.

### 5.4 Gold — the business logic, once
Age bands, visit class names (AMB → Outpatient), clinical vs social, 18 named
vital measures, cost per visit, pipeline statistics. Power BI then only counts,
sums and averages.

---

## 6. Two concepts to really understand

### 6.1 Auto Loader's memory
It remembers loaded file **paths**, not contents.

| You do | Result |
|---|---|
| add a new file | loaded next run |
| **rename** a file | loaded AGAIN → duplicates (now caught by the gate) |
| **overwrite** a file | ignored → the change is missed |
| delete a file | its rows stay in bronze |
| redeploy | nothing reloads |
| full refresh | everything reloaded from what is in the folder now |

Proof it works: batches 1–5 each loaded once (`gold_pipeline_loads` = 5 rows),
pipeline time ~2 min per batch whatever the total.

### 6.2 VARIANT
A column that holds JSON of any shape and still lets SQL read inside it.
A field taken out of it is still a VARIANT: `CAST(bundle:entry AS ARRAY<VARIANT>)`
before counting. `schema_of_variant_agg(x)` shows the shapes present.

---

## 7. Quality: quarantine and the gate

**Quarantine** = record the problem, keep the record. Rules: Q2 (link inside the
file finds nothing), Q3 (link to reference data finds nothing), Q4 (required field
missing). Final count on all data: **0** (plus the home-visit case, below).

**The gate** (`reconciliation`) stops a run when: records in bronze ≠ rows in
silver; a file is not a Bundle; a patient file has ≠ 1 patient; visits ≠ notes ≠
insurer statements; a record id repeats; a typed table lost rows.

**The home-visit story** (a good example of the whole method):
1. Rule "every location has an identifier" stopped a run.
2. The record was "Patient's Home", a FHIR `kind` location: a TYPE of place with
   nothing to identify. The **rule** was wrong, not the data. Fixed.
3. 3 visit links then failed to match … and pointed at that same location's **id**.
4. Fix: match on identifier, then on id, and SHOW which (`location_match`).
   Full data: 45,927 by identifier, 123 by id, 0 unmatched.

---

## 8. Mistakes made, and what each taught

| Mistake | Lesson |
|---|---|
| Profile read all record types through one schema → `address` became text | one schema per record type |
| Profile script saved only at the end → a failure lost 3 min of results | save after every step |
| Copy job used `requests` → serverless blocked the internet | use Databricks' storage connector (Spark) |
| `read_files` without `multiLine` failed | JSON Lines vs multi-line JSON |
| `array_size(bundle:entry)` failed | a field from VARIANT is still VARIANT → cast |
| Location rule too strict | a failing rule can mean the RULE is wrong |
| A cross-check query gave 126 million links (truth: 92,100) | sanity-check a total against a known number; discard, don't explain away |
| Told you there was an encoding problem | it was the terminal; check the real bytes |

---

## 9. Test yourself

1. Why does bronze read files as `text` + `wholeText` instead of the JSON reader?
2. What does Auto Loader do if you rename a file that was already loaded?
3. Why is `information_schema` in every catalog, even an empty one?
4. What is the difference between `urn:uuid:…` and `Practitioner?identifier=…` links?
5. Why can Power BI sum visit costs here, but could not sum BRFSS percentages?
6. When would you read S3 directly instead of copying to a landing volume?
7. Why did the SQL warehouse read the public bucket when the Python job could not?
8. Why are 80% of "conditions" split out as social findings?
9. Which file tells Databricks the pipeline's SQL folder, and which line?
10. What is the difference between `mode: development` and `mode: production`?

Answers are in this document and in `docs/learning/learning_log.md`.

---

## 10. What is next

1. **Review and commit** everything since the design doc.
2. Type the remaining record types (wave 2) — also answers the last 110 Location links.
3. Automation: one Job — copy → pipeline → checks; prod deploy.
4. Runbook and limitations log, like BRFSS.
