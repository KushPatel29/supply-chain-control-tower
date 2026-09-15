"""Focused contract tests for the interview-ready GIS decision assurance studio.

The analytical modules remain the source of business truth.  These tests cover
the app-specific joins, policy controls, publication gate and presentation
objects without tying assertions to Streamlit's generated HTML.
"""

from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app.advanced_decision_support import (
    build_country_scenario_portfolio,
    warehouse_inventory_risk_summary,
)
from app.gis_decision_engine import (
    country_disruption,
    filtered_route_geojson,
    governance_checks,
    load_app_data,
    reroute_network,
)
from app.gis_visuals import (
    country_exposure_bar,
    distance_score_scatter,
    network_map,
    reroute_penalty_chart,
    scenario_map,
    scenario_landscape,
    warehouse_posture_map,
)


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def evidence():
    return load_app_data(ROOT)


def mexico_response(evidence, minimum_score=0, recovery_days=30):
    return country_disruption(
        "Mexico",
        evidence["sourcing"],
        evidence["suppliers"],
        evidence["products"],
        evidence["concentration"],
        evidence["scorecard"],
        minimum_alternate_score=minimum_score,
        recovery_window_days=recovery_days,
    )


def test_committed_evidence_loads_and_reconciles_one_to_one(evidence):
    locations = evidence["locations"]
    routes = evidence["routes"]
    enriched = evidence["routes_enriched"]
    suppliers = locations[locations.entity_type.eq("supplier")]

    supplier_ids = set(suppliers.entity_id.astype(int))
    assert len(locations) == 23
    assert len(routes) == len(enriched) == len(supplier_ids) == 15
    assert set(routes.supplier_id.astype(int)) == supplier_ids
    assert set(enriched.supplier_id.astype(int)) == supplier_ids
    assert enriched.supplier_id.is_unique
    assert not enriched[[
        "supplier_longitude",
        "supplier_latitude",
        "warehouse_longitude",
        "warehouse_latitude",
        "composite_score",
    ]].isna().any().any()
    assert len(evidence["point_geojson"]["features"]) == len(locations)
    assert len(evidence["route_geojson"]["features"]) == len(routes)


def test_mexico_baseline_matches_the_published_decision_evidence(evidence):
    exposure = evidence["country_exposure"].set_index("country").loc["Mexico"]
    response = mexico_response(evidence)
    stranded = response[response.decision_status.eq("No qualified alternate")]
    recoverable = response[response.decision_status.ne("No qualified alternate")]

    assert exposure.exposed_share == pytest.approx(0.2724)
    assert exposure.exposed_cogs == pytest.approx(11_821_992.49)
    assert len(response) == int(exposure.skus_supplied) == 36
    assert len(stranded) == int(exposure.stranded_skus) == 13
    assert len(recoverable) == 23
    assert int(recoverable.within_recovery_window.sum()) == 7
    assert response.product_id.is_unique
    assert response.country_award_share.between(0, 1).all()


def test_policy_thresholds_make_eligibility_stricter_not_looser(evidence):
    baseline = mexico_response(evidence, minimum_score=0, recovery_days=30)
    stricter = mexico_response(evidence, minimum_score=60, recovery_days=30)
    longer_window = mexico_response(evidence, minimum_score=60, recovery_days=45)

    baseline_stranded = baseline.decision_status.eq("No qualified alternate").sum()
    stricter_stranded = stricter.decision_status.eq("No qualified alternate").sum()
    eligible = stricter[stricter.decision_status.ne("No qualified alternate")]

    assert baseline_stranded == 13
    assert stricter_stranded == 25
    assert stricter_stranded >= baseline_stranded
    assert eligible.alternate_score.ge(60).all()
    assert int(stricter.within_recovery_window.sum()) == 4
    assert int(longer_window.within_recovery_window.sum()) == 11


def test_node_outage_reroutes_only_the_impacted_suppliers(evidence):
    locations = evidence["locations"]
    routes = evidence["routes"]
    warehouses = locations[locations.entity_type.eq("warehouse")]
    offline_id = int(warehouses.loc[warehouses.name.eq("Ontario DC 1"), "entity_id"].iloc[0])
    scenario = reroute_network(locations, routes, [offline_id])

    expected_impacted = set(
        routes.loc[routes.warehouse_id.eq(offline_id), "supplier_id"].astype(int)
    )
    impacted = scenario[scenario.impacted]
    unaffected = scenario[~scenario.impacted]

    assert len(scenario) == len(routes)
    assert set(impacted.supplier_id) == expected_impacted
    assert len(impacted) == 6
    assert impacted.scenario_warehouse_id.ne(offline_id).all()
    assert impacted.extra_distance_km.gt(0).all()
    assert impacted.extra_distance_km.sum() == pytest.approx(1_155.6)
    assert unaffected.scenario_warehouse_id.eq(unaffected.baseline_warehouse_id).all()
    assert unaffected.extra_distance_km.eq(0).all()


def test_governance_gate_passes_clean_evidence_and_blocks_bad_coordinates(evidence):
    clean = governance_checks(
        evidence["locations"], evidence["routes"], evidence["scorecard"]
    )
    assert len(clean) == 8
    assert clean.status.eq("PASS").all()

    invalid = evidence["locations"].copy()
    invalid.loc[invalid.index[0], "latitude"] = 95.0
    blocked = governance_checks(invalid, evidence["routes"], evidence["scorecard"])
    coordinate_control = blocked.loc[
        blocked.control.eq("WGS 84 coordinate bounds"), "status"
    ].iloc[0]

    assert coordinate_control == "BLOCK"
    assert blocked.status.eq("BLOCK").any()


def test_geojson_export_contains_only_selected_supplier_routes(evidence):
    selected = set(evidence["routes"].supplier_id.astype(int).head(3))
    original = json.dumps(evidence["route_geojson"], sort_keys=True)
    payload = json.loads(filtered_route_geojson(evidence["route_geojson"], selected))

    exported_ids = {
        int(feature["properties"]["supplier_id"]) for feature in payload["features"]
    }
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == len(selected)
    assert exported_ids == selected
    assert {feature["geometry"]["type"] for feature in payload["features"]} == {
        "LineString"
    }
    assert json.dumps(evidence["route_geojson"], sort_keys=True) == original


def test_decision_figures_are_nonempty_and_carry_the_expected_evidence(evidence):
    locations = evidence["locations"]
    routes = evidence["routes"]
    enriched = evidence["routes_enriched"]
    mexico_ids = set(
        evidence["suppliers"].loc[
            evidence["suppliers"].country.eq("Mexico"), "supplier_id"
        ].astype(int)
    )
    scenario = reroute_network(locations, routes, [1])
    warehouse_risk = warehouse_inventory_risk_summary(
        evidence["inventory_position"], evidence["warehouses"], locations
    )
    portfolio = build_country_scenario_portfolio(
        evidence["sourcing"],
        evidence["suppliers"],
        evidence["products"],
        evidence["concentration"],
        evidence["scorecard"],
    )

    figures = [
        network_map(locations, enriched, mexico_ids),
        scenario_map(locations, enriched, scenario, [1]),
        distance_score_scatter(enriched, mexico_ids),
        country_exposure_bar(evidence["country_exposure"], "Mexico"),
        reroute_penalty_chart(scenario),
        warehouse_posture_map(locations, warehouse_risk, "Ontario DC 3"),
        scenario_landscape(portfolio, "Mexico"),
    ]

    assert all(isinstance(figure, go.Figure) for figure in figures)
    assert all(len(figure.data) > 0 for figure in figures)
    assert all(int(figure.layout.height) >= 300 for figure in figures)
    assert "Distribution node" in {trace.name for trace in figures[0].data}
    assert {"Blocked baseline", "Next-nearest screen"} <= {
        trace.name for trace in figures[1].data
    }

    screenshot = Image.open(ROOT / "docs" / "assets" / "gis-network-risk-studio.png")
    assert screenshot.size == (1600, 900)


def test_streamlit_app_runs_without_exceptions_and_shows_the_core_workflow():
    app = AppTest.from_file(
        str(ROOT / "streamlit_app.py"), default_timeout=30
    ).run(timeout=30)

    assert not app.exception
    assert [title.value for title in app.title] == [
        "Mexico disruption leaves 13 SKUs without a qualified alternate."
    ]
    workspace = app.get("button_group")[0]
    assert workspace.value == "Executive brief"
    assert workspace.options == [
        "Executive brief",
        "Incident command",
        "Origin risk",
        "Node outage",
        "Handoff",
        "Assurance",
        "Case study",
    ]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Award-weighted COGS exposure"] == "$11.82M"
    assert metrics["Affected SKUs"] == "36"
    assert metrics["No eligible alternate"] == "13"

    workspace.set_value("Incident command").run(timeout=30)
    assert not app.exception
    command_metrics = {metric.label: metric.value for metric in app.metric}
    assert command_metrics["Incident"] == "INC-MEXICOSU-SO-001"
    assert command_metrics["P0 validation queue"] == "13"
    assert command_metrics["Action SLA"] == "240 min"
    assert command_metrics["Recovery target"] == "24 hr"
    download_labels = [button.label for button in app.get("download_button")]
    assert "Download incident action register" in download_labels

    app.get("button_group")[0].set_value("Origin risk").run(timeout=30)
    assert not app.exception
    assert app.selectbox[0].value == "Mexico"
    origin_metrics = {metric.label: metric.value for metric in app.metric}
    assert origin_metrics["No eligible external alternate"] == "13"

    app.slider[0].set_value(60).run(timeout=30)
    stricter_metrics = {metric.label: metric.value for metric in app.metric}
    assert stricter_metrics["No eligible external alternate"] == "25"
    assert stricter_metrics["Eligible alternate lead time fits window"] == "4 / 11"

    app.get("button_group")[0].set_value("Node outage").run(timeout=30)
    node_metrics = {metric.label: metric.value for metric in app.metric}
    assert node_metrics["Impacted supplier screens"] == "6"

    app.get("button_group")[0].set_value("Assurance").run(timeout=30)
    tab_labels = [tab.label for tab in app.tabs]
    assert tab_labels == [
        "Traceability",
        "Replayable UAT",
        "GIS governance",
        "Lineage",
    ]
    assert any("8 of 8 controls are green" in item.value for item in app.success)
    app.toggle[0].set_value(True).run(timeout=30)
    assert any("Publication blocked" in item.value for item in app.error)
    download_labels = [button.label for button in app.get("download_button")]
    assert "Download nine-file evidence pack" not in download_labels
