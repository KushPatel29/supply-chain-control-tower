# %% [markdown]
# ## 03 - Gold Curate
# Builds the governed star schema (see `sql/ddl_gold_star_schema.sql`) from
# Silver: surrogate keys, dim_date, and final fact tables ready for the
# Power BI semantic model. This is the only layer Power BI should ever
# query directly — Bronze/Silver stay internal.

# %%
from pyspark.sql import functions as F

SILVER = "silver"
GOLD = "gold"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {GOLD}")


def with_surrogate_key(df, natural_key_col, surrogate_col):
    return df.withColumn(surrogate_col, F.abs(F.hash(F.col(natural_key_col))))


# %% [markdown]
# ### Dimensions — add surrogate keys

# %%
dim_product = with_surrogate_key(spark.table(f"{SILVER}.dim_product"), "product_id", "product_key")
dim_product.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_product")

dim_supplier = with_surrogate_key(spark.table(f"{SILVER}.dim_supplier"), "supplier_id", "supplier_key")
dim_supplier.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_supplier")

dim_warehouse = with_surrogate_key(spark.table(f"{SILVER}.dim_warehouse"), "warehouse_id", "warehouse_key")
dim_warehouse.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_warehouse")

dim_customer = with_surrogate_key(spark.table(f"{SILVER}.dim_customer"), "customer_id", "customer_key")
dim_customer.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_customer")

dim_lot = (
    with_surrogate_key(spark.table(f"{SILVER}.dim_lot"), "lot_id", "lot_key")
    .join(dim_product.select("product_id", "product_key"), "product_id")
    .join(dim_supplier.select("supplier_id", "supplier_key"), "supplier_id")
    .join(dim_warehouse.select("warehouse_id", "warehouse_key"), "warehouse_id")
)
dim_lot.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_lot")

# %% [markdown]
# ### dim_date — spans the full range of order and snapshot dates

# %%
date_bounds = spark.table(f"{SILVER}.fact_orders").select(
    F.min("order_date").alias("min_d"), F.max("order_date").alias("max_d")
).first()

dim_date = (
    spark.sql(f"SELECT explode(sequence(to_date('{date_bounds['min_d']}'), "
              f"to_date('{date_bounds['max_d']}'), interval 1 day)) AS full_date")
    .withColumn("date_key", F.date_format("full_date", "yyyyMMdd").cast("int"))
    .withColumn("year", F.year("full_date"))
    .withColumn("quarter", F.quarter("full_date"))
    .withColumn("month", F.month("full_date"))
    .withColumn("month_name", F.date_format("full_date", "MMMM"))
    .withColumn("week_of_year", F.weekofyear("full_date"))
    .withColumn("day_of_week_name", F.date_format("full_date", "EEEE"))
)
dim_date.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.dim_date")

# %% [markdown]
# ### fact_inventory — join to surrogate keys + inventory valuation

# %%
fact_inventory = (
    spark.table(f"{SILVER}.fact_inventory_snapshot")
    .withColumn("date_key", F.date_format("snapshot_date", "yyyyMMdd").cast("int"))
    .join(dim_lot.select("lot_id", "lot_key", "product_key", "warehouse_key"), "lot_id")
    .join(dim_product.select("product_key", "unit_cost"), "product_key")
    .withColumn("inventory_value", F.round(F.col("qty_on_hand") * F.col("unit_cost"), 2))
    .select("date_key", "lot_key", "product_key", "warehouse_key",
            "qty_on_hand", "days_until_expiry", "expiry_risk_flag", "inventory_value")
)
fact_inventory.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.fact_inventory")

# %% [markdown]
# ### fact_orders — join to surrogate keys

# %%
fact_orders = (
    spark.table(f"{SILVER}.fact_orders")
    .withColumn("date_key", F.date_format("order_date", "yyyyMMdd").cast("int"))
    .join(dim_customer.select("customer_id", "customer_key"), "customer_id")
    .join(dim_product.select("product_id", "product_key"), "product_id")
    .join(dim_lot.select("lot_id", "lot_key", "warehouse_key"), "lot_id")
    .select("date_key", "order_id", "customer_key", "product_key", "lot_key", "warehouse_key",
            "qty_ordered", "qty_shipped", "fill_rate", "promised_date", "shipped_date",
            "otif_flag", "revenue", "cogs", "gross_margin")
)
fact_orders.write.format("delta").mode("overwrite").saveAsTable(f"{GOLD}.fact_orders")

print("Gold layer build complete. Point the Power BI semantic model at the `gold` schema.")
