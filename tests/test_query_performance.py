"""Correctness gates for profiling; speed is observed, never a flaky CI target."""

import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "query_performance", Path(__file__).resolve().parents[1] / "benchmarks/query_performance.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_equivalent_queries_match_independent_integer_oracle():
    measured = module.measure(10_000, 3)
    assert measured["result"]["independent_oracle_equal"]
    assert measured["result"]["groups"] > 0
    assert all(len(values) == 3 for values in measured["samples_ms"].values())
    assert all(values > 0 for values in measured["median_ms"].values())
    assert all("READ_PARQUET" in plan for plan in measured["plans"].values())
    assert "2025-06-01" in measured["queries"]["partition_and_range_filter"]


@pytest.mark.parametrize("rows,repeats", [(0, 3), (10_000, 0), (10_000_001, 3)])
def test_unsafe_or_uninformative_runs_are_rejected(rows, repeats):
    with pytest.raises(ValueError):
        module.measure(rows, repeats)
