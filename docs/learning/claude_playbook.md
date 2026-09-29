# Claude playbook — build a public-data pipeline on Databricks + Snowflake

How this project was built with Claude Code, written so a colleague can repeat it
with their own dataset. Copy the prompts, change the words in `[BRACKETS]`.

---

## 0. Before the first prompt

1. Create a folder and a git repo. Put the brief (PDF) in `docs/reference/`.
2. Copy this repo's `CLAUDE.md` into your repo root and edit "About me".
   It holds the rules Claude follows every session:
   - never invent numbers ("NOT MEASURED" instead)
   - verify before marking anything done (show the query)
   - nothing silently dropped (quarantine with a reason)
   - no secrets in code (`.env`, git-ignored)
   - start with a sample; state expected cost and wait for OK before spending credits
   - record gaps in `docs/report/scope_and_gaps.md`
   - teach: simple English, explain every line, one step at a time
3. Open Claude Code in that folder: `claude`
4. Tell it your preferences once, so it saves them to memory. Ours were:
   - "Commits show only my name, no Claude co-author line."
   - "Don't commit until I have reviewed; then commit and push when I say."

---

## 1. Kickoff prompt (paste this first)

```
Read CLAUDE.md and docs/reference/[BRIEF].pdf.

Goal: take ONE public dataset ([DATASET NAME], files in [FOLDER]) through an
identical medallion pipeline (bronze -> silver -> quarantine -> gold) on BOTH
Databricks and Snowflake, and measure ingestion, time, cost and quality the SAME
way on both, so the platforms are compared with evidence, not opinion.

Timebox: [N] days. Accounts: Databricks [trial/free], Snowflake trial, Power BI
Desktop, Windows. I am new to data engineering: explain every step simply.

Work in this order and stop after each step for my OK:
1. Profile the raw files locally (free): rows, columns, types, defects per column.
   Save the facts as JSON in docs/profiles/. Write docs/design/dataset_profile.md.
2. Write docs/report/scope_and_gaps.md: every place our situation differs from
   the brief, and what that does to the numbers. Write it BEFORE building.
3. Write docs/report/metrics.md: metric definitions, frozen before any measuring.
4. Cost guardrails on both platforms (smallest compute, short auto-stop, a hard
   spend ceiling where the platform allows one). Tell me what can BLOCK spend
   and what can only WARN.
5. Build Databricks end to end on a small sample, then the full data.
6. Port to Snowflake by GENERATING its SQL from the same source, not rewriting it.
7. Prove parity value by value, not just row counts.
8. Automate both (Databricks: bundle + ETL pipeline + Job; Snowflake: task graph).
9. External Python/pandas client reading both.
10. Power BI dashboard as a Power BI Project (.pbip) generated from code.
11. Manager report: status and evidence, clearly NOT a platform recommendation
    unless every metric is filled in.
```

---

## 2. Prompts we used at each step (in order)

| Step | Prompt |
|---|---|
| Plan check | `Before starting, explain simply why [platform/tool] and what we will build. No code yet.` |
| Guardrails | `Start Phase 1: cost guardrails on both platforms. Tell me the expected cost first.` |
| Sample | `Build bronze and silver on a 10,000-row sample first. Show me the defects you find.` |
| Quarantine | `Every bad value goes to a quarantine table with column, raw value, rule and reason. Nothing silently dropped. If row-level quarantine would drop most rows, measure it and propose cell-level.` |
| Full load | `Now the full data. Reconcile: rows in = rows out, per file, and fail the run if not.` |
| Completeness | `Add a source manifest (expected files + row counts from the profiles) so a missing file fails the gate.` |
| Automation | `Automate Databricks: asset bundle, ETL pipeline for transforms, Job only schedules it. Explain why Job vs pipeline.` |
| Review | `Review my folder structure and pipeline: is it production level? Fix what is not; list what cannot be done on a trial.` |
| Snowflake | `Port to Snowflake. Generate the SQL from the Databricks source with a script; hand-write only what genuinely differs. Same checks, same gate.` |
| Parity | `Compare every gold value on both platforms, not just counts. Report any difference.` |
| Metrics | `Collect rows, timings, cost and parity from both into one metrics table, same method both sides.` |
| Client | `Write an external pandas client that reads gold from both: 1 cold + 5 warm runs, median and p95, type fidelity. Check whether warm runs hit the result cache.` |
| Gold | `Add [N] gold tables as a star schema (dims + facts). Check every code against the official codebook BEFORE writing SQL, and verify our numbers against any figures the publisher prints.` |
| Prod | `Deploy to a clean prod catalog with its own landing volume, via the bundle's prod target.` |
| Power BI | `Build the Power BI report as a .pbip from code. I will save an empty .pbip and two sample charts first so you can copy my version's exact file format.` |
| Report | `Write docs/report/manager_report.md: only measured numbers, the gaps, and what a real platform decision still needs.` |

After EVERY step: Claude tells you what to run, what you should see, and asks one
checkpoint question. Answer it - it is how you learn.

---

## 3. Lessons we paid for - tell your Claude up front

**Measuring**
- A trivial `SELECT 1` can be answered from metadata on one platform and start a
  cluster on the other. Latency tests must force real work on both.
- Repeat queries are often answered from the **result cache**. Check query history
  (`result_from_cache`, 0 bytes scanned) before calling anything "warm compute".
- Single runs on the cheapest tier are indicative, not a benchmark. Say so on
  every chart.
- Databricks trial: no hard spend ceiling and billing tables not readable. Record
  cost as NOT MEASURED; never estimate silently.

**Data**
- Read the official codebook before trusting a column name. Our trap:
  `_RFBMI5` means "overweight OR obese", not obese (`_BMI5CAT = 4` is obese).
- If the publisher prints counts or percentages, reproduce them exactly. It is
  the strongest outside check you can get (we matched 11 of 11).
- Never sum or average percentages. Re-compute from counts/weights, and make
  Power BI measures return blank when more than one row is behind a value.

**Platforms**
- Unity Catalog names: letters, digits, `_`. A hyphen (`prod-catalog`) breaks SQL.
- Databricks pipelines work out step order from `FROM`; Snowflake tasks need an
  explicit `AFTER` for every dependency - forget one and it runs too early.
- Snowflake returns UPPER-case column names and the smallest integer type that
  fits (int8); Databricks returns decimals as Python `Decimal`. Set types yourself.
- Prod bundle files go in a folder only the deployer can write, not
  `/Workspace/Shared` (bundle validate warns about this).

**Git and files**
- Never commit a large binary (our `.pbix` hit 325 MB). Ignore it BEFORE the
  first save. Use `.pbip` (text) instead, and ignore `.pbi/cache.abf`.
- A file already committed is not removed by `.gitignore`; it must also leave history.
- Generated files say `GENERATED` at the top: change the source and regenerate,
  never hand-edit.

**Working with Claude**
- Claude cannot click in the Databricks, Snowflake or Power BI UIs. Ask for exact
  click-by-click steps, or for files it can generate (bundle YAML, SQL, .pbip).
- Production deploys and force-pushes may be blocked for Claude; it will hand you
  the exact command. Run it yourself and paste back the last lines.
- Paste screenshots of errors. Claude explains the cause before the fix.

---

## 4. What the finished repo looks like

See `docs/design/project_map.md` - every folder, what it is for, and where to
make a change.
