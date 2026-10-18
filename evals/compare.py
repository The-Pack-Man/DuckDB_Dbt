"""
Result-set comparison for execution accuracy.

A prediction matches a reference result when every reference column can be
paired with a distinct predicted column so that, row for row, the values
agree. Extra predicted columns are allowed (a model that returns
category *and* revenue for "which category earns most?" is still right).

- Rows are compared as multisets unless order_matters is set.
- Numbers match within a tolerance; ints and floats compare numerically.
- Dates and midnight timestamps compare equal (2024-03-01 == 2024-03-01 00:00).
- Strings compare case-insensitively after trimming.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
from collections import Counter
from decimal import Decimal
from typing import Any, Sequence

DEFAULT_TOLERANCE = 0.01
MAX_COLUMN_COMBINATIONS = 5000


def _norm(value: Any, tolerance: float) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        f = float(value)
        if math.isnan(f):
            return "nan"
        # Bucket to the tolerance so multiset comparison can use hashing.
        return round(f / tolerance) * tolerance if tolerance else f
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0) and value.tzinfo is None:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip().lower()
    return str(value)


def _close(a: Any, b: Any, tolerance: float) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, abs_tol=tolerance + 1e-9)
    return a == b


def _column(rows: Sequence[Sequence[Any]], i: int, tolerance: float) -> list[Any]:
    return [_norm(r[i], tolerance) for r in rows]


def _columns_equal_unordered(ref: list[list[Any]], pred: list[list[Any]], tolerance: float) -> bool:
    ref_rows = sorted(zip(*ref), key=repr)
    pred_rows = sorted(zip(*pred), key=repr)
    if len(ref_rows) != len(pred_rows):
        return False
    if Counter(ref_rows) == Counter(pred_rows):
        return True
    # Fall back to tolerant pairwise matching for values near bucket edges.
    remaining = list(pred_rows)
    for r in ref_rows:
        for k, p in enumerate(remaining):
            if all(_close(x, y, tolerance) for x, y in zip(r, p)):
                del remaining[k]
                break
        else:
            return False
    return True


def _columns_equal_ordered(ref: list[list[Any]], pred: list[list[Any]], tolerance: float) -> bool:
    ref_rows, pred_rows = list(zip(*ref)), list(zip(*pred))
    return len(ref_rows) == len(pred_rows) and all(
        all(_close(x, y, tolerance) for x, y in zip(r, p)) for r, p in zip(ref_rows, pred_rows)
    )


def results_match(
    reference: Sequence[Sequence[Any]],
    predicted: Sequence[Sequence[Any]],
    order_matters: bool = False,
    tolerance: float = DEFAULT_TOLERANCE,
) -> bool:
    """True if the predicted rows answer the question the reference rows answer."""
    if len(reference) != len(predicted):
        return False
    if not reference:
        return True
    n_ref, n_pred = len(reference[0]), len(predicted[0]) if predicted else 0
    if n_pred < n_ref:
        return False

    ref_cols = [_column(reference, i, tolerance) for i in range(n_ref)]
    pred_cols = [_column(predicted, j, tolerance) for j in range(n_pred)]

    # Candidate predicted columns for each reference column: same multiset of values.
    def compatible(rc: list[Any], pc: list[Any]) -> bool:
        if Counter(rc) == Counter(pc):
            return True
        return sorted(map(repr, rc)) == sorted(map(repr, pc)) or all(
            _close(a, b, tolerance) for a, b in zip(sorted(rc, key=repr), sorted(pc, key=repr))
        )

    candidates = [[j for j, pc in enumerate(pred_cols) if compatible(rc, pc)] for rc in ref_cols]
    if any(not c for c in candidates):
        return False

    equal = _columns_equal_ordered if order_matters else _columns_equal_unordered
    for n, combo in enumerate(itertools.product(*candidates)):
        if n >= MAX_COLUMN_COMBINATIONS:
            break
        if len(set(combo)) != len(combo):
            continue
        if equal(ref_cols, [pred_cols[j] for j in combo], tolerance):
            return True
    return False
