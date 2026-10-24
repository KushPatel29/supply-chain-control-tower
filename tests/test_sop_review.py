import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "sop_review", Path(__file__).resolve().parents[1] / "analytics/sop_review.py"
)
sop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sop)


def test_joint_service_constraints_reject_the_single_objective_trap():
    result = sop.build()
    assert result["candidate"] == "optimal for revenue"
    alternatives = {row["policy"]: row for row in result["alternatives"]}
    assert not alternatives["optimal for units"]["eligible"]
    assert "fill_revenue below agreed floor" in alternatives["optimal for units"]["reasons"]
    assert not alternatives["ABC ladder 98/95/90"]["eligible"]
    assert result["execution_approved"] is False


def test_unaffordable_target_is_not_silently_relaxed():
    rows = [{"policy": "flat 95% (in force)", "safety_stock_value": "100",
             "fill_units": ".98", "fill_revenue": ".97"}]
    result = sop.review(rows, min_units=".99", budget="99")
    assert result["candidate"] is None
    assert result["decision"] == "NO FEASIBLE CANDIDATE"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1.1"])
def test_invalid_service_target_is_rejected(bad):
    rows = [{"policy": "flat 95% (in force)", "safety_stock_value": "100",
             "fill_units": ".98", "fill_revenue": ".97"}]
    with pytest.raises(ValueError):
        sop.review(rows, min_units=bad)
