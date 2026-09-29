"""
Download a sample of the FHIR R4 bundles from the public source bucket.

The source: the S3 folder the Marketplace listing's notebook reads,
    s3://hls-eng-data-public/data/synthea/fhir/fhir/   (1,156 files, one per patient)
It is public, so plain HTTPS works: no login, no cost.

Which files: sorted by size, then every Nth file, so the sample runs from the
smallest patient history to the largest. Taking the first 50 by name would give
only names starting with "A" - not representative. Same sample every run.

    python scripts/profile/download_sample.py            # 50 files
    python scripts/profile/download_sample.py --n 1156   # all files (2.08 GB)

Files land in data/raw/ (git-ignored: data never goes into git).
"""

import argparse
import pathlib
import urllib.parse
import xml.etree.ElementTree as ET

import requests

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUCKET = "https://hls-eng-data-public.s3.amazonaws.com/"
PREFIX = "data/synthea/fhir/fhir/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}   # S3's XML namespace


def list_files():
    """Every file in the folder: (key, size in bytes). S3 returns max 1,000 per page."""
    files, token = [], None
    while True:
        params = {"list-type": "2", "prefix": PREFIX, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        root = ET.fromstring(requests.get(BUCKET, params=params, timeout=60).content)
        files += [(c.find("s:Key", NS).text, int(c.find("s:Size", NS).text))
                  for c in root.findall("s:Contents", NS)]
        if root.find("s:IsTruncated", NS).text != "true":
            return files
        token = root.find("s:NextContinuationToken", NS).text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args()

    files = sorted(list_files(), key=lambda f: (f[1], f[0]))     # by size, then name
    step = len(files) / args.n
    sample = [files[int(i * step)] for i in range(args.n)]      # evenly spaced by size

    out = ROOT / "data" / "raw"
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, size in sample:
        target = out / key.split("/")[-1]
        if not (target.exists() and target.stat().st_size == size):   # skip if already there
            # Names can hold characters like "ñ": quote them for the URL.
            r = requests.get(BUCKET + urllib.parse.quote(key), timeout=120)
            r.raise_for_status()
            target.write_bytes(r.content)
        total += size
    print(f"source files: {len(files)} | sampled: {len(sample)} | "
          f"sample size: {total / 1e6:.1f} MB | smallest {sample[0][1] / 1e3:.0f} KB, "
          f"largest {sample[-1][1] / 1e3:.0f} KB | saved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
