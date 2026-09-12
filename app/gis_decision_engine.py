"""Pure data and scenario logic for the GIS Network Risk Decision Room.

The Streamlit page is deliberately thin. These functions hold the business
rules so the calculations can be reviewed and tested without a browser.
All locations are synthetic and all distances are great-circle screening
distances, not road or freight routes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EARTH_RADIUS_KM = 6371.0088


def _require(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {sorted(missing)}")


def load_app_data(root: Path = ROOT) -> dict[str, object]:
    """Load the committed evidence the app is allowed to present."""
    output = root / "analytics" / "output"
    bronze = root / "data" / "bronze"
    frames = {
        "locations": pd.read_csv(root / "gis" / "network_locations.csv"),
        "routes": pd.read_csv(output / "gis_route_summary.csv"),
        "scorecard": pd.read_csv(output / "supplier_scorecard.csv"),
        "country_exposure": pd.read_csv(output / "country_exposure.csv"),
        "concentration": pd.read_csv(output / "sourcing_concentration.csv"),
        "sourcing": pd.read_csv(bronze / "fact_sourcing.csv"),
        "suppliers": pd.read_csv(bronze / "dim_supplier.csv"),
        "products": pd.read_csv(bronze / "dim_product.csv"),
    }
    _require(frames["locations"], {
        "entity_type", "entity_id", "name", "country", "region",
        "longitude", "latitude", "location_basis",
    }, "network locations")
    _require(frames["routes"], {
        "supplier_id", "supplier_name", "supplier_country", "warehouse_id",
        "warehouse_name", "distance_km", "distance_band", "analysis_basis",
    }, "route summary")
    _require(frames["scorecard"], {
        "supplier_id", "spend", "otif_rate", "composite_score", "supplier_tier",
        "measured_band", "tier_matches_measurement",
    }, "supplier scorecard")
    for frame in frames.values():
        if isinstance(frame, pd.DataFrame):
            frame.columns = [str(column).strip() for column in frame.columns]

    frames["point_geojson"] = json.loads(
        (output / "network_locations.geojson").read_text(encoding="utf-8")
    )
    frames["route_geojson"] = json.loads(
        (output / "supplier_routes.geojson").read_text(encoding="utf-8")
    )
    frames["routes_enriched"] = enrich_routes(
        frames["routes"], frames["locations"], frames["scorecard"]
    )
    return frames


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance for WGS 84 longitude/latitude pairs."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(value))


def distance_band(distance_km: float) -> str:
    if distance_km <= 500:
        return "regional"
    if distance_km <= 2500:
        return "continental"
    return "intercontinental"


def enrich_routes(
    routes: pd.DataFrame, locations: pd.DataFrame, scorecard: pd.DataFrame
) -> pd.DataFrame:
    suppliers = locations[locations.entity_type.eq("supplier")].rename(columns={
        "entity_id": "supplier_id",
        "longitude": "supplier_longitude",
        "latitude": "supplier_latitude",
        "region": "supplier_region",
        "name": "location_supplier_name",
    })
    warehouses = locations[locations.entity_type.eq("warehouse")].rename(columns={
        "entity_id": "warehouse_id",
        "longitude": "warehouse_longitude",
        "latitude": "warehouse_latitude",
        "region": "warehouse_region",
        "name": "location_warehouse_name",
    })
    supplier_columns = [
        "supplier_id", "supplier_longitude", "supplier_latitude", "supplier_region",
    ]
    warehouse_columns = [
        "warehouse_id", "warehouse_longitude", "warehouse_latitude", "warehouse_region",
    ]
    score_columns = [
        "supplier_id", "spend", "otif_rate", "composite_score", "supplier_tier",
        "measured_band", "tier_matches_measurement", "is_qualified_alternate",
    ]
    enriched = (
        routes.merge(suppliers[supplier_columns], on="supplier_id", how="left", validate="one_to_one")
        .merge(warehouses[warehouse_columns], on="warehouse_id", how="left", validate="many_to_one")
        .merge(scorecard[score_columns], on="supplier_id", how="left", validate="one_to_one")
    )
    if enriched[["supplier_longitude", "warehouse_longitude", "composite_score"]].isna().any().any():
        raise ValueError("route enrichment left an unmatched supplier, warehouse or scorecard row")
    return enriched.sort_values("supplier_id").reset_index(drop=True)


def filter_routes(
    routes: pd.DataFrame,
    regions: Iterable[str] | None = None,
    distance_bands: Iterable[str] | None = None,
    min_distance_km: float = 0,
) -> pd.DataFrame:
    filtered = routes.copy()
    selected_regions = set(regions or [])
    selected_bands = set(distance_bands or [])
    if selected_regions:
        filtered = filtered[filtered.supplier_region.isin(selected_regions)]
    if selected_bands:
        filtered = filtered[filtered.distance_band.isin(selected_bands)]
    filtered = filtered[filtered.distance_km.ge(float(min_distance_km))]
    return filtered.sort_values(["distance_km", "supplier_name"], ascending=[False, True]).reset_index(drop=True)


def rank_warehouses(
    supplier: pd.Series | dict,
    warehouses: pd.DataFrame,
    unavailable_warehouse_ids: Iterable[int] = (),
) -> pd.DataFrame:
    unavailable = {int(item) for item in unavailable_warehouse_ids}
    available = warehouses[~warehouses.entity_id.astype(int).isin(unavailable)].copy()
    if available.empty:
        raise ValueError("at least one distribution node must remain available")
    available["distance_km"] = available.apply(
        lambda row: haversine_km(
            float(supplier["longitude"]), float(supplier["latitude"]),
            float(row["longitude"]), float(row["latitude"]),
        ), axis=1,
    )
    return available.sort_values(["distance_km", "entity_id"]).reset_index(drop=True)


def reroute_network(
    locations: pd.DataFrame,
    baseline_routes: pd.DataFrame,
    unavailable_warehouse_ids: Iterable[int],
) -> pd.DataFrame:
    unavailable = {int(item) for item in unavailable_warehouse_ids}
    warehouses = locations[locations.entity_type.eq("warehouse")].copy()
    suppliers = locations[locations.entity_type.eq("supplier")].set_index("entity_id")
    if unavailable and warehouses.entity_id.astype(int).isin(unavailable).all():
        raise ValueError("at least one distribution node must remain available")

    rows = []
    for route in baseline_routes.sort_values("supplier_id").to_dict("records"):
        supplier = suppliers.loc[int(route["supplier_id"])]
        impacted = int(route["warehouse_id"]) in unavailable
        if impacted:
            ranked = rank_warehouses(supplier, warehouses, unavailable)
            destination = ranked.iloc[0]
            scenario_distance = round(float(destination.distance_km), 1)
            scenario_warehouse_id = int(destination.entity_id)
            scenario_warehouse_name = str(destination["name"])
        else:
            scenario_distance = float(route["distance_km"])
            scenario_warehouse_id = int(route["warehouse_id"])
            scenario_warehouse_name = str(route["warehouse_name"])
        rows.append({
            "supplier_id": int(route["supplier_id"]),
            "supplier_name": route["supplier_name"],
            "supplier_country": route["supplier_country"],
            "baseline_warehouse_id": int(route["warehouse_id"]),
            "baseline_warehouse_name": route["warehouse_name"],
            "baseline_distance_km": float(route["distance_km"]),
            "scenario_warehouse_id": scenario_warehouse_id,
            "scenario_warehouse_name": scenario_warehouse_name,
            "scenario_distance_km": scenario_distance,
            "extra_distance_km": round(scenario_distance - float(route["distance_km"]), 1),
            "scenario_distance_band": distance_band(scenario_distance),
            "impacted": impacted,
        })
    return pd.DataFrame(rows)


def country_disruption(
    country: str,
    sourcing: pd.DataFrame,
    suppliers: pd.DataFrame,
    products: pd.DataFrame,
    concentration: pd.DataFrame,
    scorecard: pd.DataFrame,
    minimum_alternate_score: float = 0,
    recovery_window_days: int = 45,
) -> pd.DataFrame:
    """Return one decision row per SKU touched by the selected origin."""
    network = sourcing.merge(
        suppliers[["supplier_id", "supplier_name", "country", "is_qualified_alternate"]],
        on="supplier_id", how="left", validate="many_to_one",
    ).merge(
        scorecard[["supplier_id", "composite_score"]],
        on="supplier_id", how="left", validate="many_to_one",
    )
    affected = network[network.country.eq(country)]
    if affected.empty:
        return pd.DataFrame(columns=[
            "product_id", "sku", "category", "cogs", "country_award_share",
            "decision_status", "qualified_alternate", "alternate_country",
            "alternate_score", "switch_lead_days", "within_recovery_window",
            "recommended_next_check",
        ])

    product_lookup = products.set_index("product_id")
    concentration_lookup = concentration.set_index("product_id")
    rows = []
    for product_id, country_rows in affected.groupby("product_id"):
        alternates = network[
            network.product_id.eq(product_id)
            & network.country.ne(country)
            & network.is_qualified_alternate.eq(1)
            & network.composite_score.ge(float(minimum_alternate_score))
        ].sort_values(["contract_lead_days", "supplier_id"])
        stranded = alternates.empty
        alternate = None if stranded else alternates.iloc[0]
        rows.append({
            "product_id": int(product_id),
            "sku": product_lookup.loc[product_id, "sku"],
            "category": product_lookup.loc[product_id, "category"],
            "cogs": float(concentration_lookup.loc[product_id, "cogs"]),
            "country_award_share": float(country_rows.allocation_share.sum()),
            "decision_status": "No qualified alternate" if stranded else "Qualified alternate exists",
            "qualified_alternate": "—" if stranded else str(alternate.supplier_name),
            "alternate_country": "—" if stranded else str(alternate.country),
            "alternate_score": None if stranded else float(alternate.composite_score),
            "switch_lead_days": None if stranded else int(alternate.contract_lead_days),
            "within_recovery_window": (
                False if stranded else int(alternate.contract_lead_days) <= int(recovery_window_days)
            ),
            "recommended_next_check": (
                "Open alternate qualification" if stranded
                else (
                    "Confirm capacity and commercial terms"
                    if int(alternate.contract_lead_days) <= int(recovery_window_days)
                    else "Close recovery-window gap or extend cover"
                )
            ),
        })
    return pd.DataFrame(rows).sort_values(
        ["decision_status", "cogs"], ascending=[False, False]
    ).reset_index(drop=True)


def country_decision_brief(
    country: str,
    exposure: pd.Series | dict,
    response_register: pd.DataFrame,
    owner: str,
    review_window: str,
    minimum_alternate_score: float = 0,
) -> str:
    stranded = response_register[response_register.decision_status.eq("No qualified alternate")]
    highest = "None"
    if not stranded.empty:
        highest = f"{stranded.iloc[0].sku} (${stranded.iloc[0].cogs:,.0f} COGS)"
    recoverable = response_register[response_register.decision_status.ne("No qualified alternate")]
    within_window = int(recoverable.within_recovery_window.sum()) if not recoverable.empty else 0
    mean_switch = float(recoverable.switch_lead_days.mean()) if not recoverable.empty else float("nan")
    switch_text = "not available" if math.isnan(mean_switch) else f"{mean_switch:.1f} days"
    return f"""# Network disruption decision brief

- **Scenario:** Supplier origin unavailable - {country}
- **Decision owner:** {owner}
- **Review window:** {review_window}

## Evidence

- Award-weighted COGS exposure: ${float(exposure['exposed_cogs']):,.0f} ({float(exposure['exposed_share']):.1%})
- Suppliers in origin: {int(exposure['suppliers'])}
- SKUs supplied: {int(exposure['skus_supplied'])}
- Minimum acceptable alternate score: {float(minimum_alternate_score):.1f}
- SKUs without an eligible external alternate: {len(stranded)}
- Recoverable SKUs within the selected window: {within_window} of {len(recoverable)}
- Highest-COGS stranded SKU: {highest}
- Mean best eligible-alternate contract lead time: {switch_text}

## Recommended next checks

1. Confirm alternate capacity, commercial terms and qualification status.
2. Validate on-hand cover and transfer options for stranded SKUs.
3. Replace screening distance with road/freight routing, border time and node capacity before execution.

## Method and boundary

The portfolio dataset and coordinates are synthetic. Location is WGS 84 and distance is great-circle proximity screening. This brief is decision support, not a shipment plan or a claim of live operations.
"""


def governance_checks(
    locations: pd.DataFrame,
    routes: pd.DataFrame,
    scorecard: pd.DataFrame,
) -> pd.DataFrame:
    suppliers = locations[locations.entity_type.eq("supplier")]
    warehouses = locations[locations.entity_type.eq("warehouse")]
    unique_keys = not locations.duplicated(["entity_type", "entity_id"]).any()
    coordinates_valid = (
        locations.longitude.between(-180, 180).all()
        and locations.latitude.between(-90, 90).all()
    )
    route_supplier_ids = set(routes.supplier_id.astype(int))
    supplier_ids = set(suppliers.entity_id.astype(int))
    route_warehouse_ids = set(routes.warehouse_id.astype(int))
    warehouse_ids = set(warehouses.entity_id.astype(int))

    nearest_matches = True
    for route in routes.to_dict("records"):
        supplier = suppliers[suppliers.entity_id.eq(route["supplier_id"])].iloc[0]
        nearest = rank_warehouses(supplier, warehouses).iloc[0]
        if int(nearest.entity_id) != int(route["warehouse_id"]):
            nearest_matches = False
            break

    checks = [
        ("Reference-point inventory", len(locations) == 23, f"{len(locations)} points; expected 23"),
        ("WGS 84 coordinate bounds", bool(coordinates_valid), "longitude ±180; latitude ±90"),
        ("Stable business keys", bool(unique_keys), "entity type + entity ID is unique"),
        ("Supplier route coverage", route_supplier_ids == supplier_ids, f"{len(route_supplier_ids)} of {len(supplier_ids)} suppliers"),
        ("Warehouse referential integrity", route_warehouse_ids <= warehouse_ids, f"{len(route_warehouse_ids)} routed nodes found in master"),
        ("Nearest-node selection", bool(nearest_matches), "published destination recomputed by Haversine distance"),
        ("Declared analysis basis", routes.analysis_basis.eq("nearest_node_great_circle_screening").all(), "every route declares screening basis"),
        ("Supplier performance join", set(scorecard.supplier_id.astype(int)) == supplier_ids, f"{scorecard.supplier_id.nunique()} scorecards for {len(supplier_ids)} suppliers"),
    ]
    return pd.DataFrame([
        {"control": name, "status": "PASS" if passed else "BLOCK", "evidence": evidence}
        for name, passed, evidence in checks
    ])


def filtered_route_geojson(route_geojson: dict, supplier_ids: Iterable[int]) -> str:
    selected = {int(item) for item in supplier_ids}
    payload = {
        "type": "FeatureCollection",
        "features": [
            feature for feature in route_geojson.get("features", [])
            if int(feature.get("properties", {}).get("supplier_id", -1)) in selected
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
