"""Measure equivalent SQL over a temporary, partitioned orders-shaped dataset.

Run: python benchmarks/query_performance.py --rows 1000000 --repeats 7
This adds evidence; it never changes the existing Delta benchmark or live data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
START = date(2024, 7, 1)
LOWER = (date(2025, 6, 1) - START).days
UPPER = (date(2025, 7, 1) - START).days


def oracle(rows: int) -> list[tuple[int, int, int, int]]:
    """Independent integer calculation: no SQL, parquet or benchmark queries."""
    groups = defaultdict(lambda: [0, 0])
    for i in range(rows):
        if LOWER <= i % 730 < UPPER:
            key = (i % 150 + 1, i % 10 + 1)
            qty = i % 17 + 1
            groups[key][0] += qty
            groups[key][1] += qty * (199 + i % 4000)
    return [(p, w, *totals) for (p, w), totals in sorted(groups.items())]


def queries() -> dict[str, str]:
    aggregate = """SELECT product_key, warehouse_key,
        sum(qty)::BIGINT AS units, sum(qty * price_cents)::BIGINT AS revenue_cents
        FROM orders WHERE {predicate}
        GROUP BY product_key, warehouse_key ORDER BY product_key, warehouse_key"""
    return {
        "formatted_date_filter": aggregate.format(
            predicate="strftime(order_date, '%Y-%m') = '2025-06'"
        ),
        "partition_and_range_filter": aggregate.format(
            predicate="year=2025 AND month=6 AND order_date >= DATE '2025-06-01' "
            "AND order_date < DATE '2025-07-01'"
        ),
    }


def measure(rows: int = 1_000_000, repeats: int = 7) -> dict:
    if not 10_000 <= rows <= 10_000_000 or repeats < 3 or repeats > 30:
        raise ValueError("rows must be 10k–10M; repeats must be 3–30")
    expected = oracle(rows)
    sql = queries()
    samples = {name: [] for name in sql}
    plans = {}
    with tempfile.TemporaryDirectory(prefix="control-tower-query-") as tmp:
        lake = (Path(tmp) / "orders").as_posix().replace("'", "''")
        con = duckdb.connect()
        try:
            con.execute("SET threads=2")
            con.execute("SET memory_limit='512MB'")
            con.execute(f"""COPY (
                SELECT i AS order_id,
                    DATE '2024-07-01' + (i % 730)::INTEGER AS order_date,
                    (i % 150 + 1)::INTEGER AS product_key,
                    (i % 10 + 1)::INTEGER AS warehouse_key,
                    (i % 17 + 1)::BIGINT AS qty,
                    (199 + i % 4000)::BIGINT AS price_cents,
                    year(order_date) AS year, month(order_date) AS month
                FROM range({rows}) AS t(i)
            ) TO '{lake}' (FORMAT PARQUET, PARTITION_BY (year, month))""")
            con.execute(f"CREATE VIEW orders AS SELECT * FROM read_parquet('{lake}/**/*.parquet', hive_partitioning=true)")
            for name, query in sql.items():
                if con.execute(query).fetchall() != expected:
                    raise AssertionError(f"{name}: independent oracle mismatch")
                plans[name] = "\n".join(str(row[-1]) for row in con.execute(
                    "EXPLAIN ANALYZE " + query
                ).fetchall())
            rng = random.Random(29)
            schedule = list(sql) * repeats
            rng.shuffle(schedule)
            for name in schedule:
                start = time.perf_counter_ns()
                actual = con.execute(sql[name]).fetchall()
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
                if actual != expected:
                    raise AssertionError(f"{name}: timed execution changed results")
                samples[name].append(elapsed_ms)
        finally:
            con.close()
    medians = {name: statistics.median(values) for name, values in samples.items()}
    return {
        "schema_version": 1,
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "environment": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                        "os": platform.system(), "threads": 2, "memory_limit": "512MB"},
        "boundary": "Local synthetic orders-shaped parquet; warm-process timings, not enterprise or cold-storage performance. No DAX timings are inferred.",
        "rows": rows, "repeats_per_query": repeats, "warmups_per_query": 1,
        "timing_schedule": schedule, "samples_ms": samples, "median_ms": medians,
        "baseline_over_partitioned_median": medians["formatted_date_filter"] / medians["partition_and_range_filter"],
        "queries": sql, "plans": plans,
        "result": {"groups": len(expected), "units": sum(r[2] for r in expected),
                   "revenue_cents": sum(r[3] for r in expected),
                   "sha256": hashlib.sha256(json.dumps(expected).encode()).hexdigest(),
                   "independent_oracle_equal": True},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path, default=ROOT / "query_performance.json")
    args = parser.parse_args()
    result = measure(args.rows, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("rows", "median_ms", "result")}))


if __name__ == "__main__":
    main()
