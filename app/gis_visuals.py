"""Plotly figures for the GIS Network Risk Decision Room."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.graph_objects as go


OCEAN = "#071014"
LAND = "#173036"
GRID = "#315158"
INK = "#e8f1ef"
MUTED = "#8ea7a8"
CYAN = "#46e5d5"
AMBER = "#e4b35a"
CORAL = "#f06d67"


def _base_geo(height: int = 500) -> dict:
    return {
        "height": height,
        "margin": {"l": 0, "r": 0, "t": 12, "b": 0},
        "paper_bgcolor": OCEAN,
        "plot_bgcolor": OCEAN,
        "font": {"family": "Arial, sans-serif", "color": INK},
        "legend": {
            "orientation": "h", "x": 0.01, "y": 0.02,
            "bgcolor": "rgba(7,16,20,0.86)", "bordercolor": GRID, "borderwidth": 1,
            "font": {"size": 11},
        },
        "geo": {
            "projection": {"type": "natural earth"},
            "showland": True, "landcolor": LAND,
            "showocean": True, "oceancolor": OCEAN,
            "showlakes": True, "lakecolor": OCEAN,
            "showcoastlines": True, "coastlinecolor": GRID, "coastlinewidth": 0.8,
            "showcountries": True, "countrycolor": GRID, "countrywidth": 0.4,
            "bgcolor": OCEAN,
            "lonaxis": {"showgrid": True, "gridcolor": "rgba(49,81,88,0.28)", "dtick": 30},
            "lataxis": {"showgrid": True, "gridcolor": "rgba(49,81,88,0.28)", "dtick": 30},
        },
        "hoverlabel": {"bgcolor": "#0d1b20", "bordercolor": GRID, "font": {"color": INK}},
    }


def _route_trace(row: dict, color: str, width: float, name: str, dash: str = "solid", showlegend: bool = False) -> go.Scattergeo:
    return go.Scattergeo(
        lon=[row["supplier_longitude"], row["warehouse_longitude"]],
        lat=[row["supplier_latitude"], row["warehouse_latitude"]],
        mode="lines",
        line={"width": width, "color": color, "dash": dash},
        name=name,
        legendgroup=name,
        showlegend=showlegend,
        hovertemplate=(
            f"<b>{row['supplier_name']}</b><br>"
            f"{row['supplier_country']} → {row['warehouse_name']}<br>"
            f"{float(row['distance_km']):,.1f} km · great-circle screening<extra></extra>"
        ),
    )


def network_map(
    locations: pd.DataFrame,
    routes: pd.DataFrame,
    highlighted_supplier_ids: Iterable[int] = (),
) -> go.Figure:
    highlighted = {int(item) for item in highlighted_supplier_ids}
    fig = go.Figure()
    legend_written = {"Focused route": False, "Other route": False}
    for row in routes.to_dict("records"):
        focus = not highlighted or int(row["supplier_id"]) in highlighted
        name = "Focused route" if focus else "Other route"
        color = "rgba(228,179,90,0.74)" if focus else "rgba(142,167,168,0.16)"
        fig.add_trace(_route_trace(
            row, color, 1.8 if focus else 0.8, name,
            showlegend=not legend_written[name],
        ))
        legend_written[name] = True

    suppliers = locations[locations.entity_type.eq("supplier")].copy()
    suppliers["focused"] = suppliers.entity_id.astype(int).isin(highlighted) if highlighted else True
    for focused, label, color, size in (
        (False, "Other supplier", "rgba(142,167,168,0.45)", 7),
        (True, "Supplier in scenario", AMBER, 10),
    ):
        subset = suppliers[suppliers.focused.eq(focused)]
        if subset.empty:
            continue
        fig.add_trace(go.Scattergeo(
            lon=subset.longitude, lat=subset.latitude, mode="markers",
            marker={"size": size, "color": color, "symbol": "circle", "line": {"color": OCEAN, "width": 1.2}},
            text=subset.apply(lambda row: f"<b>{row['name']}</b><br>{row['country']} · {row['region']}", axis=1),
            hovertemplate="%{text}<extra></extra>", name=label,
        ))
    warehouses = locations[locations.entity_type.eq("warehouse")]
    fig.add_trace(go.Scattergeo(
        lon=warehouses.longitude, lat=warehouses.latitude, mode="markers",
        marker={"size": 12, "color": CYAN, "symbol": "diamond", "line": {"color": OCEAN, "width": 1.4}},
        text=warehouses.apply(lambda row: f"<b>{row['name']}</b><br>{row['region']} · synthetic node", axis=1),
        hovertemplate="%{text}<extra></extra>", name="Distribution node",
    ))
    fig.update_layout(**_base_geo())
    return fig


def scenario_map(
    locations: pd.DataFrame,
    routes: pd.DataFrame,
    scenario: pd.DataFrame,
    unavailable_warehouse_ids: Iterable[int],
) -> go.Figure:
    unavailable = {int(item) for item in unavailable_warehouse_ids}
    impacted_ids = set(scenario.loc[scenario.impacted, "supplier_id"].astype(int))
    fig = go.Figure()
    route_by_supplier = routes.set_index("supplier_id")

    for row in routes.to_dict("records"):
        if int(row["supplier_id"]) in impacted_ids:
            continue
        fig.add_trace(_route_trace(row, "rgba(142,167,168,0.15)", 0.8, "Unaffected route", showlegend=False))

    baseline_legend = False
    scenario_legend = False
    warehouses = locations[locations.entity_type.eq("warehouse")].set_index("entity_id")
    for decision in scenario[scenario.impacted].to_dict("records"):
        baseline = route_by_supplier.loc[int(decision["supplier_id"])].to_dict()
        fig.add_trace(_route_trace(
            baseline, "rgba(240,109,103,0.62)", 1.6, "Blocked baseline", "dash",
            showlegend=not baseline_legend,
        ))
        baseline_legend = True
        destination = warehouses.loc[int(decision["scenario_warehouse_id"])]
        fig.add_trace(go.Scattergeo(
            lon=[baseline["supplier_longitude"], destination.longitude],
            lat=[baseline["supplier_latitude"], destination.latitude],
            mode="lines", line={"width": 2.4, "color": CYAN},
            name="Screened reroute", legendgroup="Screened reroute", showlegend=not scenario_legend,
            hovertemplate=(
                f"<b>{decision['supplier_name']}</b><br>"
                f"Reroute → {decision['scenario_warehouse_name']}<br>"
                f"{decision['scenario_distance_km']:,.1f} km · +{decision['extra_distance_km']:,.1f} km<extra></extra>"
            ),
        ))
        scenario_legend = True

    suppliers = locations[locations.entity_type.eq("supplier")]
    impacted_suppliers = suppliers[suppliers.entity_id.astype(int).isin(impacted_ids)]
    fig.add_trace(go.Scattergeo(
        lon=impacted_suppliers.longitude, lat=impacted_suppliers.latitude, mode="markers",
        marker={"size": 10, "color": AMBER, "symbol": "circle", "line": {"color": OCEAN, "width": 1.2}},
        text=impacted_suppliers.name, hovertemplate="<b>%{text}</b><extra></extra>", name="Impacted supplier",
    ))
    node_rows = locations[locations.entity_type.eq("warehouse")].copy()
    online = node_rows[~node_rows.entity_id.astype(int).isin(unavailable)]
    offline = node_rows[node_rows.entity_id.astype(int).isin(unavailable)]
    fig.add_trace(go.Scattergeo(
        lon=online.longitude, lat=online.latitude, mode="markers",
        marker={"size": 12, "color": CYAN, "symbol": "diamond", "line": {"color": OCEAN, "width": 1.4}},
        text=online.name, hovertemplate="<b>%{text}</b><br>Available node<extra></extra>", name="Available node",
    ))
    if not offline.empty:
        fig.add_trace(go.Scattergeo(
            lon=offline.longitude, lat=offline.latitude, mode="markers",
            marker={"size": 14, "color": CORAL, "symbol": "x", "line": {"color": CORAL, "width": 2}},
            text=offline.name, hovertemplate="<b>%{text}</b><br>Unavailable in scenario<extra></extra>", name="Unavailable node",
        ))
    fig.update_layout(**_base_geo())
    return fig


def distance_score_scatter(routes: pd.DataFrame, highlighted_supplier_ids: Iterable[int] = ()) -> go.Figure:
    highlighted = {int(item) for item in highlighted_supplier_ids}
    fig = go.Figure()
    for region, subset in routes.groupby("supplier_region", sort=True):
        sizes = 9 + 21 * (subset.spend / routes.spend.max()).pow(0.5)
        line_width = [2.2 if int(item) in highlighted else 0.8 for item in subset.supplier_id]
        fig.add_trace(go.Scatter(
            x=subset.distance_km, y=subset.composite_score, mode="markers",
            marker={"size": sizes, "color": AMBER if region == "Asia Pacific" else CYAN,
                    "opacity": 0.88, "line": {"color": INK, "width": line_width}},
            text=subset.supplier_name,
            customdata=subset[["supplier_country", "warehouse_name", "spend", "otif_rate"]],
            hovertemplate=(
                "<b>%{text}</b><br>%{customdata[0]} → %{customdata[1]}<br>"
                "%{x:,.0f} km · score %{y:.1f}<br>"
                "$%{customdata[2]:,.0f} spend · OTIF %{customdata[3]:.1%}<extra></extra>"
            ), name=region,
        ))
    fig.update_layout(
        height=370, margin={"l": 18, "r": 12, "t": 24, "b": 22},
        paper_bgcolor=OCEAN, plot_bgcolor=OCEAN, font={"family": "Arial", "color": INK},
        xaxis={"title": "Great-circle screening distance (km)", "gridcolor": GRID, "zeroline": False},
        yaxis={"title": "Measured supplier score", "range": [30, 75], "gridcolor": GRID, "zeroline": False},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        hoverlabel={"bgcolor": "#0d1b20", "bordercolor": GRID, "font": {"color": INK}},
    )
    return fig


def country_exposure_bar(exposure: pd.DataFrame, selected_country: str) -> go.Figure:
    ordered = exposure.sort_values("exposed_share", ascending=True)
    colors = [AMBER if country == selected_country else "rgba(70,229,213,0.36)" for country in ordered.country]
    fig = go.Figure(go.Bar(
        x=ordered.exposed_share, y=ordered.country, orientation="h",
        marker={"color": colors},
        text=ordered.exposed_share, texttemplate="%{text:.0%}",
        textposition="outside", cliponaxis=False,
        customdata=ordered[["stranded_skus", "mean_switch_lead_days"]],
        hovertemplate="<b>%{y}</b><br>%{x:.1%} COGS exposure<br>%{customdata[0]} stranded SKUs<br>%{customdata[1]:.1f} switch days<extra></extra>",
    ))
    fig.update_layout(
        height=370, margin={"l": 4, "r": 12, "t": 24, "b": 22},
        paper_bgcolor=OCEAN, plot_bgcolor=OCEAN, font={"family": "Arial", "color": INK},
        xaxis={"title": "Award-weighted COGS exposure", "tickformat": ".0%", "gridcolor": GRID, "range": [0, max(0.30, ordered.exposed_share.max() * 1.12)]},
        yaxis={"title": "", "gridcolor": OCEAN}, showlegend=False,
        hoverlabel={"bgcolor": "#0d1b20", "bordercolor": GRID, "font": {"color": INK}},
    )
    return fig


def reroute_penalty_chart(scenario: pd.DataFrame) -> go.Figure:
    impacted = scenario[scenario.impacted].sort_values("extra_distance_km", ascending=True)
    fig = go.Figure(go.Bar(
        x=impacted.extra_distance_km, y=impacted.supplier_name, orientation="h",
        marker={"color": [CORAL if value > 500 else AMBER for value in impacted.extra_distance_km]},
        text=impacted.extra_distance_km, texttemplate="+%{text:,.0f} km",
        textposition="outside", cliponaxis=False,
        customdata=impacted[["scenario_warehouse_name", "scenario_distance_km"]],
        hovertemplate="<b>%{y}</b><br>+%{x:,.1f} km<br>Reroute to %{customdata[0]} (%{customdata[1]:,.1f} km)<extra></extra>",
    ))
    fig.update_layout(
        height=max(310, 54 * max(1, len(impacted))), margin={"l": 6, "r": 12, "t": 20, "b": 20},
        paper_bgcolor=OCEAN, plot_bgcolor=OCEAN, font={"family": "Arial", "color": INK},
        xaxis={"title": "Additional screening distance (km)", "gridcolor": GRID, "rangemode": "tozero"},
        yaxis={"title": "", "gridcolor": OCEAN}, showlegend=False,
        hoverlabel={"bgcolor": "#0d1b20", "bordercolor": GRID, "font": {"color": INK}},
    )
    return fig
