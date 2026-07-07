"""
Synthetic data generator for the Supply Chain Control Tower portfolio project.
Produces realistic perishable-goods supply chain data (products, lots, warehouses,
customers, inventory snapshots, orders) and writes it as CSVs into data/bronze/,
mimicking the raw landing zone of a Fabric Lakehouse.

Usage:
    python generate_data.py
"""

import numpy as np
import pandas as pd
from faker import Faker
from datetime import timedelta
from pathlib import Path

fake = Faker()
Faker.seed(42)
np.random.seed(42)

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "bronze"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_START = pd.Timestamp("2025-01-01")
SNAPSHOT_END = pd.Timestamp("2025-06-30")

CATEGORIES = {
    "Fresh Meat": ["Beef", "Pork", "Lamb", "Poultry"],
    "Deli": ["Sliced Meats", "Cheese", "Prepared Salads"],
    "Seafood": ["Fresh Fish", "Shellfish", "Smoked Seafood"],
    "Frozen": ["Frozen Poultry", "Frozen Seafood", "Frozen Prepared"],
}

CHANNELS = ["Retail", "Foodservice", "Wholesale"]
REGIONS = ["BC Lower Mainland", "BC Interior", "Alberta", "Ontario", "Quebec"]

N_PRODUCTS = 60
N_SUPPLIERS = 15
N_WAREHOUSES = 8
N_CUSTOMERS = 40
N_LOTS = 3000
N_ORDERS = 20000


def gen_dim_product():
    rows = []
    for i in range(1, N_PRODUCTS + 1):
        category = np.random.choice(list(CATEGORIES.keys()))
        subcategory = np.random.choice(CATEGORIES[category])
        # Fresh/deli/seafood = short shelf life, frozen = long
        shelf_life_days = (
            np.random.randint(3, 10) if category in ("Fresh Meat", "Deli", "Seafood")
            else np.random.randint(90, 270)
        )
        unit_cost = round(np.random.uniform(2.5, 40.0), 2)
        margin_pct = np.random.uniform(0.18, 0.42)
        rows.append({
            "product_id": i,
            "sku": f"SKU-{1000 + i}",
            "product_name": f"{subcategory} {fake.word().capitalize()}",
            "category": category,
            "subcategory": subcategory,
            "shelf_life_days": shelf_life_days,
            "unit_of_measure": np.random.choice(["KG", "CASE", "EA"]),
            "unit_cost": unit_cost,
            "unit_price": round(unit_cost * (1 + margin_pct), 2),
        })
    return pd.DataFrame(rows)


def gen_dim_supplier():
    rows = []
    for i in range(1, N_SUPPLIERS + 1):
        rows.append({
            "supplier_id": i,
            "supplier_name": fake.company(),
            "region": np.random.choice(REGIONS),
        })
    return pd.DataFrame(rows)


def gen_dim_warehouse():
    rows = []
    for i in range(1, N_WAREHOUSES + 1):
        region = np.random.choice(REGIONS)
        rows.append({
            "warehouse_id": i,
            "warehouse_name": f"{region} DC {i}",
            "region": region,
            "city": fake.city(),
        })
    return pd.DataFrame(rows)


def gen_dim_customer():
    rows = []
    for i in range(1, N_CUSTOMERS + 1):
        rows.append({
            "customer_id": i,
            "customer_name": fake.company(),
            "channel": np.random.choice(CHANNELS, p=[0.5, 0.3, 0.2]),
            "region": np.random.choice(REGIONS),
        })
    return pd.DataFrame(rows)


def gen_dim_lot(products: pd.DataFrame, suppliers: pd.DataFrame, warehouses: pd.DataFrame):
    rows = []
    for i in range(1, N_LOTS + 1):
        product = products.sample(1).iloc[0]
        production_date = SNAPSHOT_START + timedelta(days=int(np.random.uniform(-30, 150)))
        expiry_date = production_date + timedelta(days=int(product["shelf_life_days"]))
        rows.append({
            "lot_id": i,
            "product_id": product["product_id"],
            "supplier_id": int(suppliers.sample(1)["supplier_id"].iloc[0]),
            "warehouse_id": int(warehouses.sample(1)["warehouse_id"].iloc[0]),
            "production_date": production_date.date(),
            "received_date": (production_date + timedelta(days=np.random.randint(1, 4))).date(),
            "expiry_date": expiry_date.date(),
        })
    return pd.DataFrame(rows)


def gen_fact_inventory_snapshot(lots: pd.DataFrame):
    """Weekly on-hand qty per lot until it expires or depletes."""
    rows = []
    snapshot_dates = pd.date_range(SNAPSHOT_START, SNAPSHOT_END, freq="7D")
    for _, lot in lots.iterrows():
        starting_qty = np.random.randint(50, 800)
        qty = starting_qty
        for snap in snapshot_dates:
            if snap.date() < lot["received_date"] or snap.date() > lot["expiry_date"]:
                continue
            depletion = np.random.uniform(0.05, 0.25) * starting_qty
            qty = max(0, qty - depletion)
            rows.append({
                "snapshot_date": snap.date(),
                "lot_id": lot["lot_id"],
                "product_id": lot["product_id"],
                "warehouse_id": lot["warehouse_id"],
                "qty_on_hand": round(qty, 1),
            })
            if qty <= 0:
                break
    return pd.DataFrame(rows)


def gen_fact_orders(products, customers, warehouses, lots):
    rows = []
    order_dates = pd.date_range(SNAPSHOT_START, SNAPSHOT_END, freq="D")
    for i in range(1, N_ORDERS + 1):
        product = products.sample(1).iloc[0]
        customer = customers.sample(1).iloc[0]
        candidate_lots = lots[lots["product_id"] == product["product_id"]]
        if candidate_lots.empty:
            continue
        lot = candidate_lots.sample(1).iloc[0]
        order_date = np.random.choice(order_dates)
        promised_date = pd.Timestamp(order_date) + timedelta(days=np.random.randint(1, 5))
        # 90% ship on time, 10% late -> drives OTIF KPI
        on_time = np.random.random() < 0.90
        ship_delay = 0 if on_time else np.random.randint(1, 6)
        shipped_date = promised_date + timedelta(days=ship_delay)
        qty_ordered = np.random.randint(5, 200)
        # Most orders ship complete; a realistic minority fall short (drives OTIF/fill-rate KPIs)
        fill_rate = 1.0 if np.random.random() < 0.85 else np.random.uniform(0.85, 0.99)
        qty_shipped = round(qty_ordered * fill_rate, 1)
        rows.append({
            "order_id": i,
            "order_date": pd.Timestamp(order_date).date(),
            "customer_id": customer["customer_id"],
            "product_id": product["product_id"],
            "lot_id": lot["lot_id"],
            "warehouse_id": lot["warehouse_id"],
            "qty_ordered": qty_ordered,
            "qty_shipped": qty_shipped,
            "promised_date": promised_date.date(),
            "shipped_date": shipped_date.date(),
            "unit_price": product["unit_price"],
            "unit_cost": product["unit_cost"],
        })
    return pd.DataFrame(rows)


def main():
    print("Generating dimension tables...")
    products = gen_dim_product()
    suppliers = gen_dim_supplier()
    warehouses = gen_dim_warehouse()
    customers = gen_dim_customer()

    print("Generating lots (traceability)...")
    lots = gen_dim_lot(products, suppliers, warehouses)

    print("Generating inventory snapshots (this may take a moment)...")
    inventory = gen_fact_inventory_snapshot(lots)

    print("Generating orders...")
    orders = gen_fact_orders(products, customers, warehouses, lots)

    tables = {
        "dim_product": products,
        "dim_supplier": suppliers,
        "dim_warehouse": warehouses,
        "dim_customer": customers,
        "dim_lot": lots,
        "fact_inventory_snapshot": inventory,
        "fact_orders": orders,
    }

    for name, df in tables.items():
        path = OUT_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"  wrote {path}  ({len(df):,} rows)")

    print("\nDone. Raw CSVs are in data/bronze/ — these represent the Bronze layer.")


if __name__ == "__main__":
    main()
