"""
Text-to-SQL pipeline shared by the CLI and the evaluation harness.

The model gets the live DuckDB schema, and optionally the semantic layer:
the hand-written manifest plus the business rules that depend on it. The
evaluation compares accuracy with and without that semantic layer.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import duckdb
import yaml

MANIFEST_PATH = Path(__file__).parent / "semantic_manifest.yaml"

# A chat function takes OpenAI/Ollama-style messages and returns the reply text.
ChatFn = Callable[[list[dict]], str]


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    with open(path) as fh:
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
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [table_name],
        ).fetchall()
        col_defs = ", ".join(f"{col} {dtype}" for col, dtype in cols)
        lines.append(f"  {table_name}({col_defs})")

    return "\n".join(lines)


def build_sql_prompt(question: str, schema: str, manifest: dict | None) -> str:
    """Build the generation prompt. manifest=None gives the schema-only baseline."""
    sections = [
        "You are a SQL expert working with a DuckDB analytical database.",
        f"## Live Database Schema\n{schema}",
    ]
    rules = [
        "- Output ONLY the SQL inside a ```sql ... ``` code block — no other text.",
        "- Use DuckDB-compatible syntax (e.g. datediff, date_trunc, strftime).",
        "- Round monetary results to 2 decimal places.",
    ]
    if manifest is not None:
        manifest_str = yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
        sections.append(f"## Semantic Manifest (business context)\n{manifest_str}")
        # Business rules are part of the semantic layer, so they are only
        # included alongside the manifest.
        rules += [
            "- Prefer mart tables (fct_orders, dim_customers, dim_products) over staging tables.",
            "- When computing revenue, filter status = 'completed' unless the question asks about all orders.",
        ]
    sections.append(
        "## Instructions\nWrite a single, correct DuckDB SQL query that answers the user's question.\n\n"
        "Rules:\n" + "\n".join(rules)
    )
    sections.append(f'Question: "{question}"')
    return "\n\n".join(sections) + "\n"


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
    """Pull SQL out of a ```sql ... ``` fence, or fall back to a bare SELECT/WITH."""
    m = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"((?:WITH|SELECT)\b.*?)(?:;|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


@dataclass
class PipelineResult:
    sql: str | None
    rows: list[tuple] | None
    columns: list[str] | None
    attempts: int
    error: str | None
    latency_s: float
    sql_history: list[str] = field(default_factory=list)


def generate_and_execute(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    chat: ChatFn,
    schema: str,
    manifest: dict | None,
    max_retries: int = 2,
    on_attempt: Callable[[int, str], Any] | None = None,
    on_error: Callable[[int, str], Any] | None = None,
) -> PipelineResult:
    """Generate SQL, run it, and feed errors back to the model up to max_retries times."""
    t0 = time.monotonic()
    messages: list[dict] = [{"role": "user", "content": build_sql_prompt(question, schema, manifest)}]
    raw = chat(messages)
    sql = extract_sql(raw)
    history: list[str] = []

    for attempt in range(1, max_retries + 2):
        if not sql:
            return PipelineResult(None, None, None, attempt, "could not extract SQL from model output",
                                  time.monotonic() - t0, history)
        history.append(sql)
        if on_attempt:
            on_attempt(attempt, sql)
        try:
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return PipelineResult(sql, rows, columns, attempt, None, time.monotonic() - t0, history)
        except Exception as exc:
            if on_error:
                on_error(attempt, str(exc))
            if attempt == max_retries + 1:
                return PipelineResult(sql, None, None, attempt, f"{type(exc).__name__}: {exc}"[:500],
                                      time.monotonic() - t0, history)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": build_fix_prompt(str(exc))})
            raw = chat(messages)
            sql = extract_sql(raw)

    raise AssertionError("unreachable")


def ollama_chat(base_url: str, model: str, temperature: float | None = None, seed: int | None = None) -> ChatFn:
    """Chat function backed by a local Ollama server."""
    from ollama import Client

    client = Client(host=base_url)
    options: dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if seed is not None:
        options["seed"] = seed

    def chat(messages: list[dict]) -> str:
        return client.chat(model=model, messages=messages, options=options or None).message.content

    return chat
