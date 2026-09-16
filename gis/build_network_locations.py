"""
Build the governed GIS reference layer from the business dimensions.

`network_locations.csv` gives every distribution centre and vendor a point on the
earth, and `analytics/geospatial_network.py` refuses to run if that layer and
`data/bronze/` disagree about which entities exist or what they are called. That
check is the right one - a GIS layer that has drifted from the master data draws
confident routes to places the business does not have - but it also means the
layer cannot be maintained by hand once the network changes.

So it is derived: distribution centres take the coordinates of the city the
dimension says they are in, and vendors take a representative port or industrial
city in their country of origin, nudged by a fixed per-vendor offset so two
vendors in the same country are not stacked on one pixel and every lane has a real
length.

The coordinates are real places; the assignment of a synthetic business to one is
not, which is what `location_basis` records.

Usage:
    python gis/build_network_locations.py
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "data" / "bronze"
OUT = ROOT / "gis" / "network_locations.csv"

# Canadian cities the network runs through: (latitude, longitude).
CITIES: dict[str, tuple[float, float]] = {
    "Vancouver": (49.2827, -123.1207), "Surrey": (49.1913, -122.8490),
    "Burnaby": (49.2488, -122.9805), "Richmond": (49.1666, -123.1336),
    "Coquitlam": (49.2838, -122.7932), "Kelowna": (49.8880, -119.4960),
    "Kamloops": (50.6745, -120.3273), "Prince George": (53.9171, -122.7497),
    "Nelson": (49.4928, -117.2948), "Vernon": (50.2670, -119.2720),
    "Calgary": (51.0447, -114.0719), "Edmonton": (53.5461, -113.4909),
    "Red Deer": (52.2681, -113.8112), "Lethbridge": (49.6956, -112.8451),
    "Grande Prairie": (55.1707, -118.7947), "Toronto": (43.6532, -79.3832),
    "Ottawa": (45.4215, -75.6972), "Hamilton": (43.2557, -79.8711),
    "London": (42.9849, -81.2453), "Sudbury": (46.4917, -80.9930),
    "Montreal": (45.5019, -73.5673), "Quebec City": (46.8139, -71.2080),
    "Laval": (45.6066, -73.7124), "Gatineau": (45.4765, -75.7013),
    "Sherbrooke": (45.4042, -71.8929),
}

# A representative export port or industrial city per sourcing country.
ORIGIN_POINTS: dict[str, tuple[float, float]] = {
    "Canada": (45.5019, -73.5673),        # Montreal
    "USA": (41.8781, -87.6298),           # Chicago
    "Mexico": (25.6866, -100.3161),       # Monterrey
    "Chile": (-33.4489, -70.6693),        # Santiago
    "Brazil": (-23.5505, -46.6333),       # Sao Paulo
    "Spain": (39.4699, -0.3763),          # Valencia
    "Poland": (52.2297, 21.0122),         # Warsaw
    "Turkiye": (41.0082, 28.9784),        # Istanbul
    "Thailand": (13.7563, 100.5018),      # Bangkok
    "Vietnam": (10.8231, 106.6297),       # Ho Chi Minh City
    "China": (31.2304, 121.4737),         # Shanghai
    "India": (19.0760, 72.8777),          # Mumbai
    "New Zealand": (-36.8485, 174.7633),  # Auckland
}
JITTER_DEGREES = 0.45


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def offset(key: str) -> tuple[float, float]:
    """A fixed, reproducible nudge, so vendors in one country spread out."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return ((digest[0] / 255 - 0.5) * 2 * JITTER_DEGREES,
            (digest[1] / 255 - 0.5) * 2 * JITTER_DEGREES)


def build() -> list[dict]:
    rows = []
    for warehouse in read_csv(BRONZE / "dim_warehouse.csv"):
        city = warehouse["city"]
        if city not in CITIES:
            raise KeyError(f"no coordinate for distribution centre city {city!r}")
        latitude, longitude = CITIES[city]
        rows.append({
            "entity_type": "warehouse", "entity_id": int(warehouse["warehouse_id"]),
            "name": warehouse["warehouse_name"], "country": "Canada",
            "region": warehouse["region"], "longitude": round(longitude, 4),
            "latitude": round(latitude, 4), "location_basis": "dimension_city_reference_point",
        })
    for supplier in read_csv(BRONZE / "dim_supplier.csv"):
        country = supplier["country"]
        if country not in ORIGIN_POINTS:
            raise KeyError(f"no coordinate for sourcing country {country!r}")
        latitude, longitude = ORIGIN_POINTS[country]
        d_lat, d_lon = offset(supplier["supplier_name"])
        rows.append({
            "entity_type": "supplier", "entity_id": int(supplier["supplier_id"]),
            "name": supplier["supplier_name"], "country": country,
            "region": supplier["sourcing_bloc"], "longitude": round(longitude + d_lon, 4),
            "latitude": round(latitude + d_lat, 4), "location_basis": "synthetic_reference_point",
        })
    return rows


def main() -> int:
    rows = build()
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    warehouses = sum(1 for row in rows if row["entity_type"] == "warehouse")
    print(f"wrote {len(rows)} points to {OUT} "
          f"({warehouses} distribution centres, {len(rows) - warehouses} vendors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
