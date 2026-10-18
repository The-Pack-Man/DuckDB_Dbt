---
name: Text-to-SQL over a dbt semantic layer
repo: The-Pack-Man/DuckDB_Dbt
status: active
one_liner: Local text-to-SQL CLI that grounds a local LLM in both the live DuckDB schema and a dbt-built semantic manifest.
problem: Text-to-SQL breaks when the model only sees raw tables. Business definitions live in the modeling layer.
user: Portfolio demonstration (seeded e-commerce data).
tags: [observability-data, eval-reliability]
stack: [Python, DuckDB, dbt, Ollama (qwen2.5-coder:7b), Rich]
run: python cli.py "Which product category generates the most revenue?"
test: none

claims:
  - id: C1
    text: Modeled seed data with dbt into staging and mart layers (fct_orders, dim_customers, dim_products) with documented schemas.
    evidence: [models/staging/, models/marts/, dbt_project.yml]
  - id: C2
    text: Built dual-context prompting that combines the live DuckDB schema with a hand-written semantic manifest of business definitions.
    evidence: [cli.py, semantic_manifest.yaml]
  - id: C3
    text: Executed generated SQL on a read-only DuckDB connection, with an automatic error-feedback repair loop (configurable retries).
    evidence: [cli.py]
  - id: C4
    text: Generated plain-English explanations of results, with an optional flag to show the SQL.
    evidence: [cli.py]

metrics: []

decisions:
  - Runs fully local on a 7B coder model, with no data leaving the machine.
  - Read-only connection is the safety boundary rather than parsing or allowlisting SQL.

limitations:
  - No accuracy evaluation (execution accuracy against expected results).
---
