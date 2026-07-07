# %% [markdown]
# ## 01 - Bronze Ingest
# Fabric notebook (PySpark). Reads raw CSVs from Lakehouse `Files/bronze/`
# (uploaded from `data_generator/generate_data.py`) and lands them as Delta
# tables in the Lakehouse `Tables/bronze/` area, unchanged except for
# ingestion metadata. This is the landing zone — no business logic here.
#
# Copy each `# %%` cell into its own cell in a Fabric notebook attached to
# your Lakehouse.

# %%
from pyspark.sql import functions as F

LAKEHOUSE_FILES = "Files/bronze"  # relative to the attached Lakehouse
BRONZE_SCHEMA = "bronze"

TABLES = [
    "dim_product",
    "dim_supplier",
    "dim_warehouse",
    "dim_customer",
    "dim_lot",
    "fact_inventory_snapshot",
    "fact_orders",
]

# %%
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")

for table in TABLES:
    src_path = f"{LAKEHOUSE_FILES}/{table}.csv"
    df = (
        spark.read.option("header", True)
        .option("inferSchema", True)
        .csv(src_path)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.lit(f"{table}.csv"))
    )

    (
        df.write.format("delta")
        .mode("overwrite")  # bronze is a full landing snapshot; silver handles incremental logic
        .option("overwriteSchema", "true")
        .saveAsTable(f"{BRONZE_SCHEMA}.{table}")
    )

    print(f"Landed {BRONZE_SCHEMA}.{table}: {df.count():,} rows")

# %% [markdown]
# ### Sanity check
# Row counts here should match the generator's console output exactly —
# this is the first control-total checkpoint referenced in
# `04_data_quality_checks.py`.

# %%
for table in TABLES:
    cnt = spark.table(f"{BRONZE_SCHEMA}.{table}").count()
    print(f"{BRONZE_SCHEMA}.{table}: {cnt:,} rows")
