# %% [markdown]
# ## 06 - Metadata-Driven MERGE Engine
# One parameterized notebook instead of one notebook per table. With 7 source
# tables this is tidy; with 500 it's the difference between a platform and a
# pile of copy-pasted notebooks. Table behavior — merge keys, partitioning,
# Z-ordering — lives in `config/pipeline_metadata.json` (the same file the
# local orchestrator reads), and this engine loops it, building each Delta
# MERGE dynamically.
#
# Onboarding a new source table = one JSON entry + a data contract. No code.

# %%
import json

SILVER = "silver"
BRONZE = "bronze"

metadata = json.loads(
    mssparkutils.fs.head("Files/config/pipeline_metadata.json", 1_000_000)
)["tables"]

# %%
def merge_table(table_name: str, spec: dict) -> None:
    """Build and run the MERGE for one table from its metadata entry."""
    source = spark.table(f"{BRONZE}.{table_name}")
    target_name = f"{SILVER}.{table_name}"
    keys = spec["merge_keys"]

    if "natural_key" in spec:
        source = source.dropDuplicates(spec["natural_key"])

    if not spark.catalog.tableExists(target_name):
        writer = source.write.format("delta")
        if spec.get("partition_cols"):
            writer = writer.partitionBy(*spec["partition_cols"])
        writer.saveAsTable(target_name)
        print(f"created {target_name} ({source.count():,} rows)")
        return

    on_clause = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    source.createOrReplaceTempView(f"_src_{table_name}")
    spark.sql(f"""
        MERGE INTO {target_name} t
        USING _src_{table_name} s
        ON {on_clause}
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    print(f"merged into {target_name} on ({', '.join(keys)})")


# %%
for table_name, spec in metadata.items():
    merge_table(table_name, spec)

# %%
# maintenance from the same metadata: Z-order what the config says to Z-order
for table_name, spec in metadata.items():
    cols = spec.get("z_order_cols")
    if cols:
        spark.sql(f"OPTIMIZE {SILVER}.{table_name} ZORDER BY ({', '.join(cols)})")
        print(f"z-ordered {SILVER}.{table_name} by {cols}")

print("metadata-driven merge complete — table count is a config property now")
