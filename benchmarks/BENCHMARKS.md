# Scale benchmarks — proving the design at 10M rows

The README's scale section claims the medallion design holds beyond the
30k-row demo dataset. This directory measures it instead of asserting it:
[`scale_benchmark.py`](scale_benchmark.py) builds a **10,000,000-row**
`fact_orders`-shaped table and runs it through Delta Lake (delta-rs) on a
local machine. Reproduce with:

```bash
pip install deltalake pyarrow
python benchmarks/scale_benchmark.py --rows 10000000
```

## Results (10M rows, local NVMe, delta-rs 1.x)

| Operation | Result |
|---|---|
| Initial load, 20 batched appends | **1.9 s** |
| Incremental `MERGE` of a 50k-row daily delta | **0.5 s** (~4x cheaper than reloading) |
| `OPTIMIZE Z-ORDER BY (date_key, product_key)` | 5.4 s one-time |
| Point query (1 day x 1 product) before Z-order | 0.16 s — **20/20 files** are candidates |
| Same query after Z-order | **0.05 s — 1/20 files** is a candidate (95% skipped) |

![Benchmark chart](benchmark_chart.png)

## What the numbers teach

- **File skipping is a data-layout property, not a query-engine trick.** A
  table loaded in arrival order spreads every date across every file, so the
  engine must consider all 20 files for a single-day query (min/max stats
  bracket everything). Z-ordering on `(date_key, product_key)` co-locates
  rows so the same stats eliminate 19 of 20 files — measured directly from
  the Delta transaction log's per-file min/max, not inferred from timings.
- **MERGE pays off when the delta is small relative to the table.** The 50k
  daily upsert lands in 0.5 s vs 1.9 s to reload — and unlike a reload, it's
  idempotent and preserves table history (time travel). This is the same
  `whenMatchedUpdateAll / whenNotMatchedInsertAll` pattern notebook
  `02_silver_transform.py` uses in Fabric.
- **Honest caveat:** on local NVMe at 10M rows, even a full rewrite is cheap
  (1.0–1.9 s) — rewrite bandwidth only becomes the constraint on cloud
  object storage and at 100M+ rows. The pattern is what scales, and the
  file-skipping ratio (95% here) is the number that grows more valuable
  with size.

## What the 95% is worth in dollars (FinOps)

Consumption-priced engines — Fabric capacity units, Databricks DBUs,
BigQuery on-demand — all bill scan-bound workloads roughly linearly with
bytes scanned. That makes the measured file-skipping ratio translatable
into money, with assumptions stated instead of hidden:

| Assumption | Value (edit for your environment) |
|---|---|
| Fact table at production scale | 100M rows ≈ 5 GB compressed parquet |
| Scan-bound point/filter queries per day | 500 (reports, APIs, alert checks) |
| Effective scan price | $6.25/TB (BigQuery-style on-demand, *illustrative — check current rates*) |

| | Bytes scanned/day | Cost/day | Cost/year |
|---|---:|---:|---:|
| Arrival-ordered layout (every file a candidate) | 2.44 TB | $15.26 | ~$5,570 |
| Z-ordered layout (95% skipped, as measured) | 0.12 TB | $0.76 | ~$278 |

**~$5,300/year saved on one workload against one table** — from a 5.4-second
`OPTIMIZE` that runs in the maintenance window. On capacity-based pricing
(Fabric F-SKUs) the same effect shows up as headroom instead of a line item:
scan-bound consumption dropping ~95% is frequently the difference between
capacity throttling at peak and not needing the next SKU tier up.

Two smaller FinOps notes from this repo, same logic:

- **Incremental MERGE vs daily reload** (0.5s vs 1.9s at 10M rows): compute
  scales with the *delta*, not the table. At 100M+ rows the reload path is
  the one that quietly forces the bigger cluster.
- **Semantic model memory** ([MODEL_OPTIMIZATION.md](../docs/MODEL_OPTIMIZATION.md)):
  removing auto date/time cut column storage ~90%. Capacity memory is what
  Fabric SKUs actually gate — model bloat is a procurement problem wearing
  a technical costume.
