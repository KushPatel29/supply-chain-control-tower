# %% [markdown]
# ## 02 - Silver Transform
# Cleans and conforms Bronze tables: type casting, dedup, referential
# validation, and the FEFO/shelf-life and OTIF business logic. Writes
# Delta tables to the `silver` schema using MERGE for idempotent,
# re-runnable incremental loads (rerunning this notebook never duplicates
# rows, matching the incremental-load pattern called out on the resume).

# %%
from pyspark.sql import functions as F
from delta.tables import DeltaTable

BRONZE = "bronze"
SILVER = "silver"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER}")


def merge_into_silver(df, table_name, key_cols):
    """Upsert df into silver.<table_name> keyed on key_cols (idempotent incremental load)."""
    target_name = f"{SILVER}.{table_name}"
    if not spark.catalog.tableExists(target_name):
        df.write.format("delta").saveAsTable(target_name)
        print(f"Created {target_name} ({df.count():,} rows)")
        return

    target = DeltaTable.forName(spark, target_name)
    merge_condition = " AND ".join([f"t.{c} = s.{c}" for c in key_cols])
    (
        target.alias("t")
        .merge(df.alias("s"), merge_condition)
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(f"Merged into {target_name}")


# %% [markdown]
# ### Dimensions — light cleaning + dedup on natural key

# %%
dim_product = (
    spark.table(f"{BRONZE}.dim_product")
    .dropDuplicates(["product_id"])
    .withColumn("unit_cost", F.col("unit_cost").cast("decimal(10,2)"))
    .withColumn("unit_price", F.col("unit_price").cast("decimal(10,2)"))
    .select("product_id", "sku", "product_name", "category", "subcategory",
             "shelf_life_days", "unit_of_measure", "unit_cost", "unit_price")
)
merge_into_silver(dim_product, "dim_product", ["product_id"])

dim_supplier = spark.table(f"{BRONZE}.dim_supplier").dropDuplicates(["supplier_id"])
merge_into_silver(dim_supplier, "dim_supplier", ["supplier_id"])

dim_warehouse = spark.table(f"{BRONZE}.dim_warehouse").dropDuplicates(["warehouse_id"])
merge_into_silver(dim_warehouse, "dim_warehouse", ["warehouse_id"])

dim_customer = spark.table(f"{BRONZE}.dim_customer").dropDuplicates(["customer_id"])
merge_into_silver(dim_customer, "dim_customer", ["customer_id"])

# %% [markdown]
# ### dim_lot — referential integrity check against dim_product before merge

# %%
dim_lot_raw = spark.table(f"{BRONZE}.dim_lot").dropDuplicates(["lot_id"])

valid_product_ids = spark.table(f"{SILVER}.dim_product").select("product_id")
orphan_lots = dim_lot_raw.join(valid_product_ids, "product_id", "left_anti")
orphan_count = orphan_lots.count()
if orphan_count > 0:
    print(f"WARNING: {orphan_count} lots reference a product_id not in dim_product — dropping before merge")
    dim_lot_raw = dim_lot_raw.join(valid_product_ids, "product_id", "inner")

merge_into_silver(dim_lot_raw, "dim_lot", ["lot_id"])

# %% [markdown]
# ### fact_inventory_snapshot — FEFO / shelf-life risk calculation
# `days_until_expiry` and `expiry_risk_flag` are computed here so Gold and
# Power BI only ever consume a pre-calculated, governed risk flag —
# no business logic duplicated downstream.

# %%
inventory_raw = spark.table(f"{BRONZE}.fact_inventory_snapshot")
lot_expiry = spark.table(f"{SILVER}.dim_lot").select("lot_id", "expiry_date")

fact_inventory = (
    inventory_raw.join(lot_expiry, "lot_id", "inner")
    .withColumn("days_until_expiry", F.datediff(F.col("expiry_date"), F.col("snapshot_date")))
    .withColumn(
        "expiry_risk_flag",
        F.when(F.col("days_until_expiry") <= 2, "Critical")
        .when(F.col("days_until_expiry") <= 5, "Warning")
        .otherwise("OK"),
    )
    .drop("expiry_date")
)
merge_into_silver(fact_inventory, "fact_inventory_snapshot", ["lot_id", "snapshot_date"])

# %% [markdown]
# ### fact_orders — OTIF, fill rate, revenue/COGS/gross margin
# OTIF = shipped on/before the promised date **and** fill rate >= 95%,
# the standard combined on-time-and-in-full definition used in the KPI
# workshops this project simulates.

# %%
orders_raw = spark.table(f"{BRONZE}.fact_orders")
product_econ = spark.table(f"{SILVER}.dim_product").select("product_id", "unit_cost", "unit_price")

fact_orders = (
    orders_raw.drop("unit_price", "unit_cost")  # recompute from governed dim_product, don't trust source copy
    .join(product_econ, "product_id", "inner")
    .withColumn("fill_rate", F.round(F.col("qty_shipped") / F.col("qty_ordered"), 4))
    .withColumn(
        "otif_flag",
        F.when(
            (F.col("shipped_date") <= F.col("promised_date")) & (F.col("fill_rate") >= 0.95), 1
        ).otherwise(0),
    )
    .withColumn("revenue", F.round(F.col("qty_shipped") * F.col("unit_price"), 2))
    .withColumn("cogs", F.round(F.col("qty_shipped") * F.col("unit_cost"), 2))
    .withColumn("gross_margin", F.round(F.col("revenue") - F.col("cogs"), 2))
)
merge_into_silver(fact_orders, "fact_orders", ["order_id"])

print("Silver layer refresh complete.")
