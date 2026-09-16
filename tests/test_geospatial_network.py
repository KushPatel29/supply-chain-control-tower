"""Contract tests for the GIS screening layer."""

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import geospatial_network as gis  # noqa: E402


def built():
    locations = gis.load_locations()
    gis.validate_against_master(locations)
    points = gis.point_collection(locations)
    routes, summary = gis.nearest_routes(locations)
    return locations, points, routes, summary


def test_gis_reference_matches_both_governed_dimensions():
    locations = gis.load_locations()
    gis.validate_against_master(locations)
    assert len(locations) == 34


def test_every_coordinate_is_valid_wgs84():
    locations, _, _, _ = built()
    assert all(-180 <= row["longitude"] <= 180 for row in locations)
    assert all(-90 <= row["latitude"] <= 90 for row in locations)


def test_point_layer_is_rfc7946_geojson():
    locations, points, _, _ = built()
    assert points["type"] == "FeatureCollection"
    assert len(points["features"]) == len(locations)
    assert {feature["geometry"]["type"] for feature in points["features"]} == {"Point"}


def test_each_supplier_has_one_screening_route():
    _, _, routes, summary = built()
    assert len(routes["features"]) == 24
    assert len(summary) == 24
    assert len({row["supplier_id"] for row in summary}) == 24


def test_route_endpoint_is_really_the_nearest_warehouse():
    locations, _, _, summary = built()
    suppliers = {row["entity_id"]: row for row in locations if row["entity_type"] == "supplier"}
    warehouses = [row for row in locations if row["entity_type"] == "warehouse"]
    for route in summary:
        expected = min(warehouses, key=lambda node: gis.haversine_km(
            suppliers[route["supplier_id"]], node))
        assert route["warehouse_id"] == expected["entity_id"]


def test_published_geojson_can_be_parsed_and_has_a_declared_basis():
    for name in ("network_locations.geojson", "supplier_routes.geojson"):
        payload = json.loads((ROOT / "analytics" / "output" / name).read_text(encoding="utf-8"))
        assert payload["type"] == "FeatureCollection"
        assert payload["features"]
    routes = json.loads((ROOT / "analytics" / "output" / "supplier_routes.geojson").read_text(encoding="utf-8"))
    assert all(feature["properties"]["analysis_basis"]
               == "nearest_node_great_circle_screening" for feature in routes["features"])


def test_gis_readme_visual_is_a_1600_by_900_png():
    """Keep the portfolio proof tied to a reviewable, high-resolution artifact."""
    image = ROOT / "docs" / "assets" / "gis-network-risk-map.png"
    payload = image.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", payload[16:24])
    assert (width, height) == (1600, 900)
