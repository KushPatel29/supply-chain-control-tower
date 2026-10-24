# SQL performance: preserve the answer, then measure the work

`python benchmarks/query_performance.py --rows 1000000 --repeats 7`

The workload aggregates June 2025 shipped units and revenue at product/warehouse
grain over a deterministic orders-shaped parquet dataset. The first query applies
a formatted-date predicate; the second makes the same half-open date range and
physical year/month partitions explicit. Integer cents avoid rounding drift.
An independent Python calculation verifies every group before and during timing.

[Observed run, including raw plans and timings](query_performance.json).
There is one untimed warmup per variant and a seeded, interleaved measurement
schedule. Read the median and all repeated observations together. CI checks
equivalence on a small dataset; it does not require a speedup on shared hardware.

The optimization is justified when the plan eliminates files or work for a
selective partition-aligned query. It need not help an all-history query. Layout
maintenance, write amplification, partition granularity and the access pattern
must be considered before changing a production lake. This is a local synthetic
parquet exercise; a timing ratio is neither cloud cost savings nor DAX performance.

The [existing Delta 10M-row study](BENCHMARKS.md) and the
[measured Desktop model-storage optimization](../docs/MODEL_OPTIMIZATION.md)
remain separate evidence. DAX query latency still needs actual engine execution;
no Python or SQL proxy is presented as that measurement.

Engine interpretation: [DuckDB profiling documentation](https://duckdb.org/docs/stable/dev/profiling).

## Spark join strategy and skew

`spark_tuning.py` runs the same regional unit/margin calculation through a forced
shuffle join and a broadcast of a ten-row dimension. An independent Python
integer oracle checks each output. It records repeated warm-process timings,
formatted physical plans and actual row distribution across eight hash partitions
under an explicit 80% hot-warehouse key. AQE and automatic broadcast are disabled
to isolate the chosen strategy; neither setting is a production recommendation.

The `spark-join-tuning` CI job supplies Java 17 and PySpark 4.0.1 and uploads the
execution evidence. The measurement is local[2] on an ephemeral runner. Broadcasting
is appropriate only when the dimension fits worker memory; growth can reverse
the tradeoff. This does not establish managed Databricks tuning or cluster tenure.
