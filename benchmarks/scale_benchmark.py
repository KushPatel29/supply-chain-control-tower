"""
Scale proof: the README claims the medallion design holds at 10M+ rows —
this script actually measures it, locally, on Delta Lake (delta-rs).

Benchmarked on a 10M-row fact_orders-shaped table:

  1. full overwrite write            (the naive daily rebuild)
  2. incremental Delta MERGE         (the pattern notebooks 02/03 use: upsert
                                      only the day's ~50k changed rows)
  3. OPTIMIZE Z-ORDER BY             (date_key, product_key)
  4. selective query before/after    (single day + single product), timing
                                     plus candidate-file counts from Delta's
                                     min/max stats — the file-skipping effect
                                     Z-ordering exists to create

Outputs: benchmarks/results.json, benchmarks/benchmark_chart.png, and the
numbers quoted in BENCHMARKS.md.

Usage:
    python benchmarks/scale_benchmark.py --rows 10000000
"""

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

ROOT = Path(__file__).resolve().parent
LAKE = ROOT / "_bench_lake"

RNG = np.random.default_rng(7)


def build_orders(rows: int) -> pa.Table:
    """fact_orders-shaped frame: 2 years x 500 products x 8 warehouses."""
    date_keys = pd.date_range("2024-01-01", periods=730, freq="D").strftime("%Y%m%d").astype(int)
    df = pd.DataFrame({
        "date_key": RNG.choice(date_keys, rows),
        "order_id": np.arange(rows, dtype=np.int64),
        "product_key": RNG.integers(1, 501, rows),
        "warehouse_key": RNG.integers(1, 9, rows),
        "customer_key": RNG.integers(1, 5001, rows),
        "qty_shipped": RNG.integers(1, 500, rows),
        "revenue": np.round(RNG.gamma(2.0, 180.0, rows), 2),
        "otif_flag": RNG.integers(0, 2, rows),
    })
    return pa.Table.from_pandas(df, preserve_index=False)


def candidate_files(dt: DeltaTable, date_key: int, product_key: int) -> tuple[int, int]:
    """How many files could contain the predicate, per Delta min/max stats."""
    adds = pa.table(dt.get_add_actions(flatten=True)).to_pandas()
    total = len(adds)
    dmin, dmax = adds["min.date_key"], adds["max.date_key"]
    pmin, pmax = adds["min.product_key"], adds["max.product_key"]
    hits = ((dmin <= date_key) & (dmax >= date_key)
            & (pmin <= product_key) & (pmax >= product_key)).sum()
    return int(hits), total


def timed_query(dt: DeltaTable, date_key: int, product_key: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    ds = dt.to_pyarrow_dataset()
    out = ds.to_table(filter=((pa.dataset.field("date_key") == date_key)
                              & (pa.dataset.field("product_key") == product_key)))
    return time.perf_counter() - t0, out.num_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10_000_000)
    args = ap.parse_args()

    if LAKE.exists():
        shutil.rmtree(LAKE)
    results: dict = {"rows": args.rows}

    print(f"building {args.rows:,}-row orders table ...")
    t0 = time.perf_counter()
    tbl = build_orders(args.rows)
    results["build_seconds"] = round(time.perf_counter() - t0, 1)

    # 1. initial load as 20 batched appends — the realistic shape of a table
    # loaded daily, where every file ends up spanning many dates (the exact
    # layout problem Z-ordering fixes)
    n_batches = 20
    step = args.rows // n_batches
    t0 = time.perf_counter()
    for i in range(n_batches):
        write_deltalake(LAKE, tbl.slice(i * step, step),
                        mode="overwrite" if i == 0 else "append")
    results["full_load_seconds"] = round(time.perf_counter() - t0, 1)
    results["load_batches"] = n_batches
    print(f"initial load ({n_batches} batches): {results['full_load_seconds']}s")

    # 2. incremental MERGE of a daily 0.5% batch (half updates, half inserts)
    batch_n = args.rows // 200
    upd = tbl.slice(0, batch_n // 2).to_pandas()
    upd["revenue"] = np.round(upd["revenue"] * 1.1, 2)
    ins = tbl.slice(0, batch_n - batch_n // 2).to_pandas()
    ins["order_id"] = ins["order_id"] + args.rows  # brand-new keys
    batch = pa.Table.from_pandas(pd.concat([upd, ins]), preserve_index=False)

    dt = DeltaTable(LAKE)
    t0 = time.perf_counter()
    (dt.merge(batch, "t.order_id = s.order_id", source_alias="s", target_alias="t")
       .when_matched_update_all()
       .when_not_matched_insert_all()
       .execute())
    results["merge_batch_rows"] = batch_n
    results["incremental_merge_seconds"] = round(time.perf_counter() - t0, 1)
    print(f"incremental MERGE of {batch_n:,} rows: {results['incremental_merge_seconds']}s")

    # 3. query before Z-order
    dt = DeltaTable(LAKE)
    date_key, product_key = 20240915, 250
    q_before, nrows = timed_query(dt, date_key, product_key)
    files_before, total_before = candidate_files(dt, date_key, product_key)
    results["query_before_zorder_seconds"] = round(q_before, 2)
    results["candidate_files_before"] = files_before
    results["total_files_before"] = total_before
    print(f"query before z-order: {q_before:.2f}s "
          f"({files_before}/{total_before} candidate files, {nrows} rows)")

    # 4. OPTIMIZE Z-ORDER + query after
    t0 = time.perf_counter()
    dt.optimize.z_order(["date_key", "product_key"])
    results["zorder_seconds"] = round(time.perf_counter() - t0, 1)

    dt = DeltaTable(LAKE)
    q_after, nrows2 = timed_query(dt, date_key, product_key)
    files_after, total_after = candidate_files(dt, date_key, product_key)
    results["query_after_zorder_seconds"] = round(q_after, 2)
    results["candidate_files_after"] = files_after
    results["total_files_after"] = total_after
    assert nrows == nrows2, "z-order must not change query results"
    print(f"z-order: {results['zorder_seconds']}s; query after: {q_after:.2f}s "
          f"({files_after}/{total_after} candidate files)")

    (ROOT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # chart
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].bar([f"full load\n({n_batches} batches)", f"MERGE\n({batch_n:,} rows)"],
                [results["full_load_seconds"], results["incremental_merge_seconds"]],
                color=["#9AA5B1", "#12436D"])
    axes[0].set_title(f"Daily load strategy at {args.rows / 1e6:.0f}M rows (seconds)",
                      fontsize=10, fontweight="bold", color="#12436D", loc="left")
    for i, v in enumerate([results["full_load_seconds"],
                           results["incremental_merge_seconds"]]):
        axes[0].text(i, v, f" {v}s", ha="center", va="bottom", fontweight="bold")
    axes[1].bar(["before\nZ-order", "after\nZ-order"],
                [results["query_before_zorder_seconds"], results["query_after_zorder_seconds"]],
                color=["#9AA5B1", "#28A197"])
    axes[1].set_title("Point query: 1 day x 1 product (seconds)",
                      fontsize=10, fontweight="bold", color="#12436D", loc="left")
    for i, v in enumerate([results["query_before_zorder_seconds"],
                           results["query_after_zorder_seconds"]]):
        axes[1].text(i, v, f" {v}s", ha="center", va="bottom", fontweight="bold")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(ROOT / "benchmark_chart.png", dpi=130)
    print(f"wrote results.json + benchmark_chart.png -> {ROOT}")

    shutil.rmtree(LAKE)  # keep the repo light; numbers + chart are the artifact


if __name__ == "__main__":
    main()
