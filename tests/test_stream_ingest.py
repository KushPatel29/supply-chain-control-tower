"""Streaming ingest must honor Autoloader's contract: incremental + exactly-once."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.stream_ingest import drain, load_ledger  # noqa: E402


@pytest.fixture()
def landing(tmp_path):
    d = tmp_path / "landing"
    d.mkdir()
    return d


@pytest.fixture()
def lake(tmp_path):
    return tmp_path / "lake"


def _drop(landing: Path, name: str, rows: int = 50) -> None:
    src = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=rows)
    src.to_csv(landing / name, index=False)


def test_drain_ingests_new_files_once(landing, lake):
    _drop(landing, "orders_a.csv")
    _drop(landing, "orders_b.csv")
    assert drain(lake, landing) == {"ingested": 2, "rejected": 0}

    # exactly-once: a second drain sees nothing new
    assert drain(lake, landing) == {"ingested": 0, "rejected": 0}
    table = pd.read_parquet(lake / "bronze" / "fact_orders_stream.parquet")
    assert len(table) == 100, "re-draining must not duplicate rows"


def test_incremental_discovery(landing, lake):
    _drop(landing, "orders_a.csv")
    drain(lake, landing)
    _drop(landing, "orders_c.csv", rows=25)
    assert drain(lake, landing)["ingested"] == 1
    table = pd.read_parquet(lake / "bronze" / "fact_orders_stream.parquet")
    assert len(table) == 75
    assert set(table["_source_file"]) == {"orders_a.csv", "orders_c.csv"}


def test_malformed_file_rejected_without_blocking(landing, lake):
    pd.DataFrame({"totally": [1], "wrong": [2]}).to_csv(
        landing / "garbage.csv", index=False)
    _drop(landing, "orders_good.csv")
    result = drain(lake, landing)
    assert result == {"ingested": 1, "rejected": 1}
    ledger = load_ledger(lake)
    assert "contract violation" in ledger["rejected"]["garbage.csv"]["reason"]
    # the rejected file is remembered — never retried, never fatal
    assert drain(lake, landing) == {"ingested": 0, "rejected": 0}
