"""Contract tests for the incident-command operating model."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.gis_decision_engine import country_disruption, load_app_data
from app.incident_command import (
    controlled_decision_journal,
    event_to_action_timeline,
    incident_action_register,
    incident_playbook_catalogue,
)


ROOT = Path(__file__).resolve().parent.parent
INCIDENT_TYPES = {
    "Supplier outage",
    "Lane closure",
    "Port delay",
    "Demand spike",
    "Data-feed failure",
}


@pytest.fixture(scope="module")
def mexico_response():
    evidence = load_app_data(ROOT)
    return country_disruption(
        "Mexico",
        evidence["sourcing"],
        evidence["suppliers"],
        evidence["products"],
        evidence["concentration"],
        evidence["scorecard"],
        minimum_alternate_score=0,
        recovery_window_days=30,
    )


def test_playbook_catalogue_covers_five_operating_failure_modes():
    playbooks = incident_playbook_catalogue()
    assert set(playbooks.incident_type) == INCIDENT_TYPES
    assert playbooks.incident_type.is_unique
    assert (
        playbooks.detect_sla_min
        <= playbooks.triage_sla_min
    ).all()
    assert (
        playbooks.triage_sla_min
        <= playbooks.decision_sla_min
    ).all()
    assert (
        playbooks.decision_sla_min
        <= playbooks.action_sla_min
    ).all()
    assert (
        playbooks.action_sla_min
        <= playbooks.recovery_target_min
    ).all()
    assert playbooks.escalation_rule.str.len().gt(30).all()
    assert playbooks.rollback_condition.str.len().gt(30).all()


@pytest.mark.parametrize("incident_type", sorted(INCIDENT_TYPES))
def test_each_playbook_produces_a_complete_event_to_recovery_timeline(incident_type):
    timeline = event_to_action_timeline(incident_type, "Mexico disruption")
    assert timeline.stage.tolist() == [
        "Source event",
        "Ingestion",
        "Detection",
        "Triage",
        "Recommendation",
        "Approval",
        "Action",
        "Recovery",
    ]
    assert timeline.sequence.tolist() == list(range(1, 9))
    assert timeline.elapsed_min.is_monotonic_increasing
    assert timeline.event_id.nunique() == 1
    assert not timeline.service_clock_status.eq("BREACH").any()
    assert timeline.required_evidence.str.len().gt(20).all()


def test_timeline_makes_a_service_level_breach_visible():
    timeline = event_to_action_timeline(
        "Supplier outage",
        "Mexico disruption",
        observed_minutes=(0, 5, 20, 40, 100, 150, 280, 1600),
    )
    assert timeline.loc[timeline.stage.eq("Detection"), "service_clock_status"].item() == "BREACH"
    assert timeline.loc[timeline.stage.eq("Recovery"), "service_clock_status"].item() == "BREACH"
    assert timeline.stage_latency_min.sum() == 1600


@pytest.mark.parametrize(
    "minutes,message",
    [
        ((0, 2), "eight stages"),
        ((0, 5, 10, 20, 40, 60, 90, -1), "cannot be negative"),
        ((0, 5, 10, 20, 19, 60, 90, 120), "must be monotonic"),
    ],
)
def test_timeline_rejects_invalid_observations(minutes, message):
    with pytest.raises(ValueError, match=message):
        event_to_action_timeline("Supplier outage", "Mexico disruption", minutes)


def test_action_register_routes_every_affected_sku_once(mexico_response):
    actions = incident_action_register(
        mexico_response, "Supplier outage", "Mexico supplier-origin disruption"
    )
    assert len(actions) == len(mexico_response) == 36
    assert actions.sku.is_unique
    assert actions.priority.value_counts().to_dict() == {"P2": 7, "P1": 16, "P0": 13}
    assert actions.iloc[:13].priority.eq("P0").all()
    assert actions.status.eq("REQUIRES VALIDATION").all()
    assert actions.award_weighted_cogs.sum() == pytest.approx(11_821_992.49)
    assert actions.closure_evidence.str.len().gt(20).all()


def test_action_register_fails_closed_on_duplicate_skus(mexico_response):
    duplicate = pd.concat([mexico_response, mexico_response.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="one row per SKU"):
        incident_action_register(
            duplicate, "Supplier outage", "Mexico supplier-origin disruption"
        )


def test_decision_journal_preserves_options_authority_and_outcome_boundary(mexico_response):
    actions = incident_action_register(
        mexico_response, "Supplier outage", "Mexico supplier-origin disruption"
    )
    journal = controlled_decision_journal(
        actions, "Supplier outage", "Mexico supplier-origin disruption"
    )
    assert len(journal) == 1
    record = journal.iloc[0]
    assert record.decision_status == "RECOMMENDATION — NOT APPROVED"
    assert "13 P0 exceptions" in record.decision_basis
    assert "$11,821,992.48" in record.decision_basis
    assert "Automatic supplier switch" in record.rejected_options
    assert "NOT MEASURED" in record.actual_outcome
    assert "Procurement" in record.required_approvers
    assert "capacity" in record.next_gate


def test_decision_journal_rejects_a_mismatched_incident(mexico_response):
    actions = incident_action_register(
        mexico_response, "Supplier outage", "Mexico supplier-origin disruption"
    )
    with pytest.raises(ValueError, match="does not match"):
        controlled_decision_journal(
            actions, "Supplier outage", "Brazil supplier-origin disruption"
        )
