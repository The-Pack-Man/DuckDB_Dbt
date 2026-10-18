#!/usr/bin/env python3
"""
Execution-accuracy evaluation for the text-to-SQL pipeline.

Runs every golden question under two conditions:

  schema_only    - live schema + generic SQL rules
  with_manifest  - schema + semantic manifest + business rules (what cli.py ships)

A prediction is correct when its result set matches the reference result
(evals/compare.py). Results go to evals/results/<timestamp>_<model>.json.

Examples:
  python evals/run_eval.py                         # Ollama, model from .env
  python evals/run_eval.py --model qwen2.5-coder:14b --repeats 3
  python evals/run_eval.py --generator reference   # harness self-check, must score 100%
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare import DEFAULT_TOLERANCE, results_match  # noqa: E402
from text2sql import ChatFn, generate_and_execute, get_schema, load_manifest, ollama_chat  # noqa: E402

CONDITIONS = ("schema_only", "with_manifest")


def load_golden(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["questions"]


def reference_results(conn: duckdb.DuckDBPyConnection, q: dict[str, Any]) -> list[list[tuple]]:
    return [conn.execute(sql).fetchall() for sql in [q["sql"], *q.get("accept", [])]]


def reference_chat(golden: list[dict[str, Any]]) -> ChatFn:
    """Answers with the reference SQL. Used to check that the harness scores 100%."""
    by_question = {q["question"]: q["sql"] for q in golden}

    def chat(messages: list[dict]) -> str:
        m = re.search(r'Question: "(.*)"', messages[0]["content"], re.DOTALL)
        return f"```sql\n{by_question[m.group(1)]}\n```"

    return chat


def evaluate(
    conn: duckdb.DuckDBPyConnection,
    golden: list[dict[str, Any]],
    chat: ChatFn,
    conditions: tuple[str, ...] = CONDITIONS,
    repeats: int = 1,
    max_retries: int = 2,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    schema = get_schema(conn)
    manifest = load_manifest()
    refs = {q["id"]: reference_results(conn, q) for q in golden}
    rows: list[dict[str, Any]] = []

    for rep in range(1, repeats + 1):
        for cond in conditions:
            for q in golden:
                result = generate_and_execute(
                    q["question"], conn, chat, schema,
                    manifest if cond == "with_manifest" else None,
                    max_retries=max_retries,
                )
                correct = result.rows is not None and any(
                    results_match(ref, result.rows, q.get("order_matters", False),
                                  q.get("tolerance", DEFAULT_TOLERANCE))
                    for ref in refs[q["id"]]
                )
                rows.append({
                    "repeat": rep,
                    "condition": cond,
                    "id": q["id"],
                    "tags": q["tags"],
                    "question": q["question"],
                    "correct": correct,
                    "executed": result.error is None,
                    "attempts": result.attempts,
                    "repaired": result.error is None and result.attempts > 1,
                    "error": result.error,
                    "sql": result.sql,
                    "sql_history": result.sql_history,
                    "latency_s": round(result.latency_s, 3),
                    "result_preview": [list(map(str, r)) for r in (result.rows or [])[:5]],
                })
                mark = "✓" if correct else ("✗" if result.error is None else "!")
                log(f"  [{cond:13s} r{rep}] {mark} {q['id']} {q['question'][:60]}")
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cond in sorted({r["condition"] for r in rows}):
        rs = [r for r in rows if r["condition"] == cond]
        per_repeat = defaultdict(list)
        for r in rs:
            per_repeat[r["repeat"]].append(r["correct"])
        accs = [sum(v) / len(v) for v in per_repeat.values()]
        by_tag: dict[str, list[bool]] = defaultdict(list)
        for r in rs:
            for t in r["tags"]:
                by_tag[t].append(r["correct"])
        out[cond] = {
            "accuracy": round(statistics.mean(accs), 4),
            "accuracy_stdev": round(statistics.stdev(accs), 4) if len(accs) > 1 else None,
            "repeats": len(accs),
            "n_questions": len(rs) // len(accs),
            "execution_rate": round(sum(r["executed"] for r in rs) / len(rs), 4),
            "repair_rate": round(sum(r["repaired"] for r in rs) / len(rs), 4),
            "by_tag": {t: {"accuracy": round(sum(v) / len(v), 4), "n": len(v)} for t, v in sorted(by_tag.items())},
            "median_latency_s": round(statistics.median(r["latency_s"] for r in rs), 3),
        }
    if {"schema_only", "with_manifest"} <= out.keys():
        out["manifest_lift"] = round(out["with_manifest"]["accuracy"] - out["schema_only"]["accuracy"], 4)
    return out


def print_summary(summary: dict[str, Any]) -> None:
    print("\nCondition        Accuracy   Executed   Repaired")
    for cond in CONDITIONS:
        if cond in summary:
            s = summary[cond]
            sd = f" ± {s['accuracy_stdev']:.1%}" if s["accuracy_stdev"] is not None else ""
            print(f"{cond:15s}  {s['accuracy']:>7.1%}{sd}  {s['execution_rate']:>8.1%}  {s['repair_rate']:>8.1%}")
    if "manifest_lift" in summary:
        print(f"\nManifest lift: {summary['manifest_lift']:+.1%}")
    tags = sorted({t for c in CONDITIONS if c in summary for t in summary[c]["by_tag"]})
    print("\nBy tag:" + "".join(f"  {c}" for c in CONDITIONS if c in summary))
    for t in tags:
        cells = "".join(f"  {summary[c]['by_tag'].get(t, {}).get('accuracy', float('nan')):>13.1%}"
                        for c in CONDITIONS if c in summary)
        print(f"  {t:14s}{cells}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Text-to-SQL execution-accuracy eval")
    p.add_argument("--generator", choices=["ollama", "reference"], default="ollama")
    p.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))
    p.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--golden", default=str(ROOT / "evals" / "golden.yaml"))
    p.add_argument("--db", default=os.getenv("DUCKDB_PATH", str(ROOT / "dev.duckdb")))
    p.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = p.parse_args()

    if not Path(args.db).exists():
        sys.exit(f"Database not found at {args.db}. Run `dbt seed && dbt run` first.")

    golden = load_golden(Path(args.golden))
    conditions = tuple(c.strip() for c in args.conditions.split(","))
    conn = duckdb.connect(args.db, read_only=True)
    if args.generator == "reference":
        chat, model = reference_chat(golden), "reference"
    else:
        # Temperature 0 by default; repeats then measure run-to-run variance from the server.
        chat, model = ollama_chat(args.ollama_url, args.model, temperature=args.temperature), args.model

    print(f"Evaluating {len(golden)} questions × {len(conditions)} conditions × {args.repeats} repeat(s) with {model}")
    t0 = time.monotonic()
    rows = evaluate(conn, golden, chat, conditions, args.repeats, args.max_retries)
    summary = summarize(rows)
    print_summary(summary)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": args.generator,
        "model": model,
        "params": {"temperature": args.temperature if args.generator == "ollama" else None,
                   "max_retries": args.max_retries, "repeats": args.repeats,
                   "conditions": list(conditions), "golden": Path(args.golden).name,
                   "n_questions": len(golden)},
        "duration_s": round(time.monotonic() - t0, 1),
        "summary": summary,
        "rows": rows,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"{stamp}_{re.sub(r'[^A-Za-z0-9.-]+', '-', model)}.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


if __name__ == "__main__":
    main()
