import datetime as dt
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "evals")]

from compare import results_match  # noqa: E402
from run_eval import evaluate, load_golden, reference_chat, summarize  # noqa: E402
from text2sql import build_sql_prompt, generate_and_execute, load_manifest  # noqa: E402

DB = ROOT / "dev.duckdb"
GOLDEN = load_golden(ROOT / "evals" / "golden.yaml")
needs_db = pytest.mark.skipif(not DB.exists(), reason="run `dbt seed && dbt run` first")


# ── Comparator ────────────────────────────────────────────────────────────────

def test_row_order_ignored_by_default():
    assert results_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])


def test_row_order_enforced_when_required():
    assert not results_match([("a",), ("b",)], [("b",), ("a",)], order_matters=True)


def test_extra_and_reordered_columns_allowed():
    assert results_match([("Furniture",)], [(9713.7, "Furniture")])


def test_missing_column_fails():
    assert not results_match([("Furniture", 9713.7)], [("Furniture",)])


def test_numeric_tolerance():
    assert results_match([(15905.08,)], [(15905.0800001,)])
    assert not results_match([(15905.08,)], [(19234.44,)])


def test_date_equals_midnight_timestamp():
    assert results_match([(dt.date(2024, 3, 1), 5)], [(dt.datetime(2024, 3, 1), 5)])


def test_strings_case_insensitive():
    assert results_match([("Furniture",)], [(" furniture ",)])


def test_different_row_count_fails():
    assert not results_match([("TX",)], [("TX",), ("CA",)])


# ── Pipeline ──────────────────────────────────────────────────────────────────

def test_schema_only_prompt_has_no_semantic_layer():
    prompt = build_sql_prompt("q?", "  t(a INT)", None)
    assert "Semantic Manifest" not in prompt and "status = 'completed'" not in prompt
    with_manifest = build_sql_prompt("q?", "  t(a INT)", load_manifest())
    assert "Semantic Manifest" in with_manifest and "status = 'completed'" in with_manifest


def test_repair_loop_feeds_error_back():
    conn = duckdb.connect()
    replies = iter(["```sql\nSELECT nope FROM missing\n```", "```sql\nSELECT 42\n```"])
    seen = []

    def chat(messages):
        seen.append(messages)
        return next(replies)

    result = generate_and_execute("q?", conn, chat, "", None, max_retries=2)
    assert result.rows == [(42,)] and result.attempts == 2
    assert "error" in seen[1][-1]["content"].lower()


def test_gives_up_after_max_retries():
    conn = duckdb.connect()
    result = generate_and_execute("q?", conn, lambda m: "```sql\nSELECT nope\n```", "", None, max_retries=1)
    assert result.error and result.attempts == 2 and result.rows is None


# ── Harness on the real golden set ────────────────────────────────────────────

@needs_db
def test_reference_generator_scores_100_percent():
    conn = duckdb.connect(str(DB), read_only=True)
    rows = evaluate(conn, GOLDEN, reference_chat(GOLDEN), log=lambda s: None)
    assert all(r["correct"] for r in rows), [r["id"] for r in rows if not r["correct"]]


@needs_db
def test_ignoring_business_rules_is_scored_wrong():
    """Revenue without the completed-only filter must fail the business-rule questions."""
    conn = duckdb.connect(str(DB), read_only=True)
    biz = [q for q in GOLDEN if "business_rule" in q["tags"] and "'completed'" in q["sql"]]
    sloppy = {q["question"]: q["sql"].replace("status = 'completed' AND ", "")
                                     .replace("WHERE status = 'completed'", "WHERE TRUE")
              for q in biz}

    def chat(messages):
        import re
        question = re.search(r'Question: "(.*)"', messages[0]["content"], re.DOTALL).group(1)
        return f"```sql\n{sloppy[question]}\n```"

    rows = evaluate(conn, biz, chat, conditions=("with_manifest",), log=lambda s: None)
    survived = {r["id"] for r in rows if r["correct"]}
    # Top category (q22) and top 2023 product (q30) are the same with or without the filter.
    assert survived == {"q22", "q30"}, survived


@needs_db
def test_summary_reports_lift_and_tags():
    conn = duckdb.connect(str(DB), read_only=True)
    s = summarize(evaluate(conn, GOLDEN[:3], reference_chat(GOLDEN), log=lambda s: None))
    assert s["manifest_lift"] == 0 and s["with_manifest"]["by_tag"]["basic"]["accuracy"] == 1.0
