# Prompt: let Claude build the Power BI dashboard automatically

For a colleague who already has gold tables (Databricks or Snowflake) and wants
Claude Code to build the Power BI report for them. Claude cannot click in Power
BI, so it writes the report as a **Power BI Project (.pbip)**: plain-text files
for the model (TMDL) and the charts (PBIR) that Power BI Desktop opens directly.

Worked example in this repo: `scripts/generate/gen_powerbi_model.py` and
`scripts/generate/gen_powerbi_report.py` (output in `power-bi/`).

---

## Step 1 — you do this once (2 minutes)

1. Power BI Desktop → **File → Options → Preview features**: tick anything named
   *Power BI Project (.pbip)*, *TMDL* or *PBIR* if listed (newer versions have them on).
2. **File → New** → connect to ONE of your gold tables with **Get data** (so Power BI
   writes the exact connection code for your version) → **Load**.
3. Make **two sample charts**: a Card with any number, and a Clustered column chart
   with a category on the axis and a number on Y.
4. **File → Save as → Power BI project files (\*.pbip)** into your repo, e.g. `power-bi/`.
5. **Close Power BI Desktop** (it overwrites the files if left open).

## Step 2 — paste this prompt into Claude Code

```
I saved a Power BI Project at [power-bi/NAME.pbip] with one gold table loaded and
two sample charts. Build the full dashboard as code, by writing the .pbip files.

My gold data: [catalog.schema / DATABASE.SCHEMA] on [Databricks / Snowflake].
Tables: [list, e.g. dim_state, dim_indicator, fact_state_indicator, fact_group_indicator].
The question the dashboard answers: [e.g. "how do health indicators differ by state,
year, income, education, age and sex"]. Audience: a manager.

How to work:
1. Read every file Power BI created (.pbip, *.SemanticModel, *.Report, the two
   sample visual.json files, .pbi/unappliedChanges.json if present). Copy the
   EXACT connection code, schema versions and JSON shapes from them - do not guess
   formats.
2. Read the column names and types of my gold tables from the platform's
   information_schema (tell me the cost first if it starts a warehouse).
3. Write a Python generator for the SEMANTIC MODEL (TMDL): one table per gold
   table with Power Query (M) that sets every column type explicitly; a Year table
   built in Power Query; relationships fact (many) -> dimension (one); sort-by
   columns; data category for geography columns; auto date/time off.
4. Measures: NEVER sum or average percentages. A percentage measure returns a
   value only when exactly one row is behind it (IF(COUNTROWS(t)=1, MAX(t[pct]))),
   otherwise blank. Counts use COALESCE(..., 0) so cards show 0, not "(Blank)".
5. Write a second Python generator for the REPORT PAGES (PBIR): [N] pages,
   [~10] charts each, laid out on a 1920-wide grid. Include: headline cards,
   a map by region, top 10, a trend over time, breakdowns by group, a heatmap
   matrix, a scatter of two measures, single-select slicers with a default value,
   visual-level filters, titles and subtitles, data labels where readable, and
   "edit interactions" so slicers don't filter charts that must show all values.
   Stable ids (hash of a key) so regenerating doesn't rename files.
6. Tell me to close Power BI (Don't save), then run both generators, validate
   that every JSON file parses, and tell me what I should see.
7. Give me ONE known number to check (e.g. a published national figure or a row
   count) so we can prove the model is right the moment it opens.
8. If Power BI shows an error or a chart looks wrong, I will send a screenshot:
   explain the cause first, then fix the generator (not the output files).
9. Git: commit the .pbip text files; ignore *.pbix, .pbi/cache.abf and
   .pbi/localSettings.json.

Rules: simple English, explain each file you write, one step at a time, and ask
me one checkpoint question after each step.
```

## Step 3 — after Claude writes the files

1. Open the `.pbip` in Power BI Desktop → **Home → Refresh** → enter your login once.
2. Check the known number Claude gave you.
3. Send a screenshot of each page. Anything wrong: screenshot + "fix it".
4. To change a chart later: ask Claude to change the **generator**, close Power
   BI without saving, rerun the generator, reopen.

## Traps we hit (tell Claude if it forgets)

- Clicking **Load** instead of **Transform Data** skips Power Query - fine for this
  method, Claude writes the queries itself.
- Save while Power BI is open **after** Claude wrote files = Power BI overwrites them.
- Snowflake column names arrive UPPER-case; Databricks lower-case. Materialized
  views from a Databricks pipeline appear as `Kind = "View"` in Power Query.
- The Filled map may need **Options → Security → Use Map and Filled Map visuals**.
- A table visual summing a whole column can mix different things (rows + cells).
  Use named measures that pick the right rows.
