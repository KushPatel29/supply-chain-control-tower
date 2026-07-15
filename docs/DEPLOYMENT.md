# Deployment: Dev → QA → Prod on Microsoft Fabric

This repo carries a complete, dispatch-ready CI/CD pipeline for promoting
the semantic model and report across three Fabric workspaces —
[`deploy_fabric.yml`](../.github/workflows/deploy_fabric.yml) — using
Microsoft's [`fabric-cicd`](https://microsoft.github.io/fabric-cicd/)
library with service-principal auth.

**Status: armed, not fired.** The workflow triggers only on
`workflow_dispatch` and needs a Fabric tenant this portfolio machine doesn't
currently have. That's disclosed rather than screenshotted around: every
line of the pipeline is real, reviewable YAML/Python, and arming it is
configuration, not code.

## What the pipeline does

```
workflow_dispatch
      │
      ▼
[validate]      regenerate data, run the gated pipeline, full test suite —
      │         nothing deploys if the build can't prove itself first
      ▼
[deploy-dev]    auto-publish PBIP -> Dev workspace (fabric-cicd)
      │
      ▼
[deploy-qa]     GitHub Environment "qa" — required-reviewer approval gate
      │         (skippable via the hotfix input, which then forces prod approval)
      ▼
[deploy-prod]   GitHub Environment "prod" — approval + wait timer
```

Per-environment wiring lives in [`deploy/parameter.yml`](../deploy/parameter.yml):
the semantic model's data source swaps from the repo-local path to each
workspace's OneLake Lakehouse, and the dynamic-RLS `security_mapping` seed
swaps from the local demo principal to governed entitlement identities.

## Arming it (one-time, ~15 minutes with a tenant)

1. **Service principal**: `az ad sp create-for-rbac`, then in the Fabric
   admin portal allow service principals to use Fabric APIs, and grant the
   SPN Member on each workspace.
2. **GitHub Environments**: create `dev`, `qa`, `prod`; add required
   reviewers on `qa` and `prod` (and a wait timer on `prod` if policy wants
   one).
3. **Secrets**: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
   (repo-level) and `FABRIC_WORKSPACE_ID_DEV/_QA/_PROD` (one per
   environment).
4. Actions → *Deploy to Fabric* → **Run workflow**.

## Why fabric-cicd and not raw REST

The REST APIs work, but `fabric-cicd` is the supported acceleration layer
for exactly this shape — source-controlled PBIP/TMDL definitions published
idempotently (`publish_all_items` + `unpublish_all_orphan_items`), with
environment parameterization as data instead of sed scripts. Less custom
code to review, fewer places to be wrong.
