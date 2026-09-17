"""Decision Assurance Studio for governed network-risk analysis.

Run with: ``streamlit run streamlit_app.py``.

The interface reads committed synthetic evidence. It does not persist workflow
state, geocode locations, or make operational sourcing and routing decisions.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from app.advanced_decision_support import (
    build_country_scenario_portfolio,
    build_evidence_manifest,
    build_evidence_pack,
    warehouse_inventory_risk_summary,
)
from app.gis_decision_engine import (
    country_disruption,
    filter_routes,
    governance_checks,
    load_app_data,
    reroute_network,
)
from app.gis_visuals import (
    distance_score_scatter,
    network_map,
    reroute_penalty_chart,
    scenario_landscape,
    scenario_map,
    warehouse_posture_map,
)
from app.incident_command import (
    controlled_decision_journal,
    event_to_action_timeline,
    incident_action_register,
    incident_playbook_catalogue,
)


ROOT = Path(__file__).resolve().parent


def collected_test_count() -> str:
    """The README badge, which test_published_prose pins to what pytest collects.

    The header typed out 704 long after the suite reached 826. Read from the one
    number something checks, it cannot fall behind again.
    """
    try:
        badge = re.search(r"tests-(\d+)%20collected", (ROOT / "README.md").read_text(encoding="utf-8"))
    except OSError:
        badge = None
    return f"{int(badge.group(1)):,} automated tests" if badge else "Automated test suite"


st.set_page_config(
    page_title="Decision Assurance Studio | Kush Patel",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
<style>
  :root {
    --ocean: #071014; --panel: #0d1b20; --panel-2: #102429;
    --line: #29454b; --ink: #e8f1ef; --muted: #9db1b2;
    --cyan: #46e5d5; --amber: #e4b35a; --coral: #f06d67;
  }
  .stApp { background: var(--ocean); color: var(--ink); }
  [data-testid="stHeader"] { background: rgba(7, 16, 20, 0.94); }
  [data-testid="stAppDeployButton"] { display: none; }
  [data-testid="stSidebar"] { background: #09171b; border-right: 1px solid var(--line); }
  [data-testid="stSidebar"] > div { padding-top: 1.3rem; }
  #MainMenu, footer { visibility: hidden; }
  .block-container { max-width: 1480px; padding-top: 2.2rem; padding-bottom: 4rem; }
  h1, h2, h3, h4 { color: var(--ink); letter-spacing: -0.025em; }
  h1 { max-width: 1080px; font-size: clamp(2.3rem, 4vw, 4.4rem) !important; line-height: 1 !important; }
  p, li { color: var(--muted); }
  a { color: var(--cyan) !important; }
  :focus-visible { outline: 3px solid var(--amber) !important; outline-offset: 3px !important; }
  .studio-lede { max-width: 840px; margin: 1rem 0 1.2rem; font-size: 1.05rem; line-height: 1.7; }
  .studio-meta { display: flex; flex-wrap: wrap; align-items: center; gap: .55rem 1rem; margin: .15rem 0 1rem; color: var(--muted); font-size: .78rem; }
  .studio-meta strong { color: var(--cyan); font-weight: 700; }
  .studio-meta span { padding-left: 1rem; border-left: 1px solid var(--line); }
  .brief-shell { display: grid; grid-template-columns: minmax(0,1.55fr) minmax(260px,.75fr); border: 1px solid var(--line); background: linear-gradient(120deg,rgba(70,229,213,.055),rgba(228,179,90,.035)); margin: 1.1rem 0 1.25rem; }
  .brief-primary { padding: 1.25rem 1.35rem 1.35rem; }
  .brief-primary small { display: block; color: var(--amber); margin-bottom: .5rem; font-weight: 650; }
  .brief-primary strong { display: block; max-width: 24ch; color: var(--ink); font-size: clamp(1.35rem,2.2vw,2.15rem); line-height: 1.15; letter-spacing: -.025em; }
  .brief-primary p { max-width: 70ch; margin: .72rem 0 0; line-height: 1.6; }
  .brief-next { padding: 1.25rem 1.35rem; border-left: 1px solid var(--line); background: rgba(7,16,20,.42); }
  .brief-next small { display: block; color: var(--muted); margin-bottom: .45rem; }
  .brief-next strong { display: block; color: var(--cyan); line-height: 1.4; }
  .brief-next p { margin: .55rem 0 0; font-size: .88rem; line-height: 1.55; }
  .workspace-intro { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin: 1.4rem 0 .55rem; }
  .workspace-intro strong { color: var(--ink); font-size: 1.05rem; }
  .workspace-intro span { color: var(--muted); font-size: .82rem; }
  .brief-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); margin: 1rem 0 1.2rem; border: 1px solid var(--line); }
  .brief-grid div { padding: 1rem 1.05rem; border-right: 1px solid var(--line); }
  .brief-grid div:last-child { border-right: 0; }
  .brief-grid b { display: block; color: var(--amber); margin-bottom: .4rem; }
  .brief-grid strong { display: block; color: var(--ink); margin-bottom: .35rem; }
  .brief-grid span { color: var(--muted); font-size: .86rem; line-height: 1.55; }
  .truth-strip { display: flex; flex-wrap: wrap; gap: .65rem 1.35rem; margin: 1rem 0 1.3rem; padding: .82rem 1rem; border-left: 3px solid var(--amber); background: rgba(228,179,90,.055); color: #c5d2d2; font: .76rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
  .truth-strip strong { color: var(--amber); }
  .decision-rail { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); border: 1px solid var(--line); margin: 1.1rem 0 1.6rem; background: var(--panel); }
  .decision-rail div { padding: .8rem .9rem; border-right: 1px solid var(--line); }
  .decision-rail div:last-child { border-right: 0; }
  .decision-rail b { display: block; color: var(--cyan); font-size: .78rem; margin-bottom: .22rem; }
  .decision-rail span { color: var(--muted); font-size: .78rem; line-height: 1.4; }
  .section-note { margin: .2rem 0 1rem; max-width: 78ch; line-height: 1.65; }
  .decision-line { margin: .7rem 0 1rem; padding: .9rem 1rem; border: 1px solid var(--line); background: var(--panel); color: var(--ink); font-size: .94rem; line-height: 1.55; }
  .decision-line strong { color: var(--amber); }
  .map-caption { margin: -.35rem 0 1rem; color: var(--muted); font: .73rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
  .side-mark { padding: .82rem 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); color: var(--ink); font-size: .92rem; line-height: 1.55; }
  .side-mark b { color: var(--cyan); }
  .side-meta { margin-top: 1rem; color: var(--muted); font: .72rem/1.65 ui-monospace, SFMono-Regular, Consolas, monospace; }
  .handoff-card { padding: 1rem 1.1rem; border: 1px solid var(--line); background: var(--panel); min-height: 152px; }
  .handoff-card b { color: var(--cyan); }
  .handoff-card strong { display: block; margin: .35rem 0; color: var(--ink); }
  .handoff-card span { color: var(--muted); font-size: .88rem; line-height: 1.55; }
  .process-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); border-top: 1px solid var(--line); margin: 1rem 0 1.4rem; }
  .process-grid div { padding: 1rem 1rem 1rem 0; border-bottom: 1px solid var(--line); min-height: 140px; }
  .process-grid div:nth-child(3n+2), .process-grid div:nth-child(3n+3) { padding-left: 1rem; border-left: 1px solid var(--line); }
  .process-grid b { color: var(--amber); }
  .process-grid strong { display: block; color: var(--ink); margin: .35rem 0; }
  .process-grid span { color: var(--muted); font-size: .86rem; line-height: 1.55; }
  .closing-line { margin: 1.2rem 0; padding: 1.15rem 1.3rem; border-left: 3px solid var(--cyan); color: var(--ink); background: var(--panel); font-size: 1.03rem; line-height: 1.65; }
  [data-testid="stMetric"] { min-height: 108px; padding: .82rem .2rem .42rem; border-top: 1px solid var(--line); background: transparent; }
  [data-testid="stMetricLabel"] { color: var(--muted); }
  [data-testid="stMetricValue"] { color: var(--cyan); letter-spacing: -.04em; }
  [data-testid="stMetricDelta"] { color: var(--amber); }
  [data-baseweb="tab-list"] { gap: 1.25rem; border-bottom: 1px solid var(--line); }
  [data-baseweb="tab"] { height: 3.25rem; padding-left: .1rem; padding-right: .1rem; }
  [data-baseweb="tab-highlight"] { background-color: var(--cyan); }
  [data-testid="stDataFrame"] { border: 1px solid var(--line); }
  .stButton > button, .stDownloadButton > button { border-radius: 2px; border: 1px solid var(--cyan); min-height: 2.8rem; background: transparent; color: var(--cyan); font-weight: 650; }
  .stButton > button:hover, .stDownloadButton > button:hover { border-color: #8af6ed; color: #8af6ed; background: rgba(70,229,213,.07); }
  div[data-testid="stSegmentedControl"] { margin-bottom: 1.1rem; }
  div[data-testid="stSegmentedControl"] button { min-height: 2.75rem; font-weight: 650; }
  .stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div { border-radius: 2px; border-color: var(--line); }
  @media (max-width: 900px) {
    .block-container { padding-top: 3.1rem; }
    h1 { font-size: 2.5rem !important; }
    .brief-shell, .brief-grid, .decision-rail, .process-grid { grid-template-columns: 1fr; }
    .brief-next { border-left: 0; border-top: 1px solid var(--line); }
    .brief-grid div { border-right: 0; border-bottom: 1px solid var(--line); }
    .brief-grid div:last-child { border-bottom: 0; }
    .workspace-intro { display: block; }
    .workspace-intro span { display: block; margin-top: .25rem; }
    .decision-rail div { border-right: 0; border-bottom: 1px solid var(--line); }
    .decision-rail div:last-child { border-bottom: 0; }
    .process-grid div, .process-grid div:nth-child(3n+2), .process-grid div:nth-child(3n+3) { padding-left: 0; border-left: 0; }
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def app_data() -> dict[str, object]:
    return load_app_data()


@st.cache_data(show_spinner=False)
def evidence_manifest() -> pd.DataFrame:
    return build_evidence_manifest(ROOT)


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
        config={"displaylogo": False, "responsive": True, "scrollZoom": False},
    )


def stakeholder_for(row: pd.Series) -> tuple[str, str, str]:
    """Return the primary handoff without asserting operational feasibility."""
    if row["decision_status"] == "No qualified alternate":
        return (
            "Procurement lead",
            "Open or confirm alternate qualification work.",
            "Qualification decision or documented service-risk escalation.",
        )
    if not bool(row["within_recovery_window"]):
        return (
            "Supply planning lead",
            "Validate cover and close the lead-time gap before the required date.",
            "Approved recovery window, additional cover, or escalated service impact.",
        )
    return (
        "Cross-functional risk review",
        "Validate SKU-specific capacity, commercial terms, and the operational route.",
        "Procurement, planning, and logistics acceptance evidence.",
    )


data = app_data()
locations: pd.DataFrame = data["locations"]
routes: pd.DataFrame = data["routes"]
routes_enriched: pd.DataFrame = data["routes_enriched"]
scorecard: pd.DataFrame = data["scorecard"]
country_exposure: pd.DataFrame = data["country_exposure"]
warehouse_risk = warehouse_inventory_risk_summary(
    data["inventory_position"], data["warehouses"], locations
)
manifest = evidence_manifest()

state_defaults = {
    "handoff_owner": "Cross-functional risk review",
    "handoff_status": "Needs validation",
    "handoff_target": None,
    "handoff_note": "",
    "assurance_inject_bad_coordinate": False,
}
for state_key, default_value in state_defaults.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value

checked_locations = locations.copy()
if st.session_state["assurance_inject_bad_coordinate"]:
    checked_locations.loc[checked_locations.index[0], "latitude"] = 95.0
checks = governance_checks(checked_locations, routes, scorecard)
blocked_controls = checks[checks.status.eq("BLOCK")]
publication_ready = blocked_controls.empty

ordered_countries = country_exposure.country.tolist()
selected_country = st.session_state.get("origin_country", "Mexico")
if selected_country not in ordered_countries:
    selected_country = "Mexico"
minimum_score = int(st.session_state.get("origin_minimum_score", 0))
recovery_days = int(st.session_state.get("origin_recovery_days", 30))
selected_exposure = country_exposure[country_exposure.country.eq(selected_country)].iloc[0]
response = country_disruption(
    selected_country,
    data["sourcing"],
    data["suppliers"],
    data["products"],
    data["concentration"],
    scorecard,
    minimum_score,
    recovery_days,
)
stranded = response[response.decision_status.eq("No qualified alternate")]
eligible = response[response.decision_status.ne("No qualified alternate")]
within_window = int(eligible.within_recovery_window.sum()) if not eligible.empty else 0
highlighted_ids = set(
    data["suppliers"].loc[
        data["suppliers"].country.eq(selected_country), "supplier_id"
    ].astype(int)
)
portfolio = build_country_scenario_portfolio(
    data["sourcing"],
    data["suppliers"],
    data["products"],
    data["concentration"],
    scorecard,
    minimum_score,
    recovery_days,
)
response_display = response.assign(
    priority=response.decision_status.eq("No qualified alternate").map(
        {True: 0, False: 1}
    )
).sort_values(["priority", "cogs"], ascending=[True, False])
warehouse_rows = locations[locations.entity_type.eq("warehouse")].sort_values(
    "entity_id"
)
warehouse_options = dict(
    zip(warehouse_rows.name, warehouse_rows.entity_id.astype(int))
)
# The node the outage scenario opens on: the one the most supplier screens land on,
# found from the routes rather than named. A named node ties the app to one drawing
# of the network and raises a KeyError the day the network is redrawn.
BUSIEST_NODE_ID = int(routes.warehouse_id.value_counts().index[0])
BUSIEST_NODE_NAME = next(name for name, wid in warehouse_options.items() if wid == BUSIEST_NODE_ID)


def open_workspace(name: str) -> None:
    st.session_state["workspace"] = name

with st.sidebar:
    st.markdown("### Decision Assurance Studio")
    st.markdown(
        '<div class="side-mark"><b>Operating question</b><br>What changed, who validates it next, and is the evidence fit to share?</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="side-meta">Evidence scope<br>{len(routes)} supplier screens<br>{len(locations)} governed points<br>{len(warehouse_risk)} warehouse postures<br>{len(checks)} publication controls<br><br>Current gate<br>{"PASS" if publication_ready else "BLOCKED"}<br><br>Method boundary<br>Synthetic reference points<br>Great-circle proximity only<br>No road, border, capacity or throughput model</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "[GIS method](https://github.com/KushPatel29/supply-chain-control-tower/blob/master/docs/gis_network_analysis.md)  \n"
        "[Process case](https://github.com/KushPatel29/supply-chain-control-tower/blob/master/docs/business_process_improvement_case.md)  \n"
        "[Repository evidence](https://github.com/KushPatel29/supply-chain-control-tower)"
    )

st.markdown(
    f'<p class="studio-meta"><strong>Decision Assurance Studio</strong><span>Opening scenario: {selected_country}</span><span>Publication gate: {"PASS" if publication_ready else "BLOCKED"}</span><span>{collected_test_count()}</span></p>',
    unsafe_allow_html=True,
)
st.title(
    f"{selected_country} disruption leaves {len(stranded)} SKUs without a qualified alternate."
)
st.markdown(
    '<p class="studio-lede">Move from a network signal to a reviewable decision: challenge the policy, inspect the governed spatial evidence, assign the next validation, and export the exact evidence considered.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    f"""
<div class="brief-shell">
  <div class="brief-primary">
    <small>Live decision brief · score floor {minimum_score} · {recovery_days}-day review window</small>
    <strong>{money(float(selected_exposure.exposed_cogs))} of award-weighted COGS is exposed.</strong>
    <p>{len(response)} SKUs are touched by the scenario. {len(stranded)} have no eligible external alternate under the selected rule; {within_window} of {len(eligible)} eligible alternates fit the contract-lead review window.</p>
  </div>
  <div class="brief-next">
    <small>Next accountable decision</small>
    <strong>Validate qualification, capacity, commercial terms, and operational feasibility.</strong>
    <p>Proximity and annual supplier score support screening. They do not authorize a supplier switch or distribution change.</p>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="workspace-intro"><strong>Choose a decision workspace</strong><span>Only the selected workspace is rendered for a faster, calmer review.</span></div>',
    unsafe_allow_html=True,
)
workspace = st.segmented_control(
    "Decision workspace",
    [
        "Executive brief",
        "Incident command",
        "Origin risk",
        "Node outage",
        "Handoff",
        "Assurance",
        "Case study",
    ],
    default="Executive brief",
    key="workspace",
    required=True,
    label_visibility="collapsed",
    width="stretch",
    wrap=True,
)

if workspace == "Executive brief":
    brief_1, brief_2, brief_3, brief_4 = st.columns(4)
    brief_1.metric(
        "Award-weighted COGS exposure",
        money(float(selected_exposure.exposed_cogs)),
        f"{float(selected_exposure.exposed_share):.1%} of network",
        delta_color="off",
        delta_arrow="off",
    )
    brief_2.metric(
        "Affected SKUs",
        f"{len(response)}",
        f"{int(selected_exposure.suppliers)} suppliers",
        delta_color="off",
        delta_arrow="off",
    )
    brief_3.metric(
        "No eligible alternate",
        f"{len(stranded)}",
        "qualification or escalation",
        delta_color="off",
        delta_arrow="off",
    )
    brief_4.metric(
        "Lead time fits window",
        f"{within_window} / {len(eligible)}",
        f"≤ {recovery_days} contract days",
        delta_color="off",
        delta_arrow="off",
    )
    st.markdown(
        """
<div class="brief-grid">
  <div><b>What the evidence supports</b><strong>A prioritized validation queue</strong><span>Exposure, alternative eligibility, contract lead time, governed keys, and spatial screening are traceable to committed synthetic sources.</span></div>
  <div><b>What remains unknown</b><strong>Operational feasibility</strong><span>Capacity, certification, commercial terms, road or freight routing, border time, throughput, and authorization are not modeled.</span></div>
  <div><b>What happens next</b><strong>Named owner, evidence, and close condition</strong><span>Route one exception to the accountable role, record the unresolved question, and export the controlled evidence package.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )
    brief_map, brief_register = st.columns([1.08, .92])
    with brief_map:
        st.markdown("## Governed spatial context")
        plot(network_map(locations, routes_enriched, highlighted_ids), "brief-network-map")
        st.caption(
            f"{len(highlighted_ids)} supplier reference points in {selected_country} are highlighted. Lines are nearest-node great-circle screens, not shipment lanes."
        )
    with brief_register:
        st.markdown("### First exceptions to validate")
        st.dataframe(
            response_display[
                ["sku", "category", "cogs", "decision_status", "recommended_next_check"]
            ].head(8),
            hide_index=True,
            width="stretch",
            height=355,
            column_config={
                "cogs": st.column_config.NumberColumn("Product COGS", format="$%,.0f"),
            },
        )
    action_1, action_2, action_3 = st.columns(3)
    action_1.button(
        "Challenge origin policy",
        key="brief_open_origin",
        on_click=open_workspace,
        args=("Origin risk",),
        width="stretch",
    )
    action_2.button(
        "Prepare stakeholder handoff",
        key="brief_open_handoff",
        on_click=open_workspace,
        args=("Handoff",),
        width="stretch",
    )
    action_3.button(
        "Inspect assurance evidence",
        key="brief_open_assurance",
        on_click=open_workspace,
        args=("Assurance",),
        width="stretch",
    )
    st.markdown(
        '<div class="truth-strip"><strong>Evidence boundary</strong><span>All records and coordinates are synthetic.</span><span>WGS 84 and great-circle screening.</span><span>No live business-system connection.</span><span>Not an authorization to execute.</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="decision-rail"><div><b>Question</b><span>Choose the disruption.</span></div><div><b>Rules</b><span>Expose policy assumptions.</span></div><div><b>Outcome</b><span>Prioritize exceptions.</span></div><div><b>Handoff</b><span>Name the next validation.</span></div><div><b>Assurance</b><span>Trace and test the evidence.</span></div></div>',
        unsafe_allow_html=True,
    )

if workspace == "Incident command":
    st.subheader("Incident command: from signal to controlled response")
    st.markdown(
        '<p class="section-note">Replay a supplier-origin disruption through an eight-stage service clock. Detection, triage, recommendation, approval, execution, and recovery stay separate so a fast response never bypasses accountable validation.</p>',
        unsafe_allow_html=True,
    )
    incident_type = "Supplier outage"
    scenario_name = f"{selected_country} supplier-origin disruption"
    playbooks = incident_playbook_catalogue()
    selected_playbook = playbooks[playbooks.incident_type.eq(incident_type)].iloc[0]
    incident_timeline = event_to_action_timeline(incident_type, scenario_name)
    incident_actions = incident_action_register(response, incident_type, scenario_name)
    decision_journal = controlled_decision_journal(
        incident_actions, incident_type, scenario_name
    )
    incident_id = str(incident_timeline.iloc[0].event_id)
    p0_actions = incident_actions[incident_actions.priority.eq("P0")]
    command_1, command_2, command_3, command_4 = st.columns(4)
    command_1.metric("Incident", incident_id, "simulated event", delta_color="off", delta_arrow="off")
    command_2.metric("P0 validation queue", len(p0_actions), f"of {len(incident_actions)} affected SKUs", delta_color="off", delta_arrow="off")
    command_3.metric("Action SLA", f"{int(selected_playbook.action_sla_min)} min", str(selected_playbook.incident_commander), delta_color="off", delta_arrow="off")
    command_4.metric("Recovery target", f"{int(selected_playbook.recovery_target_min / 60)} hr", "clock starts at source event", delta_color="off", delta_arrow="off")

    st.markdown(
        f'<div class="decision-line"><strong>Containment:</strong> {selected_playbook.default_containment}<br><strong>Escalation:</strong> {selected_playbook.escalation_rule}</div>',
        unsafe_allow_html=True,
    )
    timeline_col, playbook_col = st.columns([1.25, .75])
    with timeline_col:
        st.markdown("#### Event-to-action service clock")
        st.dataframe(
            incident_timeline[[
                "sequence", "stage", "elapsed_min", "stage_latency_min",
                "cumulative_sla_min", "service_clock_status", "accountable_role",
            ]],
            hide_index=True,
            width="stretch",
            height=330,
            column_config={
                "sequence": st.column_config.NumberColumn("Step", format="%d"),
                "elapsed_min": st.column_config.NumberColumn("Elapsed T+ min", format="%d"),
                "stage_latency_min": st.column_config.NumberColumn("Stage min", format="%d"),
                "cumulative_sla_min": st.column_config.NumberColumn("SLA T+ min", format="%d"),
                "service_clock_status": "Clock",
                "accountable_role": "Accountable role",
            },
        )
        st.caption("T+ values are deterministic demonstration timings, not historical timestamps or claimed operating performance.")
    with playbook_col:
        st.markdown("#### Control conditions")
        st.markdown(
            f"**Trigger**  \n{selected_playbook.trigger}\n\n"
            f"**Severity rule**  \n{selected_playbook.severity_rule}\n\n"
            f"**Rollback**  \n{selected_playbook.rollback_condition}\n\n"
            f"**Close only with**  \n{selected_playbook.closure_evidence}"
        )

    st.markdown("#### Prioritized action queue")
    action_filter = st.segmented_control(
        "Action priority",
        ["P0", "P1", "P2", "All"],
        default="P0",
        key="incident_priority_filter",
        label_visibility="collapsed",
    )
    visible_actions = (
        incident_actions
        if action_filter == "All"
        else incident_actions[incident_actions.priority.eq(action_filter)]
    )
    st.dataframe(
        visible_actions[[
            "sku", "category", "priority", "award_weighted_cogs", "exception",
            "accountable_role", "response_action", "status",
        ]],
        hide_index=True,
        width="stretch",
        height=330,
        column_config={
            "award_weighted_cogs": st.column_config.NumberColumn("Award-weighted COGS", format="$%,.0f"),
            "accountable_role": "Accountable role",
            "response_action": "Next controlled action",
        },
    )

    st.markdown("#### Controlled decision journal")
    journal_record = decision_journal.iloc[0]
    journal_1, journal_2 = st.columns([1.05, .95])
    with journal_1:
        st.markdown(
            f'<div class="handoff-card"><b>{journal_record.decision_status}</b><strong>{journal_record.selected_option}</strong><span>{journal_record.decision_basis}<br><br>Expected benefit: {journal_record.expected_benefit}</span></div>',
            unsafe_allow_html=True,
        )
    with journal_2:
        st.markdown(
            f'<div class="handoff-card"><b>Next approval gate</b><strong>{journal_record.accountable_role}</strong><span>{journal_record.next_gate}<br><br>Actual outcome: {journal_record.actual_outcome}</span></div>',
            unsafe_allow_html=True,
        )
    with st.expander("Compare all five governed response playbooks"):
        st.dataframe(
            playbooks[[
                "incident_type", "incident_commander", "detect_sla_min",
                "triage_sla_min", "decision_sla_min", "action_sla_min",
                "recovery_target_min", "escalation_rule", "rollback_condition",
            ]],
            hide_index=True,
            width="stretch",
        )
        st.caption("Catalogue includes supplier outage, lane closure, port delay, demand spike, and data-feed failure. Thresholds are portfolio design assumptions requiring operational approval before use.")
    st.download_button(
        "Download incident action register",
        incident_actions.to_csv(index=False),
        file_name=f"{selected_country.lower().replace(' ', '-')}-incident-action-register.csv",
        mime="text/csv",
        width="stretch",
        key="incident_action_register_download",
    )

if workspace == "Origin risk":
    st.subheader("Origin disruption scenario")
    st.markdown(
        '<p class="section-note">If one supplier origin becomes unavailable, which SKUs have no eligible external alternate, and whose validation is required next?</p>',
        unsafe_allow_html=True,
    )
    control_1, control_2, control_3 = st.columns([1.1, 1, 1])
    with control_1:
        selected_country = st.selectbox(
            "Unavailable supplier country",
            ordered_countries,
            index=ordered_countries.index("Mexico"),
            help="Uses the governed supplier origin recorded in the committed evidence.",
            key="origin_country",
        )
    with control_2:
        minimum_score = st.slider(
            "Minimum annual alternate score", 0, 65, 0, 5,
            help="An explicit policy screen; the score is annual and supplier-wide.",
            key="origin_minimum_score",
        )
    with control_3:
        recovery_days = st.slider(
            "Lead-time review window (days)", 15, 60, 30, 5,
            help="Compares the best eligible alternate's contract lead to the selected window.",
            key="origin_recovery_days",
        )

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric(
        "Award-weighted COGS exposure", money(float(selected_exposure.exposed_cogs)),
        f"{float(selected_exposure.exposed_share):.1%} of network", delta_color="off", delta_arrow="off",
    )
    metric_2.metric(
        "Affected SKUs", f"{len(response)}", f"{int(selected_exposure.suppliers)} suppliers",
        delta_color="off", delta_arrow="off",
    )
    metric_3.metric(
        "No eligible external alternate", f"{len(stranded)}", "qualification or escalation",
        delta_color="off", delta_arrow="off",
    )
    metric_4.metric(
        "Eligible alternate lead time fits window", f"{within_window} / {len(eligible)}",
        f"≤ {recovery_days} contract days", delta_color="off", delta_arrow="off",
    )
    st.markdown(
        f'<div class="decision-line"><strong>Decision signal:</strong> {selected_country} touches {len(response)} SKUs and {float(selected_exposure.exposed_share):.1%} of award-weighted COGS. Under an annual alternate-score floor of {minimum_score}, {len(stranded)} SKUs have no eligible external alternate. Eligibility still does not prove capacity, product certification, commercial terms, or route feasibility.</div>',
        unsafe_allow_html=True,
    )

    map_col, register_col = st.columns([1.05, .95])
    with map_col:
        st.markdown("## Governed spatial context")
        plot(network_map(locations, routes_enriched, highlighted_ids), "origin-network-map")
        st.markdown(
            f'<p class="map-caption">{len(highlighted_ids)} supplier reference point(s) in {selected_country} are highlighted. Lines terminate at the nearest synthetic Canadian node by great-circle distance; they are not shipment lanes.</p>',
            unsafe_allow_html=True,
        )
    with register_col:
        st.markdown("#### Prioritized SKU exceptions")
        st.dataframe(
            response_display[[
                "sku", "category", "cogs", "decision_status", "qualified_alternate",
                "alternate_score", "switch_lead_days", "within_recovery_window",
                "recommended_next_check",
            ]],
            hide_index=True, width="stretch", height=500,
            column_config={
                "cogs": st.column_config.NumberColumn("Product COGS", format="$%,.0f"),
                "alternate_score": st.column_config.NumberColumn("Alt. score", format="%.1f"),
                "switch_lead_days": st.column_config.NumberColumn("Contract days", format="%d"),
                "within_recovery_window": st.column_config.CheckboxColumn("Lead fits window"),
            },
        )

    st.markdown("#### Country portfolio under the same policy")
    portfolio_chart, portfolio_table = st.columns([1.1, .9])
    with portfolio_chart:
        plot(scenario_landscape(portfolio, selected_country), "origin-scenario-landscape")
    with portfolio_table:
        st.dataframe(
            portfolio[[
                "country", "network_cogs_share", "affected_skus", "stranded_skus",
                "recoverable_within_window", "highest_exposure_stranded_sku",
            ]],
            hide_index=True, width="stretch", height=430,
            column_config={
                "network_cogs_share": st.column_config.NumberColumn("COGS share", format="percent"),
                "recoverable_within_window": st.column_config.NumberColumn("Lead fits window", format="%d"),
            },
        )

    with st.expander("Additional supplier-distance analysis"):
        filter_a, filter_b, filter_c = st.columns(3)
        regions = sorted(routes_enriched.supplier_region.unique())
        bands = ["regional", "continental", "intercontinental"]
        with filter_a:
            selected_regions = st.multiselect(
                "Supplier regions", regions, default=regions, key="origin_route_regions"
            )
        with filter_b:
            selected_bands = st.multiselect(
                "Distance bands", bands, default=bands, key="origin_route_bands"
            )
        with filter_c:
            min_distance = st.slider(
                "Minimum screening distance (km)", 0, 12_000, 0, 500,
                key="origin_route_min_distance",
            )
        scoped = filter_routes(routes_enriched, selected_regions, selected_bands, min_distance)
        if scoped.empty:
            st.info("No supplier screens match these filters. Lower the distance threshold or restore a region.")
        else:
            plot(distance_score_scatter(scoped, highlighted_ids), "origin-distance-score")
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

if workspace == "Node outage":
    st.subheader("Distribution-node screening scenario")
    st.markdown(
        '<p class="section-note">Remove one or more synthetic nodes. The model identifies the next-nearest available node and its great-circle distance difference. This is screening evidence, not an operational route recommendation.</p>',
        unsafe_allow_html=True,
    )
    offline_names = st.multiselect(
        "Nodes unavailable in this scenario", list(warehouse_options), default=[BUSIEST_NODE_NAME],
        help="At least one synthetic distribution node must remain available.",
        key="node_unavailable_names",
    )
    offline_ids = {warehouse_options[name] for name in offline_names}
    if len(offline_ids) == len(warehouse_options):
        st.error("Next-nearest node screening cannot run because every node is unavailable. Restore at least one node.")
        scenario = pd.DataFrame()
    else:
        scenario = reroute_network(locations, routes, offline_ids).merge(
            scorecard[["supplier_id", "spend", "otif_rate", "composite_score"]],
            on="supplier_id", how="left", validate="one_to_one",
        )
        impacted = scenario[scenario.impacted].copy()
        supplier_spend_context = float(impacted.spend.sum()) if not impacted.empty else 0.0
        outage_1, outage_2, outage_3, outage_4 = st.columns(4)
        outage_1.metric("Impacted supplier screens", len(impacted), f"of {len(routes)}", delta_color="off", delta_arrow="off")
        outage_2.metric("Annual supplier spend - context only", money(supplier_spend_context), "not node throughput", delta_color="off", delta_arrow="off")
        outage_3.metric("Additional screening distance", f"{impacted.extra_distance_km.sum():,.0f} km", "sum of impacted connections", delta_color="off", delta_arrow="off")
        outage_4.metric("Largest screening difference", f"{(impacted.extra_distance_km.max() if not impacted.empty else 0):,.0f} km", "great-circle delta", delta_color="off", delta_arrow="off")
        if impacted.empty:
            st.info("No baseline supplier screen terminates at the selected node set, so no connection changes.")
        plot(scenario_map(locations, routes_enriched, scenario, offline_ids), "node-screening-map")
        st.markdown(
            '<p class="map-caption">Coral dashed lines are blocked baseline screens; cyan lines indicate the next-nearest available synthetic node. Capacity, service territory, road access, throughput, and delivery time are not modeled.</p>',
            unsafe_allow_html=True,
        )
        if not impacted.empty:
            penalty_col, table_col = st.columns([.8, 1.2])
            with penalty_col:
                st.markdown("#### Distance difference")
                plot(reroute_penalty_chart(scenario), "node-distance-difference")
            with table_col:
                st.markdown("#### Next-nearest node screening register")
                st.dataframe(
                    impacted[[
                        "supplier_name", "supplier_country", "baseline_warehouse_name",
                        "scenario_warehouse_name", "baseline_distance_km", "scenario_distance_km",
                        "extra_distance_km", "spend",
                    ]].sort_values("extra_distance_km", ascending=False),
                    hide_index=True, width="stretch",
                    column_config={
                        "baseline_distance_km": st.column_config.NumberColumn("Baseline km", format="%,.1f"),
                        "scenario_distance_km": st.column_config.NumberColumn("Next-nearest km", format="%,.1f"),
                        "extra_distance_km": st.column_config.NumberColumn("Difference km", format="+%,.1f"),
                        "spend": st.column_config.NumberColumn("Supplier spend", format="$%,.0f"),
                    },
                )
            st.download_button(
                "Download node screening register", impacted.to_csv(index=False),
                file_name="next-nearest-node-screening.csv", mime="text/csv",
                key="node_register_download",
            )

    st.markdown("#### Warehouse inventory posture")
    st.markdown(
        '<p class="section-note">This separate evidence layer shows inventory-policy pressure at governed warehouse points. It does not imply supplier flow, node throughput, or outage feasibility.</p>',
        unsafe_allow_html=True,
    )
    selected_warehouse = st.selectbox(
        "Inspect warehouse posture", warehouse_risk.warehouse_name.tolist(),
        key="node_posture_warehouse",
    )
    selected_posture = warehouse_risk[warehouse_risk.warehouse_name.eq(selected_warehouse)].iloc[0]
    posture_map_col, posture_detail_col = st.columns([1.15, .85])
    with posture_map_col:
        plot(warehouse_posture_map(locations, warehouse_risk, selected_warehouse), "warehouse-posture-map")
    with posture_detail_col:
        posture_1, posture_2 = st.columns(2)
        posture_1.metric("Replenishment gap", money(float(selected_posture.gap_value)))
        posture_2.metric("On-hand value", money(float(selected_posture.on_hand_value)))
        posture_3, posture_4 = st.columns(2)
        posture_3.metric("Positions below policy", int(selected_posture.gap_positions))
        posture_4.metric("Do not cover lead", int(selected_posture.not_covering_lead))
        st.dataframe(
            warehouse_risk[["warehouse_name", "gap_value_rank", "gap_value", "gap_position_share", "lead_cover_failure_share", "excess_value"]],
            hide_index=True, width="stretch", height=265,
            column_config={
                "gap_value": st.column_config.NumberColumn("Gap value", format="$%,.0f"),
                "gap_position_share": st.column_config.NumberColumn("Below policy", format="percent"),
                "lead_cover_failure_share": st.column_config.NumberColumn("Lead-cover fail", format="percent"),
                "excess_value": st.column_config.NumberColumn("Excess value", format="$%,.0f"),
            },
        )

if workspace == "Handoff":
    st.subheader("Action and stakeholder handoff")
    st.markdown(
        '<p class="section-note">Choose one origin exception and preserve its assumptions, accountable role, required validation, and completion evidence. Entries below live only in this browser session.</p>',
        unsafe_allow_html=True,
    )
    sku_options = response_display.sku.tolist()
    if st.session_state.get("handoff_selected_sku") not in sku_options:
        st.session_state["handoff_selected_sku"] = sku_options[0]
    selected_sku = st.selectbox("Selected exception", sku_options, key="handoff_selected_sku")
    selected_row = response_display[response_display.sku.eq(selected_sku)].iloc[0]
    suggested_owner, next_action, completion_evidence = stakeholder_for(selected_row)

    summary_1, summary_2, summary_3 = st.columns(3)
    summary_1.metric("Product COGS", money(float(selected_row.cogs)))
    summary_2.metric("Origin award share", f"{float(selected_row.country_award_share):.1%}")
    summary_3.metric(
        "Best eligible contract lead",
        "Not available" if pd.isna(selected_row.switch_lead_days) else f"{int(selected_row.switch_lead_days)} days",
    )
    st.markdown(
        f'<div class="decision-line"><strong>{selected_sku}:</strong> {selected_row.decision_status}. Suggested next owner: {suggested_owner}. This suggestion routes validation work; it does not approve a supplier or distribution change.</div>',
        unsafe_allow_html=True,
    )

    lane_1, lane_2, lane_3 = st.columns(3)
    alt_score_text = "—" if pd.isna(selected_row.alternate_score) else f"{float(selected_row.alternate_score):.1f}"
    lead_text = "—" if pd.isna(selected_row.switch_lead_days) else f"{int(selected_row.switch_lead_days)} days"
    with lane_1:
        st.markdown(
            f'<div class="handoff-card"><b>Evidence supplied</b><strong>{selected_row.qualified_alternate}</strong><span>Annual supplier score: {alt_score_text}<br>Contract lead: {lead_text}<br>Origin award share: {float(selected_row.country_award_share):.1%}</span></div>',
            unsafe_allow_html=True,
        )
    with lane_2:
        st.markdown(
            f'<div class="handoff-card"><b>Next validation</b><strong>{suggested_owner}</strong><span>{next_action}</span></div>',
            unsafe_allow_html=True,
        )
    with lane_3:
        st.markdown(
            f'<div class="handoff-card"><b>Completion evidence</b><strong>Close with evidence</strong><span>{completion_evidence}</span></div>',
            unsafe_allow_html=True,
        )

    input_1, input_2, input_3 = st.columns(3)
    owner_options = [
        "Procurement lead", "Supply planning lead", "Logistics / network lead",
        "Finance partner", "GIS / data steward", "Cross-functional risk review",
    ]
    with input_1:
        owner = st.selectbox("Accountable owner - session only", owner_options, key="handoff_owner")
    with input_2:
        status = st.selectbox(
            "Status - session only",
            ["Needs validation", "In review", "Escalated", "Ready for business decision"],
            key="handoff_status",
        )
    with input_3:
        target = st.date_input("Target date - session only", value=None, key="handoff_target")
    note = st.text_area(
        "Decision note - session only",
        placeholder="Record the unresolved question, evidence requested, or escalation condition.",
        key="handoff_note",
    )

    st.markdown("#### Governed evidence package")
    st.markdown(
        '<p class="section-note">The ZIP contains nine controlled files: a decision brief and journal, incident playbook and timeline, action and SKU registers, selected supplier-route GeoJSON, source manifest with hashes, and the assumptions README.</p>',
        unsafe_allow_html=True,
    )
    if publication_ready:
        pack = build_evidence_pack(
            selected_country,
            data["sourcing"],
            data["suppliers"],
            data["products"],
            data["concentration"],
            scorecard,
            routes,
            data["route_geojson"],
            manifest,
            minimum_alternate_score=minimum_score,
            recovery_window_days=recovery_days,
            owner=owner,
            status=status,
            target_review=None if target is None else str(target),
            session_note=note,
            selected_sku=selected_sku,
        )
        st.success(f"Publication gate passed: {len(checks)} of {len(checks)} controls are green.")
        st.caption(
            "Evidence-pack fingerprint: "
            f"SHA-256 {hashlib.sha256(pack).hexdigest()[:16]}… · changes when the "
            "scenario or session handoff changes"
        )
        st.download_button(
            "Download nine-file evidence pack", pack,
            file_name=f"{selected_country.lower().replace(' ', '-')}-decision-evidence.zip",
            mime="application/zip", width="stretch", key="handoff_evidence_pack_download",
        )
    else:
        st.error(
            f"Evidence pack blocked: {len(blocked_controls)} publication control(s) failed. Correct the evidence or turn off the assurance test injection before export."
        )

if workspace == "Assurance":
    st.subheader("Requirements, acceptance, and GIS governance")
    st.markdown(
        '<p class="section-note">This workspace connects stakeholder needs to rules, outputs, and repeatable technical evidence. Business UAT sign-off remains intentionally separate.</p>',
        unsafe_allow_html=True,
    )
    assurance_requirements, assurance_uat, assurance_gis, assurance_lineage = st.tabs(
        ["Traceability", "Replayable UAT", "GIS governance", "Lineage"]
    )

    with assurance_requirements:
        traceability = pd.DataFrame(
            [
                ["BR-01", "Every exception has an owner and next action", "Handoff", "Selected exception retains owner, status, target, and note", "Session handoff + evidence brief", "PARTIAL - session only; target may be unset"],
                ["BR-04", "Supplier performance uses published anchors", "Origin risk", "Changing score floor changes eligibility without changing the source score", "Policy sensitivity replay", "DEMONSTRATED"],
                ["BR-05", "Users can identify source and quality status", "Assurance", "Each export lists source path, row count, bytes, and SHA-256", "Evidence manifest", "DEMONSTRATED"],
                ["BR-06", "Critical quality failure blocks publication", "Assurance", "Invalid WGS 84 latitude prevents ZIP export", "Publication-gate replay", "DEMONSTRATED"],
                ["GIS-01", "Spatial records use governed business keys", "GIS governance", "Supplier and warehouse IDs reconcile to master dimensions", "Business-key controls", "DEMONSTRATED"],
                ["GIS-03", "Each supplier has one transparent node screen", "Node outage", "Published destination recomputes to minimum Haversine distance", "Nearest-node technical test", "DEMONSTRATED"],
                ["GIS-04", "Analytical limits remain visible", "All workspaces", "Screens and exports state proximity, capacity, and synthetic-data limits", "Visible boundary + assumptions README", "DEMONSTRATED"],
            ],
            columns=["Requirement", "Stakeholder need", "Interface/output", "Acceptance condition", "Evidence", "Coverage"],
        )
        st.dataframe(traceability, hide_index=True, width="stretch", height=360)
        st.caption("These requirements are portfolio artifacts derived from the documented process and GIS contract. They are not requirements from a target employer or municipality.")

    with assurance_uat:
        mexico_baseline = country_disruption(
            "Mexico", data["sourcing"], data["suppliers"], data["products"],
            data["concentration"], scorecard, 0, 30,
        )
        mexico_strict = country_disruption(
            "Mexico", data["sourcing"], data["suppliers"], data["products"],
            data["concentration"], scorecard, 60, 30,
        )
        busiest_scenario = reroute_network(locations, routes, {BUSIEST_NODE_ID})
        mexico_baseline_stranded = int(mexico_baseline.decision_status.eq("No qualified alternate").sum())
        mexico_baseline_within = int(mexico_baseline.within_recovery_window.sum())
        mexico_strict_stranded = int(mexico_strict.decision_status.eq("No qualified alternate").sum())
        busiest_impacted = busiest_scenario[busiest_scenario.impacted]
        invalid_locations = locations.copy()
        invalid_locations.loc[invalid_locations.index[0], "latitude"] = 95.0
        invalid_check = governance_checks(invalid_locations, routes, scorecard)
        all_node_guard = False
        try:
            reroute_network(locations, routes, set(warehouse_options.values()))
        except ValueError:
            all_node_guard = True

        uat = pd.DataFrame([
            {
                "Case": "UAT-01 Mexico baseline",
                "Expected": "36 affected; 13 no alternate; 7 leads fit 30 days",
                "Computed": f"{len(mexico_baseline)} affected; {mexico_baseline_stranded} no alternate; {mexico_baseline_within} leads fit",
                "Technical status": "PASS" if (len(mexico_baseline), mexico_baseline_stranded, mexico_baseline_within) == (36, 13, 7) else "FAIL",
            },
            {
                "Case": "UAT-02 score floor 60",
                "Expected": "25 SKUs without an eligible alternate",
                "Computed": f"{mexico_strict_stranded} SKUs without an eligible alternate",
                "Technical status": "PASS" if mexico_strict_stranded == 25 else "FAIL",
            },
            {
                "Case": f"UAT-03 {BUSIEST_NODE_NAME} unavailable",
                "Expected": "12 screens change; +1,581.8 km",
                "Computed": f"{len(busiest_impacted)} screens change; +{busiest_impacted.extra_distance_km.sum():,.1f} km",
                "Technical status": "PASS" if len(busiest_impacted) == 12 and abs(float(busiest_impacted.extra_distance_km.sum()) - 1581.8) < .05 else "FAIL",
            },
            {
                "Case": "UAT-04 invalid latitude",
                "Expected": "Publication is blocked",
                "Computed": "BLOCK" if invalid_check.status.eq("BLOCK").any() else "PASS",
                "Technical status": "PASS" if invalid_check.status.eq("BLOCK").any() else "FAIL",
            },
            {
                "Case": "UAT-05 every node unavailable",
                "Expected": "Scenario is rejected",
                "Computed": "ValueError guard raised" if all_node_guard else "Guard did not raise",
                "Technical status": "PASS" if all_node_guard else "FAIL",
            },
        ])
        uat["Business signoff"] = "Not performed - portfolio demonstration"
        st.dataframe(uat, hide_index=True, width="stretch", height=300)
        st.info("A technical PASS shows that the implemented rule reproduced its expected result. It does not establish user acceptance, policy approval, or production readiness.")

    with assurance_gis:
        st.markdown("#### Publication gate")
        st.toggle(
            "Inject an invalid latitude to replay the blocking rule",
            help="Changes one latitude to 95° in memory. Source files are never modified.",
            key="assurance_inject_bad_coordinate",
        )
        if publication_ready:
            st.success(f"Publication gate passed: {len(checks)} of {len(checks)} controls are green.")
        else:
            st.error(f"Publication blocked: {len(blocked_controls)} control(s) failed. The nine-file evidence pack is unavailable until the evidence passes.")
        st.dataframe(checks, hide_index=True, width="stretch")

        st.markdown("#### Governed layer catalogue")
        layer_catalogue = pd.DataFrame(
            [
                ["Reference points", "gis/network_locations.csv", "entity_type + entity_id", "Point / OGC:CRS84", "synthetic_reference_point", "GIS / data steward", "Keys, coordinates, coverage", "Reference points are not verified facilities"],
                ["Supplier screens", "supplier_routes.geojson", "supplier_id", "LineString / OGC:CRS84", "nearest_node_great_circle_screening", "GIS / data steward", "Geometry, basis, nearest node", "Not a shipment lane or routable network"],
                ["Route register", "gis_route_summary.csv", "supplier_id", "Tabular", "Derived from governed points", "Business analyst", "Supplier and warehouse integrity", "Distance excludes road, border, port, and time"],
                ["Supplier performance", "supplier_scorecard.csv", "supplier_id", "Tabular", "Annual measured score", "Procurement / data owner", "One-to-one supplier join", "Not SKU- or lane-specific performance"],
                ["Warehouse posture", "inventory_position.csv", "warehouse_name via governed dimension", "Tabular joined to Point", "Synthetic inventory snapshot", "Planning / data owner", "Warehouse ID and name reconciliation", "Not node throughput, capacity, or supplier flow"],
            ],
            columns=["Layer/output", "Committed source", "Business key", "Geometry / CRS", "Provenance", "Owner role", "Publication control", "Known limitation"],
        )
        st.dataframe(layer_catalogue, hide_index=True, width="stretch", height=300)
        st.caption("Operational use would require authoritative facilities, local CRS and topology rules where applicable, routable networks, capacity, privacy controls, field-edit governance, and validation with asset owners.")

    with assurance_lineage:
        lineage = pd.DataFrame(
            [
                ["Origin exposure", "fact_sourcing + product COGS", "Allocation share by supplier origin", "Country portfolio and scenario headline", "BR-05"],
                ["Eligible alternate", "fact_sourcing + supplier + scorecard", "Outside origin + qualified + annual score floor", "SKU exception register", "BR-04"],
                ["Next-nearest node", "network_locations + route summary", "Minimum Haversine distance among available nodes", "Node screening register", "GIS-03"],
                ["Warehouse posture", "inventory_position + warehouse dimension", "Aggregate measured gap and lead-cover evidence by governed node", "Warehouse posture map", "GIS-01"],
                ["Evidence package", "All manifest sources", "Gate PASS + deterministic in-memory ZIP", "Five-file stakeholder handoff", "BR-05 / BR-06"],
            ],
            columns=["Decision output", "Committed inputs", "Rule", "Interface / handoff", "Requirement"],
        )
        st.dataframe(lineage, hide_index=True, width="stretch", height=300)
        manifest_display = manifest.copy()
        manifest_display["sha256"] = manifest_display.sha256.str.slice(0, 16) + "…"
        with st.expander("Inspect source manifest"):
            st.dataframe(manifest_display, hide_index=True, width="stretch")

if workspace == "Case study":
    st.subheader("Case study: from ambiguous signal to controlled handoff")
    st.markdown(
        '<p class="section-note">The domain is synthetic specialty-food distribution. The reusable contribution is the analysis pattern: clarify the decision, expose the rule, route the exception, and preserve acceptance evidence.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="process-grid">
  <div><b>Problem</b><strong>Reports did not assign action</strong><span>A network total could hide local shortages, while a map could imply route certainty that the source data did not contain.</span></div>
  <div><b>Analysis</b><strong>Translate questions into rules</strong><span>Define eligible alternates, recovery-window sensitivity, node availability, spatial keys, coordinate bounds, and acceptance criteria.</span></div>
  <div><b>Decision support</b><strong>Prioritize exceptions</strong><span>Separate no-alternate SKUs from records whose contract lead fits the selected window, while keeping missing feasibility evidence visible.</span></div>
  <div><b>Handoff</b><strong>Name the next validation</strong><span>Procurement validates qualification and terms; planning validates cover; logistics replaces proximity with operational evidence.</span></div>
  <div><b>Assurance</b><strong>Prove the rule can fail safely</strong><span>Replay expected scenarios, block invalid coordinates, trace outputs to committed sources, and hash the evidence supplied.</span></div>
  <div><b>Boundary</b><strong>State what remains unknown</strong><span>No live systems, road routing, capacity, throughput, approval history, or business UAT sign-off are claimed.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )

    practice, transfer = st.columns(2)
    with practice:
        st.markdown("#### Business-analysis practice demonstrated")
        st.markdown(
            """
- Stakeholder question and decision framing
- Requirements and acceptance criteria
- Current- and future-state process thinking
- Data-quality and publication controls
- Scenario sensitivity and exception prioritization
- UAT preparation with expected and computed outcomes
- Briefing material and accountable stakeholder handoff
- Explicit implementation backlog and change boundary
"""
        )
    with transfer:
        st.markdown("#### Municipal and broader analyst transfer")
        st.markdown(
            """
- Supplier or warehouse key → asset, facility, or work-order key
- Availability exception → service, condition, or maintenance exception
- Spatial publication gate → governed corporate GIS layer
- Supplier/planning handoff → department, asset owner, or technical specialist handoff
- Scenario brief → sponsor, leadership, or Council briefing material

This demonstrates a transferable method. It does not claim municipal employment,
target-organization systems access, authoritative municipal data, or production
Microsoft 365 administration.
"""
        )

    st.markdown(
        '<div class="closing-line">The map is a presentation layer. The analytical contribution is the traceable path from a stakeholder question, through governed evidence and acceptance criteria, to the next accountable decision.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Presenter notes - seven-minute walkthrough"):
        st.markdown(
            """
1. **Frame the decision (0:00–0:40).** Start with the operating question and synthetic evidence boundary.
2. **Run the Mexico scenario (0:40–1:40).** Show exposure, affected SKUs, and the exception register.
3. **Command the incident (1:40–2:40).** Trace the service clock, P0 queue, playbook controls, and non-approval decision journal.
4. **Challenge the policy (2:40–3:40).** Raise the score floor and explain why sensitivity is not a forecast.
5. **Test a node assumption (3:40–4:40).** Remove the busiest distribution node and call the result next-nearest node screening.
6. **Complete the handoff (4:40–5:40).** Select one exception, assign a session-only owner, and package its evidence.
7. **Prove trust (5:40–7:00).** Inject an invalid latitude, show the export block, and separate technical PASS from business UAT sign-off.
"""
        )
    with st.expander("Production backlog and adoption path"):
        st.markdown(
            """
- Validate decision thresholds and terminology in stakeholder workshops.
- Obtain authoritative locations and establish source ownership and refresh SLAs.
- Add routable roads or freight lanes, capacity, border time, commercial constraints, and service dates.
- Implement authentication, role-based access, persistent audit history, and approval workflow.
- Pilot with one team, compare old and new priority lists, train by role, and record formal UAT sign-off.
- Monitor owner completeness, response time, repeat exceptions, data-quality failures, and adoption.
"""
        )

st.markdown(
    '<p class="map-caption" style="margin-top:2.5rem">Committed synthetic evidence · no API key · calculations separated from the interface · session fields are not persisted</p>',
    unsafe_allow_html=True,
)
