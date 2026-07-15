"""Contract semantics: additive evolves, breaking dies before Bronze."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.data_contract import check_table, load_contract  # noqa: E402
from pipeline.run_pipeline import main  # noqa: E402


@pytest.fixture(scope="module")
def contract():
    return load_contract()


def test_contract_covers_every_bronze_table(contract):
    on_disk = {p.stem for p in (ROOT / "data" / "bronze").glob("*.csv")}
    assert on_disk == set(contract["tables"]), \
        "every landed table must have a contract, and vice versa"


def test_conforming_table_passes(contract):
    df = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=100)
    result = check_table(df, "fact_orders", contract)
    assert result == {"breaking": [], "additive": []}


def test_new_column_is_additive_not_breaking(contract):
    df = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=100)
    df["carbon_footprint_kg"] = 1.5
    result = check_table(df, "fact_orders", contract)
    assert result["breaking"] == []
    assert len(result["additive"]) == 1


def test_missing_column_is_breaking(contract):
    df = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=100)
    result = check_table(df.drop(columns=["qty_shipped"]), "fact_orders", contract)
    assert any("qty_shipped" in b and "missing" in b for b in result["breaking"])


def test_type_drift_is_breaking(contract):
    df = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=100)
    df["order_id"] = df["order_id"].astype(str)   # int -> string: the silent killer
    result = check_table(df, "fact_orders", contract)
    assert any("order_id" in b and "type drift" in b for b in result["breaking"])


def test_int_widening_to_number_is_allowed(contract):
    df = pd.read_csv(ROOT / "data" / "bronze" / "fact_orders.csv", nrows=100)
    df["qty_shipped"] = df["qty_shipped"].astype(int)   # number contract, int arrives
    assert check_table(df, "fact_orders", contract)["breaking"] == []


def test_pipeline_halts_pre_bronze_on_drift(tmp_path):
    rc = main(["--lake-dir", str(tmp_path), "--simulate-schema-drift"])
    assert rc == 3, "contract violation must exit 3 (distinct from DQ gate's 2)"
    assert not (tmp_path / "bronze").exists(), \
        "breaking drift must never reach the lake — not even Bronze"
