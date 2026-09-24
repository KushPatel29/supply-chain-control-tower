"""The notebooks ran on Databricks; the pandas mirror has to round the way they did.

The Databricks run is recorded (docs/databricks/), not repeated in CI: it
needs a browser sign-in. These tests hold the record to what the README says,
and pin the rounding rule the reconciliation exposed.
"""
import csv
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "deploy" / "databricks"))

from run_pipeline import round_half_up  # noqa: E402

EVIDENCE = ROOT / "docs" / "databricks"
README = (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(("value", "places", "spark"), [
    (1.005, 2, 1.01),      # numpy: 1.0 (the binary float is 1.00499...), Spark: 1.01
    (0.125, 2, 0.13),      # exactly representable: numpy rounds to even, 0.12
    (2.675, 2, 2.68),
    (-0.125, 2, -0.13),    # half away from zero, like Spark
    (0.95, 4, 0.95),
    (12.3456789, 4, 12.3457),
])
def test_rounding_matches_spark(value, places, spark):
    assert round_half_up(pd.Series([value]), places).iloc[0] == spark


def test_rounding_keeps_nulls():
    assert round_half_up(pd.Series([None, 1.5]), 0).isna().tolist() == [True, False]


def test_the_job_ran_twice_and_the_rerun_changed_nothing():
    s = json.loads((EVIDENCE / "run_summary.json").read_text(encoding="utf-8"))
    assert [r["state"] for r in s["runs"]] == ["SUCCESS", "SUCCESS"]
    assert all(set(r["tasks"].values()) == {"SUCCESS"} for r in s["runs"])
    assert s["rerun_idempotent"] and s["silver_row_counts"]["after_run_1"] == s["silver_row_counts"]["after_run_2"]
    assert s["dq_checks"]["failed"] == []
    assert f"{s['dq_checks']['passed']} of {s['dq_checks']['total']} data-quality checks" in README


def test_every_gold_measure_matches_the_pandas_mirror_to_the_cent():
    rows = list(csv.DictReader((EVIDENCE / "reconciliation.csv").open(encoding="utf-8")))
    assert {r["match"] for r in rows} == {"yes"}
    assert max(float(r["abs_diff"]) for r in rows) < 0.005
    tables = {r["table"] for r in rows}
    assert f"{len(rows)} of {len(rows)} measures across {len(tables)} gold tables" in README


def test_the_only_notebook_change_is_the_landing_path():
    import notebook_source as R

    for nb in R.NOTEBOOKS:
        text = (ROOT / "notebooks" / f"{nb}.py").read_text(encoding="utf-8")
        src = R.to_databricks_source(text, "/Volumes/c/landing/raw")
        compile(src, nb, "exec")
        code = [ln for ln in src.splitlines() if not ln.startswith("# ")]
        original = [ln for ln in text.splitlines() if not ln.startswith("#")]
        changed = set(code) - set(original)
        assert changed <= {'LAKEHOUSE_FILES = "/Volumes/c/landing/raw"  # relative to the attached Lakehouse'}, changed
