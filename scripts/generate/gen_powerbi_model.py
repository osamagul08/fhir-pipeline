"""
Write the Power BI semantic model (TMDL) for the FHIR dashboard.

Reads the gold tables of the FHIR pipeline (plus the gate) from Databricks.
Everything is counts, sums and averages of readings - all safe to add up
(unlike BRFSS's percentages). Data is SYNTHETIC.

    python scripts/generate/gen_powerbi_model.py

Close Power BI first; then open power-bi/fhir_dashboard.pbip and Refresh.
Same approach as the BRFSS dashboard (osamagul08/data-eng, tag v1.0).
"""

import argparse
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEF = ROOT / "power-bi" / "fhir_dashboard.SemanticModel" / "definition"
TABLES = DEF / "tables"

HOST = "dbc-b66dca1a-d331.cloud.databricks.com"
HTTP_PATH = "/sql/1.0/warehouses/87abf2d5aeeae691"

M_TYPE = {"int64": "Int64.Type", "string": "type text", "double": "type number",
          "boolean": "type logical", "dateTime": "type datetime"}


def quote(name):
    return f"'{name}'" if any(ch in name for ch in " %()-/") else name


def m_source(catalog, schema, obj, cols, extra=()):
    """Power Query: connect, open catalog.schema.obj, keep the listed columns, set types.
    Connection lines match what Power BI Desktop generates on this machine."""
    keep = ", ".join(f'"{c}"' for c, *_ in cols if not c.startswith("~"))
    types = ", ".join(f'{{"{c}", {M_TYPE[t]}}}' for c, t, *_ in cols if not c.startswith("~"))
    lines = [
        "let",
        f'    Source = DatabricksMultiCloud.Catalogs("{HOST}", "{HTTP_PATH}", null),',
        f'    Catalog = Source{{[Name = "{catalog}", Kind = "Database"]}}[Data],',
        f'    Schema = Catalog{{[Name = "{schema}", Kind = "Schema"]}}[Data],',
        f'    Data = Schema{{[Name = "{obj}", Kind = "View"]}}[Data],',
        f"    Kept = Table.SelectColumns(Data, {{{keep}}}),",
        f"    Typed = Table.TransformColumnTypes(Kept, {{{types}}})",
    ]
    last = "Typed"
    for step_name, expr in extra:                      # extra Power Query steps
        lines[-1] += ","
        lines.append(f"    {step_name} = {expr.replace('PREV', last)}")
        last = step_name
    lines += ["in", f"    {last}"]
    return lines


def write_table(name, cols, source_lines, measures=()):
    """cols: (column, tmdl type, [extra property lines], summarize_by_sum)."""
    out = [f"table {quote(name)}", ""]
    for m_name, expr, fmt in measures:
        out.append(f"\tmeasure {quote(m_name)} =")
        out += [f"\t\t\t{line}" for line in expr.strip().splitlines()]
        out += [f"\t\tformatString: {fmt}", ""]
    for col, typ, props, summ in cols:
        out.append(f"\tcolumn {quote(col)}")
        out.append(f"\t\tdataType: {typ}")
        if typ == "int64":
            out.append("\t\tformatString: 0")
        if typ == "double":
            out.append("\t\tformatString: #,0.0")
        if typ == "dateTime":
            out.append("\t\tformatString: yyyy-mm-dd")
        out += [f"\t\t{p}" for p in props]
        out.append(f"\t\tsummarizeBy: {'sum' if summ else 'none'}")
        out.append(f"\t\tsourceColumn: {col}")
        out.append("")
    out += [f"\tpartition {quote(name)} = m", "\t\tmode: import", "\t\tsource ="]
    out += [f"\t\t\t\t{line}" for line in source_lines]
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    (TABLES / f"{name}.tmdl").write_text("\n".join(out), encoding="utf-8")


def c(name, typ="string", props=(), summ=False):
    return (name, typ, list(props), summ)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="fhir")
    ap.add_argument("--schema", default="dev_osamagul08_fhir_etl")
    a = ap.parse_args()
    src = lambda obj, cols, extra=(): m_source(a.catalog, a.schema, obj, cols, extra)

    if TABLES.exists():
        for f in TABLES.glob("*.tmdl"):
            f.unlink()
    TABLES.mkdir(parents=True, exist_ok=True)

    # --- Patients: the centre of the star ---------------------------------------
    cols = [c("patient_id"), c("gender"), c("birth_date", "dateTime"), c("is_deceased", "boolean"),
            c("vital_status"), c("death_year", "int64"), c("age_years", "int64"),
            c("age_band", props=["sortByColumn: age_band_order"]), c("marital_status"), c("city")]
    # age_band_order is added in Power Query so bands sort 0-17, 18-34, ... 80+.
    order = ('Table.AddColumn(PREV, "age_band_order", each if [age_band] = "80+" then 80 '
             'else Number.From(Text.BeforeDelimiter([age_band], "-")), Int64.Type)')
    write_table("Patients", cols + [c("age_band_order", "int64")],
                src("gold_dim_patient", cols, [("Ordered", order)]), [
        ("Patients", "DISTINCTCOUNT ( Patients[patient_id] )", "#,0"),
        ("Alive", 'CALCULATE ( [Patients], Patients[vital_status] = "Alive" )', "#,0"),
        ("Deceased", 'CALCULATE ( [Patients], Patients[vital_status] = "Deceased" )', "#,0"),
        ("Average age", "AVERAGE ( Patients[age_years] )", "0.0"),
    ])

    # --- Visits -------------------------------------------------------------------
    cols = [c("encounter_id"), c("patient_id"), c("visit_class"), c("visit_type"), c("reason_text"),
            c("visit_date", "dateTime"), c("visit_year", "int64"), c("duration_minutes", "double"),
            c("organization_id"), c("location_match"), c("claim_cost_usd", "double", summ=True)]
    write_table("Visits", cols, src("gold_fact_encounter", cols), [
        ("Visits", "COUNTROWS ( Visits )", "#,0"),
        ("Patients with visits", "DISTINCTCOUNT ( Visits[patient_id] )", "#,0"),
        ("Average visit minutes", "AVERAGE ( Visits[duration_minutes] )", "#,0.0"),
        ("Visit cost USD", "SUM ( Visits[claim_cost_usd] )", "$#,0"),
        ("Average cost per visit", "AVERAGE ( Visits[claim_cost_usd] )", "$#,0"),
    ])

    # --- Conditions: clinical vs social ---------------------------------------------
    cols = [c("condition_id"), c("patient_id"), c("condition_kind"), c("condition"), c("clinical_status"),
            c("onset_date", "dateTime"), c("onset_year", "int64"), c("is_ongoing", "boolean")]
    write_table("Conditions", cols, src("gold_fact_condition", cols), [
        ("Diagnoses", "COUNTROWS ( Conditions )", "#,0"),
        ("Patients affected", "DISTINCTCOUNT ( Conditions[patient_id] )", "#,0"),
        ("Clinical diagnoses", 'CALCULATE ( [Diagnoses], Conditions[condition_kind] = "Clinical condition" )', "#,0"),
    ])

    # --- Treatments -------------------------------------------------------------------
    cols = [c("medication_request_id"), c("patient_id"), c("status"), c("medicine"),
            c("prescribed_date", "dateTime"), c("prescribed_year", "int64")]
    write_table("Medications", cols, src("gold_fact_medication", cols), [
        ("Prescriptions", "COUNTROWS ( Medications )", "#,0"),
        ("Patients prescribed", "DISTINCTCOUNT ( Medications[patient_id] )", "#,0"),
    ])
    cols = [c("procedure_id"), c("patient_id"), c("procedure"), c("performed_date", "dateTime"),
            c("performed_year", "int64")]
    write_table("Procedures", cols, src("gold_fact_procedure", cols), [
        ("Procedures done", "COUNTROWS ( Procedures )", "#,0"),
    ])
    cols = [c("immunization_id"), c("patient_id"), c("vaccine"), c("vaccine_date", "dateTime"),
            c("vaccine_year", "int64")]
    write_table("Vaccines", cols, src("gold_fact_immunization", cols), [
        ("Vaccines given", "COUNTROWS ( Vaccines )", "#,0"),
    ])

    # --- Vitals and labs ---------------------------------------------------------------
    cols = [c("patient_id"), c("measure"), c("measure_group"), c("value", "double"), c("unit"),
            c("measured_date", "dateTime"), c("measured_year", "int64")]
    write_table("Vitals", cols, src("gold_fact_vitals", cols), [
        ("Readings", "COUNTROWS ( Vitals )", "#,0"),
        # An average of readings of ONE measure. Averaging mixed measures (kg with
        # mm[Hg]) is meaningless, so it shows only when one measure is in view.
        ("Average value", "IF ( HASONEVALUE ( Vitals[measure] ), AVERAGE ( Vitals[value] ) )", "#,0.0"),
    ])

    # --- Bills -------------------------------------------------------------------------
    cols = [c("claim_id"), c("patient_id"), c("claim_type"), c("amount_usd", "double", summ=True),
            c("billed_date", "dateTime"), c("billed_year", "int64")]
    write_table("Claims", cols, src("gold_fact_claim", cols), [
        ("Claim amount USD", "SUM ( Claims[amount_usd] )", "$#,0"),
        ("Claims", "COUNTROWS ( Claims )", "#,0"),
    ])

    # --- Care providers ------------------------------------------------------------------
    cols = [c("organization_id"), c("organization"), c("organization_type"), c("city")]
    write_table("Organizations", cols, src("gold_dim_organization", cols))

    # --- Pipeline statistics ------------------------------------------------------------
    cols = [c("resource_type"), c("records", "int64", summ=True), c("files", "int64", summ=True)]
    write_table("Record types", cols, src("gold_pipeline_records", cols), [
        ("Records loaded", "SUM ( 'Record types'[records] )", "#,0"),
    ])
    cols = [c("loaded_at", "dateTime"), c("files", "int64", summ=True), c("records", "int64", summ=True),
            c("megabytes", "double", summ=True)]
    write_table("Loads", cols, src("gold_pipeline_loads", cols), [
        ("Files loaded", "SUM ( Loads[files] )", "#,0"),
    ])
    cols = [c("files_in_bronze", "int64"), c("records_in_bronze", "int64"), c("rows_in_silver", "int64"),
            c("duplicate_resource_ids", "int64"), c("typed_rows_missing", "int64"),
            c("quarantined_issues", "int64"), c("files_not_bundles", "int64")]
    write_table("Gate", cols, src("reconciliation", cols), [
        ("Quarantined issues", "SUM ( Gate[quarantined_issues] )", "#,0"),
        ("Duplicate ids", "SUM ( Gate[duplicate_resource_ids] )", "#,0"),
        ("Records lost in flattening", "SUM ( Gate[typed_rows_missing] )", "#,0"),
    ])

    # --- Years: one slicer for every fact's year ------------------------------------------
    write_table("Years", [c("Year", "int64")], [
        "let",
        "    // Every year that appears in the data, 1920-2022.",
        '    Source = Table.FromList({1920..2022}, Splitter.SplitByNothing(), {"Year"}),',
        '    Typed = Table.TransformColumnTypes(Source, {{"Year", Int64.Type}})',
        "in",
        "    Typed"])

    # --- relationships: fact (many) -> dimension (one) --------------------------------------
    rels = [(f"{quote(t)}.patient_id", "Patients.patient_id")
            for t in ("Visits", "Conditions", "Medications", "Procedures", "Vaccines", "Vitals", "Claims")]
    rels += [("Visits.organization_id", "Organizations.organization_id"),
             ("Visits.visit_year", "Years.Year"), ("Conditions.onset_year", "Years.Year"),
             ("Medications.prescribed_year", "Years.Year"), ("Procedures.performed_year", "Years.Year"),
             ("Vaccines.vaccine_year", "Years.Year"), ("Vitals.measured_year", "Years.Year"),
             ("Claims.billed_year", "Years.Year")]
    (DEF / "relationships.tmdl").write_text("".join(
        f"relationship {uuid.uuid5(uuid.NAMESPACE_URL, f + t)}\n\tfromColumn: {f}\n\ttoColumn: {t}\n\n"
        for f, t in rels), encoding="utf-8")

    names = ["Patients", "Visits", "Conditions", "Medications", "Procedures", "Vaccines", "Vitals",
             "Claims", "Organizations", "Record types", "Loads", "Gate", "Years"]
    model = [
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US", "\tvalueFilterBehavior: independent", "\tdataAccessOptions",
        "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
        "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        "annotation PBI_QueryOrder = [" + ",".join(f'"{n}"' for n in names) + "]", "",
        'annotation PBI_ProTooling = ["DevMode"]', "",
    ] + [f"ref table {quote(n)}" for n in names] + ["", "ref cultureInfo en-US", ""]
    (DEF / "model.tmdl").write_text("\n".join(model), encoding="utf-8")
    print(f"written: {len(names)} tables, {len(rels)} relationships")


if __name__ == "__main__":
    main()
