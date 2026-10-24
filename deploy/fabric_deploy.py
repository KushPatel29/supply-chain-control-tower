"""Prepare a reviewable Fabric deployment; --execute is an explicit cloud write.

The parameter file is staged in the library's documented repository root.
Orphan retirement is opt-in. Tenant configuration remains unexecuted until an
actual configured workspace and credentials are available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

import yaml


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "powerbi/pbip"
PARAMETERS = ROOT / "deploy/parameter.yml"


def prepare(environment, workspace_id=None, parameters=PARAMETERS, items=ITEMS):
    if environment not in {"DEV", "QA", "PROD"}:
        raise ValueError("Unknown environment")
    blocks = []
    try:
        UUID(workspace_id or "")
    except (ValueError, AttributeError):
        blocks.append("A configured workspace UUID is required")
    config = yaml.safe_load(parameters.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not config.get("find_replace"):
        raise ValueError("An explicit parameterization contract is required")
    for replacement in config["find_replace"]:
        value = replacement.get("replace_value", {}).get(environment)
        if not isinstance(value, str) or not value.strip():
            blocks.append("Missing binding for the selected environment")
        elif any(
            marker in value
            for marker in (
                ".example",
                "dev-lakehouse",
                "qa-lakehouse",
                "prod-lakehouse",
            )
        ):
            blocks.append("Example bindings must be replaced with actual tenant values")
    files = {}
    for path in sorted(items.rglob("*")):
        if path.is_file() and ".pbi" not in path.parts and path != items / "parameter.yml":
            if not path.resolve().is_relative_to(items.resolve()):
                raise ValueError("Publish source escapes the item directory")
            files[path.relative_to(items).as_posix()] = hashlib.sha256(
                path.read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
    if not files:
        raise ValueError("No publishable source")
    body = {
        "environment": environment,
        "workspace_id": workspace_id,
        "source_files_sha256_lf": files,
        "parameter_sha256_lf": hashlib.sha256(
            parameters.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "orphan_retirement_default": False,
        "blocks": sorted(set(blocks)),
    }
    return {
        **body,
        "plan_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest(),
    }


def publish(plan, retire_orphans=False):
    current = prepare(plan["environment"], os.environ.get("FABRIC_WORKSPACE_ID"))
    if current != plan or plan["blocks"]:
        raise ValueError(
            "Deployment plan is stale, targets differ or configuration is incomplete"
        )
    required = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
    if any(not os.environ.get(name) for name in required):
        raise ValueError("Configured service-principal credentials are required")
    # Imported only after all offline gates pass. A dry run needs no Azure login.
    from azure.identity import ClientSecretCredential
    from fabric_cicd import (
        FabricWorkspace,
        publish_all_items,
        unpublish_all_orphan_items,
    )

    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )
    with tempfile.TemporaryDirectory(prefix="control-tower-fabric-") as temporary:
        staged = Path(temporary) / "items"
        shutil.copytree(ITEMS, staged, ignore=shutil.ignore_patterns(".pbi"))
        shutil.copy2(PARAMETERS, staged / "parameter.yml")
        staged_plan = prepare(
            plan["environment"], plan["workspace_id"],
            parameters=staged / "parameter.yml", items=staged,
        )
        if staged_plan != plan:
            raise ValueError("Source changed while staging; re-review the deployment")
        workspace = FabricWorkspace(
            workspace_id=plan["workspace_id"],
            environment=plan["environment"],
            repository_directory=str(staged),
            item_type_in_scope=["SemanticModel", "Report"],
            token_credential=credential,
        )
        publish_all_items(workspace)
        if retire_orphans:
            unpublish_all_orphan_items(workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["DEV", "QA", "PROD"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--retire-orphans", action="store_true")
    parser.add_argument("--plan-output", type=Path)
    args = parser.parse_args()
    if args.retire_orphans and not args.execute:
        parser.error("Orphan retirement requires an explicit executed deployment")
    plan = prepare(args.environment, os.environ.get("FABRIC_WORKSPACE_ID"))
    if args.plan_output:
        args.plan_output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "environment": plan["environment"],
                "files": len(plan["source_files_sha256_lf"]),
                "plan_sha256": plan["plan_sha256"],
                "blocks": plan["blocks"],
                "executed": False,
            }
        )
    )
    if args.execute:
        publish(plan, args.retire_orphans)
        print(
            "Publish call completed; validate Service refresh and intended-user security separately."
        )


if __name__ == "__main__":
    main()
