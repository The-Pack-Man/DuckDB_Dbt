---
name: Text-to-SQL over a dbt semantic layer
repo: The-Pack-Man/DuckDB_Dbt
status: active
one_liner: Local text-to-SQL CLI that grounds a local LLM in both the live DuckDB schema and a dbt-built semantic manifest.
problem: Text-to-SQL breaks when the model only sees raw tables. Business definitions live in the modeling layer.
user: Portfolio demonstration (seeded e-commerce data).
tags: [eval-reliability, observability-data, problem-selection]
stack: [Python, DuckDB, dbt, Ollama (qwen2.5-coder:7b), Rich, pytest]
run: python cli.py "Which product category generates the most revenue?"
test: pytest

claims:
  - id: C1
    text: Modeled seed data with dbt into staging and mart layers (fct_orders, dim_customers, dim_products) with documented schemas.
    evidence: [models/staging/, models/marts/, dbt_project.yml]
  - id: C2
    text: Built dual-context prompting that combines the live DuckDB schema with a hand-written semantic manifest of business definitions.
    evidence: [text2sql.py, semantic_manifest.yaml]
  - id: C3
    text: Executed generated SQL on a read-only DuckDB connection, with an automatic error-feedback repair loop (configurable retries).
    evidence: [text2sql.py, cli.py]
  - id: C4
    text: Generated plain-English explanations of results.
    evidence: [cli.py, text2sql.py]
  - id: C5
    text: Built an execution-accuracy evaluation harness that runs a 32-question golden set (tagged basic, join, time, ranking, business-rule) with and without the semantic layer, to measure the manifest's lift per question type.
    evidence: [evals/run_eval.py, evals/golden.yaml]
  - id: C6
    text: Wrote a result-set comparator that tolerates legitimate variation (row order, extra columns, numeric rounding, date vs timestamp, alternative accepted answers) without accepting wrong answers.
    evidence: [evals/compare.py, tests/test_eval.py]
  - id: C7
    text: Validated the harness two ways. A reference generator scores 100%, and a generator that ignores the completed-orders revenue rule is scored wrong on 11 of 13 business-rule questions.
    evidence: [tests/test_eval.py]
  - id: C8
    text: Refactored the CLI into a shared pipeline module so the CLI and the evaluation exercise the same prompt, execution, and repair code.
    evidence: [text2sql.py, cli.py]

metrics:
  - id: M1
    name: Test suite passing
    value: 14
    status: measured
    method: pytest, 2026-10-17
    artifact: ""
    date: 2026-10-17
  - id: M2
    name: Execution accuracy, schema only vs with semantic layer (32-question golden set)
    value: "56.2% (18/32) -> 90.6% (29/32), +34.4 points"
    status: measured
    method: evals/run_eval.py, qwen2.5-coder:7b via Ollama, temperature 0, max 2 repairs, 3 repeats (identical)
    artifact: evals/results/20261018T022611Z_qwen2.5-coder-7b.json
    date: 2026-10-18
  - id: M3
    name: Execution accuracy on business-rule questions, schema only vs with semantic layer
    value: "15.4% (2/13) -> 92.3% (12/13)"
    status: measured
    method: same run as M2, questions tagged business_rule
    artifact: evals/results/20261018T022611Z_qwen2.5-coder-7b.json
    date: 2026-10-18
  - id: M4
    name: Questions fixed vs broken by the semantic layer
    value: "12 fixed, 1 broken (q15: completed-only rule over-applied to an order count)"
    status: measured
    method: same run as M2, per-question comparison
    artifact: evals/results/20261018T022611Z_qwen2.5-coder-7b.json
    date: 2026-10-18

decisions:
  - Runs fully local on a 7B coder model, with no data leaving the machine.
  - The ablation treats the business rules as part of the semantic layer, so the baseline gets the schema only.
  - Reported the regression the manifest introduced (q15) alongside its gains, rather than only the net lift.
  - Read-only connection is the safety boundary rather than parsing or allowlisting SQL.

limitations:
  - Results are for one model (qwen2.5-coder 7B). The lift may differ for larger models.
  - Remaining failures with the manifest - an over-applied revenue rule (q15), an anti-join error (q17), and an undefined discount-amount metric (q28).
  - The golden set is small (32) and written by the manifest's author, so the lift may be optimistic.
  - Small synthetic dataset (20 customers, 15 products, 80 order lines).
---
