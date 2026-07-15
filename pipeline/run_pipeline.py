"""
Medallion pipeline orchestrator — the runnable mirror of the Fabric DAG.

Executes the same stage graph the Fabric Data Pipeline (docs/fabric_pipeline_spec.md)
orchestrates, entirely locally in pandas:

    bronze_ingest -> silver_transform -> gold_curate -> data_quality_checks
                                                              |
                                             [GATE: any CRITICAL failure?]
                                              yes -> HALT, exit 2, no publish
                                              no  -> publish_semantic_model

The gate is the point. In Fabric, the DQ notebook's output feeds an If
Condition activity that blocks the semantic-model refresh and fires a
Teams/email alert when a critical check fails; here the same rule guards a
publish marker and the process exit code, and CI proves the gate actually
trips by injecting a duplicate-key failure (`--inject-dq-failure`).

Transform logic is line-for-line the business rules of the PySpark
notebooks (FEFO expiry risk, OTIF, margin, surrogate keys) so the local
lake in data/lake/ matches what Fabric's gold schema would hold.

Usage:
    python pipeline/run_pipeline.py                       # full run
    python pipeline/run_pipeline.py --inject-dq-failure   # prove the gate trips
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BRONZE_SRC = ROOT / "data" / "bronze"

CRITICAL = "critical"
WARNING = "warning"


def _surrogate(series: pd.Series) -> pd.Series:
    """Deterministic surrogate key from a natural key (mirrors gold notebook)."""
    return series.astype(str).map(
        lambda s: int(hashlib.md5(s.encode()).hexdigest()[:12], 16))


# --------------------------------------------------------------- stages

def bronze_ingest(lake: Path) -> dict:
    out = lake / "bronze"
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for csv in sorted(BRONZE_SRC.glob("*.csv")):
        df = pd.read_csv(csv)
        df.to_parquet(out / f"{csv.stem}.parquet", index=False)
        counts[csv.stem] = len(df)
    return counts


def silver_transform(lake: Path) -> dict:
    src, out = lake / "bronze", lake / "silver"
    out.mkdir(exist_ok=True)
    t = {p.stem: pd.read_parquet(p) for p in src.glob("*.parquet")}

    # dimensions: dedup on natural key
    dims = {"dim_product": "product_id", "dim_supplier": "supplier_id",
            "dim_warehouse": "warehouse_id", "dim_customer": "customer_id"}
    for name, key in dims.items():
        t[name] = t[name].drop_duplicates(key)

    # dim_lot: referential check against dim_product before load
    lots = t["dim_lot"].drop_duplicates("lot_id")
    t["dim_lot"] = lots[lots["product_id"].isin(t["dim_product"]["product_id"])]

    # fact_inventory_snapshot: FEFO / shelf-life risk
    inv = t["fact_inventory_snapshot"].merge(
        t["dim_lot"][["lot_id", "expiry_date"]], on="lot_id", how="inner")
    inv["days_until_expiry"] = (
        pd.to_datetime(inv["expiry_date"]) - pd.to_datetime(inv["snapshot_date"])).dt.days
    inv["expiry_risk_flag"] = pd.cut(
        inv["days_until_expiry"], bins=[-10_000, 2, 5, 10_000],
        labels=["Critical", "Warning", "OK"]).astype(str)
    t["fact_inventory_snapshot"] = inv.drop(columns=["expiry_date"])

    # fact_orders: OTIF, fill rate, economics from governed dim_product
    orders = t["fact_orders"].drop(columns=["unit_price", "unit_cost"], errors="ignore")
    orders = orders.merge(
        t["dim_product"][["product_id", "unit_cost", "unit_price"]],
        on="product_id", how="inner")
    orders["fill_rate"] = (orders["qty_shipped"] / orders["qty_ordered"]).round(4)
    on_time = pd.to_datetime(orders["shipped_date"]) <= pd.to_datetime(orders["promised_date"])
    orders["otif_flag"] = ((on_time) & (orders["fill_rate"] >= 0.95)).astype(int)
    orders["revenue"] = (orders["qty_shipped"] * orders["unit_price"]).round(2)
    orders["cogs"] = (orders["qty_shipped"] * orders["unit_cost"]).round(2)
    orders["gross_margin"] = (orders["revenue"] - orders["cogs"]).round(2)
    t["fact_orders"] = orders

    for name, df in t.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    return {name: len(df) for name, df in t.items()}


def gold_curate(lake: Path, inject_dq_failure: bool = False) -> dict:
    src, out = lake / "silver", lake / "gold"
    out.mkdir(exist_ok=True)
    t = {p.stem: pd.read_parquet(p) for p in src.glob("*.parquet")}

    sk = {"dim_product": ("product_id", "product_key"),
          "dim_supplier": ("supplier_id", "supplier_key"),
          "dim_warehouse": ("warehouse_id", "warehouse_key"),
          "dim_customer": ("customer_id", "customer_key"),
          "dim_lot": ("lot_id", "lot_key")}
    for name, (nk, key) in sk.items():
        t[name][key] = _surrogate(t[name][nk])

    # dim_lot carries product/supplier/warehouse surrogate keys
    t["dim_lot"] = (t["dim_lot"]
                    .merge(t["dim_product"][["product_id", "product_key"]], on="product_id")
                    .merge(t["dim_supplier"][["supplier_id", "supplier_key"]], on="supplier_id")
                    .merge(t["dim_warehouse"][["warehouse_id", "warehouse_key"]], on="warehouse_id"))

    if inject_dq_failure:
        # deliberately duplicate a product natural key so the DQ stage trips
        t["dim_product"] = pd.concat([t["dim_product"], t["dim_product"].head(1)],
                                     ignore_index=True)

    # dim_date spine across order dates
    od = pd.to_datetime(t["fact_orders"]["order_date"])
    spine = pd.date_range(od.min(), od.max(), freq="D")
    dim_date = pd.DataFrame({"full_date": spine})
    dim_date["date_key"] = dim_date["full_date"].dt.strftime("%Y%m%d").astype(int)
    dim_date["year"] = dim_date["full_date"].dt.year
    dim_date["quarter"] = dim_date["full_date"].dt.quarter
    dim_date["month"] = dim_date["full_date"].dt.month
    dim_date["month_name"] = dim_date["full_date"].dt.month_name()
    dim_date["week_of_year"] = dim_date["full_date"].dt.isocalendar().week.astype(int)
    dim_date["day_of_week_name"] = dim_date["full_date"].dt.day_name()

    inv = (t["fact_inventory_snapshot"]
           .assign(date_key=lambda d: pd.to_datetime(d["snapshot_date"]).dt.strftime("%Y%m%d").astype(int))
           .merge(t["dim_lot"][["lot_id", "lot_key", "product_key", "warehouse_key"]], on="lot_id")
           .merge(t["dim_product"][["product_key", "unit_cost"]], on="product_key"))
    inv["inventory_value"] = (inv["qty_on_hand"] * inv["unit_cost"]).round(2)
    fact_inventory = inv[["date_key", "lot_key", "product_key", "warehouse_key",
                          "qty_on_hand", "days_until_expiry", "expiry_risk_flag",
                          "inventory_value"]]

    fo = (t["fact_orders"]
          .assign(date_key=lambda d: pd.to_datetime(d["order_date"]).dt.strftime("%Y%m%d").astype(int))
          .merge(t["dim_customer"][["customer_id", "customer_key"]], on="customer_id")
          .merge(t["dim_product"][["product_id", "product_key"]], on="product_id")
          .merge(t["dim_lot"][["lot_id", "lot_key", "warehouse_key"]], on="lot_id"))
    fact_orders = fo[["date_key", "order_id", "customer_key", "product_key", "lot_key",
                      "warehouse_key", "qty_ordered", "qty_shipped", "fill_rate",
                      "promised_date", "shipped_date", "otif_flag",
                      "revenue", "cogs", "gross_margin"]]

    gold = {"dim_product": t["dim_product"], "dim_supplier": t["dim_supplier"],
            "dim_warehouse": t["dim_warehouse"], "dim_customer": t["dim_customer"],
            "dim_lot": t["dim_lot"], "dim_date": dim_date,
            "fact_inventory": fact_inventory, "fact_orders": fact_orders}
    for name, df in gold.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    return {name: len(df) for name, df in gold.items()}


def data_quality_checks(lake: Path) -> list[dict]:
    """Mirror of notebook 04, with severity levels. Returns the check log."""
    gold = {p.stem: pd.read_parquet(p) for p in (lake / "gold").glob("*.parquet")}
    silver_orders = pd.read_parquet(lake / "silver" / "fact_orders.parquet")
    log: list[dict] = []

    def check(name, table, passed, severity, detail=""):
        log.append({"run_ts": datetime.now(timezone.utc).isoformat(),
                    "check_name": name, "table_name": table,
                    "passed": bool(passed), "severity": severity, "detail": detail})

    # completeness (critical)
    for table, cols in {"fact_orders": ["order_id", "customer_key", "product_key", "revenue"],
                        "fact_inventory": ["lot_key", "product_key", "qty_on_hand"],
                        "dim_product": ["product_id", "sku"]}.items():
        for col in cols:
            nulls = int(gold[table][col].isna().sum())
            check("completeness", table, nulls == 0, CRITICAL, f"{col}: {nulls} nulls")

    # uniqueness of natural and surrogate keys (critical)
    for table, key in {"dim_product": "product_id", "dim_customer": "customer_id",
                       "dim_lot": "lot_id"}.items():
        df = gold[table]
        dupes = len(df) - df[key].nunique()
        check("uniqueness", table, dupes == 0, CRITICAL, f"{dupes} duplicate {key}")
    for table, key in {"dim_product": "product_key", "dim_lot": "lot_key"}.items():
        df = gold[table]
        dupes = len(df) - df[key].nunique()
        check("surrogate_uniqueness", table, dupes == 0, CRITICAL, f"{dupes} duplicate {key}")

    # referential integrity (critical)
    for fact, fk, dim, pk in [("fact_orders", "product_key", "dim_product", "product_key"),
                              ("fact_orders", "customer_key", "dim_customer", "customer_key"),
                              ("fact_inventory", "product_key", "dim_product", "product_key"),
                              ("fact_inventory", "warehouse_key", "dim_warehouse", "warehouse_key")]:
        orphans = int((~gold[fact][fk].isin(gold[dim][pk])).sum())
        check("referential_integrity", fact, orphans == 0, CRITICAL,
              f"{orphans} orphans on {fk} -> {dim}.{pk}")

    # control-total reconciliation silver -> gold (critical)
    s_rev, g_rev = silver_orders["revenue"].sum(), gold["fact_orders"]["revenue"].sum()
    check("reconciliation", "fact_orders", abs(s_rev - g_rev) < 0.01, CRITICAL,
          f"silver {s_rev:,.2f} vs gold {g_rev:,.2f}")

    # freshness (warning): newest order within 45 days of today's synthetic window
    newest = pd.to_datetime(silver_orders["order_date"]).max()
    age_days = (pd.Timestamp.now() - newest).days
    check("freshness", "fact_orders", age_days <= 45, WARNING,
          f"newest order {newest.date()} ({age_days}d old)")

    pd.DataFrame(log).to_csv(lake / "gold" / "dq_log.csv", index=False)
    return log


def publish_semantic_model(lake: Path) -> str:
    """The gated stage. Locally this stamps the publish marker Power BI reads;
    in Fabric this is the semantic-model refresh activity the If Condition
    protects."""
    marker = lake / "gold" / "_PUBLISHED"
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return str(marker)


# --------------------------------------------------------------- runner

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"),
                    help="where the medallion layers are materialized")
    ap.add_argument("--inject-dq-failure", action="store_true",
                    help="deliberately break gold to prove the DQ gate halts the publish")
    args = ap.parse_args(argv)
    lake = Path(args.lake_dir)

    stages = [
        ("bronze_ingest", lambda: bronze_ingest(lake)),
        ("silver_transform", lambda: silver_transform(lake)),
        ("gold_curate", lambda: gold_curate(lake, args.inject_dq_failure)),
    ]
    run_log = []
    for name, fn in stages:
        t0 = time.perf_counter()
        result = fn()
        secs = time.perf_counter() - t0
        run_log.append({"stage": name, "seconds": round(secs, 2), "tables": result})
        print(f"[OK]   {name:<18} {secs:5.2f}s  {sum(result.values()):,} rows")

    dq = data_quality_checks(lake)
    criticals = [c for c in dq if not c["passed"] and c["severity"] == CRITICAL]
    warnings = [c for c in dq if not c["passed"] and c["severity"] == WARNING]
    print(f"[DQ]   {len(dq)} checks: {len(dq) - len(criticals) - len(warnings)} pass, "
          f"{len(warnings)} warning, {len(criticals)} CRITICAL")

    (lake / "run_log.json").write_text(json.dumps(run_log, indent=2), encoding="utf-8")

    if criticals:
        for c in criticals:
            print(f"       CRITICAL {c['check_name']} on {c['table_name']}: {c['detail']}")
        print("[GATE] critical DQ failure -> semantic model refresh HALTED (alert would fire)")
        # remove any stale publish marker so downstream never reads a bad build
        marker = lake / "gold" / "_PUBLISHED"
        if marker.exists():
            marker.unlink()
        return 2

    marker = publish_semantic_model(lake)
    print(f"[PUB]  gate passed -> semantic model publish marker written: {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
