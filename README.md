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
| `--max-retries` | 2 | Fix attempts after a SQL error |
| `--max-rows` | 50 | Rows to display |

## Configuration (`.env`)

| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` |
| `DUCKDB_PATH` | `dev.duckdb` |

## Project layout

```
cli.py                   # question → prompt → SQL → execute/repair → explain
semantic_manifest.yaml   # business-meaning layer for the model
models/staging/          # dbt staging models
models/marts/            # dbt fact and dimension models
seeds/                   # source CSVs
```

## Limitations

- There is no accuracy evaluation yet. Planned: a golden question set scored on execution accuracy, with and without the semantic manifest.
- The seed dataset is small and synthetic.
