"""Render the governed supplier-to-distribution GIS screening layer.

This presentation artifact reads the same committed GeoJSON that analysts can
open in QGIS or ArcGIS. It does not recalculate routes, invent a road network,
or change the analytical output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import plotly.graph_objects as go


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "gis-network-risk-map.png"

OCEAN = "#071014"
LAND = "#15262a"
GRID = "#29454b"
INK = "#e8f1ef"
MUTED = "#8ea7a8"
CYAN = "#46e5d5"
AMBER = "#e4b35a"


def load_geojson() -> tuple[dict, dict]:
    output = ROOT / "analytics" / "output"
    locations = json.loads((output / "network_locations.geojson").read_text(encoding="utf-8"))
    routes = json.loads((output / "supplier_routes.geojson").read_text(encoding="utf-8"))
    return locations, routes


def build_figure() -> go.Figure:
    locations, routes = load_geojson()
    fig = go.Figure()

    for feature in routes["features"]:
        start, end = feature["geometry"]["coordinates"]
        properties = feature["properties"]
        fig.add_trace(go.Scattergeo(
            lon=[start[0], end[0]],
            lat=[start[1], end[1]],
            mode="lines",
            line={"width": 1.35, "color": "rgba(228, 179, 90, 0.48)"},
            hovertemplate=(
                f"<b>{properties['supplier_name']}</b><br>"
                f"{properties['supplier_country']} → {properties['warehouse_name']}<br>"
                f"{properties['distance_km']:,.1f} km · screening distance<extra></extra>"
            ),
            showlegend=False,
        ))

    suppliers = [item for item in locations["features"] if item["properties"]["entity_type"] == "supplier"]
    warehouses = [item for item in locations["features"] if item["properties"]["entity_type"] == "warehouse"]

    def point_trace(features: list[dict], name: str, color: str, size: int, symbol: str) -> go.Scattergeo:
        return go.Scattergeo(
            lon=[item["geometry"]["coordinates"][0] for item in features],
            lat=[item["geometry"]["coordinates"][1] for item in features],
            text=[
                f"<b>{item['properties']['name']}</b><br>"
                f"{item['properties']['country']} · {item['properties']['region']}"
                for item in features
            ],
            hovertemplate="%{text}<extra></extra>",
            mode="markers",
            marker={
                "size": size,
                "color": color,
                "symbol": symbol,
                "line": {"width": 1.5, "color": OCEAN},
            },
            name=name,
        )

    fig.add_trace(point_trace(suppliers, "Supplier origin", AMBER, 10, "circle"))
    fig.add_trace(point_trace(warehouses, "Canadian distribution node", CYAN, 13, "diamond"))

    intercontinental = sum(
        feature["properties"]["distance_band"] == "intercontinental"
        for feature in routes["features"]
    )
    fig.update_layout(
        width=1600,
        height=900,
        margin={"l": 46, "r": 42, "t": 142, "b": 54},
        paper_bgcolor=OCEAN,
        plot_bgcolor=OCEAN,
        font={"family": "Arial, sans-serif", "color": INK},
        title={
            "text": (
                "<b>Global sourcing risk needs spatial context</b>"
                "<br><span style='font-size:17px;color:#8ea7a8'>Supplier origins to the nearest Canadian distribution node · governed screening layer</span>"
            ),
            "x": 0.035,
            "xanchor": "left",
            "y": 0.965,
            "yanchor": "top",
            "font": {"size": 32, "color": INK},
        },
        geo={
            "domain": {"x": [0.0, 0.745], "y": [0.0, 0.94]},
            "projection": {"type": "natural earth"},
            "showland": True,
            "landcolor": LAND,
            "showocean": True,
            "oceancolor": OCEAN,
            "showlakes": True,
            "lakecolor": OCEAN,
            "showcoastlines": True,
            "coastlinecolor": GRID,
            "coastlinewidth": 0.9,
            "showcountries": True,
            "countrycolor": GRID,
            "countrywidth": 0.45,
            "bgcolor": OCEAN,
            "lonaxis": {"showgrid": True, "gridcolor": "rgba(41,69,75,0.35)", "dtick": 30},
            "lataxis": {"showgrid": True, "gridcolor": "rgba(41,69,75,0.35)", "dtick": 30},
        },
        legend={
            "orientation": "h",
            "x": 0.02,
            "y": 0.01,
            "bgcolor": "rgba(7,16,20,0.82)",
            "bordercolor": GRID,
            "borderwidth": 1,
            "font": {"size": 13, "color": INK},
        },
        shapes=[
            {
                "type": "rect", "xref": "paper", "yref": "paper",
                "x0": 0.77, "x1": 1.0, "y0": 0.05, "y1": 0.92,
                "line": {"color": GRID, "width": 1}, "fillcolor": "#0d1b20",
            },
            {
                "type": "line", "xref": "paper", "yref": "paper",
                "x0": 0.795, "x1": 0.975, "y0": 0.565, "y1": 0.565,
                "line": {"color": GRID, "width": 1},
            },
        ],
        annotations=[
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.865,
                "text": "<b>SCREENING EVIDENCE</b>", "showarrow": False,
                "xanchor": "left", "font": {"size": 13, "color": CYAN},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.79,
                "text": f"<b>{len(locations['features'])}</b>",
                "showarrow": False, "xanchor": "left", "font": {"size": 30, "color": INK},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.735,
                "text": "governed reference points",
                "showarrow": False, "xanchor": "left", "font": {"size": 13, "color": MUTED},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.64,
                "text": f"<b>{len(routes['features'])}</b>",
                "showarrow": False, "xanchor": "left", "font": {"size": 30, "color": INK},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.585,
                "text": "nearest-node routes",
                "showarrow": False, "xanchor": "left", "font": {"size": 13, "color": MUTED},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.91, "y": 0.64,
                "text": f"<b>{intercontinental}</b>",
                "showarrow": False, "xanchor": "left", "font": {"size": 30, "color": AMBER},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.91, "y": 0.585,
                "text": "intercontinental lanes",
                "showarrow": False, "xanchor": "left", "font": {"size": 13, "color": MUTED},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.51,
                "text": "<b>ANALYSIS CONTRACT</b>", "showarrow": False,
                "xanchor": "left", "font": {"size": 13, "color": CYAN},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.42,
                "text": (
                    "WGS 84 · EPSG:4326<br>"
                    "Great-circle distance<br>"
                    "Nearest-node selection<br>"
                    "Stable business keys"
                ),
                "showarrow": False, "xanchor": "left", "align": "left",
                "font": {"size": 16, "color": INK},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.27,
                "text": "<b>DECISION USE</b>", "showarrow": False,
                "xanchor": "left", "font": {"size": 13, "color": CYAN},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.205,
                "text": (
                    "Screen long inbound lanes<br>"
                    "before supplier review."
                ),
                "showarrow": False, "xanchor": "left", "align": "left",
                "font": {"size": 15, "color": INK},
            },
            {
                "xref": "paper", "yref": "paper", "x": 0.795, "y": 0.095,
                "text": "Synthetic coordinates · screening,<br>not road routing or live operations.",
                "showarrow": False, "xanchor": "left", "align": "left",
                "font": {"size": 12, "color": MUTED},
            },
        ],
    )
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_figure().write_image(args.output, width=1600, height=900, scale=1)
    print(f"Rendered {args.output}")


if __name__ == "__main__":
    main()
