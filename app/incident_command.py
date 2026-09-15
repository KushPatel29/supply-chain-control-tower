"""Deterministic incident-command evidence for the network decision studio.

The module turns an analytical disruption result into an operating model:
service clocks, accountable handoffs, response playbooks and a controlled
decision journal.  It deliberately records recommended validation work, not
operational approval.  All inputs remain synthetic portfolio evidence.
"""

from __future__ import annotations

import re

import pandas as pd


PLAYBOOK_COLUMNS = [
    "incident_type",
    "trigger",
    "severity_rule",
    "incident_commander",
    "detect_sla_min",
    "triage_sla_min",
    "decision_sla_min",
    "action_sla_min",
    "recovery_target_min",
    "default_containment",
    "escalation_rule",
    "rollback_condition",
    "closure_evidence",
]


def incident_playbook_catalogue() -> pd.DataFrame:
    """Return five governed disruption playbooks with explicit service clocks."""

    rows = [
        (
            "Supplier outage",
            "Qualified supplier becomes unavailable or confirms a material capacity loss",
            "Critical when an affected SKU has no eligible alternate",
            "Procurement lead",
            15,
            30,
            120,
            240,
            1440,
            "Freeze unapproved reallocations; identify exposed SKUs and protect priority demand",
            "Escalate immediately when no qualified alternate exists or cover is below the recovery window",
            "Withdraw a proposed switch when certification, capacity, terms, or service evidence fails",
            "Supplier status confirmed; allocation decision approved; affected orders and residual risk recorded",
        ),
        (
            "Lane closure",
            "A governed transport lane is unavailable or its expected transit time breaches tolerance",
            "Critical when priority orders cannot meet their required date",
            "Logistics / network lead",
            10,
            25,
            90,
            180,
            720,
            "Hold route execution; identify affected orders and request feasible carrier alternatives",
            "Escalate when no validated route fits the service window or cost authority",
            "Return to the baseline lane when the closure clears and execution control confirms readiness",
            "Carrier route accepted; cost and service impact approved; shipment milestones monitored",
        ),
        (
            "Port delay",
            "Port dwell or vessel milestone exceeds the governed delay threshold",
            "Critical when projected arrival consumes available inventory cover",
            "Logistics / network lead",
            30,
            60,
            180,
            360,
            2880,
            "Recalculate order exposure and protect constrained demand before expediting",
            "Escalate when the delay exceeds available cover or expedite cost authority",
            "Cancel expedite when updated milestones restore service inside tolerance",
            "Milestones reconciled; expedite or allocation decision approved; customer impact recorded",
        ),
        (
            "Demand spike",
            "Actual or forecast demand exceeds the approved planning tolerance",
            "Critical when projected inventory falls below protected service stock",
            "Supply planning lead",
            30,
            90,
            240,
            480,
            4320,
            "Re-segment demand, reserve protected stock, and validate the source of the spike",
            "Escalate when protected demand cannot be covered inside the replenishment window",
            "Reverse temporary allocations when demand normalizes or the signal is rejected",
            "Demand signal accepted; allocation plan approved; fill-rate and backlog outcome recorded",
        ),
        (
            "Data-feed failure",
            "Expected source arrival is late, incomplete, duplicated, or fails a publication control",
            "Critical when a decision output cannot be refreshed or trusted",
            "Data product owner",
            10,
            20,
            60,
            120,
            240,
            "Block publication, preserve the last trusted snapshot, and open source-owner triage",
            "Escalate when the recovery-time objective is threatened or downstream decisions are waiting",
            "Return to the last trusted snapshot when replay creates reconciliation or quality failures",
            "Source reconciled; replay idempotent; controls pass; freshness and lineage updated",
        ),
    ]
    return pd.DataFrame(rows, columns=PLAYBOOK_COLUMNS)


def _event_id(incident_type: str, scenario: str) -> str:
    incident_code = "".join(word[0] for word in incident_type.upper().split())
    scenario_code = re.sub(r"[^A-Z0-9]", "", scenario.upper())[:8] or "NETWORK"
    return f"INC-{scenario_code}-{incident_code}-001"


def event_to_action_timeline(
    incident_type: str,
    scenario: str,
    observed_minutes: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Build an eight-stage service-clock timeline for one simulated incident.

    Times are elapsed minutes (T+) rather than invented wall-clock timestamps.
    Custom observations make SLA breaches replayable in tests and interviews.
    """

    catalogue = incident_playbook_catalogue()
    selected = catalogue[catalogue["incident_type"].eq(incident_type)]
    if selected.empty:
        raise ValueError(f"unknown incident type: {incident_type}")
    playbook = selected.iloc[0]
    stages = (
        "Source event",
        "Ingestion",
        "Detection",
        "Triage",
        "Recommendation",
        "Approval",
        "Action",
        "Recovery",
    )
    default_minutes = (
        0,
        max(1, int(playbook.detect_sla_min) // 3),
        int(playbook.detect_sla_min),
        int(playbook.triage_sla_min),
        max(int(playbook.triage_sla_min) + 1, int(playbook.decision_sla_min) - 20),
        int(playbook.decision_sla_min),
        int(playbook.action_sla_min),
        int(playbook.recovery_target_min),
    )
    elapsed = default_minutes if observed_minutes is None else observed_minutes
    if len(elapsed) != len(stages):
        raise ValueError("observed_minutes must contain one value for each of the eight stages")
    if any(int(value) < 0 for value in elapsed):
        raise ValueError("observed minutes cannot be negative")
    if list(map(int, elapsed)) != sorted(map(int, elapsed)):
        raise ValueError("observed minutes must be monotonic")

    sla = (
        0,
        int(playbook.detect_sla_min),
        int(playbook.detect_sla_min),
        int(playbook.triage_sla_min),
        int(playbook.decision_sla_min),
        int(playbook.decision_sla_min),
        int(playbook.action_sla_min),
        int(playbook.recovery_target_min),
    )
    owners = (
        "Source owner",
        "Data product owner",
        "Control-tower analyst",
        str(playbook.incident_commander),
        "Cross-functional risk review",
        "Delegated decision authority",
        str(playbook.incident_commander),
        "Incident commander + control owner",
    )
    evidence = (
        "Source signal retained",
        "Arrival and quality controls recorded",
        "Rule and affected scope recorded",
        "Severity, owner, and service clock accepted",
        "Options, assumptions, and residual risks documented",
        "Authority, conditions, and rejected options recorded",
        "Execution reference and rollback trigger recorded",
        "Outcome, residual risk, and closure evidence reconciled",
    )
    event_id = _event_id(incident_type, scenario)
    rows = []
    prior = 0
    for sequence, (stage, minute, target, owner, proof) in enumerate(
        zip(stages, elapsed, sla, owners, evidence), start=1
    ):
        minute = int(minute)
        rows.append(
            {
                "event_id": event_id,
                "sequence": sequence,
                "stage": stage,
                "elapsed_min": minute,
                "stage_latency_min": minute - prior if sequence > 1 else 0,
                "cumulative_sla_min": target,
                "service_clock_status": "START" if sequence == 1 else ("MET" if minute <= target else "BREACH"),
                "accountable_role": owner,
                "required_evidence": proof,
            }
        )
        prior = minute
    return pd.DataFrame(rows)


def incident_action_register(
    scenario_response: pd.DataFrame,
    incident_type: str,
    scenario: str,
) -> pd.DataFrame:
    """Turn affected SKUs into a deterministic, owner-routed validation queue."""

    required = {
        "sku",
        "category",
        "cogs",
        "country_award_share",
        "decision_status",
        "qualified_alternate",
        "switch_lead_days",
        "within_recovery_window",
        "recommended_next_check",
    }
    missing = required - set(scenario_response.columns)
    if missing:
        raise ValueError(f"scenario response is missing required columns: {sorted(missing)}")
    if scenario_response["sku"].duplicated().any():
        raise ValueError("scenario response must contain one row per SKU")
    playbooks = incident_playbook_catalogue()
    selected = playbooks[playbooks.incident_type.eq(incident_type)]
    if selected.empty:
        raise ValueError(f"unknown incident type: {incident_type}")
    playbook = selected.iloc[0]
    event_id = _event_id(incident_type, scenario)

    rows = []
    for row in scenario_response.itertuples(index=False):
        stranded = row.decision_status == "No qualified alternate"
        within = bool(row.within_recovery_window) if pd.notna(row.within_recovery_window) else False
        if stranded:
            priority, owner, action = (
                "P0",
                "Procurement lead + supply planning lead",
                "Protect priority demand and open alternate-qualification or service-risk escalation",
            )
        elif not within:
            priority, owner, action = (
                "P1",
                "Supply planning lead",
                "Validate inventory bridge and close the lead-time gap before the required date",
            )
        else:
            priority, owner, action = (
                "P2",
                "Cross-functional risk review",
                "Validate SKU capacity, certification, commercial terms, and executable logistics",
            )
        rows.append(
            {
                "event_id": event_id,
                "sku": str(row.sku),
                "category": str(row.category),
                "priority": priority,
                "award_weighted_cogs": round(float(row.cogs) * float(row.country_award_share), 2),
                "exception": str(row.decision_status),
                "candidate_alternate": str(row.qualified_alternate),
                "contract_lead_days": None if pd.isna(row.switch_lead_days) else int(row.switch_lead_days),
                "accountable_role": owner,
                "response_action": action,
                "target_minutes": int(playbook.action_sla_min),
                "status": "REQUIRES VALIDATION",
                "closure_evidence": str(row.recommended_next_check),
            }
        )
    priority_order = pd.CategoricalDtype(["P0", "P1", "P2"], ordered=True)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["priority"] = result["priority"].astype(priority_order)
    result = result.sort_values(
        ["priority", "award_weighted_cogs", "sku"], ascending=[True, False, True]
    ).reset_index(drop=True)
    result["priority"] = result["priority"].astype(str)
    return result


def controlled_decision_journal(
    action_register: pd.DataFrame,
    incident_type: str,
    scenario: str,
) -> pd.DataFrame:
    """Return one non-approval decision record derived from the action queue."""

    required = {"event_id", "sku", "priority", "award_weighted_cogs", "status"}
    missing = required - set(action_register.columns)
    if missing:
        raise ValueError(f"action register is missing required columns: {sorted(missing)}")
    if action_register.empty:
        raise ValueError("action register cannot be empty")
    event_ids = action_register.event_id.unique()
    if len(event_ids) != 1 or event_ids[0] != _event_id(incident_type, scenario):
        raise ValueError("action register does not match the requested incident")

    p0 = action_register[action_register.priority.eq("P0")]
    exposed = float(action_register.award_weighted_cogs.sum())
    selected = (
        "Contain priority demand and validate recovery options"
        if not p0.empty
        else "Validate eligible recovery options before execution"
    )
    basis = (
        f"{len(action_register)} affected SKUs; {len(p0)} P0 exceptions; "
        f"${exposed:,.2f} award-weighted COGS screened"
    )
    return pd.DataFrame(
        [
            {
                "decision_id": f"DEC-{event_ids[0][4:]}",
                "event_id": event_ids[0],
                "incident_type": incident_type,
                "scenario": scenario,
                "decision_status": "RECOMMENDATION — NOT APPROVED",
                "selected_option": selected,
                "rejected_options": "Automatic supplier switch | Proximity-only reroute | Wait without containment",
                "decision_basis": basis,
                "expected_benefit": "Focus scarce validation effort on service-critical exceptions while preserving approval controls",
                "accountable_role": "Cross-functional risk review",
                "required_approvers": "Procurement | Supply planning | Logistics | Finance as required",
                "next_gate": "Validate capacity, certification, commercial terms, service dates, and executable routing",
                "actual_outcome": "NOT MEASURED — synthetic scenario; no action executed",
                "evidence_status": "REPRODUCIBLE PORTFOLIO EVIDENCE",
            }
        ]
    )
