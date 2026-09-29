# Project: FHIR R4 pipeline on Databricks

Synthetic FHIR R4 patient records (Databricks Marketplace listing "FHIR R4 Synthetic
Data", notebook "FHIR R4 Read with SQL", made with Synthea) through a medallion
pipeline on Databricks: raw JSON bundles -> flat tables per FHIR resource -> gold.
Databricks only: the Snowflake Marketplace has no identical dataset
(docs/report/scope_and_gaps.md D1). Reference implementation to reuse from:
the BRFSS project, github.com/osamagul08/data-eng, tag v1.0.

## About me
- Senior backend engineer (Node.js, 7 years). New to data engineering.
- I know: Spark DataFrames, Delta Lake, MERGE, medallion (bronze/silver/gold),
  Unity Catalog basics, window functions, partitioning. Built the BRFSS pipeline
  (bundle, ETL pipeline, Job, gates, parity, Power BI as code).
- Workspace: Databricks trial, Power BI Desktop, Windows.

## How to teach me (always)
- Simple English, short sentences. A real-life example for every new concept.
- Explain EVERY line of code you write, what it does and why.
- One step at a time. After each step: tell me what to run, what I should
  see, and ask ONE short checkpoint question before moving on.
- When I hit an error, explain the cause first, then the fix.
- Keep a learning log in docs/learning/learning_log.md: each new concept in 2-3 lines.

## Rules (non-negotiable)
- NEVER invent numbers. Row counts, timings, costs must come from real runs.
  If a number is not measured yet, write "NOT MEASURED".
- NEVER mark a task done without verifying it (show the query that proves it).
- Nothing is silently dropped: bad rows go to a quarantine table with a reason.
- No secrets in code. Use a .env file (git-ignored) for tokens and passwords.
- Commit to git after each working step, with a clear message.
- Start with a small sample of the data. Scale up only after the pipeline works.
- Before any action that costs trial credits (big loads, warehouses, clusters),
  tell me the expected cost and wait for my OK.
- If something can't be done in our time or on our accounts, say so plainly and
  record it in docs/report/scope_and_gaps.md. Don't fake it.
- The data is SYNTHETIC: never present its numbers as real-world health facts.

## What you cannot do
- You can't click inside the Databricks or Power BI interfaces.
  For UI steps, give me exact click-by-click instructions and wait for me.
