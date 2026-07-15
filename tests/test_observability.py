"""Every run must leave a machine-readable trail — including the failed ones."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.run_pipeline import main  # noqa: E402


def _events(lake: Path) -> list[dict]:
    lines = (lake / "ops" / "pipeline_events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in lines.splitlines() if line]


@pytest.fixture(scope="module", autouse=True)
def bronze_exists():
    if not (ROOT / "data" / "bronze" / "fact_orders.csv").exists():
        pytest.skip("Bronze data not generated")


def test_successful_run_is_fully_traced(tmp_path):
    assert main(["--lake-dir", str(tmp_path)]) == 0
    events = _events(tmp_path)
    assert {e["component"] for e in events} == {
        "bronze_ingest", "silver_transform", "gold_curate",
        "data_quality_checks", "publish_gate"}
    assert len({e["run_id"] for e in events}) == 1, "one run, one correlation id"
    stage_events = [e for e in events if e["status"] == "completed"
                    and "duration_ms" in e]
    assert all(e["duration_ms"] >= 0 and e["rows"] > 0 for e in stage_events)
    assert events[-1]["status"] == "published"


def test_gate_block_is_traced(tmp_path):
    assert main(["--lake-dir", str(tmp_path), "--inject-dq-failure"]) == 2
    gate = [e for e in _events(tmp_path) if e["component"] == "publish_gate"]
    assert gate[-1]["status"] == "blocked"
    assert "uniqueness" in " ".join(gate[-1]["criticals"])


def test_contract_violation_is_traced(tmp_path):
    assert main(["--lake-dir", str(tmp_path), "--simulate-schema-drift"]) == 3
    events = _events(tmp_path)
    assert events[-1]["status"] == "failed"
    assert events[-1]["error_class"] == "contract_violation"


def test_runs_append_not_overwrite(tmp_path):
    main(["--lake-dir", str(tmp_path)])
    first = len(_events(tmp_path))
    main(["--lake-dir", str(tmp_path)])
    events = _events(tmp_path)
    assert len(events) == first * 2
    assert len({e["run_id"] for e in events}) == 2, "history survives across runs"
