"""Interview-ready GIS Network Risk Decision Room.

Run with:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.gis_decision_engine import (
    country_decision_brief,
    country_disruption,
    filtered_route_geojson,
    filter_routes,
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
)


st.set_page_config(
    page_title="GIS Network Risk Decision Room | Kush Patel",
    page_icon="🧭",
    layout="wide",
    # Expanded on a laptop, collapsed on narrow screens. Forcing this open
    # obscures the whole interface on a phone-sized viewport.
    initial_sidebar_state="auto",
)

st.markdown(
    """
<style>
  :root {
    --ocean: #071014;
    --panel: #0d1b20;
    --panel-2: #102429;
    --line: #29454b;
    --ink: #e8f1ef;
    --muted: #9db1b2;
    --cyan: #46e5d5;
    --amber: #e4b35a;
    --coral: #f06d67;
  }
  .stApp { background: var(--ocean); color: var(--ink); }
  [data-testid="stHeader"] { background: rgba(7, 16, 20, 0.92); }
  [data-testid="stAppDeployButton"] { display: none; }
  [data-testid="stSidebar"] { background: #09171b; border-right: 1px solid var(--line); }
  [data-testid="stSidebar"] > div { padding-top: 1.25rem; }
  #MainMenu, footer { visibility: hidden; }
  .block-container { max-width: 1460px; padding-top: 2.4rem; padding-bottom: 4rem; }
  h1, h2, h3 { color: var(--ink); letter-spacing: -0.035em; }
  h1 { max-width: 920px; font-size: clamp(2.4rem, 5vw, 4.9rem) !important; line-height: 0.98 !important; }
  h2 { margin-top: 0.5rem; }
  p, li { color: var(--muted); }
  a { color: var(--cyan) !important; }
  :focus-visible { outline: 3px solid var(--amber) !important; outline-offset: 3px !important; }
  .studio-path {
    margin-bottom: 1.1rem;
    color: var(--cyan);
    font: 600 0.78rem/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
  }
  .studio-path span { color: var(--muted); font-weight: 400; }
  .studio-lede { max-width: 820px; margin: 1.1rem 0 1.2rem; font-size: 1.08rem; line-height: 1.7; }
  .truth-strip {
    display: flex; flex-wrap: wrap; gap: 0.65rem 1.35rem;
    margin: 1.15rem 0 1.35rem; padding: 0.8rem 1rem;
    border-left: 3px solid var(--amber); background: rgba(228, 179, 90, 0.055);
    color: #c5d2d2; font: 0.76rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace;
  }
  .truth-strip strong { color: var(--amber); }
  .decision-line {
    margin: 0.7rem 0 1rem; padding: 0.85rem 1rem;
    border: 1px solid var(--line); background: var(--panel);
    color: var(--ink); font-size: 0.94rem; line-height: 1.55;
  }
  .decision-line strong { color: var(--amber); }
  .map-caption {
    margin: -0.4rem 0 1rem; color: var(--muted);
    font: 0.72rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace;
  }
  .section-note { margin: 0.2rem 0 1rem; max-width: 78ch; }
  .side-mark {
    padding: 0.8rem 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
    color: var(--ink); font-size: 0.92rem; line-height: 1.55;
  }
  .side-mark b { color: var(--cyan); }
  .side-meta { margin-top: 1rem; color: var(--muted); font: 0.72rem/1.65 ui-monospace, SFMono-Regular, Consolas, monospace; }
  [data-testid="stMetric"] {
    min-height: 112px; padding: 0.85rem 0.2rem 0.45rem;
    border-top: 1px solid var(--line); background: transparent;
  }
  [data-testid="stMetricLabel"] { color: var(--muted); }
  [data-testid="stMetricValue"] { color: var(--cyan); letter-spacing: -0.04em; }
  [data-testid="stMetricDelta"] { color: var(--amber); }
  [data-baseweb="tab-list"] { gap: 1.1rem; border-bottom: 1px solid var(--line); }
  [data-baseweb="tab"] { height: 3.2rem; padding-left: 0.1rem; padding-right: 0.1rem; }
  [data-baseweb="tab-highlight"] { background-color: var(--cyan); }
  [data-testid="stDataFrame"] { border: 1px solid var(--line); }
  .stButton > button, .stDownloadButton > button {
    border-radius: 2px; border: 1px solid var(--cyan); min-height: 2.8rem;
    background: transparent; color: var(--cyan); font-weight: 650;
  }
  .stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #8af6ed; color: #8af6ed; background: rgba(70, 229, 213, 0.07);
  }
  .stSelectbox [data-baseweb="select"] > div,
  .stMultiSelect [data-baseweb="select"] > div { border-radius: 2px; border-color: var(--line); }
  .control-pass { color: var(--cyan); }
  .control-block { color: var(--coral); }
  .trace-flow {
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
    margin: 1rem 0 1.4rem; border: 1px solid var(--line);
  }
  .trace-flow div { padding: 1rem; border-right: 1px solid var(--line); }
  .trace-flow div:last-child { border-right: 0; }
  .trace-flow b { display: block; color: var(--cyan); margin-bottom: 0.45rem; }
  .trace-flow span { color: var(--muted); font-size: 0.82rem; line-height: 1.5; }
  .walkthrough {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    border-top: 1px solid var(--line); margin: 1rem 0 1.5rem;
  }
  .walkthrough div { min-height: 150px; padding: 1rem 1rem 1rem 0; border-bottom: 1px solid var(--line); }
  .walkthrough div:nth-child(3n+2), .walkthrough div:nth-child(3n+3) { padding-left: 1rem; border-left: 1px solid var(--line); }
  .walkthrough b { color: var(--amber); }
  .walkthrough strong { display: block; color: var(--ink); margin: 0.35rem 0; }
  .walkthrough span { color: var(--muted); font-size: 0.86rem; line-height: 1.55; }
  .closing-line {
    margin: 1.4rem 0; padding: 1.2rem 1.4rem; border-left: 3px solid var(--cyan);
    color: var(--ink); background: var(--panel); font-size: 1.1rem; line-height: 1.6;
  }
  @media (max-width: 800px) {
    /* The sticky Streamlit header otherwise sits over the breadcrumb. Keep
       the primary question clear and remove the nonessential path label. */
    .block-container { padding-top: 3.2rem; }
    .studio-path { display: none; }
    h1 { font-size: 2.55rem !important; }
    .trace-flow, .walkthrough { grid-template-columns: 1fr; }
    .trace-flow div { border-right: 0; border-bottom: 1px solid var(--line); }
    .trace-flow div:last-child { border-bottom: 0; }
    .walkthrough div, .walkthrough div:nth-child(3n+2), .walkthrough div:nth-child(3n+3) { padding-left: 0; border-left: 0; }
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def app_data() -> dict[str, object]:
    return load_app_data()


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def plot(fig, key: str) -> None:
    st.plotly_chart(
        fig,
        width="stretch",
        key=key,
        # Do not capture normal page scrolling when the pointer crosses a map.
        # Plotly's controls still provide deliberate zooming.
        config={"displaylogo": False, "responsive": True, "scrollZoom": False},
    )


data = app_data()
locations: pd.DataFrame = data["locations"]
routes: pd.DataFrame = data["routes"]
routes_enriched: pd.DataFrame = data["routes_enriched"]
scorecard: pd.DataFrame = data["scorecard"]
country_exposure: pd.DataFrame = data["country_exposure"]

with st.sidebar:
    st.markdown("### Network Risk Decision Room")
    st.markdown(
        '<div class="side-mark"><b>Purpose</b><br>Turn a disruption question into a traceable action list.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="side-meta">Evidence release<br>{len(routes)} supplier routes<br>{len(locations)} governed points<br>OGC:CRS84 / WGS 84<br><br>Model boundary<br>Synthetic reference points<br>Great-circle proximity only<br>No road, border or capacity model</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "[Open the GIS analysis](https://github.com/KushPatel29/supply-chain-control-tower/blob/master/docs/gis_network_analysis.md)  \n"
        "[Inspect the source GeoJSON](https://github.com/KushPatel29/supply-chain-control-tower/blob/master/analytics/output/supplier_routes.geojson)  \n"
        "[Review the tests](https://github.com/KushPatel29/supply-chain-control-tower/blob/master/tests/test_geospatial_network.py)"
    )

st.markdown(
    '<div class="studio-path">Network risk decision room <span>/ decision support / GIS screening</span></div>',
    unsafe_allow_html=True,
)
st.title("Where does the network break first?")
st.markdown(
    '<p class="studio-lede">Explore a sourcing disruption, test a distribution-node outage, and inspect the controls that decide whether a spatial layer is fit to publish.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="truth-strip"><strong>Evidence boundary</strong><span>All business records and coordinates are synthetic.</span><span>WGS 84 · great-circle screening</span><span>Not a freight route, capacity plan or production system.</span></div>',
    unsafe_allow_html=True,
)

exposure_tab, outage_tab, evidence_tab, interview_tab = st.tabs(
    ["Country disruption", "Node outage", "Evidence trail", "Interview guide"]
)

with exposure_tab:
    st.subheader("Start with the operational question")
    st.markdown(
        '<p class="section-note">If one sourcing country becomes unavailable, which SKUs lose a qualified external source—and what must the team validate next?</p>',
        unsafe_allow_html=True,
    )
    control_1, control_2, control_3 = st.columns([1.1, 1, 1])
    ordered_countries = country_exposure.country.tolist()
    with control_1:
        selected_country = st.selectbox(
            "Unavailable supplier country",
            ordered_countries,
            index=ordered_countries.index("Mexico"),
            help="Highlights suppliers whose governed reference country matches the selected scenario.",
        )
    with control_2:
        minimum_score = st.slider(
            "Minimum alternate score", 0, 65, 0, 5,
            help="Raises the evidence threshold for which qualified suppliers count as eligible alternates.",
        )
    with control_3:
        recovery_days = st.slider(
            "Recovery window (days)", 15, 60, 30, 5,
            help="Tests whether the best eligible alternate's contract lead time fits the response window.",
        )

    exposure = country_exposure[country_exposure.country.eq(selected_country)].iloc[0]
    response = country_disruption(
        selected_country,
        data["sourcing"], data["suppliers"], data["products"], data["concentration"],
        scorecard, minimum_score, recovery_days,
    )
    stranded = response[response.decision_status.eq("No qualified alternate")]
    recoverable = response[response.decision_status.ne("No qualified alternate")]
    within_window = int(recoverable.within_recovery_window.sum()) if not recoverable.empty else 0
    highlighted_ids = set(
        data["suppliers"].loc[data["suppliers"].country.eq(selected_country), "supplier_id"].astype(int)
    )

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric(
        "Award-weighted COGS exposure", money(float(exposure.exposed_cogs)),
        f"{float(exposure.exposed_share):.1%} of network",
        delta_color="off", delta_arrow="off",
    )
    metric_2.metric(
        "Affected SKUs", f"{len(response)}", f"{int(exposure.suppliers)} suppliers",
        delta_color="off", delta_arrow="off",
    )
    metric_3.metric(
        "No eligible alternate", f"{len(stranded)}", "requires qualification",
        delta_color="off", delta_arrow="off",
    )
    metric_4.metric(
        "Recoverable in window", f"{within_window} / {len(recoverable)}",
        f"≤ {recovery_days} days", delta_color="off", delta_arrow="off",
    )

    st.markdown(
        f'<div class="decision-line"><strong>Decision signal:</strong> {selected_country} touches {len(response)} SKUs and {float(exposure.exposed_share):.1%} of award-weighted COGS. Under a minimum alternate score of {minimum_score}, {len(stranded)} SKUs have no eligible external alternate.</div>',
        unsafe_allow_html=True,
    )
    plot(network_map(locations, routes_enriched, highlighted_ids), "country-network-map")
    st.markdown(
        f'<p class="map-caption">Map summary: {len(highlighted_ids)} supplier reference point(s) in {selected_country} are highlighted. Lines connect each supplier to the nearest synthetic Canadian node by great-circle distance; they are not shipment lanes.</p>',
        unsafe_allow_html=True,
    )

    chart_col, register_col = st.columns([0.75, 1.25])
    with chart_col:
        st.markdown("#### Compare origin exposure")
        plot(country_exposure_bar(country_exposure, selected_country), "country-exposure-bar")
    with register_col:
        st.markdown("#### SKU response register")
        response_display = response.assign(
            priority=response.decision_status.eq("No qualified alternate").map({True: 0, False: 1})
        ).sort_values(["priority", "cogs"], ascending=[True, False])
        st.dataframe(
            response_display[[
                "sku", "category", "cogs", "country_award_share", "decision_status",
                "qualified_alternate", "alternate_score", "switch_lead_days",
                "recommended_next_check",
            ]],
            hide_index=True,
            width="stretch",
            height=370,
            column_config={
                "cogs": st.column_config.NumberColumn("Product COGS", format="$%,.0f"),
                "country_award_share": st.column_config.NumberColumn("Origin award", format="%.1%%"),
                "alternate_score": st.column_config.NumberColumn("Alt. score", format="%.1f"),
                "switch_lead_days": st.column_config.NumberColumn("Switch days", format="%d"),
            },
        )

    with st.expander("Explore route distance and supplier performance"):
        filter_a, filter_b, filter_c = st.columns(3)
        regions = sorted(routes_enriched.supplier_region.unique())
        bands = ["regional", "continental", "intercontinental"]
        with filter_a:
            selected_regions = st.multiselect("Supplier regions", regions, default=regions)
        with filter_b:
            selected_bands = st.multiselect("Distance bands", bands, default=bands)
        with filter_c:
            min_distance = st.slider("Minimum distance (km)", 0, 12_000, 0, 500)
        scoped = filter_routes(routes_enriched, selected_regions, selected_bands, min_distance)
        if scoped.empty:
            st.info("No supplier routes match this filter. Lower the distance threshold or restore a region.")
        else:
            plot(distance_score_scatter(scoped, highlighted_ids), "distance-score-scatter")
            st.dataframe(
                scoped[["supplier_name", "supplier_country", "warehouse_name", "distance_km", "composite_score", "otif_rate", "spend"]],
                hide_index=True, width="stretch",
                column_config={
                    "distance_km": st.column_config.NumberColumn("Screening km", format="%,.1f"),
                    "composite_score": st.column_config.NumberColumn("Score", format="%.1f"),
                    "otif_rate": st.column_config.NumberColumn("Supplier OTIF", format="%.1%%"),
                    "spend": st.column_config.NumberColumn("Inbound spend", format="$%,.0f"),
                },
            )

    action_1, action_2 = st.columns([1, 1])
    with action_1:
        owner = st.selectbox("Decision owner", ["Procurement lead", "Supply planning lead", "Cross-functional risk review"])
    with action_2:
        brief = country_decision_brief(
            selected_country, exposure, response, owner, f"{recovery_days} days", minimum_score
        )
        st.download_button(
            "Download decision brief",
            brief,
            file_name=f"{selected_country.lower().replace(' ', '-')}-network-risk-brief.md",
            mime="text/markdown",
            width="stretch",
        )

with outage_tab:
    st.subheader("Test a distribution-node outage")
    st.markdown(
        '<p class="section-note">Remove one or more synthetic nodes. The model recomputes the next-nearest available node for every affected supplier and publishes the distance penalty.</p>',
        unsafe_allow_html=True,
    )
    warehouse_rows = locations[locations.entity_type.eq("warehouse")].sort_values("entity_id")
    warehouse_options = dict(zip(warehouse_rows.name, warehouse_rows.entity_id.astype(int)))
    offline_names = st.multiselect(
        "Nodes unavailable in this scenario",
        list(warehouse_options),
        default=["Ontario DC 1"],
        help="At least one distribution node must remain available.",
    )
    offline_ids = {warehouse_options[name] for name in offline_names}
    if len(offline_ids) == len(warehouse_options):
        st.error("The scenario cannot reroute the network because every distribution node is unavailable. Restore at least one node.")
    else:
        scenario = reroute_network(locations, routes, offline_ids).merge(
            scorecard[["supplier_id", "spend", "otif_rate", "composite_score"]],
            on="supplier_id", how="left", validate="one_to_one",
        )
        impacted = scenario[scenario.impacted].copy()
        affected_spend = float(impacted.spend.sum()) if not impacted.empty else 0.0
        outage_1, outage_2, outage_3, outage_4 = st.columns(4)
        outage_1.metric(
            "Impacted suppliers", len(impacted), f"of {len(routes)}",
            delta_color="off", delta_arrow="off",
        )
        outage_2.metric(
            "Inbound spend represented", money(affected_spend), "screening context",
            delta_color="off", delta_arrow="off",
        )
        outage_3.metric(
            "Additional network distance", f"{impacted.extra_distance_km.sum():,.0f} km",
            "sum of impacted lanes", delta_color="off", delta_arrow="off",
        )
        outage_4.metric(
            "Largest single penalty",
            f"{(impacted.extra_distance_km.max() if not impacted.empty else 0):,.0f} km",
            "great-circle delta", delta_color="off", delta_arrow="off",
        )
        if impacted.empty:
            st.info("No published nearest-node route terminates at the selected node set, so this scenario does not trigger a reroute.")
        plot(scenario_map(locations, routes_enriched, scenario, offline_ids), "node-outage-map")
        st.markdown(
            '<p class="map-caption">Coral dashed lines show blocked baseline connections; cyan lines show the next-nearest available screening destination. Capacity, service territory and road access are not modelled.</p>',
            unsafe_allow_html=True,
        )
        if not impacted.empty:
            penalty_col, table_col = st.columns([0.8, 1.2])
            with penalty_col:
                st.markdown("#### Distance penalty")
                plot(reroute_penalty_chart(scenario), "reroute-penalty")
            with table_col:
                st.markdown("#### Reroute decision register")
                st.dataframe(
                    impacted[[
                        "supplier_name", "supplier_country", "baseline_warehouse_name",
                        "scenario_warehouse_name", "baseline_distance_km",
                        "scenario_distance_km", "extra_distance_km", "spend",
                    ]].sort_values("extra_distance_km", ascending=False),
                    hide_index=True, width="stretch",
                    column_config={
                        "baseline_distance_km": st.column_config.NumberColumn("Baseline km", format="%,.1f"),
                        "scenario_distance_km": st.column_config.NumberColumn("Scenario km", format="%,.1f"),
                        "extra_distance_km": st.column_config.NumberColumn("Added km", format="+%,.1f"),
                        "spend": st.column_config.NumberColumn("Inbound spend", format="$%,.0f"),
                    },
                )
            st.download_button(
                "Download reroute register",
                impacted.to_csv(index=False),
                file_name="node-outage-reroute-register.csv",
                mime="text/csv",
            )

with evidence_tab:
    st.subheader("Inspect the evidence before trusting the map")
    st.markdown(
        '<div class="trace-flow"><div><b>1. Govern</b><span>Stable supplier and warehouse keys with named owners.</span></div><div><b>2. Validate</b><span>Coordinate bounds, uniqueness and referential integrity.</span></div><div><b>3. Analyse</b><span>Haversine proximity and disruption rules in tested functions.</span></div><div><b>4. Publish</b><span>GeoJSON, decision registers and visible limitations.</span></div></div>',
        unsafe_allow_html=True,
    )
    inject_bad_coordinate = st.toggle(
        "Inject an invalid latitude to test the publication gate",
        value=False,
        help="Changes one in-memory latitude to 95°. Source files are never modified.",
    )
    checked_locations = locations.copy()
    if inject_bad_coordinate:
        checked_locations.loc[checked_locations.index[0], "latitude"] = 95.0
    checks = governance_checks(checked_locations, routes, scorecard)
    blocked = checks[checks.status.eq("BLOCK")]
    if blocked.empty:
        st.success(f"Publication gate passed: {len(checks)} of {len(checks)} controls are green.")
    else:
        control_word = "control" if len(blocked) == 1 else "controls"
        st.error(
            f"Publication blocked: {len(blocked)} {control_word} failed. "
            "Correct the source before rebuilding the GIS layer."
        )
    st.dataframe(checks, hide_index=True, width="stretch")

    st.markdown("#### Decision lineage")
    lineage = pd.DataFrame([
        ["Country COGS exposure", "country_exposure.csv", "Award COGS by supplier origin", "Baseline reconciles to published scenario"],
        ["Eligible alternate", "fact_sourcing + dim_supplier", "Outside origin + qualified + score floor", "Business-key and qualification checks"],
        ["Nearest distribution node", "network_locations.csv", "Minimum Haversine distance", "Destination recomputed in tests"],
        ["Supplier performance", "supplier_scorecard.csv", "One annual score per supplier", "15/15 one-to-one join"],
    ], columns=["Decision output", "Committed source", "Rule", "Acceptance evidence"])
    st.dataframe(lineage, hide_index=True, width="stretch")

    download_1, download_2, download_3 = st.columns(3)
    with download_1:
        st.download_button(
            "Download route GeoJSON",
            filtered_route_geojson(data["route_geojson"], routes.supplier_id),
            file_name="supplier-routes-screening.geojson",
            mime="application/geo+json",
            width="stretch",
        )
    with download_2:
        st.download_button(
            "Download point GeoJSON",
            json.dumps(data["point_geojson"], indent=2) + "\n",
            file_name="network-reference-points.geojson",
            mime="application/geo+json",
            width="stretch",
        )
    with download_3:
        st.download_button(
            "Download route register",
            routes.to_csv(index=False),
            file_name="gis-route-register.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Method limits and production next steps"):
        st.markdown(
            """
- Reference points are synthetic and do not represent real supplier or warehouse facilities.
- Great-circle distance is a fast geographic screen; it excludes roads, ports, border time, duty, capacity, carbon and commercial service territory.
- Country exposure is award-weighted product COGS, not shipment volume. Supplier scores are annual and supplier-wide, not lane-specific.
- A production version would confirm the decision thresholds with users, manage CRS transformations, source governed addresses, introduce a road/freight network, test node capacity, and record approval history.
"""
        )

with interview_tab:
    st.subheader("A six-minute interview walkthrough")
    st.markdown(
        '<p class="section-note">Use the app to demonstrate how you think. The strongest story is the path from an ambiguous question to a controlled decision—not the number of charts.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="walkthrough">
  <div><b>0:00–0:40</b><strong>Frame the decision</strong><span>“I began with the operational question: if an origin or node disappears, what needs attention first?”</span></div>
  <div><b>0:40–1:40</b><strong>Show Mexico</strong><span>Explain 27.2% COGS exposure, 36 affected SKUs and the highlighted spatial context.</span></div>
  <div><b>1:40–2:40</b><strong>Change the policy</strong><span>Raise the alternate-score floor and shorten the recovery window. Show how the action queue changes.</span></div>
  <div><b>2:40–3:40</b><strong>Remove a node</strong><span>Take Ontario DC 1 offline and explain the recalculated destination and distance penalty.</span></div>
  <div><b>3:40–4:40</b><strong>Export the decision</strong><span>Download the brief or reroute register. Decisions retain assumptions, owner and limitations.</span></div>
  <div><b>4:40–6:00</b><strong>Prove trust</strong><span>Inject an invalid latitude, show publication blocking, then explain what a production routing model would add.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="closing-line">“The map is the presentation layer. My contribution is the traceable path from a stakeholder question, through governed data and acceptance criteria, to a practical decision.”</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Questions an interviewer may ask"):
        st.markdown(
            """
**Why use great-circle distance?**

It is deterministic and appropriate for initial proximity screening. I would never use it as transit time; the production backlog would add a road/freight network, border time and capacity.

**How do you know the joins are reliable?**

Supplier and warehouse IDs are governed against the same dimensions used by the analytical model. Tests assert one-to-one supplier coverage, valid coordinates, unique keys and recomputed nearest-node destinations.

**What did you clarify as a business analyst?**

The decision, acceptable alternate policy, recovery window, meaning of “qualified,” evidence owner, exception path and the point at which screening must hand off to operational routing.

**How does this transfer to municipal work?**

The same pattern applies to asset IDs, facilities, work orders and service areas: govern the key and CRS, reconcile the system of record to the spatial layer, route exceptions, and publish only accepted features. This portfolio app demonstrates the method; it does not claim municipal production experience.
"""
        )

st.markdown(
    '<p class="map-caption" style="margin-top:2.5rem">Built from committed synthetic evidence · no API key · calculations separated from the interface and covered by automated tests</p>',
    unsafe_allow_html=True,
)
