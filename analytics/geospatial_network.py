"""Build QGIS/ArcGIS-ready network layers from governed location references.

This is a screening layer, not a transport-routing engine. It uses WGS 84
points and great-circle distance to connect each synthetic supplier reference
point to its nearest synthetic distribution node. Road distance, border time,
capacity and service commitments are intentionally out of scope.

Outputs (analytics/output/):
    network_locations.geojson  supplier and warehouse points
    supplier_routes.geojson    screening lines to the nearest warehouse
    gis_route_summary.csv      auditable attributes for BI or GIS joins
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gis" / "network_locations.csv"
BRONZE = ROOT / "data" / "bronze"
OUT = Path(__file__).resolve().parent / "output"
EARTH_RADIUS_KM = 6371.0088


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_locations() -> list[dict]:
    rows = read_csv(SOURCE)
    locations = []
    for row in rows:
        locations.append({
            **row,
            "entity_id": int(row["entity_id"]),
            "longitude": float(row["longitude"]),
            "latitude": float(row["latitude"]),
        })
    return locations


def validate_against_master(locations: list[dict]) -> None:
    """Refuse GIS layers that drift from the governed business dimensions."""
    masters = {
        "supplier": read_csv(BRONZE / "dim_supplier.csv"),
        "warehouse": read_csv(BRONZE / "dim_warehouse.csv"),
    }
    for entity_type, master_rows in masters.items():
        expected = {(int(row[f"{entity_type}_id"]), row[f"{entity_type}_name"])
                    for row in master_rows}
        actual = {(row["entity_id"], row["name"])
                  for row in locations if row["entity_type"] == entity_type}
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise ValueError(
                f"{entity_type} GIS reference drift: missing={missing}, "
                f"unexpected={unexpected}")

    for row in locations:
        if not (-180 <= row["longitude"] <= 180
                and -90 <= row["latitude"] <= 90):
            raise ValueError(f"invalid WGS 84 coordinate: {row}")


def haversine_km(a: dict, b: dict) -> float:
    """Great-circle distance between two WGS 84 points."""
    lat1, lon1 = math.radians(a["latitude"]), math.radians(a["longitude"])
    lat2, lon2 = math.radians(b["latitude"]), math.radians(b["longitude"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(value))


def distance_band(distance_km: float) -> str:
    if distance_km <= 500:
        return "regional"
    if distance_km <= 2500:
        return "continental"
    return "intercontinental"


def point_collection(locations: list[dict]) -> dict:
    features = []
    for row in sorted(locations, key=lambda item: (item["entity_type"], item["entity_id"])):
        properties = {key: value for key, value in row.items()
                      if key not in {"longitude", "latitude"}}
        features.append({
            "type": "Feature",
            "id": f'{row["entity_type"]}-{row["entity_id"]}',
            "properties": properties,
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def nearest_routes(locations: list[dict]) -> tuple[dict, list[dict]]:
    suppliers = [row for row in locations if row["entity_type"] == "supplier"]
    warehouses = [row for row in locations if row["entity_type"] == "warehouse"]
    features, summary = [], []
    for supplier in sorted(suppliers, key=lambda item: item["entity_id"]):
        warehouse, distance = min(
            ((warehouse, haversine_km(supplier, warehouse)) for warehouse in warehouses),
            key=lambda pair: pair[1],
        )
        distance = round(distance, 1)
        attributes = {
            "supplier_id": supplier["entity_id"],
            "supplier_name": supplier["name"],
            "supplier_country": supplier["country"],
            "warehouse_id": warehouse["entity_id"],
            "warehouse_name": warehouse["name"],
            "distance_km": distance,
            "distance_band": distance_band(distance),
            "analysis_basis": "nearest_node_great_circle_screening",
        }
        summary.append(attributes)
        features.append({
            "type": "Feature",
            "id": f'supplier-{supplier["entity_id"]}-route',
            "properties": attributes,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [supplier["longitude"], supplier["latitude"]],
                    [warehouse["longitude"], warehouse["latitude"]],
                ],
            },
        })
    return {"type": "FeatureCollection", "features": features}, summary


def build() -> None:
    locations = load_locations()
    validate_against_master(locations)
    points = point_collection(locations)
    routes, summary = nearest_routes(locations)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in (("network_locations.geojson", points),
                          ("supplier_routes.geojson", routes)):
        (OUT / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    with (OUT / "gis_route_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    build()
