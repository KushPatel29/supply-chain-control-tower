"""Quarantine & replay: toxic rows are isolated, not fatal — until they flood."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.run_pipeline import main, replay_quarantine  # noqa: E402

QFILE = "quarantine/fact_orders_quarantine.parquet"


@pytest.fixture(scope="module", autouse=True)
def bronze_exists():
    if not (ROOT / "data" / "bronze" / "fact_orders.csv").exists():
        pytest.skip("Bronze data not generated — run data_generator/generate_data.py first")


def test_toxic_rows_are_quarantined_not_fatal(tmp_path):
    """A handful of bad rows must not block the publish — resilience, not fragility."""
    rc = main(["--lake-dir", str(tmp_path), "--inject-bad-rows", "40"])
    assert rc == 0, "small toxin count must not halt the pipeline"
    assert (tmp_path / "gold" / "_PUBLISHED").exists()
    q = pd.read_parquet(tmp_path / QFILE)
    assert len(q) == 40, "every injected toxic row must be captured"
    # machine-readable reasons on every quarantined row
    reasons = q["error_metadata"].map(json.loads)
    assert all(len(r) >= 1 and {"field", "issue"} <= set(r[0]) for r in reasons)
    issues = {r[0]["issue"] for r in reasons}
    assert issues == {"orphan_foreign_key", "negative_value"}


def test_quarantined_rows_never_reach_silver_or_gold(tmp_path):
    main(["--lake-dir", str(tmp_path), "--inject-bad-rows", "40"])
    silver = pd.read_parquet(tmp_path / "silver" / "fact_orders.parquet")
    gold = pd.read_parquet(tmp_path / "gold" / "fact_orders.parquet")
    assert (silver["qty_shipped"] >= 0).all()
    assert not silver["order_id"].gt(10_000_000).any()
    assert not gold["order_id"].gt(10_000_000).any()


def test_quarantine_flood_halts_publish(tmp_path):
    """>2% toxic rows means the source system is broken: halt, don't publish."""
    rc = main(["--lake-dir", str(tmp_path), "--inject-bad-rows", "900"])
    assert rc == 2
    assert not (tmp_path / "gold" / "_PUBLISHED").exists()


def test_replay_releases_fixed_rows_only(tmp_path):
    main(["--lake-dir", str(tmp_path), "--inject-bad-rows", "40"])
    silver_before = len(pd.read_parquet(tmp_path / "silver" / "fact_orders.parquet"))

    # nothing is fixable yet: the orphan product still doesn't exist
    assert replay_quarantine(tmp_path) == 0

    # the "source fix" arrives: the missing product appears in silver dims
    dims_file = tmp_path / "silver" / "dim_product.parquet"
    dims = pd.read_parquet(dims_file)
    fix = dims.head(1).copy()
    fix["product_id"] = -999_999
    pd.concat([dims, fix], ignore_index=True).to_parquet(dims_file, index=False)

    released = replay_quarantine(tmp_path)
    assert released == 20, "the 20 orphan-FK rows are now clean and must be released"
    silver_after = pd.read_parquet(tmp_path / "silver" / "fact_orders.parquet")
    assert len(silver_after) == silver_before + 20
    # released rows carry the full Silver business rules
    assert {"otif_flag", "gross_margin", "fill_rate"} <= set(silver_after.columns)
    # the negative-quantity rows are still toxic and still quarantined
    q = pd.read_parquet(tmp_path / QFILE)
    assert len(q) == 20
