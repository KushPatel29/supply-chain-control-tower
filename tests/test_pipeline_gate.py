"""The DQ gate must be load-bearing: a critical failure blocks the publish."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.run_pipeline import main  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def bronze_exists():
    if not (ROOT / "data" / "bronze" / "fact_orders.csv").exists():
        pytest.skip("Bronze data not generated — run data_generator/generate_data.py first")


def test_clean_run_publishes(tmp_path):
    rc = main(["--lake-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "gold" / "_PUBLISHED").exists()
    assert (tmp_path / "gold" / "dq_log.csv").exists()
    # all three layers materialized
    for layer in ("bronze", "silver", "gold"):
        assert any((tmp_path / layer).glob("*.parquet")), f"{layer} empty"


def test_injected_critical_failure_halts_publish(tmp_path):
    rc = main(["--lake-dir", str(tmp_path), "--inject-dq-failure"])
    assert rc == 2, "gate must exit non-zero on critical DQ failure"
    assert not (tmp_path / "gold" / "_PUBLISHED").exists(), \
        "publish marker must not exist when the gate halts"


def test_gate_removes_stale_marker(tmp_path):
    assert main(["--lake-dir", str(tmp_path)]) == 0
    assert (tmp_path / "gold" / "_PUBLISHED").exists()
    # a later bad run must revoke the previously-published marker
    assert main(["--lake-dir", str(tmp_path), "--inject-dq-failure"]) == 2
    assert not (tmp_path / "gold" / "_PUBLISHED").exists()


def test_gold_matches_notebook_business_rules(tmp_path):
    """Spot-check the pandas mirror against the PySpark notebooks' rules."""
    import pandas as pd
    main(["--lake-dir", str(tmp_path)])
    orders = pd.read_parquet(tmp_path / "gold" / "fact_orders.parquet")
    # OTIF definition: shipped on time AND fill rate >= 95%
    on_time = pd.to_datetime(orders["shipped_date"]) <= pd.to_datetime(orders["promised_date"])
    expected = ((on_time) & (orders["fill_rate"] >= 0.95)).astype(int)
    assert (orders["otif_flag"] == expected).all()
    # margin identity
    assert ((orders["revenue"] - orders["cogs"]).round(2) == orders["gross_margin"]).all()
