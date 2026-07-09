# Fabric Data Pipeline Spec — `pl_control_tower_nightly`

Orchestration layer for the medallion notebooks. Build this as a **Data
Pipeline** in the Fabric workspace (Data Factory experience) — pipeline
definitions export as workspace-specific JSON, so like the SSIS/SSRS specs
in the migration project, this documents exactly what to build in the
designer rather than shipping JSON that won't import cleanly elsewhere.

## Activities and dependency chain

```
[Notebook: 01_bronze_ingest]
        | on success
[Notebook: 02_silver_transform]
        | on success
[Notebook: 03_gold_curate]
        | on success
[Notebook: 04_data_quality_checks]
        | on success                        | on failure
[Semantic model refresh]            [Teams/Outlook alert:
        | on failure                 "DQ checks failed — gold NOT refreshed"]
[Teams/Outlook alert:
 "Refresh failed"]
```

Two design decisions worth defending in an interview:

1. **The semantic model refresh depends on the DQ notebook succeeding.**
   `04_data_quality_checks.py` raises when a critical check fails, which
   fails its activity, which blocks the refresh — a broken load can never
   silently reach an executive dashboard. Data quality is a gate, not a
   report.
2. **Alert on the failure edge, not by polling.** Each stage's failure path
   posts to a Teams channel (Teams activity or Office 365 Outlook activity)
   with the pipeline run ID and the failed activity name, so triage starts
   from the alert, not from a stakeholder noticing stale numbers.

## Activity settings

| Activity | Type | Timeout | Retry | Retry interval |
|---|---|---|---|---|
| 01_bronze_ingest | Notebook | 30 min | 2 | 5 min |
| 02_silver_transform | Notebook | 30 min | 2 | 5 min |
| 03_gold_curate | Notebook | 30 min | 2 | 5 min |
| 04_data_quality_checks | Notebook | 15 min | 0 | — |
| Semantic model refresh | Semantic model refresh activity | 30 min | 1 | 10 min |

DQ gets **zero retries** deliberately: a failed quality check is
deterministic — retrying it just delays the alert. Transient-failure
retries belong on the load stages, where they actually help.

## Schedule

- **Trigger**: Daily at 05:00 America/Vancouver (before the 6am refresh SLA
  in [`metric_dictionary.md`](metric_dictionary.md)).
- **Concurrency**: 1 (a slow run must not overlap the next one; Delta MERGE
  is idempotent, but overlapping runs waste capacity and confuse lineage).

## Monitoring

- Pipeline run history is the first stop; each notebook logs row counts to
  stdout and DQ results to `gold.dq_log`.
- The Power BI "Data Quality" report page reads `gold.dq_log`, so DQ trends
  (pass rate over time, which checks fail most) are visible to consumers,
  not just the data team.
