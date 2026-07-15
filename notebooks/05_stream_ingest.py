# %% [markdown]
# ## 05 - Streaming Ingest (Spark Structured Streaming)
# The near-real-time entry point: order-event files land continuously in
# `Files/bronze/stream_landing/` (dropped by an integration service, or an
# Event Hub/Kafka sink writing micro-batch files) and stream incrementally
# into the Bronze Delta table with exactly-once semantics — the checkpoint
# tracks which files have been consumed, so restarts never double-ingest.
#
# This is the plain Structured Streaming file source, which runs on Fabric
# Spark as-is. On Databricks the same pattern is `format("cloudFiles")`
# (Autoloader), which adds scalable file notification; the contract —
# incremental discovery + checkpointed exactly-once — is identical, and
# `pipeline/stream_ingest.py` implements the same contract locally so the
# pattern is testable without a cluster.

# %%
from pyspark.sql.types import (DoubleType, IntegerType, StringType,
                               StructField, StructType)

LANDING = "Files/bronze/stream_landing/"
CHECKPOINT = "Files/checkpoints/orders_stream/"
BRONZE_TABLE = "bronze.fact_orders_stream"

bronze_schema = StructType([
    StructField("order_id", IntegerType()),
    StructField("order_date", StringType()),
    StructField("customer_id", IntegerType()),
    StructField("product_id", IntegerType()),
    StructField("lot_id", IntegerType()),
    StructField("warehouse_id", IntegerType()),
    StructField("qty_ordered", IntegerType()),
    StructField("qty_shipped", DoubleType()),
    StructField("promised_date", StringType()),
    StructField("shipped_date", StringType()),
    StructField("unit_price", DoubleType()),
    StructField("unit_cost", DoubleType()),
])

# %%
streaming_df = (
    spark.readStream
    .format("csv")                      # on Databricks: .format("cloudFiles")
    .option("header", "true")           #   .option("cloudFiles.format", "csv")
    .schema(bronze_schema)              # explicit schema: no inference drift
    .load(LANDING)
)

# %%
# availableNow: drain everything new, then stop — the scheduled micro-batch
# pattern (swap for .trigger(processingTime="1 minute") for a hot stream).
query = (
    streaming_df.writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", CHECKPOINT)
    .trigger(availableNow=True)
    .toTable(BRONZE_TABLE)
)
query.awaitTermination()

# %%
# Downstream, 02_silver_transform's MERGE picks these rows up idempotently —
# the streaming path and the batch path converge on the same Silver tables.
print(f"stream drained into {BRONZE_TABLE}")
