"""
Fabric workspace deployment via fabric-cicd (Microsoft's CI/CD library).

Publishes the PBIP artifacts (semantic model + report) from this repo into
the target Fabric workspace, applying per-environment parameterization from
deploy/parameter.yml — the Dev workspace points at dev storage, Prod at
prod, and the RLS security-mapping source swaps with them.

Auth is a service principal (never a user identity) supplied by the GitHub
Environment's secrets. Run from CI:

    python deploy/fabric_deploy.py --environment DEV
"""

import argparse
import os

from azure.identity import ClientSecretCredential
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--environment", required=True, choices=["DEV", "QA", "PROD"])
    args = ap.parse_args()

    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )

    workspace = FabricWorkspace(
        workspace_id=os.environ["FABRIC_WORKSPACE_ID"],
        environment=args.environment,
        repository_directory="powerbi/pbip",
        item_type_in_scope=["SemanticModel", "Report"],
        token_credential=credential,
    )

    # idempotent publish: new/changed items deploy, deleted items are retired
    publish_all_items(workspace)
    unpublish_all_orphan_items(workspace)
    print(f"deployed powerbi/pbip -> {args.environment} "
          f"workspace {os.environ['FABRIC_WORKSPACE_ID']}")


if __name__ == "__main__":
    main()
