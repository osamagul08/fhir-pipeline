"""
Full profile of ALL source bundles, run inside Databricks (read-only).

The laptop profile (profile_fhir.py) covered 50 files. This one reads all 1,156
straight from the public S3 folder on the SQL warehouse - no download - and answers
what the sample could not: true totals, the largest patients, the two reference
files (hospitals, practitioners), and whether every patient-to-doctor/hospital
link finds a match. Nothing is written to any table.

    python scripts/profile/profile_databricks.py

Cost: SQL warehouse time; each query reads the 2 GB again. State it before running.
Writes docs/profiles/full_1156.json.
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "common"))
from sql_run import connect  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "s3://hls-eng-data-public/data/synthea/fhir/fhir/"

# One FHIR bundle per file, spread over many lines -> multiLine. _metadata gives
# each row's file name and size for free.
BUNDLES = f"read_files('{SOURCE}', format => 'json', multiLine => true)"

# One row per record inside a bundle: explode() turns the entry list into rows.
RECORDS = f"""(SELECT _metadata.file_name AS file, e.resource AS r, e.fullUrl AS full_url
              FROM {BUNDLES} LATERAL VIEW explode(entry) AS e)"""

QUERIES = {
    # Every file: bundle type, record count, size. Shows which files are not patients.
    "files": f"""
        SELECT _metadata.file_name AS file, _metadata.file_size AS bytes,
               type AS bundle_type, size(entry) AS records
        FROM {BUNDLES}""",

    # Every record type: how many, in how many files.
    "resources": f"""
        SELECT r.resourceType AS resource_type, COUNT(*) AS total,
               COUNT(DISTINCT file) AS files_with_it
        FROM {RECORDS} GROUP BY r.resourceType ORDER BY total DESC""",

    # Patients: gender, state, alive or not, birth range.
    # r.address is a STRING here, not a list: Patient.address is a list but
    # Location.address is a single object, and with ONE schema for all record
    # types Databricks falls back to text when shapes conflict. get_json_object
    # reads a value out of that JSON text: '$[0].state' = first address's state.
    "patients": f"""
        SELECT r.gender AS gender, get_json_object(r.address, '$[0].state') AS state,
               r.deceasedDateTime IS NOT NULL AS deceased,
               COUNT(*) AS patients, MIN(r.birthDate) AS born_first, MAX(r.birthDate) AS born_last
        FROM {RECORDS} WHERE r.resourceType = 'Patient'
        GROUP BY ALL ORDER BY patients DESC""",

    # Visit dates: first and last.
    "encounter_dates": f"""
        SELECT MIN(get_json_object(to_json(r), '$.period.start')) AS first_visit,
               MAX(get_json_object(to_json(r), '$.period.start')) AS last_visit,
               COUNT(*) AS encounters
        FROM {RECORDS} WHERE r.resourceType = 'Encounter'""",

    # Links to doctors / hospitals / locations. A patient file points to them by a
    # search ("Practitioner?identifier=<system>|<value>"). The reference files
    # hold the targets. Count how many links find a matching target.
    #   regexp_extract_all: pull every such link out of the record's JSON text.
    #   targets: every identifier the reference files offer, in the same text form.
    "conditional_links": f"""
        WITH links AS (
            SELECT explode(regexp_extract_all(to_json(r),
                   '"reference":"((Practitioner|Organization|Location)\\\\?identifier=[^"]+)"', 1)) AS link
            FROM {RECORDS}
        ),
        targets AS (
            -- Shape-proof: record -> JSON text -> its "identifier" -> a list of
            -- (system, value), whatever shape the merged schema guessed.
            SELECT DISTINCT concat(r.resourceType, '?identifier=', i.system, '|', i.value) AS link
            FROM {RECORDS} LATERAL VIEW explode(from_json(
                     get_json_object(to_json(r), '$.identifier'),
                     'array<struct<system:string,value:string>>')) AS i
            WHERE r.resourceType IN ('Practitioner', 'Organization', 'Location')
        )
        SELECT split(l.link, '\\\\?')[0] AS target_type,
               COUNT(*) AS links,
               COUNT(t.link) AS found,
               COUNT(*) - COUNT(t.link) AS not_found,
               COUNT(DISTINCT l.link) AS distinct_targets_asked
        FROM links l LEFT JOIN targets t ON l.link = t.link
        GROUP BY ALL ORDER BY links DESC""",
}


def main():
    partial = ROOT / "docs" / "profiles" / "full_1156.partial.json"
    saved = json.loads(partial.read_text(encoding="utf-8")) if partial.exists() else {}
    result, timings = saved.get("result", {}), saved.get("timings", {})
    con = connect("databricks")
    cur = con.cursor()
    try:
        for name, sql in QUERIES.items():
            if name in result:
                print(f"-- {name}: already saved, skipped")
                continue
            t0 = time.perf_counter()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            timings[name] = round(time.perf_counter() - t0, 1)
            result[name] = rows
            print(f"-- {name}: {len(rows)} rows in {timings[name]} s")
            partial.write_text(json.dumps({"result": result, "timings": timings}, default=str),
                               encoding="utf-8")
    finally:
        cur.close()
        con.close()

    files = result["files"]
    summary = {
        "files": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "records": sum(f["records"] for f in files),
        "bundle_types": {},
        "non_patient_files": [f for f in files if not f["file"].count("_") >= 2],
        "records_per_file": sorted(f["records"] for f in files),
    }
    for f in files:
        summary["bundle_types"][f["bundle_type"]] = summary["bundle_types"].get(f["bundle_type"], 0) + 1
    rpf = summary.pop("records_per_file")
    summary["records_per_file"] = {"min": rpf[0], "median": rpf[len(rpf) // 2], "max": rpf[-1]}
    result["summary"], result["query_seconds"] = summary, timings
    result.pop("files")   # 1,156 rows: summarised above

    out = ROOT / "docs" / "profiles" / "full_1156.json"
    partial.unlink(missing_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("summary", "query_seconds")}, indent=1, default=str))
    for k in ("resources", "patients", "encounter_dates", "conditional_links"):
        print(f"\n== {k}")
        for r in result[k]:
            print("  ", {a: (str(b)[:19] if b is not None else None) for a, b in r.items()})
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
