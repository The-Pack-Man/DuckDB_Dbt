#!/usr/bin/env python3
"""
Text-to-SQL CLI
---------------
Ask a natural-language question; get a SQL query executed against DuckDB
and a plain-English explanation — all powered by a local Ollama model.

Usage:
    python cli.py "Which product category generates the most revenue?"
    python cli.py --no-explain "Top 5 customers by net revenue"
    python cli.py --show-sql "How many orders were returned in 2024?"

Environment variables (see .env.example):
    OLLAMA_BASE_URL  – default http://localhost:11434
    OLLAMA_MODEL     – default qwen2.5-coder:7b
    DUCKDB_PATH      – default dev.duckdb
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import duckdb
import yaml
from dotenv import load_dotenv
from ollama import Client
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "qwen2.5-coder:7b")
DUCKDB_PATH     = os.getenv("DUCKDB_PATH",     "dev.duckdb")
MANIFEST_PATH   = Path(__file__).parent / "semantic_manifest.yaml"

console = Console()


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    with open(MANIFEST_PATH) as fh:
        return yaml.safe_load(fh)


def get_schema(conn: duckdb.DuckDBPyConnection) -> str:
    """Return a compact DDL-style schema string for all tables in the main schema."""
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()

    lines: list[str] = []
    for (table_name,) in tables:
        cols = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = 'main' AND table_name = '{table_name}' "
            "ORDER BY ordinal_position"
        ).fetchall()
        col_defs = ", ".join(f"{col} {dtype}" for col, dtype in cols)
        lines.append(f"  {table_name}({col_defs})")

    return "\n".join(lines)


def build_sql_prompt(question: str, manifest: dict, schema: str) -> str:
    manifest_str = yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
    return f"""You are a SQL expert working with a DuckDB analytical database.

## Live Database Schema
{schema}

## Semantic Manifest (business context)
{manifest_str}

## Instructions
Write a single, correct DuckDB SQL query that answers the user's question.

Rules:
- Output ONLY the SQL inside a ```sql ... ``` code block — no other text.
- Prefer mart tables (fct_orders, dim_customers, dim_products) over staging tables.
- Use DuckDB-compatible syntax (e.g. datediff, date_trunc, strftime).
- When computing revenue, filter status = 'completed' unless the question asks about all orders.
- Round monetary results to 2 decimal places.

Question: "{question}"
"""


def build_fix_prompt(error: str) -> str:
    return (
        f"The SQL produced this error:\n\n    {error}\n\n"
        "Please fix the SQL and return only the corrected ```sql ... ``` block."
    )


def build_explanation_prompt(question: str, sql: str, result_preview: str) -> str:
    return f"""A user asked: "{question}"

SQL executed:
```sql
{sql}
```

Result (first rows):
{result_preview}

Write 2–4 sentences of plain-English business insight based on the result.
Be specific with numbers. Do not describe the SQL — describe what the data means."""


def extract_sql(text: str) -> str | None:
    """Pull SQL out of a ```sql ... ``` fence, or fall back to a bare SELECT."""
    m = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(SELECT\b.*?)(?:;|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def df_to_rich_table(df) -> Table:
    table = Table(show_header=True, header_style="bold cyan", show_lines=False)
    for col in df.columns:
        table.add_column(str(col), overflow="fold")
    for _, row in df.iterrows():
        table.add_row(*[str(v) for v in row])
    return table


def call_ollama(client: Client, messages: list[dict]) -> str:
    response = client.chat(model=OLLAMA_MODEL, messages=messages)
    return response.message.content


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Natural-language → DuckDB SQL via Ollama"
    )
    parser.add_argument(
        "question", nargs="+",
        help="Question in plain English (wrap in quotes if it contains spaces)"
    )
    parser.add_argument(
        "--no-explain", action="store_true",
        help="Skip the plain-English explanation step"
    )
    parser.add_argument(
        "--show-sql", action="store_true", default=True,
        help="Print the generated SQL (default: on)"
    )
    parser.add_argument(
        "--max-retries", type=int, default=2,
        help="How many times to ask Ollama to fix broken SQL (default: 2)"
    )
    parser.add_argument(
        "--max-rows", type=int, default=50,
        help="Maximum rows to display (default: 50)"
    )
    args = parser.parse_args()
    question = " ".join(args.question)

    console.print(f"\n[bold blue]Question:[/bold blue] {question}\n")

    # Load resources
    manifest = load_manifest()

    if not Path(DUCKDB_PATH).exists():
        console.print(
            f"[red]Database not found at '{DUCKDB_PATH}'.[/red]\n"
            "Run [bold]dbt seed && dbt run[/bold] (with --profiles-dir .) first."
        )
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    schema = get_schema(conn)
    client = Client(host=OLLAMA_BASE_URL)

    # ── Step 1: generate SQL ──────────────────────────────────────────────────
    messages: list[dict] = [
        {"role": "user", "content": build_sql_prompt(question, manifest, schema)}
    ]

    with console.status(f"[yellow]Generating SQL ({OLLAMA_MODEL})…[/yellow]"):
        raw = call_ollama(client, messages)

    sql = extract_sql(raw)
    if not sql:
        console.print("[red]Could not extract SQL from model response.[/red]")
        console.print(raw)
        sys.exit(1)

    # ── Step 2: execute with auto-fix retry ───────────────────────────────────
    df = None
    for attempt in range(args.max_retries + 1):
        if args.show_sql:
            console.print(
                Panel(
                    Syntax(sql, "sql", theme="monokai", word_wrap=True),
                    title=f"[bold]Generated SQL[/bold] (attempt {attempt + 1})",
                )
            )

        try:
            df = conn.execute(sql).df()
            break
        except Exception as exc:
            if attempt == args.max_retries:
                console.print(
                    f"[red]SQL failed after {attempt + 1} attempt(s): {exc}[/red]"
                )
                sys.exit(1)

            console.print(f"[yellow]SQL error (attempt {attempt + 1}): {exc}[/yellow]")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": build_fix_prompt(str(exc))})

            with console.status("[yellow]Asking model to fix SQL…[/yellow]"):
                raw = call_ollama(client, messages)

            sql = extract_sql(raw)
            if not sql:
                console.print("[red]Could not extract fixed SQL.[/red]")
                sys.exit(1)

    # ── Step 3: display results ───────────────────────────────────────────────
    console.print(f"\n[bold green]Results[/bold green] — {len(df)} row(s)\n")

    if df.empty:
        console.print("[dim]Query returned no rows.[/dim]")
    else:
        display_df = df.head(args.max_rows)
        console.print(df_to_rich_table(display_df))
        if len(df) > args.max_rows:
            console.print(
                f"[dim]… {len(df) - args.max_rows} more rows not shown "
                f"(use --max-rows to increase)[/dim]"
            )

    # ── Step 4: plain-English explanation ────────────────────────────────────
    if not args.no_explain and not df.empty:
        preview = df.head(5).to_string(index=False)
        with console.status("[yellow]Generating insight…[/yellow]"):
            explanation = call_ollama(
                client,
                [{"role": "user", "content": build_explanation_prompt(question, sql, preview)}],
            )
        console.print(
            Panel(
                explanation.strip(),
                title="[bold]Insight[/bold]",
                border_style="green",
            )
        )

    conn.close()


if __name__ == "__main__":
    main()
