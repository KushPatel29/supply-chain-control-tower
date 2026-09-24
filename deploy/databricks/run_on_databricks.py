"""Run the medallion notebooks on Databricks as a job, then hold the result to the local pipeline.

    python deploy/databricks/run_on_databricks.py --host dbc-xxxx.cloud.databricks.com \
        --warehouse-id <sql-warehouse-id> [--fresh]

The four PySpark notebooks in notebooks/ were written for Microsoft Fabric.
This script runs them, unchanged except for one line, on Databricks
(serverless compute, Unity Catalog, Delta):

1. uploads the seven raw CSVs to a Unity Catalog volume,
   /Volumes/<catalog>/landing/raw;
2. imports notebooks 01-04 into the workspace, substituting only the landing
   path (Fabric's `Files/bronze` becomes the volume);
3. creates or updates a four-task job (bronze -> silver -> gold -> data
   quality) on serverless compute and runs it twice. The silver notebook
   loads with Delta MERGE, so the second run must leave every row count as
   the first run left it;
4. compares every gold table with the local pandas mirror
   (pipeline/run_pipeline.py): row counts and the sum of every numeric
   column that is not a surrogate key, to the cent. The two pipelines hash surrogate keys
   differently (Spark `hash()` vs md5), so keys are compared by count only.

It signs in with OAuth in the browser, so no token is read or stored.
Evidence lands in docs/databricks/.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
import time
from pathlib import Path

import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service import jobs
from databricks.sdk.service.catalog import VolumeType
from databricks.sdk.service.workspace import ImportFormat, Language
from notebook_source import NOTEBOOKS, to_databricks_source

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "databricks"
RAW = ["dim_product", "dim_supplier", "dim_warehouse", "dim_customer", "dim_lot",
       "fact_inventory_snapshot", "fact_orders"]
GOLD = ["dim_product", "dim_supplier", "dim_warehouse", "dim_customer", "dim_lot", "dim_date",
        "fact_inventory", "fact_orders"]
JOB_NAME = "control-tower-medallion"
HALF_CENT = 0.005  # sums must agree to the cent


def ensure_landing(w: WorkspaceClient, catalog: str) -> str:
    try:
        w.schemas.get(f"{catalog}.landing")
    except NotFound:
        w.schemas.create(name="landing", catalog_name=catalog)
    try:
        w.volumes.read(f"{catalog}.landing.raw")
    except NotFound:
        w.volumes.create(catalog_name=catalog, schema_name="landing", name="raw",
                         volume_type=VolumeType.MANAGED)
    landing = f"/Volumes/{catalog}/landing/raw"
    for t in RAW:
        with (ROOT / "data" / "bronze" / f"{t}.csv").open("rb") as fh:
            w.files.upload(f"{landing}/{t}.csv", fh, overwrite=True)
    return landing


def import_notebooks(w: WorkspaceClient, landing: str) -> str:
    folder = f"/Workspace/Users/{w.current_user.me().user_name}/control-tower"
    w.workspace.mkdirs(folder)
    for nb in NOTEBOOKS:
        src = to_databricks_source((ROOT / "notebooks" / f"{nb}.py").read_text(encoding="utf-8"), landing)
        w.workspace.import_(f"{folder}/{nb}", format=ImportFormat.SOURCE, language=Language.PYTHON,
                            content=base64.b64encode(src.encode()).decode(), overwrite=True)
    return folder


def upsert_job(w: WorkspaceClient, folder: str) -> int:
    tasks = [jobs.Task(task_key=nb[3:], notebook_task=jobs.NotebookTask(notebook_path=f"{folder}/{nb}"),
                       depends_on=[jobs.TaskDependency(task_key=NOTEBOOKS[i - 1][3:])] if i else None)
             for i, nb in enumerate(NOTEBOOKS)]
    settings = jobs.JobSettings(name=JOB_NAME, tasks=tasks, max_concurrent_runs=1)
    existing = [j for j in w.jobs.list(name=JOB_NAME)]
    if existing:
        w.jobs.reset(job_id=existing[0].job_id, new_settings=settings)
        return existing[0].job_id
    return w.jobs.create(name=JOB_NAME, tasks=tasks, max_concurrent_runs=1).job_id


def sql(w: WorkspaceClient, warehouse: str, statement: str) -> list[list[str]]:
    r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=statement, wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"{statement}: {r.status.error}")
    return r.result.data_array or [] if r.result else []


def run_job(w: WorkspaceClient, job_id: int) -> dict:
    run = w.jobs.run_now(job_id=job_id).result(timeout=__import__("datetime").timedelta(minutes=40))
    return {"run_id": run.run_id, "state": run.state.result_state.value,
            "seconds": round((run.end_time - run.start_time) / 1000, 1),
            "tasks": {t.task_key: t.state.result_state.value for t in run.tasks}}


def counts(w: WorkspaceClient, warehouse: str, catalog: str, schema: str, tables: list[str]) -> dict[str, int]:
    return {t: int(sql(w, warehouse, f"select count(*) from {catalog}.{schema}.{t}")[0][0]) for t in tables}


def reconcile(w: WorkspaceClient, warehouse: str, catalog: str) -> list[dict]:
    rows = []
    for t in GOLD:
        local = pd.read_parquet(ROOT / "data" / "lake" / "gold" / f"{t}.parquet")
        cols = [r[0] for r in sql(w, warehouse, f"describe {catalog}.gold.{t}") if r[0] and not r[0].startswith("#")]
        types = {r[0]: r[1] for r in sql(w, warehouse, f"describe {catalog}.gold.{t}")}
        measures = [c for c in cols if not c.endswith("_key")
                    and types[c].split("(")[0] in ("int", "bigint", "double", "decimal", "float", "smallint")
                    and c in local.columns]
        exprs = ", ".join(["count(*)"] + [f"sum({c})" for c in measures])
        remote = [float(v or 0) for v in sql(w, warehouse, f"select {exprs} from {catalog}.gold.{t}")[0]]
        here = [float(len(local))] + [float(pd.to_numeric(local[c]).sum()) for c in measures]
        for m, a, b in zip(["row_count"] + measures, here, remote, strict=True):
            ok = abs(a - b) < HALF_CENT
            rows.append({"table": f"gold.{t}", "measure": m, "pandas": repr(a), "databricks": repr(b),
                         "abs_diff": f"{abs(a - b):.3g}", "match": "yes" if ok else "NO"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--warehouse-id", required=True)
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--fresh", action="store_true", help="drop bronze/silver/gold first")
    a = ap.parse_args()

    w = WorkspaceClient(host=f"https://{a.host}", auth_type="external-browser")
    if a.fresh:
        for s in ("bronze", "silver", "gold"):
            sql(w, a.warehouse_id, f"drop schema if exists {a.catalog}.{s} cascade")
    landing = ensure_landing(w, a.catalog)
    folder = import_notebooks(w, landing)
    job_id = upsert_job(w, folder)

    runs, silver_counts = [], []
    silver = ["dim_product", "dim_supplier", "dim_warehouse", "dim_customer", "dim_lot",
              "fact_inventory_snapshot", "fact_orders"]
    for _ in range(2):
        runs.append(run_job(w, job_id))
        silver_counts.append(counts(w, a.warehouse_id, a.catalog, "silver", silver))
        print(runs[-1])

    dq = sql(w, a.warehouse_id, f"select check_name, table_name, passed, detail from {a.catalog}.gold.dq_log "
                                f"where run_ts = (select max(run_ts) from {a.catalog}.gold.dq_log)")
    rows = reconcile(w, a.warehouse_id, a.catalog)

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "reconciliation.csv").open("w", newline="\n", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
    summary = {
        "engine": "Databricks Free Edition, serverless jobs compute, Unity Catalog catalog "
                  f"`{a.catalog}`, Delta tables",
        "job": JOB_NAME,
        "tasks": [nb for nb in NOTEBOOKS],
        "landing": landing.replace(a.catalog, "<catalog>"),
        "runs": [{k: v for k, v in r.items() if k != "run_id"} for r in runs],
        "silver_row_counts": {"after_run_1": silver_counts[0], "after_run_2": silver_counts[1]},
        "rerun_idempotent": silver_counts[0] == silver_counts[1],
        "dq_checks": {"total": len(dq), "passed": sum(r[2] == "true" for r in dq),
                      "failed": [f"{r[0]} on {r[1]}: {r[3]}" for r in dq if r[2] != "true"]},
        "reconciliation": {"measures": len(rows), "tables": len(GOLD),
                           "mismatches": [f"{r['table']}.{r['measure']}" for r in rows if r["match"] != "yes"]},
    }
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: summary[k] for k in ("rerun_idempotent", "dq_checks", "reconciliation")}, indent=2))
    ok = all(r["state"] == "SUCCESS" for r in runs) and summary["rerun_idempotent"] \
        and not summary["reconciliation"]["mismatches"]
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as e:
        sys.exit(f"not found: {e}")
