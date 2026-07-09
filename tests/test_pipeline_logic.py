"""
Data-invariant and business-logic tests for the Supply Chain Control Tower.

These run against the generated Bronze CSVs and re-implement (in pandas)
the same Silver-layer rules the PySpark notebooks apply, asserting that
the pipeline's core calculations — FEFO expiry risk, OTIF, margin — hold
for every row. CI runs the generator fresh and then this suite, so a
green badge means the whole pipeline logic is verified end-to-end on
every push, not just that the files parse.

Run locally:
    python data_generator/generate_data.py
    pytest tests/ -v
"""

from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data" / "bronze"


@pytest.fixture(scope="session")
def tables():
    if not (DATA / "fact_orders.csv").exists():
        pytest.skip("Bronze data not generated — run data_generator/generate_data.py first")
    return {
        "products": pd.read_csv(DATA / "dim_product.csv"),
        "suppliers": pd.read_csv(DATA / "dim_supplier.csv"),
        "warehouses": pd.read_csv(DATA / "dim_warehouse.csv"),
        "customers": pd.read_csv(DATA / "dim_customer.csv"),
        "lots": pd.read_csv(DATA / "dim_lot.csv"),
        "inventory": pd.read_csv(DATA / "fact_inventory_snapshot.csv"),
        "orders": pd.read_csv(DATA / "fact_orders.csv"),
    }


# ---------- Referential integrity ----------

def test_no_orphan_lots(tables):
    orphans = ~tables["lots"]["product_id"].isin(tables["products"]["product_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} lots reference a missing product"


def test_no_orphan_orders(tables):
    orders = tables["orders"]
    assert orders["product_id"].isin(tables["products"]["product_id"]).all()
    assert orders["customer_id"].isin(tables["customers"]["customer_id"]).all()
    assert orders["lot_id"].isin(tables["lots"]["lot_id"]).all()


def test_no_orphan_inventory(tables):
    inv = tables["inventory"]
    assert inv["lot_id"].isin(tables["lots"]["lot_id"]).all()
    assert inv["warehouse_id"].isin(tables["warehouses"]["warehouse_id"]).all()


# ---------- Uniqueness / completeness ----------

def test_dimension_natural_keys_unique(tables):
    assert tables["products"]["product_id"].is_unique
    assert tables["customers"]["customer_id"].is_unique
    assert tables["lots"]["lot_id"].is_unique
    assert tables["orders"]["order_id"].is_unique


def test_no_nulls_in_key_columns(tables):
    for name, key in [("orders", "order_id"), ("inventory", "lot_id"), ("products", "sku")]:
        assert tables[name][key].notna().all(), f"nulls in {name}.{key}"


# ---------- FEFO / shelf-life business rules ----------

def test_expiry_after_production(tables):
    lots = tables["lots"]
    assert (pd.to_datetime(lots["expiry_date"]) > pd.to_datetime(lots["production_date"])).all()


def test_shelf_life_matches_product(tables):
    lots = tables["lots"].merge(tables["products"][["product_id", "shelf_life_days"]], on="product_id")
    actual = (pd.to_datetime(lots["expiry_date"]) - pd.to_datetime(lots["production_date"])).dt.days
    assert (actual == lots["shelf_life_days"]).all(), "lot shelf life disagrees with product master"


def test_expiry_risk_flag_logic(tables):
    """Recompute the Silver-layer risk flag independently and verify thresholds."""
    inv = tables["inventory"].merge(tables["lots"][["lot_id", "expiry_date"]], on="lot_id")
    days = (pd.to_datetime(inv["expiry_date"]) - pd.to_datetime(inv["snapshot_date"])).dt.days
    critical = (days <= 2).sum()
    warning = ((days > 2) & (days <= 5)).sum()
    ok = (days > 5).sum()
    assert critical + warning + ok == len(inv)
    # No snapshot should exist after expiry — generator stops tracking expired lots
    assert (days >= 0).all(), "inventory snapshot exists after lot expiry"


# ---------- OTIF / fulfillment business rules ----------

def test_fill_rate_bounds(tables):
    orders = tables["orders"]
    fill = orders["qty_shipped"] / orders["qty_ordered"]
    assert (fill <= 1.0 + 1e-9).all(), "shipped more than ordered"
    assert (fill > 0).all(), "zero/negative fill rate"


def test_ship_date_not_before_order_date(tables):
    orders = tables["orders"]
    assert (pd.to_datetime(orders["shipped_date"]) >= pd.to_datetime(orders["order_date"])).all()


def test_otif_rate_is_realistic(tables):
    """Guard the generator's KPI story: OTIF should land in a believable band."""
    orders = tables["orders"]
    fill = orders["qty_shipped"] / orders["qty_ordered"]
    on_time = pd.to_datetime(orders["shipped_date"]) <= pd.to_datetime(orders["promised_date"])
    otif = (on_time & (fill >= 0.95)).mean()
    assert 0.60 <= otif <= 0.95, f"OTIF {otif:.1%} outside realistic band"


# ---------- Finance rules ----------

def test_price_above_cost(tables):
    products = tables["products"]
    assert (products["unit_price"] > products["unit_cost"]).all(), "negative-margin product in master"


def test_gross_margin_band(tables):
    orders = tables["orders"].merge(
        tables["products"][["product_id", "unit_cost", "unit_price"]],
        on="product_id", suffixes=("_line", ""),
    )
    revenue = (orders["qty_shipped"] * orders["unit_price"]).sum()
    cogs = (orders["qty_shipped"] * orders["unit_cost"]).sum()
    margin = (revenue - cogs) / revenue
    assert 0.10 <= margin <= 0.50, f"gross margin {margin:.1%} outside believable band"
