"""The metadata config must stay in lockstep with the tables it governs."""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.data_contract import load_contract  # noqa: E402
from pipeline.run_pipeline import load_metadata  # noqa: E402


def test_every_bronze_table_has_metadata():
    contract_tables = set(load_contract()["tables"])
    assert contract_tables == set(load_metadata()), \
        "contract and pipeline metadata must govern the same tables"


def test_merge_keys_exist_in_contracted_schema():
    contract = load_contract()["tables"]
    for name, spec in load_metadata().items():
        for key in spec["merge_keys"]:
            assert key in contract[name], f"{name}: merge key '{key}' not in contract"


def test_merge_keys_are_actually_unique_in_data():
    """A MERGE on non-unique keys silently multiplies rows — verify grain."""
    for name, spec in load_metadata().items():
        df = pd.read_csv(ROOT / "data" / "bronze" / f"{name}.csv")
        dupes = df.duplicated(subset=spec["merge_keys"]).sum()
        assert dupes == 0, f"{name}: {dupes} duplicate rows on merge keys {spec['merge_keys']}"


def test_surrogate_keys_configured_for_all_dims():
    meta = load_metadata()
    for name, spec in meta.items():
        if name.startswith("dim_"):
            assert "surrogate_key" in spec and "natural_key" in spec


def test_metadata_json_parses_and_documents_itself():
    raw = json.loads((ROOT / "config" / "pipeline_metadata.json").read_text(encoding="utf-8"))
    assert "description" in raw and "tables" in raw
