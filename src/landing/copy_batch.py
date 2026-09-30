"""
Copy ONE batch of FHIR bundles from the public source into our landing volume.

Why batches: the source never changes (all 1,156 files dated 2022-04-15), but real
FHIR feeds arrive a bit at a time. Copying in batches lets Auto Loader practise
"load only what is new" (design.md §4).

The batch plan is a fixed rule, so every run and every machine agrees:
  batch 1  the same 50 patient files as the local sample profile
           (all files sorted by size, every Nth) + the 2 reference files
  batch 2-5  the other 1,104 patient files sorted by name, 276 each

How files move - two routes, because the network differs:
  on Databricks  Spark's binaryFile reader on s3://... (the built-in storage
                 connector, the same one read_files uses). Serverless compute may
                 NOT open ordinary internet connections: the first run with
                 `requests` failed with "Connection reset by peer" (2026-09-30).
  on a laptop    plain HTTPS (normal internet), used only for --plan-only.
Files are written into the volume, which Python sees as a folder (/Volumes/...).
A file already there with the same size is skipped, so a rerun copies nothing twice.

Run as a Databricks job task (see resources/copy_batch.job.yml), or locally:
    python src/landing/copy_batch.py --batch 1 --plan-only     # print the plan, copy nothing
"""

import argparse
import os
import urllib.parse
import xml.etree.ElementTree as ET

import requests

BUCKET = "https://hls-eng-data-public.s3.amazonaws.com/"
PREFIX = "data/synthea/fhir/fhir/"
S3_SOURCE = "s3://hls-eng-data-public/" + PREFIX
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}     # S3's XML namespace
SAMPLE_SIZE = 50                                            # batch 1 patients
LATER_BATCHES = 4                                           # batches 2..5


def get_spark():
    """The Spark session when running on Databricks; None on a laptop."""
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.getOrCreate()
    except Exception:  # noqa: BLE001 - no Spark here: laptop mode
        return None


def list_source_spark(spark):
    """Every source file as (name, size, full s3 path), through Spark.

    binaryFile gives one row per file with path, length and content; selecting
    only path and length lists the folder without reading 2 GB of content.
    Spark writes special letters in paths URL-encoded ("ñ" -> "%C3%B1"), so the
    name is decoded to match the plain names S3 lists.
    """
    rows = (spark.read.format("binaryFile").option("pathGlobFilter", "*.json")
            .load(S3_SOURCE).select("path", "length").collect())
    return [(urllib.parse.unquote(r.path.split("/")[-1]), r.length, r.path) for r in rows]


def list_source():
    """Every source file as (name, size), over HTTPS. Laptop only (--plan-only).
    S3 returns at most 1,000 per page."""
    files, token = [], None
    while True:
        params = {"list-type": "2", "prefix": PREFIX, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        root = ET.fromstring(requests.get(BUCKET, params=params, timeout=60).content)
        files += [(c.find("s:Key", NS).text.split("/")[-1], int(c.find("s:Size", NS).text))
                  for c in root.findall("s:Contents", NS)]
        if root.find("s:IsTruncated", NS).text != "true":
            return files


def is_reference(name):
    """The 2 non-patient files: hospitals and practitioners."""
    return name.startswith(("hospitalInformation", "practitionerInformation"))


def plan_batches(files):
    """{batch number: [file names]} - the fixed rule described at the top."""
    # Batch 1: the SAME selection as scripts/profile/download_sample.py -
    # all files by (size, name), every Nth - so its results can be compared
    # with docs/profiles/sample_50.json.
    by_size = sorted(files, key=lambda f: (f[1], f[0]))
    step = len(by_size) / SAMPLE_SIZE
    sample = [by_size[int(i * step)][0] for i in range(SAMPLE_SIZE)]
    batches = {1: sample + sorted(n for n, _ in files if is_reference(n))}

    rest = sorted(n for n, _ in files if n not in batches[1])
    size = -(-len(rest) // LATER_BATCHES)                   # ceiling division
    for b in range(LATER_BATCHES):
        batches[b + 2] = rest[b * size:(b + 1) * size]
    return batches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--target", help="landing folder, e.g. /Volumes/fhir/landing/raw_bundles")
    ap.add_argument("--plan-only", action="store_true", help="print the plan, copy nothing")
    args = ap.parse_args()

    spark = None if args.plan_only else get_spark()
    if spark is None:
        listed = [(n, s, None) for n, s in list_source()]   # laptop: HTTPS
    else:
        listed = list_source_spark(spark)                   # Databricks: storage connector
    sizes = {n: s for n, s, _ in listed}
    s3_path = {n: p for n, _, p in listed}
    plan = plan_batches([(n, s) for n, s, _ in listed])
    names = plan[args.batch]
    print(f"source files {len(listed)} | batches { {b: len(n) for b, n in plan.items()} } "
          f"| batch {args.batch}: {len(names)} files, {sum(sizes[n] for n in names) / 1e6:.1f} MB")
    if args.plan_only:
        return
    if spark is None:
        raise SystemExit("Copying needs Spark (run as the Databricks job); use --plan-only locally.")

    os.makedirs(args.target, exist_ok=True)
    todo = [n for n in names
            if not (os.path.exists(os.path.join(args.target, n))
                    and os.path.getsize(os.path.join(args.target, n)) == sizes[n])]
    skipped = len(names) - len(todo)                        # already landed: never twice
    copied = 0
    # 20 files at a time: each chunk's bytes pass through the driver's memory,
    # and the largest file is 39.6 MB, so small chunks keep that bounded.
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        rows = (spark.read.format("binaryFile").load([s3_path[n] for n in chunk])
                .select("path", "content").collect())
        for r in rows:
            name = urllib.parse.unquote(r.path.split("/")[-1])
            with open(os.path.join(args.target, name), "wb") as f:
                f.write(r.content)
            copied += 1
    print(f"batch {args.batch}: copied {copied}, already there {skipped}, into {args.target}")
    # Fail loudly if anything is missing - the pipeline must not run on a half batch.
    missing = [n for n in names if not os.path.exists(os.path.join(args.target, n))]
    if missing:
        raise SystemExit(f"{len(missing)} files missing after copy, e.g. {missing[:3]}")


if __name__ == "__main__":
    main()
