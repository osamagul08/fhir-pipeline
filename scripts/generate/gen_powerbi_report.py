"""
Write the Power BI report pages (PBIR) for the FHIR dashboard: 7 pages.

  1 Overview            patients, visits, conditions, cost at a glance
  2 Visits              how care is used: by class, type, year, provider
  3 Diagnoses           clinical conditions vs social findings
  4 Treatments          medicines, procedures, vaccines
  5 Vitals & labs       BMI, blood pressure, HbA1c, cholesterol ... by age and year
  6 Costs               claims by year, type, visit class, provider
  7 Data quality        how the pipeline loaded and checked the data

Chart JSON shapes are copied from charts Power BI Desktop itself saved on this
machine (the BRFSS dashboard, visualContainer schema 2.13.0). Data is SYNTHETIC.

    python scripts/generate/gen_powerbi_report.py

Close Power BI first (Don't save), then open power-bi/fhir_dashboard.pbip.
"""

import hashlib
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGES = ROOT / "power-bi" / "fhir_dashboard.Report" / "definition" / "pages"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"


# --- builders for Power BI's query language (proven on the BRFSS dashboard) ----
def uid(*parts):
    """Stable 20-character id, so regenerating does not rename every file."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def lit(v):
    """A literal: text 'x' (quotes doubled), whole number 2015L, or true/false."""
    if isinstance(v, bool):
        return {"Literal": {"Value": "true" if v else "false"}}
    if isinstance(v, int):
        return {"Literal": {"Value": f"{v}L"}}
    return {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def total(entity, prop):
    """Sum of a column (Function 0 = Sum)."""
    return {"Aggregation": {"Expression": col(entity, prop), "Function": 0}}


def ref(field):
    """queryRef / nativeQueryRef names, as Power BI writes them."""
    if "Aggregation" in field:
        c = field["Aggregation"]["Expression"]["Column"]
        e, p = c["Expression"]["SourceRef"]["Entity"], c["Property"]
        return f"Sum({e}.{p})", f"Sum of {p}"
    kind = "Column" if "Column" in field else "Measure"
    e, p = field[kind]["Expression"]["SourceRef"]["Entity"], field[kind]["Property"]
    return f"{e}.{p}", p


def proj(field):
    q, n = ref(field)
    return {"field": field, "queryRef": q, "nativeQueryRef": n}


def in_filter(entity, prop, values, negate=False):
    """A 'basic' filter: prop is one of values (or, with negate, none of them)."""
    cond = {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                                               "Property": prop}}],
                   "Values": [[lit(v)] for v in values]}}
    if negate:
        cond = {"Not": {"Expression": cond}}
    return {"Version": 2, "From": [{"Name": "t", "Entity": entity, "Type": 0}],
            "Where": [{"Condition": cond}]}


def visual_filter(entity, prop, values, negate=False):
    return {"name": uid(entity, prop, *map(str, values), str(negate)),
            "field": col(entity, prop), "type": "Categorical",
            "filter": in_filter(entity, prop, values, negate)}


def top_n(entity, prop, by_entity, by_measure, n):
    """Top N filter: keep the n items with the highest measure value."""
    sub = {"Version": 2,
           "From": [{"Name": "d", "Entity": entity, "Type": 0},
                    {"Name": "f", "Entity": by_entity, "Type": 0}],
           "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": prop},
                       "Name": "field"}],
           "OrderBy": [{"Direction": 2, "Expression": {"Measure": {
               "Expression": {"SourceRef": {"Source": "f"}}, "Property": by_measure}}}],
           "Top": n}
    return {"name": uid("topn", entity, prop), "field": col(entity, prop), "type": "TopN",
            "filter": {"Version": 2,
                       "From": [{"Name": "subquery", "Expression": {"Subquery": {"Query": sub}}, "Type": 2},
                                {"Name": "d", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}},
                                                       "Property": prop}}],
                           "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}


def gradient(measure_field):
    """Colour by value: light blue (low) to dark blue (high)."""
    return {"FillRule": {"Input": measure_field, "FillRule": {"linearGradient2": {
        "min": {"color": lit("#E3EEFA")}, "max": {"color": lit("#0B3C8C")},
        "nullColoringStrategy": {"strategy": lit("asZero")}}}}}


def show(flag=True):
    return {"expr": lit(flag)}


class Page:
    def __init__(self, key, display, height):
        self.name = uid("page", key)
        self.display, self.height = display, height
        self.visuals, self.no_filter = [], []

    def add(self, key, vtype, x, y, w, h, roles=None, title=None, subtitle=None,
            filters=(), sort=None, objects=None, labels=False):
        name = uid(self.name, key)
        visual = {"visualType": vtype}
        if roles:
            visual["query"] = {"queryState": {
                role: {"projections": [proj(f) for f in fields]} for role, fields in roles.items()}}
            if sort:
                field, direction = sort
                visual["query"]["sortDefinition"] = {
                    "sort": [{"field": field, "direction": direction}], "isDefaultSort": False}
        objs = dict(objects or {})
        if vtype == "card":
            # Display units "None" (1): 29,402 - not 29K. A manager checks exact figures.
            objs["labels"] = [{"properties": {"labelDisplayUnits": {"expr": {"Literal": {"Value": "1D"}}}}}]
        if vtype == "tableEx":
            # No total row: adding different metrics (credits + ceiling) means nothing.
            objs["total"] = [{"properties": {"totals": show(False)}}]
        if labels:
            objs["labels"] = [{"properties": {"show": show()}}]
        if objs:
            visual["objects"] = objs
        if title:
            vco = {"title": [{"properties": {"show": show(), "text": {"expr": lit(title)}}}]}
            if subtitle:
                vco["subTitle"] = [{"properties": {"show": show(), "text": {"expr": lit(subtitle)}}}]
            visual["visualContainerObjects"] = vco
        visual["drillFilterOtherVisuals"] = True
        body = {"$schema": f"{SCHEMA}/visualContainer/2.13.0/schema.json", "name": name,
                "position": {"x": x, "y": y, "z": len(self.visuals), "height": h, "width": w,
                             "tabOrder": len(self.visuals)},
                "visual": visual}
        if filters:
            body["filterConfig"] = {"filters": list(filters)}
        self.visuals.append(body)
        return name

    def text(self, key, x, y, w, h, lines, size="12pt", bold_first=False):
        runs = []
        for i, line in enumerate(lines):
            style = {"fontSize": size}
            if bold_first and i == 0:
                style["fontWeight"] = "bold"
            runs.append({"textRuns": [{"value": line, "textStyle": style}]})
        name = uid(self.name, key)
        self.visuals.append({
            "$schema": f"{SCHEMA}/visualContainer/2.13.0/schema.json", "name": name,
            "position": {"x": x, "y": y, "z": len(self.visuals), "height": h, "width": w,
                         "tabOrder": len(self.visuals)},
            "visual": {"visualType": "textbox",
                       "objects": {"general": [{"properties": {"paragraphs": runs}}]},
                       "drillFilterOtherVisuals": True}})
        return name

    def slicer(self, key, x, y, w, h, field, entity, prop, selected, title):
        """Single-select dropdown slicer with one value pre-selected."""
        return self.add(key, "slicer", x, y, w, h, roles={"Values": [field]}, title=title, objects={
            "data": [{"properties": {"mode": {"expr": lit("Dropdown")}}}],
            # The visual title already names the slicer; hide its own small header.
            "header": [{"properties": {"show": show(False)}}],
            "selection": [{"properties": {"singleSelect": show(), "strictSingleSelect": show()}}],
            "general": [{"properties": {"filter": {"filter": in_filter(entity, prop, [selected])}}}],
        })

    def write(self):
        folder = PAGES / self.name
        (folder / "visuals").mkdir(parents=True, exist_ok=True)
        page = {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": self.name,
                "displayName": self.display, "displayOption": "FitToWidth",
                "height": self.height, "width": 1920}
        if self.no_filter:
            page["visualInteractions"] = [{"source": s, "target": t, "type": "NoFilter"}
                                          for s, t in self.no_filter]
        (folder / "page.json").write_text(json.dumps(page, indent=2), encoding="utf-8")
        for v in self.visuals:
            vf = folder / "visuals" / v["name"]
            vf.mkdir(exist_ok=True)
            (vf / "visual.json").write_text(json.dumps(v, indent=2), encoding="utf-8")


# --- fields ---------------------------------------------------------------------
P, V, C, MD, PR, VA, VI, CL, O, RT, LO, G, Y = (
    "Patients", "Visits", "Conditions", "Medications", "Procedures", "Vaccines", "Vitals",
    "Claims", "Organizations", "Record types", "Loads", "Gate", "Years")
YEAR = col(Y, "Year")
SINCE_2000 = lambda: visual_filter(Y, "Year", list(range(2000, 2023)))    # dense years only
CLINICAL = lambda: visual_filter(C, "condition_kind", ["Clinical condition"])
SOCIAL = lambda: visual_filter(C, "condition_kind", ["Social / other finding"])
NOTE = "SYNTHETIC data (Synthea): realistic, but not real people or real health statistics."


def title(p, text, sub):
    p.text("title", 10, 10, 1480, 70, [text, sub + "  " + NOTE], size="14pt", bold_first=True)


def page_overview():
    p = Page("overview", "1 Overview", 1180)
    title(p, "FHIR patient records - overview",
          "1,154 synthetic patients from 1,156 FHIR bundles, Massachusetts, visits 1920-2022.")
    for i, (key, m, t) in enumerate([
            ("k1", mea(P, "Patients"), "Patients"), ("k2", mea(P, "Alive"), "Alive"),
            ("k3", mea(P, "Deceased"), "Deceased"), ("k4", mea(V, "Visits"), "Visits"),
            ("k5", mea(C, "Clinical diagnoses"), "Clinical diagnoses"),
            ("k6", mea(CL, "Claim amount USD"), "Total claims (USD)")]):
        p.add(key, "card", 10 + i * 318, 90, 308, 130, roles={"Values": [m]}, title=t)
    p.add("gender", "donutChart", 10, 230, 460, 420,
          roles={"Category": [col(P, "gender")], "Y": [mea(P, "Patients")]},
          title="Patients by gender", labels=True)
    p.add("ages", "clusteredColumnChart", 480, 230, 700, 420,
          roles={"Category": [col(P, "age_band")], "Y": [mea(P, "Patients")], "Series": [col(P, "vital_status")]},
          title="Patients by age band and vital status",
          subtitle="Age at death, or on 2022-04-12 (last date in the data).",
          sort=(col(P, "age_band"), "Ascending"), labels=True)
    p.add("classes", "clusteredBarChart", 1190, 230, 720, 420,
          roles={"Category": [col(V, "visit_class")], "Y": [mea(V, "Visits")]},
          title="Visits by class", subtitle="Outpatient visits dominate.",
          sort=(mea(V, "Visits"), "Descending"), labels=True)
    p.add("trend", "lineChart", 10, 660, 1180, 500,
          roles={"Category": [YEAR], "Y": [mea(V, "Visits")]},
          title="Visits per year, 2000-2022",
          subtitle="Older years hold few visits: histories are recorded back to 1920.",
          filters=[SINCE_2000()], labels=True)
    p.add("marital", "clusteredBarChart", 1200, 660, 710, 500,
          roles={"Category": [col(P, "marital_status")], "Y": [mea(P, "Patients")]},
          title="Patients by marital status code",
          subtitle="M married, S single, D divorced, W widowed; blank = not recorded.",
          sort=(mea(P, "Patients"), "Descending"), labels=True)
    return p


def page_visits():
    p = Page("visits", "2 Visits", 1180)
    title(p, "How care is used", "46,050 visits across 1,206 organizations.")
    s = p.slicer("s_year", 1500, 10, 410, 70, YEAR, Y, "Year", 2021, "Year")
    by_year = p.add("byyear", "columnChart", 10, 90, 1180, 480,
                    roles={"Category": [YEAR], "Y": [mea(V, "Visits")], "Series": [col(V, "visit_class")]},
                    title="Visits per year by class, 2000-2022", subtitle="Not filtered by the Year slicer.",
                    filters=[SINCE_2000()])
    p.add("dur", "clusteredColumnChart", 1200, 90, 710, 480,
          roles={"Category": [col(V, "visit_class")], "Y": [mea(V, "Average visit minutes")]},
          title="Average visit length in minutes (selected year)",
          sort=(mea(V, "Average visit minutes"), "Descending"), labels=True)
    p.add("types", "clusteredBarChart", 10, 580, 940, 580,
          roles={"Category": [col(V, "visit_type")], "Y": [mea(V, "Visits")]},
          title="Top 12 visit types (selected year)",
          filters=[top_n(V, "visit_type", V, "Visits", 12)], sort=(mea(V, "Visits"), "Descending"), labels=True)
    p.add("orgs", "clusteredBarChart", 960, 580, 950, 580,
          roles={"Category": [col(O, "organization")], "Y": [mea(V, "Visits")]},
          title="Top 10 organizations by visits (selected year)",
          filters=[top_n(O, "organization", V, "Visits", 10)], sort=(mea(V, "Visits"), "Descending"), labels=True)
    p.no_filter += [(s, by_year)]
    return p


def page_diagnoses():
    p = Page("diagnoses", "3 Diagnoses", 1240)
    title(p, "Clinical conditions and social findings",
          "SNOMED findings here are mostly social (employment, stress, isolation) - kept apart from diseases.")
    p.add("clin", "clusteredBarChart", 10, 90, 940, 600,
          roles={"Category": [col(C, "condition")], "Y": [mea(C, "Patients affected")]},
          title="Top 15 clinical conditions - patients affected",
          filters=[CLINICAL(), top_n(C, "condition", C, "Patients affected", 15)],
          sort=(mea(C, "Patients affected"), "Descending"), labels=True)
    p.add("soc", "clusteredBarChart", 960, 90, 950, 600,
          roles={"Category": [col(C, "condition")], "Y": [mea(C, "Patients affected")]},
          title="Top 10 social and other findings - patients affected",
          filters=[SOCIAL(), top_n(C, "condition", C, "Patients affected", 10)],
          sort=(mea(C, "Patients affected"), "Descending"), labels=True)
    p.add("status", "donutChart", 10, 700, 500, 520,
          roles={"Category": [col(C, "clinical_status")], "Y": [mea(C, "Diagnoses")]},
          title="Clinical conditions: active vs resolved", filters=[CLINICAL()], labels=True)
    p.add("onset", "lineChart", 520, 700, 700, 520,
          roles={"Category": [YEAR], "Y": [mea(C, "Diagnoses")], "Series": [col(C, "condition_kind")]},
          title="New diagnoses per year, 2000-2022", filters=[SINCE_2000()])
    p.add("byage", "pivotTable", 1230, 700, 680, 520,
          roles={"Rows": [col(C, "condition")], "Columns": [col(P, "age_band")],
                 "Values": [mea(C, "Patients affected")]},
          title="Top clinical conditions by age band", subtitle="Patients affected; age today or at death.",
          filters=[CLINICAL(), top_n(C, "condition", C, "Patients affected", 10)],
          objects={"values": [{"properties": {"backColor": {"solid": {"color": {
                                   "expr": gradient(mea(C, "Patients affected"))}}}},
                               "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                            "metadata": "Conditions.Patients affected"}}]})
    return p


def page_treatments():
    p = Page("treatments", "4 Treatments", 1240)
    title(p, "Medicines, procedures and vaccines", "RxNorm medicines, SNOMED procedures, CVX vaccines.")
    p.add("meds", "clusteredBarChart", 10, 90, 940, 560,
          roles={"Category": [col(MD, "medicine")], "Y": [mea(MD, "Prescriptions")]},
          title="Top 10 medicines by prescriptions",
          subtitle="Blood-pressure drugs lead: lisinopril, hydrochlorothiazide, amlodipine.",
          filters=[top_n(MD, "medicine", MD, "Prescriptions", 10)],
          sort=(mea(MD, "Prescriptions"), "Descending"), labels=True)
    p.add("proc", "clusteredBarChart", 960, 90, 950, 560,
          roles={"Category": [col(PR, "procedure")], "Y": [mea(PR, "Procedures done")]},
          title="Top 10 procedures", filters=[top_n(PR, "procedure", PR, "Procedures done", 10)],
          sort=(mea(PR, "Procedures done"), "Descending"), labels=True)
    p.add("rxyear", "lineChart", 10, 660, 620, 560,
          roles={"Category": [YEAR], "Y": [mea(MD, "Prescriptions")]},
          title="Prescriptions per year, 2000-2022", filters=[SINCE_2000()])
    p.add("vacc", "clusteredBarChart", 640, 660, 640, 560,
          roles={"Category": [col(VA, "vaccine")], "Y": [mea(VA, "Vaccines given")]},
          title="Top 10 vaccines", filters=[top_n(VA, "vaccine", VA, "Vaccines given", 10)],
          sort=(mea(VA, "Vaccines given"), "Descending"), labels=True)
    p.add("vyear", "lineChart", 1290, 660, 620, 560,
          roles={"Category": [YEAR], "Y": [mea(VA, "Vaccines given")]},
          title="Vaccines per year, 2000-2022", subtitle="COVID-19 vaccines appear in 2021.",
          filters=[SINCE_2000()])
    return p


def page_vitals():
    p = Page("vitals", "5 Vitals & labs", 1240)
    title(p, "Vital signs and lab results", "Averages of readings for ONE measure at a time (LOINC-coded).")
    s = p.slicer("s_measure", 1500, 10, 410, 70, col(VI, "measure"), VI, "measure", "BMI", "Measure")
    p.add("trend", "lineChart", 10, 90, 940, 540,
          roles={"Category": [YEAR], "Y": [mea(VI, "Average value")]},
          title="Selected measure: average by year, 2000-2022", filters=[SINCE_2000()], labels=True)
    p.add("age", "clusteredColumnChart", 960, 90, 950, 540,
          roles={"Category": [col(P, "age_band")], "Y": [mea(VI, "Average value")], "Series": [col(P, "gender")]},
          title="Selected measure: average by age band and gender",
          sort=(col(P, "age_band"), "Ascending"), labels=True)
    bp = p.add("bp", "clusteredColumnChart", 10, 640, 940, 580,
               roles={"Category": [col(P, "age_band")], "Y": [mea(VI, "Average value")],
                      "Series": [col(VI, "measure")]},
               title="Blood pressure by age band (mm[Hg])", subtitle="Systolic and diastolic, all years.",
               filters=[visual_filter(VI, "measure", ["Systolic BP", "Diastolic BP"])],
               sort=(col(P, "age_band"), "Ascending"), labels=True)
    tbl = p.add("all", "tableEx", 960, 640, 950, 580,
                roles={"Values": [col(VI, "measure_group"), col(VI, "measure"), col(VI, "unit"),
                                  mea(VI, "Readings"), mea(VI, "Average value")]},
                title="Every measure: readings and overall average")
    p.no_filter += [(s, bp), (s, tbl)]
    return p


def page_costs():
    p = Page("costs", "6 Costs", 1180)
    title(p, "Claims and costs (USD, synthetic prices)",
          "Institutional claims belong to visits; pharmacy claims to prescriptions.")
    for i, (key, m, t) in enumerate([("k1", mea(CL, "Claim amount USD"), "Total claims (USD)"),
                                      ("k2", mea(CL, "Claims"), "Claims"),
                                      ("k3", mea(V, "Average cost per visit"), "Average cost per visit (USD)")]):
        p.add(key, "card", 10 + i * 636, 90, 626, 130, roles={"Values": [m]}, title=t)
    p.add("year", "clusteredColumnChart", 10, 230, 1180, 460,
          roles={"Category": [YEAR], "Y": [mea(CL, "Claim amount USD")], "Series": [col(CL, "claim_type")]},
          title="Claim amount per year, 2000-2022", filters=[SINCE_2000()])
    p.add("type", "donutChart", 1200, 230, 710, 460,
          roles={"Category": [col(CL, "claim_type")], "Y": [mea(CL, "Claim amount USD")]},
          title="Amount by claim type", labels=True)
    p.add("class", "clusteredBarChart", 10, 700, 620, 460,
          roles={"Category": [col(V, "visit_class")], "Y": [mea(V, "Average cost per visit")]},
          title="Average cost per visit by class",
          sort=(mea(V, "Average cost per visit"), "Descending"), labels=True)
    p.add("orgs", "clusteredBarChart", 640, 700, 640, 460,
          roles={"Category": [col(O, "organization")], "Y": [mea(V, "Visit cost USD")]},
          title="Top 10 organizations by visit cost",
          filters=[top_n(O, "organization", V, "Visit cost USD", 10)],
          sort=(mea(V, "Visit cost USD"), "Descending"), labels=True)
    p.add("age", "clusteredColumnChart", 1290, 700, 620, 460,
          roles={"Category": [col(P, "age_band")], "Y": [mea(CL, "Claim amount USD")]},
          title="Claim amount by patient age band", sort=(col(P, "age_band"), "Ascending"), labels=True)
    return p


def page_quality():
    p = Page("quality", "7 Data quality", 1120)
    title(p, "How the data was loaded and checked",
          "Databricks pipeline fhir_etl: Auto Loader, 5 batches, gates that stop a bad run.")
    for i, (key, m, t) in enumerate([("k1", mea(LO, "Files loaded"), "Files loaded"),
                                      ("k2", mea(RT, "Records loaded"), "FHIR records"),
                                      ("k3", mea(G, "Records lost in flattening"), "Records lost in flattening"),
                                      ("k4", mea(G, "Duplicate ids"), "Duplicate record ids"),
                                      ("k5", mea(G, "Quarantined issues"), "Quarantined issues")]):
        p.add(key, "card", 10 + i * 382, 90, 372, 130, roles={"Values": [m]}, title=t)
    p.add("types", "clusteredBarChart", 10, 230, 940, 870,
          roles={"Category": [col(RT, "resource_type")], "Y": [mea(RT, "Records loaded")]},
          title="Records per FHIR resource type",
          sort=(mea(RT, "Records loaded"), "Descending"), labels=True)
    p.add("loads", "tableEx", 960, 230, 950, 330,
          roles={"Values": [col(LO, "loaded_at"), col(LO, "files"), col(LO, "records"), col(LO, "megabytes")]},
          title="Each Auto Loader load", subtitle="Each batch loaded once; earlier files never reloaded.")
    p.add("match", "donutChart", 960, 570, 470, 530,
          roles={"Category": [col(V, "location_match")], "Y": [mea(V, "Visits")]},
          title="How visit locations were matched", subtitle="id = home visits (a 'kind' location).",
          labels=True)
    p.text("checks", 1440, 570, 470, 530, [
        "Checks that passed",
        "- 631,630 records: bronze = silver, equal to an independent profile of all 1,156 files.",
        "- 24 of 24 resource types: counts identical to that profile.",
        "- Every visit has one note and one insurer statement (46,050 each).",
        "- The gate stops the run on lost records, duplicate ids or bad files.",
        "Details: docs/report/scope_and_gaps.md (D9-D13)."], bold_first=True)
    return p


def main():
    if PAGES.exists():
        shutil.rmtree(PAGES)
    PAGES.mkdir(parents=True)
    pages = [page_overview(), page_visits(), page_diagnoses(), page_treatments(),
             page_vitals(), page_costs(), page_quality()]
    for pg in pages:
        pg.write()
    (PAGES / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [pg.name for pg in pages], "activePageName": pages[0].name}, indent=2), encoding="utf-8")
    for pg in pages:
        print(f"{pg.display:<20} {len(pg.visuals)} visuals")
    print("total visuals:", sum(len(pg.visuals) for pg in pages))


if __name__ == "__main__":
    main()
