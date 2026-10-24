"""Compare equivalent shuffle and broadcast joins under an explicit skew.

Run with Java 17+ and pyspark==4.0.1. CI runs a bounded local[2] Spark engine;
this is not a managed-cluster or enterprise-scale performance claim.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


def bounds(rows, repeats):
    if not 10 <= rows <= 1_000_000 or not 3 <= repeats <= 10:
        raise ValueError("Use 10–1M rows and 3–10 repeats")


def oracle(rows):
    totals = defaultdict(lambda: [0, 0])
    for i in range(rows):
        warehouse = 1 if i % 10 < 8 else i % 9 + 2
        region = (warehouse - 1) % 5
        qty = i % 17 + 1
        totals[region][0] += qty
        totals[region][1] += qty * ((199 + i % 4000) - (99 + i % 1000))
    return [(region, *values) for region, values in sorted(totals.items())]


def run(rows=200_000, repeats=3):
    bounds(rows, repeats)
    from pyspark.sql import SparkSession, functions as f

    spark = (
        SparkSession.builder.master("local[2]")
        .appName("control-tower-join-evidence")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.adaptive.enabled", "false")
        .config("spark.sql.autoBroadcastJoinThreshold", "-1")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    try:
        fact = (
            spark.range(rows)
            .selectExpr(
                "id",
                "CASE WHEN id % 10 < 8 THEN 1 ELSE id % 9 + 2 END AS warehouse_key",
                "id % 17 + 1 AS qty",
                "199 + id % 4000 AS price_cents",
                "99 + id % 1000 AS cost_cents",
            )
            .cache()
        )
        fact.count()
        dimensions = spark.range(1, 11).selectExpr(
            "id AS warehouse_key", "(id - 1) % 5 AS region"
        )
        variants = {}
        for name, dimension in (
            ("shuffle_join", dimensions.hint("merge")),
            ("broadcast_dimension", f.broadcast(dimensions)),
        ):
            variants[name] = (
                fact.join(dimension, "warehouse_key")
                .groupBy("region")
                .agg(
                    f.sum("qty").alias("units"),
                    f.sum(
                        f.col("qty") * (f.col("price_cents") - f.col("cost_cents"))
                    ).alias("margin_cents"),
                )
                .orderBy("region")
            )
        expected = oracle(rows)
        plans, samples = {}, {name: [] for name in variants}
        for name, query in variants.items():
            assert [tuple(row) for row in query.collect()] == expected, name
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                query.explain(mode="formatted")
            plans[name] = buffer.getvalue()
        assert "SortMergeJoin" in plans["shuffle_join"]
        assert "BroadcastHashJoin" in plans["broadcast_dimension"]
        order = list(variants) * repeats
        random.Random(29).shuffle(order)
        for name in order:
            start = time.perf_counter_ns()
            actual = [tuple(row) for row in variants[name].collect()]
            elapsed = (time.perf_counter_ns() - start) / 1e6
            assert actual == expected
            samples[name].append(elapsed)
        partitions = fact.repartition(8, "warehouse_key").withColumn(
            "partition", f.spark_partition_id()
        )
        observed = {
            int(row["partition"]): int(row["count"])
            for row in partitions.groupBy("partition").count().collect()
        }
        return {
            "schema_version": 1,
            "executed_at_utc": datetime.now(UTC).isoformat(),
            "engine": spark.version,
            "master": spark.sparkContext.master,
            "rows": rows,
            "repeats_per_variant": repeats,
            "warmups_per_variant": 1,
            "samples_ms": samples,
            "median_ms": {k: statistics.median(v) for k, v in samples.items()},
            "partition_rows": [observed.get(i, 0) for i in range(8)],
            "plans": plans,
            "result": expected,
            "independent_oracle_equal": True,
            "boundary": "Bounded CI/local[2], cached synthetic fact and 10-row dimension, AQE disabled to isolate join strategy. Not Databricks cluster tuning, cloud cost or production throughput.",
        }
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("spark_tuning.json")
    )
    args = parser.parse_args()
    result = run(args.rows, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "engine",
                    "master",
                    "rows",
                    "median_ms",
                    "independent_oracle_equal",
                )
            }
        )
    )
