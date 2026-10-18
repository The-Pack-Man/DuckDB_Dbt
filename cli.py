#!/usr/bin/env python3
"""
Text-to-SQL CLI
---------------
Ask a natural-language question; get a SQL query executed against DuckDB
and a plain-English explanation — all powered by a local Ollama model.

Usage:
    python cli.py "Which product category generates the most revenue?"
    python cli.py --no-explain "Top 5 customers by net revenue"
    python cli.py --no-manifest "How many orders were returned in 2024?"

Environment variables (see .env.example):
    OLLAMA_BASE_URL  – default http://localhost:11434
    OLLAMA_MODEL     – default qwen2.5-coder:7b
    DUCKDB_PATH      – default dev.duckdb
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from text2sql import (
    build_explanation_prompt,
    generate_and_execute,
    get_schema,
    load_manifest,
    ollama_chat,
)

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "qwen2.5-coder:7b")
DUCKDB_PATH     = os.getenv("DUCKDB_PATH",     "dev.duckdb")

console = Console()


def df_to_rich_table(df) -> Table:
    table = Table(show_header=True, header_style="bold cyan", show_lines=False)
    for col in df.columns:
        table.add_column(str(col), overflow="fold")
    for _, row in df.iterrows():
        table.add_row(*[str(v) for v in row])
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Natural-language → DuckDB SQL via Ollama")
    parser.add_argument("question", nargs="+",
                        help="Question in plain English (wrap in quotes if it contains spaces)")
    parser.add_argument("--no-explain", action="store_true",
                        help="Skip the plain-English explanation step")
    parser.add_argument("--hide-sql", action="store_true",
                        help="Don't print the generated SQL")
    parser.add_argument("--no-manifest", action="store_true",
                        help="Schema only: leave out the semantic manifest and business rules")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="How many times to ask the model to fix broken SQL (default: 2)")
    parser.add_argument("--max-rows", type=int, default=50,
                        help="Maximum rows to display (default: 50)")
    args = parser.parse_args()
    question = " ".join(args.question)

    console.print(f"\n[bold blue]Question:[/bold blue] {question}\n")

    if not Path(DUCKDB_PATH).exists():
        console.print(
            f"[red]Database not found at '{DUCKDB_PATH}'.[/red]\n"
            "Run [bold]dbt seed && dbt run[/bold] (with DBT_PROFILES_DIR=.) first."
        )
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    schema = get_schema(conn)
    manifest = None if args.no_manifest else load_manifest()
    chat = ollama_chat(OLLAMA_BASE_URL, OLLAMA_MODEL)

    def show_sql(attempt: int, sql: str) -> None:
        if not args.hide_sql:
            console.print(Panel(Syntax(sql, "sql", theme="monokai", word_wrap=True),
                                title=f"[bold]Generated SQL[/bold] (attempt {attempt})"))

    def show_error(attempt: int, err: str) -> None:
        console.print(f"[yellow]SQL error (attempt {attempt}): {err}[/yellow]")

    with console.status(f"[yellow]Generating SQL ({OLLAMA_MODEL})…[/yellow]"):
        result = generate_and_execute(question, conn, chat, schema, manifest,
                                      max_retries=args.max_retries,
                                      on_attempt=show_sql, on_error=show_error)

    if result.error:
        console.print(f"[red]Failed after {result.attempts} attempt(s): {result.error}[/red]")
        sys.exit(1)

    df = pd.DataFrame(result.rows, columns=result.columns)
    console.print(f"\n[bold green]Results[/bold green] — {len(df)} row(s)\n")
    if df.empty:
        console.print("[dim]Query returned no rows.[/dim]")
    else:
        console.print(df_to_rich_table(df.head(args.max_rows)))
        if len(df) > args.max_rows:
            console.print(f"[dim]… {len(df) - args.max_rows} more rows not shown "
                          f"(use --max-rows to increase)[/dim]")

    if not args.no_explain and not df.empty:
        preview = df.head(5).to_string(index=False)
        with console.status("[yellow]Generating insight…[/yellow]"):
            explanation = chat([{"role": "user",
                                 "content": build_explanation_prompt(question, result.sql, preview)}])
        console.print(Panel(explanation.strip(), title="[bold]Insight[/bold]", border_style="green"))

    conn.close()


if __name__ == "__main__":
    main()
