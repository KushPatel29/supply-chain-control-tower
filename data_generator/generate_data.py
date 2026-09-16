"""
Synthetic data generator for the Supply Chain Control Tower.

Northgate Retail Canada: a mass-retail chain of 90 stores served by 10 distribution
centres across five regions, buying from 24 vendors at home and offshore. The
merchandise, store formats, regions and seasonality live in `catalog.py`; this file
turns them into the raw CSVs a Fabric Lakehouse would land in Bronze.

Two years of history, to 30 June 2026, because most of what a control tower is for
only shows up over a year or more: Christmas in Toys & Seasonal, summer in Fresh,
the January reset, a lane whose reliability drifts.

The tables, in the order they are built - each depends on the ones above it:

    dim_product              150 SKUs across 10 departments, with a shelf life
    dim_supplier             24 vendors, their country and tier
    fact_sourcing            the approved vendor list: who may supply what, and how much
    dim_warehouse            10 DCs: ambient, cold chain, cross-dock
    dim_customer             90 stores, by format and region
    dim_lot                  receipts with production, receipt and expiry dates
    fact_inventory_snapshot  weekly on-hand by lot, so FEFO and expiry are answerable
    fact_orders              store replenishment lines: ordered, shipped, promised, delivered
    fact_inventory_position  weekly planning position: on hand, on order, target, reorder point
    fact_purchase_orders     the inbound half: what was ordered from vendors and what arrived

Half the catalogue has a clock on it and half does not, which is the point: the same
network runs FEFO on produce with twelve days of life and holds an air fryer for a
year. Expiry risk concentrates where it belongs instead of being sprayed across
every SKU.

Usage:
    python generate_data.py
"""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import (  # noqa: E402
    BRAND_TIERS, CATEGORIES, DC_TYPES, DEPARTMENTS, PACK_SIZES, REGIONS,
    STORE_FIRST, STORE_FORMATS, STORE_SECOND, SUPPLIER_PREFIXES, SUPPLIER_SUFFIXES,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "bronze"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_START = pd.Timestamp("2024-07-01")
SNAPSHOT_END = pd.Timestamp("2026-06-30")

N_PRODUCTS = 150
N_SUPPLIERS = 24
N_WAREHOUSES = 10
N_STORES = 90

# Each layer draws from its own generator, so changing one does not shift the
# numbers in another: regenerating the purchase orders must not move a single
# order line.
CATALOG_SEED = 20260101
SOURCING_SEED = 20260102
NETWORK_SEED = 20260103
LOT_SEED = 20260104
ORDER_SEED = 20260105
POSITION_SEED = 20260106
PO_SEED = 20260107


def weighted_choice(rng, options, weights):
    return options[int(rng.choice(len(options), p=np.asarray(weights) / np.sum(weights)))]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def gen_dim_product():
    """One row per SKU: what it is, what it costs, and how long it keeps.

    Cost is the department's typical landed cost per selling unit, moved by the
    brand tier (private label opens the price, premium tops it) and the pack size.
    Price is cost times the department's markup, so margin is a property of the
    department and the tier rather than noise - which is what makes the margin
    analysis recoverable rather than decorative.
    """
    rng = np.random.default_rng(CATALOG_SEED)
    rows = []
    departments = list(DEPARTMENTS)
    weights = [d.weight for d in departments]
    for i in range(1, N_PRODUCTS + 1):
        dept = weighted_choice(rng, departments, weights)
        category = str(rng.choice(CATEGORIES[dept.name]))
        tier, tier_index = BRAND_TIERS[int(rng.integers(len(BRAND_TIERS)))]
        pack, pack_index = PACK_SIZES[int(rng.integers(len(PACK_SIZES)))]
        weighed = bool(rng.random() < dept.weighed_share)
        unit_cost = round(dept.unit_cost * tier_index * pack_index * rng.normal(1.0, 0.12), 2)
        unit_cost = max(unit_cost, 0.45)
        markup = dept.markup * rng.normal(1.0, 0.04)
        rows.append({
            "product_id": i,
            "sku": f"SKU-{1000 + i}",
            "product_name": f"{tier} {category} {pack}",
            # The contract's column names predate the merchandising vocabulary:
            # `category` carries the department and `subcategory` the item type.
            "category": dept.name,
            "subcategory": category,
            "shelf_life_days": int(rng.integers(dept.shelf_life[0], dept.shelf_life[1] + 1)),
            "unit_of_measure": "KG" if weighed else str(rng.choice(["EA", "CASE"], p=[0.7, 0.3])),
            "unit_cost": unit_cost,
            "unit_price": round(unit_cost * markup, 2),
            # Additive columns: the contract allows them and downstream picks them
            # up when it is ready.
            "brand_tier": tier,
            "pack_size": pack,
            "sold_by_weight": int(weighed),
            "temperature_class": dept.temperature,
            "sell_through": round(float(np.clip(rng.normal(dept.sell_through, 0.02), 0.6, 1.0)), 3),
            # How often this SKU is the one a store orders. Retail demand is a
            # long tail - a fifth of the assortment carries most of the units -
            # and without that there is no ABC class worth managing and no
            # fast-mover for a lead-time policy to be about.
            "popularity": round(float(rng.lognormal(0.0, 0.95)), 4),
        })
    return pd.DataFrame(rows)


def gen_dim_supplier():
    rng = np.random.default_rng(CATALOG_SEED + 1)
    prefixes = rng.permutation(len(SUPPLIER_PREFIXES))
    rows = []
    for i in range(1, N_SUPPLIERS + 1):
        prefix = SUPPLIER_PREFIXES[prefixes[(i - 1) % len(SUPPLIER_PREFIXES)]]
        suffix = str(rng.choice(SUPPLIER_SUFFIXES))
        rows.append({
            "supplier_id": i,
            "supplier_name": f"{prefix} {suffix}",
            "region": str(rng.choice([r.name for r in REGIONS])),
        })
    return pd.DataFrame(rows)


def gen_dim_warehouse():
    """Distribution centres, allocated to regions rather than drawn at random.

    A retailer does not scatter its DCs by lottery: every region it sells in has at
    least one, and the big ones get more. Drawing each DC's region independently
    left Alberta and Ontario - half the store base - with no distribution centre at
    all, which is not a network any chain would run.

    The first DC in each region is a cross-dock, because it handles all three
    temperature classes and so guarantees the region can serve every department;
    after that the region gets an ambient DC, then a cold chain one.
    """
    regions = list(REGIONS)
    shares = np.array([r.weight for r in regions])
    counts = np.maximum(1, np.round(shares / shares.sum() * N_WAREHOUSES).astype(int))
    # Round-off can miss the target either way; settle it against the biggest region.
    while counts.sum() > N_WAREHOUSES:
        counts[int(np.argmax(counts))] -= 1
    while counts.sum() < N_WAREHOUSES:
        counts[int(np.argmax(shares))] += 1

    rng = np.random.default_rng(NETWORK_SEED)
    rows, warehouse_id = [], 1
    for region, count in zip(regions, counts):
        cities = list(region.cities)
        for index in range(int(count)):
            dc_type, handles = DC_TYPES[2] if index == 0 else DC_TYPES[(index - 1) % 2]
            rows.append({
                "warehouse_id": warehouse_id,
                "warehouse_name": f"{region.name} {dc_type} {warehouse_id}",
                "region": region.name,
                "city": cities[index % len(cities)],
                "dc_type": dc_type,
                "handles": "|".join(handles),
                "serves_region": region.name,
            })
            warehouse_id += 1
    return pd.DataFrame(rows)


def gen_dim_customer():
    """The stores. `channel` carries the format, as the source system always has."""
    rng = np.random.default_rng(NETWORK_SEED + 1)
    regions, formats = list(REGIONS), list(STORE_FORMATS)
    rows = []
    for i in range(1, N_STORES + 1):
        region = weighted_choice(rng, regions, [r.weight for r in regions])
        fmt = weighted_choice(rng, formats, [f.weight for f in formats])
        name = f"{rng.choice(STORE_FIRST)} {rng.choice(STORE_SECOND)}"
        rows.append({
            "customer_id": i,
            "customer_name": name,
            "channel": fmt.name,
            "region": region.name,
            "city": str(rng.choice(region.cities)),
            "opened_year": int(rng.integers(1998, 2025)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Global sourcing
#
# Where the goods come FROM is the half a control tower is actually built to
# watch: award concentration, single-source SKUs, country exposure, and how long a
# switch would take when a lane closes.
# ---------------------------------------------------------------------------

# country -> (bloc, transit days door-to-door, transit sigma, cost index). Transit
# dominates an offshore lead time and is the reason a cheaper unit price is not
# automatically a cheaper supply.
ORIGINS = {
    "Canada":      ("North America", 4, 1.0, 1.00),
    "USA":         ("North America", 6, 1.5, 0.97),
    "Mexico":      ("North America", 12, 3.0, 0.88),
    "Chile":       ("South America", 26, 5.0, 0.83),
    "Brazil":      ("South America", 29, 6.0, 0.81),
    "Spain":       ("Europe", 24, 4.0, 0.92),
    "Poland":      ("Europe", 27, 5.0, 0.86),
    "Turkiye":     ("Europe", 30, 6.0, 0.84),
    "Thailand":    ("Asia Pacific", 38, 7.0, 0.74),
    "Vietnam":     ("Asia Pacific", 40, 8.0, 0.72),
    "China":       ("Asia Pacific", 36, 7.0, 0.70),
    "India":       ("Asia Pacific", 41, 8.0, 0.73),
    "New Zealand": ("Asia Pacific", 33, 5.0, 0.95),
}

# Fresh food is not flown in from Vietnam. Departments that keep for days are
# sourced close to home; general merchandise is where the offshore tail lives, and
# that asymmetry is the whole sourcing-risk picture.
DOMESTIC_DEPARTMENTS = {"Fresh & Produce", "Meat & Seafood", "Dairy & Frozen"}
OFFSHORE_DEPARTMENTS = {"Electronics", "Apparel", "Toys & Seasonal", "Home & Kitchen"}


def _origin_weights(names, bias):
    weight = {"near": {"North America": 6.0, "South America": 1.2, "Europe": 0.6, "Asia Pacific": 0.3},
              "far": {"North America": 1.0, "South America": 0.9, "Europe": 1.6, "Asia Pacific": 3.0},
              "mixed": {"North America": 3.0, "South America": 1.0, "Europe": 1.6, "Asia Pacific": 1.4}}[bias]
    w = np.array([weight[ORIGINS[n][0]] for n in names])
    return w / w.sum()


def gen_sourcing(products: pd.DataFrame, suppliers: pd.DataFrame):
    """Approved vendor list: who may supply each SKU, and on what terms.

    Award shares are deliberately Pareto rather than uniform. A supply base where
    every SKU has a dozen interchangeable sources has no risk to measure and does
    not resemble any real one; a real AVL has a long tail of dual-sourced items and
    a dangerous handful that are single-sourced.
    """
    rng = np.random.default_rng(SOURCING_SEED)
    names = list(ORIGINS)

    countries = rng.choice(names, size=len(suppliers), p=_origin_weights(names, "mixed"))
    tiers = rng.choice(["Tier 1", "Tier 2", "Tier 3"], size=len(suppliers), p=[0.27, 0.40, 0.33])
    suppliers = suppliers.copy()
    suppliers["country"] = countries
    suppliers["sourcing_bloc"] = [ORIGINS[c][0] for c in countries]
    suppliers["supplier_tier"] = tiers
    # A qualified alternate can absorb volume; an unqualified one needs a
    # requalification programme before it can, which is why the scenario analysis
    # counts them separately.
    suppliers["is_qualified_alternate"] = np.where(tiers == "Tier 3", 0, 1)

    domestic = suppliers.index[suppliers["sourcing_bloc"] == "North America"].to_numpy()
    rows = []
    for product in products.itertuples(index=False):
        if product.category in DOMESTIC_DEPARTMENTS:
            pool = domestic
            n = int(rng.choice([1, 2, 3], p=[0.18, 0.47, 0.35]))
        else:
            pool = suppliers.index.to_numpy()
            n = int(rng.choice([1, 2, 3, 4], p=[0.15, 0.40, 0.30, 0.15]))
        n = min(n, len(pool))
        chosen = rng.choice(pool, size=n, replace=False)
        # Dirichlet gives a primary source with a genuine majority share.
        shares = rng.dirichlet(np.full(n, 0.9))
        shares = np.round(shares / shares.sum(), 4)
        shares[-1] = round(1.0 - shares[:-1].sum(), 4)
        for index, share in zip(chosen, shares):
            supplier = suppliers.loc[index]
            transit, sigma, cost_index = ORIGINS[supplier["country"]][1:]
            lead = int(round(transit + rng.normal(5, 1.5)))
            rows.append({
                "product_id": int(product.product_id),
                "supplier_id": int(supplier["supplier_id"]),
                "allocation_share": float(share),
                "contract_lead_days": max(2, lead),
                "lead_time_sigma_days": round(float(sigma), 1),
                "moq_units": int(rng.choice([25, 50, 100, 250, 500])),
                "price_index": round(float(cost_index * rng.normal(1.0, 0.04)), 3),
                "is_primary": 0,
            })
    sourcing = pd.DataFrame(rows)
    primary = sourcing.groupby("product_id")["allocation_share"].idxmax()
    sourcing.loc[primary, "is_primary"] = 1
    return suppliers, sourcing


# ---------------------------------------------------------------------------
# Receipts and stock
# ---------------------------------------------------------------------------

def gen_dim_lot(products: pd.DataFrame, sourcing: pd.DataFrame, warehouses: pd.DataFrame):
    """Receipts into the distribution centres.

    Two disciplines in one network, which is what makes this catalogue worth
    modelling. **Chilled and frozen stock is held regionally**: nobody trucks
    lettuce from Vancouver to Montreal, so every region receives its own lots into
    a DC that can hold them, often, in small quantities against a short clock.
    **Ambient stock is held nationally**: a kettle keeps for three years and moves
    from whichever DC has it, so it is received in fewer, larger lots.

    Receipt cadence follows the shelf life - little and often for produce, a few
    times a year for general merchandise - which is why lot counts differ by two
    orders of magnitude across the catalogue.
    """
    rng = np.random.default_rng(LOT_SEED)
    by_product = {pid: group for pid, group in sourcing.groupby("product_id")}
    handles = {row.warehouse_id: set(row.handles.split("|")) for row in warehouses.itertuples(index=False)}
    dc_region = dict(zip(warehouses["warehouse_id"], warehouses["region"]))
    region_share = {r.name: r.weight for r in REGIONS}
    days = (SNAPSHOT_END - SNAPSHOT_START).days

    rows, lot_id = [], 1
    for product in products.itertuples(index=False):
        shelf_life = int(product.shelf_life_days)
        cold = product.temperature_class in ("Chilled", "Frozen")
        eligible = [wid for wid, classes in handles.items() if product.temperature_class in classes]
        approved = by_product.get(product.product_id)
        if cold:
            # One receipt stream per region, into that region's cold-capable DCs.
            streams = [[wid for wid in eligible if dc_region[wid] == region]
                       for region in region_share]
            streams = [s for s in streams if s]
            cadence = int(np.clip(shelf_life * 0.75, 7, 60))
        else:
            # An ambient SKU lives in two or three DCs, not in all of them. A
            # national assortment spread across every building gives each
            # (SKU, DC) pair a trickle of demand - a line every other week - and
            # a planner cannot set a policy on that. It also makes lead-time
            # variability vanish beside demand noise, which is the wrong lesson:
            # the variability is real, the fan-out was not.
            home = rng.choice(eligible, size=min(3, len(eligible)), replace=False)
            streams = [list(home)]
            cadence = int(np.clip(shelf_life * 0.5, 14, 120))

        for stream in streams:
            weights = np.array([region_share[dc_region[wid]] for wid in stream], dtype=float)
            for offset in range(0, days, cadence):
                production = SNAPSHOT_START + timedelta(days=int(offset + rng.integers(0, cadence)))
                if production > SNAPSHOT_END:
                    break
                supplier_id = int(rng.choice(approved["supplier_id"].to_numpy())) if approved is not None else 1
                rows.append({
                    "lot_id": lot_id,
                    "product_id": int(product.product_id),
                    "supplier_id": supplier_id,
                    "warehouse_id": int(rng.choice(stream, p=weights / weights.sum())),
                    "production_date": production.date(),
                    "received_date": (production + timedelta(days=int(rng.integers(1, 4)))).date(),
                    "expiry_date": (production + timedelta(days=shelf_life)).date(),
                })
                lot_id += 1
    return pd.DataFrame(rows)


def gen_fact_inventory_snapshot(lots: pd.DataFrame, products: pd.DataFrame):
    """Weekly on-hand per lot until it depletes or expires.

    This is the lot-level view FEFO and recall questions need. It is deliberately
    not a planning view: by the last snapshot most lots have run down, which is the
    right shape for traceability and the wrong one for deciding what to order -
    hence `fact_inventory_position` below.
    """
    rng = np.random.default_rng(LOT_SEED + 1)
    shelf_life = dict(zip(products["product_id"], products["shelf_life_days"]))
    snapshot_dates = pd.date_range(SNAPSHOT_START, SNAPSHOT_END, freq="7D")
    rows = []
    for lot in lots.itertuples(index=False):
        life = shelf_life[lot.product_id]
        starting = int(rng.integers(60, 900) * (1.6 if life > 200 else 1.0))
        qty = float(starting)
        # A short-life lot has to move fast or it is written off; a long-life lot
        # turns slowly and sits.
        depletion = rng.uniform(0.25, 0.55) if life <= 30 else rng.uniform(0.06, 0.22)
        for snap in snapshot_dates:
            if snap.date() < lot.received_date or snap.date() > lot.expiry_date:
                continue
            qty = max(0.0, qty - depletion * starting)
            rows.append({
                "snapshot_date": snap.date(),
                "lot_id": lot.lot_id,
                "product_id": lot.product_id,
                "warehouse_id": lot.warehouse_id,
                "qty_on_hand": round(qty, 1),
            })
            if qty <= 0:
                break
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------

def gen_fact_orders(products: pd.DataFrame, stores: pd.DataFrame, lots: pd.DataFrame,
                    warehouses: pd.DataFrame):
    """Store replenishment lines, seasonal by department and sized by store format.

    Three things decide whether a line is on time and in full, and each is a
    different conversation: the region's lane (distance and whether it moves on the
    third-party carrier), the department's supply (produce runs short because it is
    grown, seasonal because the buy was committed a year ago), and the DC.
    """
    rng = np.random.default_rng(ORDER_SEED)
    departments = {d.name: d for d in DEPARTMENTS}
    regions = {r.name: r for r in REGIONS}
    formats = {f.name: f for f in STORE_FORMATS}
    by_department = {name: group["product_id"].to_numpy()
                     for name, group in products.groupby("category")}
    popularity = {name: (group["popularity"] / group["popularity"].sum()).to_numpy()
                  for name, group in products.groupby("category")}
    price = dict(zip(products["product_id"], products["unit_price"]))
    cost = dict(zip(products["product_id"], products["unit_cost"]))
    department_of = dict(zip(products["product_id"], products["category"]))
    # Which lot filled the line: the oldest lot of that product still inside its
    # life on the order date, which is what FEFO means.
    lots = lots.sort_values("expiry_date")
    dc_region = dict(zip(warehouses["warehouse_id"], warehouses["region"]))
    lots_by_product = {pid: group[["lot_id", "received_date", "expiry_date", "warehouse_id"]].to_numpy(dtype=object)
                       for pid, group in lots.groupby("product_id")}

    months = pd.date_range(SNAPSHOT_START, SNAPSHOT_END, freq="MS")
    names = list(by_department)
    base_weights = np.array([departments[n].weight for n in names])

    rows, order_id = [], 1
    for store in stores.itertuples(index=False):
        fmt = formats[store.channel]
        region = regions[store.region]
        for month_start in months:
            season = np.array([departments[n].seasonality[month_start.month - 1] for n in names])
            weights = base_weights * season
            weights = weights / weights.sum()
            n_orders = int(rng.poisson(fmt.orders_per_month))
            for _ in range(n_orders):
                day = int(rng.integers(0, month_start.days_in_month))
                order_date = month_start + timedelta(days=day)
                if order_date > SNAPSHOT_END:
                    continue
                third_party = rng.random() < region.third_party_share
                # The lane's transit plus the DC's processing day. The promise is
                # made per line, because a line served from a national DC is
                # genuinely further away - that is a longer promise, not a missed
                # one, and charging it as a service failure is how a network ends
                # up "fixing" OTIF by shipping everything short-haul.
                transit = region.transit_days + (1.5 if third_party else 0.0)
                processing = rng.uniform(0.5, 1.5)
                for _ in range(max(1, int(rng.poisson(fmt.lines_per_order)))):
                    department = names[int(rng.choice(len(names), p=weights))]
                    dept = departments[department]
                    product_id = int(rng.choice(by_department[department], p=popularity[department]))
                    candidates = lots_by_product.get(product_id)
                    if candidates is None:
                        continue
                    usable = [row for row in candidates
                              if row[1] <= order_date.date() <= row[2]]
                    if not usable:
                        continue
                    # First to expire, first out. Cold stock has to come from the
                    # region's own DC; ambient comes from whichever DC holds the
                    # oldest usable lot, which is how a national assortment works.
                    cold = dept.temperature in ("Chilled", "Frozen")
                    local = [row for row in usable if dc_region[row[3]] == store.region]
                    if cold and not local:
                        continue
                    lot = (local or usable)[0]
                    national = not local
                    qty = max(1, int(rng.lognormal(2.6, 0.7) * fmt.size_index
                                     * dept.seasonality[month_start.month - 1]))
                    # On time: the third-party lane is the one that runs late, which
                    # makes the OTIF story a network-design problem rather than a
                    # carrier problem.
                    promised = order_date + timedelta(
                        days=int(round(transit + processing + (1.0 if national else 0.0))))
                    late_rate = (0.13 if third_party else 0.02) + (0.015 if national else 0.0)
                    delay = 0 if rng.random() > late_rate else int(rng.integers(1, 6))
                    short = rng.random() < dept.short_ship_rate
                    fill = 1.0 if not short else float(np.clip(
                        rng.normal(dept.typical_fill_when_short, 0.08), 0.2, 0.99))
                    rows.append({
                        "order_id": order_id,
                        "order_date": order_date.date(),
                        "customer_id": int(store.customer_id),
                        "product_id": product_id,
                        "lot_id": int(lot[0]),
                        "warehouse_id": int(lot[3]),
                        "qty_ordered": qty,
                        "qty_shipped": round(qty * fill, 1),
                        "promised_date": promised.date(),
                        "shipped_date": (promised + timedelta(days=delay)).date(),
                        "unit_price": round(price[product_id] * fmt.price_index, 2),
                        "unit_cost": cost[product_id],
                        "department": department_of[product_id],
                        "carrier_lane": "Third Party LTL" if third_party else "Private Fleet",
                        "fulfilled_from": "National DC" if national else "Regional DC",
                    })
                    order_id += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Inventory position
#
# fact_inventory_snapshot is a lot-level depletion model; measured on it, every SKU
# looks permanently stocked out. A planner works from a stock POSITION: on hand, on
# order, allocated, and the target the policy says should be there. This generates
# that weekly per SKU x warehouse, driven by the demand actually in fact_orders so
# the analysis is not circular, with a deliberate spread of over- and under-stocked
# items to analyse.
# ---------------------------------------------------------------------------

SERVICE_Z = 1.645          # 95% cycle service level
POSITION_WEEKS = 13
LANE_PIVOT_DAYS = 36       # lanes slower than this bleed, faster than this build
LANE_DRIFT_PER_WEEK = 0.015


def gen_inventory_position(products, warehouses, orders, sourcing):
    rng = np.random.default_rng(POSITION_SEED)
    orders = orders.copy()
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    horizon = (orders.order_date.max() - orders.order_date.min()).days + 1

    daily = (orders.groupby(["product_id", "warehouse_id", "order_date"])
             .qty_shipped.sum().reset_index())
    stat = daily.groupby(["product_id", "warehouse_id"]).qty_shipped.agg(["sum", "std"])
    stat["mu"] = stat["sum"] / horizon
    stat["sigma"] = stat["std"].fillna(0.0)

    # The lead time to plan against is the SLOWEST approved source, not the average:
    # the alternate is what you fall back on, and it is the one that hurts.
    lead = sourcing.groupby("product_id").agg(
        lead_days=("contract_lead_days", "max"), lead_sigma=("lead_time_sigma_days", "max"))

    rows = []
    week_starts = pd.date_range(end=SNAPSHOT_END, periods=POSITION_WEEKS, freq="7D")
    for (pid, wid), r in stat.iterrows():
        if pid not in lead.index or r.mu <= 0:
            continue
        lead_days = float(lead.loc[pid, "lead_days"])
        lead_sigma = float(lead.loc[pid, "lead_sigma"])
        # King's formula: demand variability over the lead time, plus the
        # variability of the lead time itself against average demand.
        safety = SERVICE_Z * float(np.sqrt(lead_days * r.sigma ** 2 + (r.mu ** 2) * lead_sigma ** 2))
        target = r.mu * lead_days + safety

        # Most SKUs sit near policy; a real network always has a tail that does not,
        # in both directions, and that tail is the point of the analysis.
        bias = rng.choice([0.45, 0.8, 1.0, 1.35, 1.9], p=[0.10, 0.22, 0.38, 0.20, 0.10])

        # Lanes do not drift together. A long lane's replenishment loop is slower
        # than the demand signal driving it, so it bleeds position over a quarter; a
        # short lane re-orders inside the same period and tends to overshoot. Total
        # inventory barely moves while its composition rotates - which is how a
        # network ends up holding plenty of stock and still missing service.
        tilt = float(np.clip((lead_days - LANE_PIVOT_DAYS) / 12.0, -1.0, 1.0))
        for i, week in enumerate(week_starts):
            drift = (1.0 - LANE_DRIFT_PER_WEEK * tilt) ** i
            noise = rng.normal(1.0, 0.10)
            on_hand = max(0.0, target * bias * drift * noise * rng.uniform(0.55, 0.85))
            on_order = max(0.0, target * bias * drift * noise) - on_hand
            rows.append({
                "week_start": week.date(),
                "product_id": int(pid),
                "warehouse_id": int(wid),
                "on_hand_units": int(round(on_hand)),
                "on_order_units": int(round(max(0.0, on_order))),
                "allocated_units": int(round(r.mu * rng.uniform(1.0, 4.0))),
                "avg_daily_demand": round(float(r.mu), 3),
                "demand_sigma": round(float(r.sigma), 3),
                "lead_days": int(lead_days),
                "safety_stock_target": int(round(safety)),
                "reorder_point": int(round(target)),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Purchase orders
#
# Without a record of what was ORDERED from a vendor, when it was promised, when it
# turned up, how much was rejected and what it cost against the contract, there is
# no supplier performance to measure - a scorecard built on the outbound side alone
# is ranking noise and presenting it as procurement advice.
#
# So each approved supplier gets latent traits it is then measured on, deliberately
# NOT aligned with its contractual tier, because "our tiering does not match
# measured performance" is the finding a vendor review exists to produce.
# ---------------------------------------------------------------------------

PO_WEEKS = 78
RECEIPT_TOLERANCE = 0.98      # received at or above this share counts as in full

REJECT_REASONS = [
    ("Temperature excursion in transit", 0.26),
    ("Short shelf life on arrival", 0.22),
    ("Damaged packaging", 0.21),
    ("Failed spec check", 0.17),
    ("Documentation incomplete", 0.14),
]


def gen_purchase_orders(products, suppliers, sourcing, warehouses, orders):
    """One row per PO line: what was ordered, promised, received, and paid.

    Quantities follow the approved award shares, so the scorecard weights each
    supplier by the business it actually holds rather than by how many POs it
    happens to appear on.
    """
    rng = np.random.default_rng(PO_SEED)
    prod = products.set_index("product_id")
    handles = {row.warehouse_id: set(row.handles.split("|")) for row in warehouses.itertuples(index=False)}
    # What the stores actually pulled, so the inbound side is sized by the business
    # rather than by the minimum order quantity. Buying to MOQ alone had the chain
    # purchasing 16.7M units against 3.1M sold - five years of stock for a two-year
    # window, and a supplier scorecard weighted by fiction.
    demand_units = orders.groupby("product_id").qty_shipped.sum()

    traits = {}
    for sid in suppliers["supplier_id"]:
        traits[sid] = {
            "on_time": float(np.clip(rng.normal(0.88, 0.09), 0.55, 0.99)),
            "late_days": float(rng.uniform(2.0, 11.0)),
            "in_full": float(np.clip(rng.normal(0.93, 0.06), 0.70, 0.999)),
            "short_share": float(rng.uniform(0.04, 0.20)),
            # How often a receipt has anything wrong with it, and how much of it is
            # condemned when it does.
            "reject_freq": float(np.clip(rng.beta(2.0, 22.0), 0.005, 0.30)),
            "reject_share": float(rng.uniform(0.03, 0.22)),
            "price_drift": float(rng.normal(0.012, 0.035)),
            "lead_noise": float(rng.uniform(0.5, 2.2)),
        }

    reasons = [r for r, _ in REJECT_REASONS]
    reason_p = np.array([p for _, p in REJECT_REASONS])
    reason_p = reason_p / reason_p.sum()

    rows, po_id = [], 1
    week_starts = pd.date_range(end=SNAPSHOT_END, periods=PO_WEEKS, freq="7D")
    for s in sourcing.itertuples(index=False):
        pid, sid = int(s.product_id), int(s.supplier_id)
        trait = traits[sid]
        std_cost = float(prod.loc[pid, "unit_cost"])
        temperature = str(prod.loc[pid, "temperature_class"])
        eligible = [wid for wid, classes in handles.items() if temperature in classes]
        # The contract price is the standard cost adjusted by the origin's price
        # index - the number a buyer negotiated and is owed.
        contract_price = round(std_cost * float(s.price_index), 2)
        # Award share drives order frequency: a 5% award does not generate as many
        # POs as a 60% one.
        weeks = [w for w in week_starts if rng.random() < float(s.allocation_share)]
        if not weeks:
            continue
        # This supplier's share of the SKU's demand, spread over its own POs, with a
        # replenishment cycle's worth of cover on top. MOQ still binds on the slow
        # movers, which is where a minimum order quantity really does force stock
        # nobody needs.
        share_units = float(demand_units.get(pid, 0.0)) * float(s.allocation_share)
        per_po = share_units / len(weeks) * 1.15
        for week in weeks:
            qty = int(max(s.moq_units, rng.normal(max(per_po, 1.0), max(per_po * 0.22, 1.0))))
            promised = week + pd.Timedelta(days=int(round(float(s.contract_lead_days))))

            # On time means on or before the promise, so an on-time draw can only
            # land early - letting week-to-week wobble push an on-time delivery past
            # its own promise date is how the first cut of this reported 53% on-time
            # for suppliers drawn at 88%.
            wobble = rng.normal(0, s.lead_time_sigma_days * trait["lead_noise"])
            if rng.random() < trait["on_time"]:
                days = -int(abs(round(wobble)))
            else:
                days = max(1, int(rng.exponential(trait["late_days"])) + max(0, int(round(wobble))))
            received = promised + pd.Timedelta(days=days)

            in_full = rng.random() < trait["in_full"]
            qty_received = qty if in_full else int(qty * (1 - rng.uniform(0.02, trait["short_share"])))

            # Rejection is an event, not a rate applied to every receipt. A small
            # per-unit rate multiplied by a four-figure quantity condemns something
            # on nearly every line, which reads as "every supplier rejects a little"
            # - untrue, and no use to a buyer deciding who to put on notice.
            if rng.random() < trait["reject_freq"]:
                qty_rejected = max(1, int(qty_received * rng.uniform(0.03, trait["reject_share"])))
                reason = str(rng.choice(reasons, p=reason_p))
            else:
                qty_rejected, reason = 0, ""

            paid = round(contract_price * (1 + trait["price_drift"] + rng.normal(0, 0.01)), 2)
            rows.append({
                "po_id": f"PO-{po_id:06d}",
                "product_id": pid,
                "supplier_id": sid,
                "warehouse_id": int(rng.choice(eligible)),
                "order_date": week.date().isoformat(),
                "promised_date": promised.date().isoformat(),
                "received_date": received.date().isoformat(),
                "qty_ordered": qty,
                "qty_received": qty_received,
                "qty_rejected": qty_rejected,
                "reject_reason": reason,
                "contract_price": contract_price,
                "unit_price": paid,
                "is_primary": int(s.is_primary),
            })
            po_id += 1
    return pd.DataFrame(rows)


def main():
    print("Catalogue and network...")
    products = gen_dim_product()
    suppliers = gen_dim_supplier()
    warehouses = gen_dim_warehouse()
    stores = gen_dim_customer()

    print("Approved vendor list...")
    suppliers, sourcing = gen_sourcing(products, suppliers)

    print("Receipts (traceability)...")
    lots = gen_dim_lot(products, sourcing, warehouses)

    print("Weekly stock by lot...")
    inventory = gen_fact_inventory_snapshot(lots, products)

    print("Store replenishment orders (this takes a moment)...")
    orders = gen_fact_orders(products, stores, lots, warehouses)

    print("Weekly inventory positions (planning view)...")
    positions = gen_inventory_position(products, warehouses, orders, sourcing)

    print("Purchase orders (the inbound half of the chain)...")
    purchase_orders = gen_purchase_orders(products, suppliers, sourcing, warehouses, orders)

    tables = {
        "dim_product": products,
        "dim_supplier": suppliers,
        "fact_sourcing": sourcing,
        "fact_inventory_position": positions,
        "fact_purchase_orders": purchase_orders,
        "dim_warehouse": warehouses,
        "dim_customer": stores,
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
