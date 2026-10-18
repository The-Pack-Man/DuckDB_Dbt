# Text-to-SQL over a dbt Semantic Layer

Ask a business question in plain English and get SQL, results, and an explanation. Everything runs locally on DuckDB and an Ollama model.

```bash
python cli.py "Which product category generates the most revenue?"
```

## Why two kinds of context

Text-to-SQL breaks when the model only sees raw tables. It picks the wrong table, misses filters like "completed orders only", or invents a definition of revenue. This project gives the model two kinds of context:

1. **The live schema.** Tables and column types are read from DuckDB at query time, so the prompt always matches the database.
2. **A semantic manifest** (`semantic_manifest.yaml`). This hand-written layer records business meaning: which tables to use for analysis, each table's grain, column definitions, and rules such as filtering on `status = 'completed'` for recognized revenue.

The data is modeled with dbt into staging (`stg_*`) and mart (`fct_orders`, `dim_customers`, `dim_products`) layers. The manifest steers the model toward the marts.

## Safety and recovery

- Generated SQL runs on a **read-only** DuckDB connection.
- If a query fails, the error goes back to the model for a fix. It retries up to `--max-retries` times (default 2).

## Setup

Requires Python 3.10+ and [Ollama](https://ollama.com).

```bash
pip install -r requirements-analytics.txt
ollama pull qwen2.5-coder:7b
cp .env.example .env

# Build the database from the CSV seeds
export DBT_PROFILES_DIR=.
dbt seed
dbt run
```

This creates `dev.duckdb` from `seeds/` (20 customers, 15 products, 80 order lines). The database file is generated and is not committed.

## Usage

```bash
python cli.py "Top 5 customers by net revenue"
python cli.py --no-explain "How many orders were returned in 2024?"
python cli.py --max-retries 3 --max-rows 20 "Average discount by product category"
```

| Flag | Default | Purpose |
|---|---|---|
| `--no-explain` | off | Skip the plain-English explanation |
| `--no-manifest` | off | Schema only: drop the semantic manifest and business rules |
| `--hide-sql` | off | Don't print the generated SQL |
| `--max-retries` | 2 | Fix attempts after a SQL error |
| `--max-rows` | 50 | Rows to display |

## Configuration (`.env`)

| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` |
| `DUCKDB_PATH` | `dev.duckdb` |

## Evaluation: does the semantic layer help?

`evals/` measures **execution accuracy**: whether the generated SQL returns the same result as a reference query. It runs a golden set of 32 questions under two conditions:

| Condition | Model sees |
|---|---|
| `schema_only` | live schema + generic SQL rules |
| `with_manifest` | schema + semantic manifest + business rules (what `cli.py` ships) |

The difference between the two is the **manifest lift**, the accuracy the semantic layer adds. Questions are tagged (`basic`, `join`, `time`, `ranking`, `business_rule`) so you can see where the lift comes from. The 13 `business_rule` questions need definitions that the schema doesn't state, such as "revenue" meaning net revenue on completed orders. Those are where the manifest should matter most.

```bash
python evals/run_eval.py                                  # model from .env
python evals/run_eval.py --model qwen2.5-coder:14b --repeats 3
python evals/run_eval.py --generator reference            # harness self-check: must be 100%
```

Each run prints accuracy per condition and per tag, and writes `evals/results/<timestamp>_<model>.json` with every question's SQL, result preview, retries, and latency.

**How answers are scored** (`evals/compare.py`):
- Row order is ignored unless the question requires it, as with "top 5".
- Extra columns are fine, but every reference column must be present.
- Numbers match within 0.01 by default.
- Dates match midnight timestamps.
- Some questions list alternative accepted answers, such as IDs instead of names or month numbers instead of dates.

Defaults: temperature 0 and 2 repair attempts, the same loop the CLI uses.

### Results

qwen2.5-coder 7B via Ollama, temperature 0, up to 2 repair attempts, 3 identical repeats ([`evals/results/20261018T022611Z_qwen2.5-coder-7b.json`](evals/results/20261018T022611Z_qwen2.5-coder-7b.json)):

| | schema_only | with_manifest |
|---|---:|---:|
| **Overall** | **56.2%** (18/32) | **90.6%** (29/32) |
| business_rule | 15.4% (2/13) | 92.3% (12/13) |
| basic | 84.6% (11/13) | 100% (13/13) |
| ranking | 71.4% (5/7) | 100% (7/7) |
| time | 71.4% (5/7) | 85.7% (6/7) |
| join | 50.0% (1/2) | 50.0% (1/2) |

All generated SQL executed. The repair loop was needed once per condition. Tags overlap, so tag counts don't sum to 32.

**Manifest lift: +34.4 points.** The manifest fixed 12 questions and broke 1. Most of the gain is on business-rule questions, where the schema alone doesn't say that "revenue" means net revenue on completed orders.

The three remaining failures with the manifest:

| Question | What went wrong | Cause |
|---|---|---|
| q15 Orders per month in 2023 | Added `status = 'completed'` to an order count | **Regression from the manifest**: the revenue rule was over-applied (correct without the manifest) |
| q17 Products never returned | `JOIN … WHERE status != 'returned'` instead of an anti-join | SQL reasoning error, fails in both conditions |
| q28 Revenue given up to discounts | `SUM(net_revenue * discount_pct)` instead of `gross − net` | Manifest gap: discount amount is not defined |

At temperature 0 the three repeats were identical, so the ± 0.0% shows the run is reproducible. It is not a measure of variance.

Tests: `pip install pytest && pytest`. They cover the comparator, the repair loop, the 100% self-check, and a check that ignoring the completed-orders rule gets scored wrong.

## Project layout

```
cli.py                   # command-line interface
text2sql.py              # pipeline: prompt → SQL → execute/repair (shared with evals)
semantic_manifest.yaml   # business-meaning layer for the model
evals/golden.yaml        # 32 questions with reference SQL
evals/run_eval.py        # execution-accuracy harness, manifest ablation
evals/compare.py         # result-set comparison
tests/                   # pytest suite
models/staging/          # dbt staging models
models/marts/            # dbt fact and dimension models
seeds/                   # source CSVs
```

## Limitations

- The golden set is small (32 questions) and was written by the same author as the manifest, so it may favor the manifest's phrasing. Treat the lift as directional.
- The seed dataset is small and synthetic.
