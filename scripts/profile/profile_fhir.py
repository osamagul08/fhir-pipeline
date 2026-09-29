"""
Profile FHIR R4 bundles: what is inside, how full, how linked, how clean.

Reads every data/raw/*.json (one patient bundle each) and measures:
  1. bundles       type, entries per bundle, file size
  2. resources     how many of each type, in total and per patient
  3. fields        for each resource type, how often each top-level field is filled
  4. codes         which code systems are used (SNOMED, LOINC...), the top codes
  5. values        Observation value types (number, code, text, components), units
  6. dates         earliest and latest date per resource type
  7. patients      gender, birth years, deceased, states, cities
  8. references    links between records: do they point to something that exists?
  9. text         broken characters (U+FFFD) or double-encoded text (e.g. "Ã±")

Numbers only from the files: nothing estimated. Writes docs/profiles/<name>.json
and prints a summary.

    python scripts/profile/profile_fhir.py                     # data/raw -> sample
    python scripts/profile/profile_fhir.py --name full_1156
"""

import argparse
import json
import pathlib
import re
import statistics
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Where each resource type keeps its main date. FHIR uses different names.
DATE_FIELDS = ["effectiveDateTime", "recordedDate", "authoredOn", "onsetDateTime",
               "performedDateTime", "occurrenceDateTime", "issued", "date", "created"]
PERIOD_FIELDS = ["period", "billablePeriod", "performedPeriod", "effectivePeriod"]

CODE_SYSTEMS = {                       # plain-English names for the systems we expect
    "http://snomed.info/sct": "SNOMED CT (clinical terms)",
    "http://loinc.org": "LOINC (lab tests, observations)",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm (medicines)",
    "http://hl7.org/fhir/sid/cvx": "CVX (vaccines)",
}


def first_date(res):
    """The resource's main date, whatever FHIR calls it. None if it has none."""
    for f in DATE_FIELDS:
        if isinstance(res.get(f), str):
            return res[f][:10]
    for f in PERIOD_FIELDS:
        if isinstance(res.get(f), dict) and res[f].get("start"):
            return res[f]["start"][:10]
    return None


def walk_refs(node, found):
    """Collect every {"reference": "..."} anywhere inside a resource (any depth)."""
    if isinstance(node, dict):
        if isinstance(node.get("reference"), str):
            found.append(node["reference"])
        for v in node.values():
            walk_refs(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_refs(v, found)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--name", default="sample_50")
    args = ap.parse_args()
    files = sorted(pathlib.Path(args.dir).glob("*.json"))

    bundle_types, entries_per, sizes = Counter(), [], []
    type_total, type_per_patient = Counter(), defaultdict(list)
    field_filled = defaultdict(Counter)          # resource type -> field -> count
    systems = defaultdict(Counter)                # resource type -> code system -> count
    top_codes = defaultdict(Counter)              # resource type -> (system, code, display)
    value_types, units = Counter(), Counter()
    dates = defaultdict(list)
    genders, births, states, cities, deceased = Counter(), [], Counter(), Counter(), 0
    ref_kinds, broken = Counter(), Counter()
    bad_text, mojibake = 0, 0

    for path in files:
        raw = path.read_bytes()
        sizes.append(len(raw))
        text = raw.decode("utf-8")                # FHIR JSON must be UTF-8
        bad_text += text.count("�")          # U+FFFD = "character could not be read"
        mojibake += len(re.findall("Ã[\u0080-¿]", text))   # UTF-8 read as Latin-1
        bundle = json.loads(text)
        bundle_types[bundle.get("type")] += 1
        entries = bundle.get("entry", [])
        entries_per.append(len(entries))

        # Every record's own address inside this bundle, e.g. "urn:uuid:1234".
        full_urls = {e.get("fullUrl") for e in entries}
        here = Counter()
        for e in entries:
            res = e["resource"]
            rt = res["resourceType"]
            here[rt] += 1
            for f, v in res.items():
                if v not in (None, "", [], {}):
                    field_filled[rt][f] += 1
            for c in (res.get("code") or {}).get("coding", []) + \
                     ((res.get("vaccineCode") or {}).get("coding", [])) + \
                     ((res.get("medicationCodeableConcept") or {}).get("coding", [])):
                systems[rt][c.get("system")] += 1
                top_codes[rt][(c.get("system"), c.get("code"), c.get("display"))] += 1
            if rt == "Observation":
                vt = next((k for k in res if k.startswith("value")), None)
                value_types[vt or ("component" if "component" in res else "none")] += 1
                if "valueQuantity" in res:
                    units[res["valueQuantity"].get("unit")] += 1
            d = first_date(res)
            if d:
                dates[rt].append(d)
            if rt == "Patient":
                genders[res.get("gender")] += 1
                births.append(res.get("birthDate"))
                deceased += "deceasedDateTime" in res or res.get("deceasedBoolean") is True
                for a in res.get("address", [])[:1]:
                    states[a.get("state")] += 1
                    cities[a.get("city")] += 1
            refs = []
            walk_refs(res, refs)
            for r in refs:
                if r.startswith("urn:uuid:"):
                    ref_kinds["urn:uuid (inside the bundle)"] += 1
                    if r not in full_urls:
                        broken[rt] += 1
                elif "?" in r:
                    ref_kinds["conditional (search, e.g. Practitioner?identifier=...)"] += 1
                else:
                    ref_kinds["other: " + r.split("/")[0]] += 1
        type_total += here
        for rt, n in here.items():
            type_per_patient[rt].append(n)

    n = len(files)
    med = lambda xs: statistics.median(xs) if xs else None
    profile = {
        "files": n, "total_bytes": sum(sizes),
        "file_kb": {"min": min(sizes) / 1e3, "median": med(sizes) / 1e3, "max": max(sizes) / 1e3},
        "bundle_types": dict(bundle_types),
        "entries_per_bundle": {"min": min(entries_per), "median": med(entries_per),
                               "max": max(entries_per), "total": sum(entries_per)},
        "resources": {rt: {"total": type_total[rt],
                           "patients_with": len(type_per_patient[rt]),
                           "per_patient_min": min(type_per_patient[rt]),
                           "per_patient_median": med(type_per_patient[rt]),
                           "per_patient_max": max(type_per_patient[rt])}
                      for rt, _ in type_total.most_common()},
        "field_fill_pct": {rt: {f: round(100 * c / type_total[rt], 1)
                                for f, c in field_filled[rt].most_common()}
                           for rt in type_total},
        "code_systems": {rt: dict(c) for rt, c in systems.items()},
        "top_codes": {rt: [{"system": s, "code": k, "display": d, "count": c}
                           for (s, k, d), c in cnt.most_common(10)] for rt, cnt in top_codes.items()},
        "observation_value_types": dict(value_types),
        "observation_units_top": dict(units.most_common(15)),
        "date_range": {rt: {"min": min(ds), "max": max(ds), "with_date": len(ds)}
                       for rt, ds in dates.items()},
        "patients": {"gender": dict(genders), "birth_min": min(b for b in births if b),
                     "birth_max": max(b for b in births if b), "deceased": deceased,
                     "states": dict(states), "cities_distinct": len(cities),
                     "cities_top": dict(cities.most_common(5))},
        "references": {"kinds": dict(ref_kinds), "broken_urn_uuid_by_type": dict(broken)},
        "text": {"replacement_chars_U+FFFD": bad_text, "double_encoded_sequences": mojibake},
    }
    out = ROOT / "docs" / "profiles" / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=1, ensure_ascii=False), encoding="utf-8")

    # --- summary ---
    p = profile
    print(f"FILES {n} | {p['total_bytes'] / 1e6:.1f} MB | bundle types {p['bundle_types']}")
    e = p["entries_per_bundle"]
    print(f"RECORDS per patient: min {e['min']}, median {e['median']}, max {e['max']} | total {e['total']:,}")
    print(f"\n{'RESOURCE TYPE':<26}{'TOTAL':>8}{'PATIENTS':>10}{'PER PATIENT min/med/max':>26}")
    for rt, r in p["resources"].items():
        print(f"{rt:<26}{r['total']:>8,}{r['patients_with']:>10}"
              f"{str(r['per_patient_min']) + ' / ' + str(r['per_patient_median']) + ' / ' + str(r['per_patient_max']):>26}")
    print("\nCODE SYSTEMS (records coded with each):")
    tot_sys = Counter()
    for c in systems.values():
        tot_sys.update(c)
    for s, c in tot_sys.most_common():
        print(f"  {c:>7,}  {CODE_SYSTEMS.get(s, s)}")
    print(f"\nOBSERVATION value types: {p['observation_value_types']}")
    print(f"top units: {list(p['observation_units_top'].items())[:8]}")
    print("\nDATE RANGE (main date per resource type):")
    for rt, d in sorted(p["date_range"].items(), key=lambda kv: -kv[1]["with_date"])[:8]:
        print(f"  {rt:<24} {d['min']} .. {d['max']}  ({d['with_date']:,} dated)")
    pt = p["patients"]
    print(f"\nPATIENTS gender {pt['gender']} | born {pt['birth_min']} .. {pt['birth_max']} | "
          f"deceased {pt['deceased']} | states {pt['states']} | distinct cities {pt['cities_distinct']}")
    print(f"\nREFERENCES {p['references']['kinds']}")
    print(f"broken inside-bundle references: {sum(broken.values())} {dict(broken)}")
    print(f"TEXT: unreadable chars {bad_text} | double-encoded {mojibake}")
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
