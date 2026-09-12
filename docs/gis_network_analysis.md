# GIS Network Analysis

## Purpose

Add spatial context to the existing supplier-risk and inventory workflow: where
are the governed nodes, which distribution centre is geographically closest to
each source, and which candidate connections deserve deeper routing analysis?

This is a portfolio demonstration of GIS data preparation and analytical
requirements. It is not municipal work and it does not represent a live
transport network.

## Reviewable Evidence

| Artifact | Use |
|---|---|
| [`gis/network_locations.csv`](../gis/network_locations.csv) | Governed WGS 84 reference points for 15 suppliers and 8 warehouses |
| [`analytics/geospatial_network.py`](../analytics/geospatial_network.py) | Coordinate validation, dimension reconciliation, Haversine distance and nearest-node screening |
| [`network_locations.geojson`](../analytics/output/network_locations.geojson) | QGIS, ArcGIS Pro and web-map-ready point layer |
| [`supplier_routes.geojson`](../analytics/output/supplier_routes.geojson) | Line layer for screened supplier-to-warehouse connections |
| [`gis_route_summary.csv`](../analytics/output/gis_route_summary.csv) | Flat join surface for Power BI, Excel or GIS attribute analysis |
| [`tests/test_geospatial_network.py`](../tests/test_geospatial_network.py) | Six automated controls over identity, coordinates, geometry and route selection |

GitHub renders the committed GeoJSON files as map layers in the browser, so a
reviewer can inspect the geometries without installing desktop software.

## Spatial Data Contract

- Coordinate reference system: WGS 84 longitude/latitude (EPSG:4326), following
  RFC 7946 GeoJSON coordinate order: `[longitude, latitude]`.
- Business keys: `entity_type + entity_id`; names must reconcile to the
  corresponding supplier or warehouse dimension before publication.
- Geometry types: Point for nodes and LineString for screening connections.
- Provenance: every coordinate carries `synthetic_reference_point` as its
  basis, so approximate portfolio locations cannot be mistaken for facilities.
- Published distance: great-circle kilometres, rounded to one decimal.

## QGIS / ArcGIS Review Workflow

1. Load `network_locations.geojson` and `supplier_routes.geojson`.
2. Confirm the project CRS is EPSG:4326; use a suitable projected CRS before
   measuring or buffering at regional scale.
3. Style points by `entity_type`, lines by `distance_band`, and label by name.
4. Join `gis_route_summary.csv` to supplier attributes using `supplier_id`.
5. Filter intercontinental connections or unqualified alternates for review.
6. Validate any operational recommendation against road/port routes, capacity,
   border time and service dates before action.

## Requirements and Acceptance

| ID | Requirement | Acceptance condition |
|---|---|---|
| GIS-01 | Spatial records use governed business keys. | The build stops if a supplier or warehouse ID/name differs from the master dimension. |
| GIS-02 | Coordinates are interoperable with common GIS tools. | Both published layers parse as RFC 7946 GeoJSON with valid WGS 84 ranges. |
| GIS-03 | Each supplier receives one transparent screening connection. | The selected warehouse has the minimum calculated great-circle distance. |
| GIS-04 | Analytical limitations remain visible. | Each route declares the screening basis; the documentation excludes road-routing claims. |

## Municipal Transfer Boundary

The transferable skills are spatial requirements, coordinate/data validation,
business-key joins, layer design, symbology-ready attributes and explaining the
difference between screening distance and operational routing. A municipal
asset workflow would additionally require authoritative parcel, road, utility
or facility layers; local coordinate systems; topology and linear referencing;
privacy rules; field-edit governance; and validation with asset owners. Those
capabilities are not claimed by this demonstration.
