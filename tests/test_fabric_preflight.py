import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "fabric_deploy", Path(__file__).resolve().parents[1] / "deploy/fabric_deploy.py"
)
deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployment)


def test_current_unconfigured_tenant_fails_closed_without_authentication():
    result = deployment.prepare("DEV")
    assert any("workspace UUID" in reason for reason in result["blocks"])
    assert any("Example bindings" in reason for reason in result["blocks"])
    assert result["orphan_retirement_default"] is False


def test_correct_environment_bindings_can_be_prepared_offline(tmp_path):
    parameters = tmp_path / "parameter.yml"
    parameters.write_text(
        'find_replace:\n  - find_value: demo\n    replace_value:\n      DEV: "actual-tenant-path"\n'
    )
    result = deployment.prepare(
        "DEV", "00000000-0000-0000-0000-000000000001", parameters=parameters
    )
    assert not result["blocks"]


def test_stale_or_changed_target_is_rejected_before_importing_cloud_libraries():
    plan = deployment.prepare("DEV")
    plan["plan_sha256"] = "tampered"
    with pytest.raises(ValueError, match="stale"):
        deployment.publish(plan)


def test_unknown_environment_cannot_publish():
    with pytest.raises(ValueError):
        deployment.prepare("production-ish")
