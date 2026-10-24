import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "spark_tuning", Path(__file__).resolve().parents[1] / "benchmarks/spark_tuning.py"
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_small_reference_is_independently_hand_calculable():
    assert benchmark.oracle(5) == [(0, 15, 1500)]


def test_unbounded_experiments_are_not_accepted():
    with pytest.raises(ValueError):
        benchmark.bounds(1_000_001, 3)
    with pytest.raises(ValueError):
        benchmark.bounds(200_000, 1)
