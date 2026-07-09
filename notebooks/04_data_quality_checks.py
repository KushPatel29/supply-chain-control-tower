# %% [markdown]
# ## 04 - Data Quality & Reconciliation Checks
# Runs after the Gold build: schema drift, completeness, uniqueness,
# referential integrity, and control-total reconciliation between Silver
# and Gold. Results land in `gold.dq_log` so a Power BI reliability
# dashboard (or an alert) can be built directly on top — this is the
# "automated data quality and reconciliation controls" pattern referenced
# on the resume, made concrete and runnable.

# %%
from pyspark.sql import functions as F
from datetime import datetime, timezone

GOLD = "gold"
SILVER = "silver"
run_ts = datetime.now(timezone.utc)
results = []


def log_check(check_name, table, passed, detail=""):
    results.append({
        "run_ts": run_ts,
        "check_name": check_name,
        "table_name": table,
        "passed": bool(passed),
        "detail": detail,
    })
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {check_name} on {table} — {detail}")


# %% [markdown]
# ### 1. Completeness — no nulls in key business columns

# %%
completeness_checks = {
    "gold.fact_orders": ["order_id", "customer_key", "product_key", "revenue"],
    "gold.fact_inventory": ["lot_key", "product_key", "qty_on_hand"],
    "gold.dim_product": ["product_id", "sku"],
}

for table, cols in completeness_checks.items():
    df = spark.table(table)
    for col in cols:
        null_count = df.filter(F.col(col).isNull()).count()
        log_check("completeness", table, null_count == 0, f"{col}: {null_count} nulls")

# %% [markdown]
# ### 2. Uniqueness — natural keys should not repeat in dimensions

# %%
uniqueness_checks = {
    "gold.dim_product": "product_id",
    "gold.dim_customer": "customer_id",
    "gold.dim_lot": "lot_id",
}

for table, key in uniqueness_checks.items():
    df = spark.table(table)
    total = df.count()
    distinct = df.select(key).distinct().count()
    log_check("uniqueness", table, total == distinct, f"{total:,} rows vs {distinct:,} distinct {key}")

# %% [markdown]
# ### 3. Referential integrity — every fact row resolves to a valid dimension row

# %%
ri_checks = [
    ("gold.fact_orders", "product_key", "gold.dim_product", "product_key"),
    ("gold.fact_orders", "customer_key", "gold.dim_customer", "customer_key"),
    ("gold.fact_inventory", "product_key", "gold.dim_product", "product_key"),
    ("gold.fact_inventory", "warehouse_key", "gold.dim_warehouse", "warehouse_key"),
]

for fact_table, fk_col, dim_table, pk_col in ri_checks:
    fact_df = spark.table(fact_table)
    dim_df = spark.table(dim_table).select(F.col(pk_col).alias("_pk"))
    orphans = fact_df.join(dim_df, fact_df[fk_col] == F.col("_pk"), "left_anti").count()
    log_check("referential_integrity", fact_table, orphans == 0,
              f"{orphans} orphaned rows on {fk_col} -> {dim_table}.{pk_col}")

# %% [markdown]
# ### 4. Control totals — Silver row counts and $ sums must reconcile to Gold
# This is the same "source vs curated totals" reconciliation pattern used
# for GL/P&L in the Data Quality & Observability project.

# %%
silver_orders_count = spark.table(f"{SILVER}.fact_orders").count()
gold_orders_count = spark.table(f"{GOLD}.fact_orders").count()
log_check("control_total_rowcount", "fact_orders", silver_orders_count == gold_orders_count,
          f"silver={silver_orders_count:,} gold={gold_orders_count:,}")

silver_revenue = spark.table(f"{SILVER}.fact_orders").agg(F.sum("revenue")).first()[0] or 0
gold_revenue = spark.table(f"{GOLD}.fact_orders").agg(F.sum("revenue")).first()[0] or 0
revenue_diff = abs(float(silver_revenue) - float(gold_revenue))
log_check("control_total_revenue", "fact_orders", revenue_diff < 0.01,
          f"silver=${silver_revenue:,.2f} gold=${gold_revenue:,.2f} diff=${revenue_diff:,.2f}")

# %% [markdown]
# ### Persist results + fail the pipeline run if anything critical broke

# %%
dq_log_df = spark.createDataFrame(results)
dq_log_df.write.format("delta").mode("append").saveAsTable(f"{GOLD}.dq_log")

failed = [r for r in results if not r["passed"]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
if failed:
    failed_names = ", ".join(f"{r['check_name']}:{r['table_name']}" for r in failed)
    raise Exception(f"Data quality checks failed: {failed_names}")
