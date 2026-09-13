"""Acceptance tests for the advanced GIS decision-support evidence pack.

These tests protect reconciliations and portable evidence contracts rather
than Streamlit layout details.  Inputs are the repository's committed,
synthetic evidence unless a test deliberately constructs a broken copy.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pandas as pd
import pytest

from app.advanced_decision_support import (
    build_country_scenario_portfolio,
    build_evidence_manifest,
    build_evidence_pack,
    warehouse_inventory_risk_summary,
)
from app.gis_decision_engine import load_app_data


ROOT = Path(__file__).resolve().parent.parent
PACK_MEMBERS = [
    "README-assumptions.md",
    "decision-brief.md",
    "evidence-manifest.csv",
    "selected-supplier-routes.geojson",
    "sku-response-register.csv",
]


@pytest.fixture(scope="module")
def evidence():
    return load_app_data(ROOT)


@pytest.fixture(scope="module")
def warehouse_summary(evidence):
    return warehouse_inventory_risk_summary(
        evidence["inventory_position"],
        evidence["warehouses"],
        evidence["locations"],
    )


@pytest.fixture(scope="module")
def portfolio(evidence):
    return build_country_scenario_portfolio(
        evidence["sourcing"],
        evidence["suppliers"],
        evidence["products"],
        evidence["concentration"],
        evidence["scorecard"],
        minimum_alternate_score=0,
        recovery_window_days=30,
    )


@pytest.fixture(scope="module")
def manifest():
    return build_evidence_manifest(ROOT)


def build_pack(evidence, manifest, **overrides):
    options = {
        "country": "Mexico",
        "minimum_alternate_score": 0,
        "recovery_window_days": 30,
        "owner": "Municipal systems interview handoff",
    }
    options.update(overrides)
    return build_evidence_pack(
        sourcing=evidence["sourcing"],
        suppliers=evidence["suppliers"],
        products=evidence["products"],
        concentration=evidence["concentration"],
        scorecard=evidence["scorecard"],
        routes=evidence["routes"],
        route_geojson=evidence["route_geojson"],
        manifest=manifest,
        **options,
    )


def test_warehouse_summary_reconciles_and_pins_ontario_dc3(
    warehouse_summary, evidence
):
    assert len(warehouse_summary) == evidence["warehouses"].warehouse_id.nunique() == 8
    assert warehouse_summary.warehouse_id.is_unique
    assert set(warehouse_summary.warehouse_id) == set(evidence["warehouses"].warehouse_id)
    assert warehouse_summary.positions.sum() == len(evidence["inventory_position"]) == 478
    assert warehouse_summary.gap_value.sum() == pytest.approx(
        evidence["inventory_position"].gap_value.sum(), abs=0.01
    )
    assert warehouse_summary.on_hand_value.sum() == pytest.approx(
        evidence["inventory_position"].on_hand_value.sum(), abs=0.01
    )

    ontario = warehouse_summary.set_index("warehouse_name").loc["Ontario DC 3"]
    assert ontario.warehouse_id == 3
    assert ontario.positions == 60
    assert ontario.gap_positions == 39
    assert ontario.gap_position_share == pytest.approx(0.6500)
    assert ontario.gap_value == pytest.approx(368_150.93)
    assert ontario.not_covering_lead == 17
    assert ontario.lead_cover_failure_share == pytest.approx(0.2833)
    assert ontario.excess_positions == 3
    assert ontario.excess_value == pytest.approx(60_817.50)
    assert ontario.on_hand_value == pytest.approx(1_349_709.24)
    assert ontario.gap_value_rank == 1


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("duplicate warehouse ID", "duplicate warehouse IDs"),
        ("location name drift", "warehouse names drift"),
        ("unmatched inventory name", "no governed warehouse match"),
    ],
)
def test_warehouse_summary_fails_closed_on_key_reconciliation_errors(
    evidence, failure, message
):
    inventory = evidence["inventory_position"].copy()
    warehouses = evidence["warehouses"].copy()
    locations = evidence["locations"].copy()

    if failure == "duplicate warehouse ID":
        warehouses.loc[warehouses.index[1], "warehouse_id"] = warehouses.iloc[0].warehouse_id
    elif failure == "location name drift":
        first_location = locations.index[locations.entity_type.eq("warehouse")][0]
        locations.loc[first_location, "name"] = "Drifted warehouse name"
    else:
        inventory.loc[inventory.index[0], "warehouse_name"] = "Unknown warehouse"

    with pytest.raises(ValueError, match=message):
        warehouse_inventory_risk_summary(inventory, warehouses, locations)


def test_country_portfolio_has_one_reconciled_row_per_governed_origin(portfolio, evidence):
    governed = set(evidence["suppliers"].country.dropna().astype(str))
    assert len(portfolio) == len(governed) == 9
    assert portfolio.country.is_unique
    assert set(portfolio.country) == governed
    assert portfolio.network_cogs_share.sum() == pytest.approx(1.0, abs=0.0001)
    assert portfolio.award_weighted_cogs.sum() == pytest.approx(43_394_724.94, abs=0.01)
    assert portfolio.exposure_rank.tolist() == list(range(1, 10))
    assert portfolio.minimum_alternate_score.eq(0).all()
    assert portfolio.recovery_window_days.eq(30).all()


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        (
            "Mexico",
            (36, 11_821_992.49, 0.2724, 13, 23, 7, 31.7, 44, "SKU-1018", 1),
        ),
        (
            "Brazil",
            (23, 8_797_316.53, 0.2027, 4, 19, 16, 16.8, 34, "SKU-1011", 2),
        ),
        (
            "Spain",
            (19, 6_236_499.23, 0.1437, 2, 17, 15, 16.6, 34, "SKU-1038", 3),
        ),
    ],
)
def test_country_portfolio_pins_the_three_largest_origin_scenarios(
    portfolio, country, expected
):
    row = portfolio.set_index("country").loc[country]
    (
        affected,
        exposure,
        share,
        stranded,
        recoverable,
        within,
        mean_lead,
        max_lead,
        highest_sku,
        rank,
    ) = expected
    assert row.affected_skus == affected
    assert row.award_weighted_cogs == pytest.approx(exposure)
    assert row.network_cogs_share == pytest.approx(share)
    assert row.stranded_skus == stranded
    assert row.recoverable_skus == recoverable
    assert row.recoverable_within_window == within
    assert row.recoverable_outside_window == recoverable - within
    assert row.mean_best_alternate_lead_days == pytest.approx(mean_lead)
    assert row.maximum_best_alternate_lead_days == max_lead
    assert row.highest_exposure_stranded_sku == highest_sku
    assert row.exposure_rank == rank


def test_stricter_alternate_scores_never_reduce_stranded_skus(evidence):
    portfolios = [
        build_country_scenario_portfolio(
            evidence["sourcing"],
            evidence["suppliers"],
            evidence["products"],
            evidence["concentration"],
            evidence["scorecard"],
            minimum_alternate_score=score,
            recovery_window_days=30,
        ).set_index("country")
        for score in (0, 40, 50, 60, 65)
    ]
    for country in portfolios[0].index:
        stranded = [int(frame.loc[country, "stranded_skus"]) for frame in portfolios]
        assert stranded == sorted(stranded), (country, stranded)


def test_longer_recovery_windows_never_reduce_recoverable_skus(evidence):
    portfolios = [
        build_country_scenario_portfolio(
            evidence["sourcing"],
            evidence["suppliers"],
            evidence["products"],
            evidence["concentration"],
            evidence["scorecard"],
            minimum_alternate_score=60,
            recovery_window_days=days,
        ).set_index("country")
        for days in (15, 30, 45, 60)
    ]
    for country in portfolios[0].index:
        within = [
            int(frame.loc[country, "recoverable_within_window"])
            for frame in portfolios
        ]
        assert within == sorted(within), (country, within)
        for frame in portfolios:
            row = frame.loc[country]
            assert row.recoverable_within_window + row.recoverable_outside_window == row.recoverable_skus


def test_manifest_has_a_stable_schema_safe_paths_and_verifiable_hashes(manifest):
    assert manifest.columns.tolist() == [
        "path",
        "format",
        "rows_or_features",
        "bytes",
        "sha256",
    ]
    assert len(manifest) == 12
    assert manifest.path.tolist() == sorted(manifest.path)
    assert manifest.path.is_unique
    assert manifest.rows_or_features.gt(0).all()
    assert manifest.bytes.gt(0).all()
    assert manifest.sha256.str.fullmatch(r"[0-9a-f]{64}").all()

    for item in manifest.itertuples(index=False):
        relative = PurePosixPath(item.path)
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        assert "\\" not in item.path
        source = ROOT / Path(*relative.parts)
        assert source.is_file()
        raw = source.read_bytes()
        canonical = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert item.sha256 in {
            hashlib.sha256(raw).hexdigest(),
            hashlib.sha256(canonical).hexdigest(),
        }
        assert item.bytes in {len(raw), len(canonical)}


def test_manifest_hash_is_stable_across_lf_and_crlf_checkouts(tmp_path):
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    lf_root.mkdir()
    crlf_root.mkdir()
    logical_csv = "key,value\n1,café\n2,screening\n"
    (lf_root / "sample.csv").write_bytes(logical_csv.encode("utf-8"))
    (crlf_root / "sample.csv").write_bytes(
        logical_csv.replace("\n", "\r\n").encode("utf-8")
    )

    lf = build_evidence_manifest(lf_root, ["sample.csv"])
    crlf = build_evidence_manifest(crlf_root, ["sample.csv"])

    pd.testing.assert_frame_equal(lf, crlf)


def test_manifest_refuses_paths_that_escape_the_declared_root(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (tmp_path / "outside.csv").write_text("key\n1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes the repository"):
        build_evidence_manifest(repository, ["../outside.csv"])


def test_evidence_zip_is_exact_parseable_safe_deterministic_and_handoff_ready(
    evidence, manifest
):
    handoff = {
        "status": "Needs validation",
        "target_review": "2026-09-20",
        "session_note": "Confirm certification and available capacity.",
        "selected_sku": "SKU-1018",
    }
    first = build_pack(evidence, manifest, **handoff)
    second = build_pack(evidence, manifest, **handoff)
    assert first == second
    assert first.startswith(b"PK\x03\x04")
    assert len(first) < 1_000_000

    with ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == PACK_MEMBERS
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert "\\" not in member.filename
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert member.file_size > 0

        register = pd.read_csv(io.BytesIO(archive.read("sku-response-register.csv")))
        archived_manifest = pd.read_csv(
            io.BytesIO(archive.read("evidence-manifest.csv"))
        )
        routes = json.loads(archive.read("selected-supplier-routes.geojson"))
        brief = archive.read("decision-brief.md").decode("utf-8")
        assumptions = archive.read("README-assumptions.md").decode("utf-8")

    assert len(register) == 36
    assert register.product_id.is_unique
    assert archived_manifest.path.tolist() == manifest.path.tolist()
    assert archived_manifest.sha256.tolist() == manifest.sha256.tolist()
    assert routes["type"] == "FeatureCollection"
    assert len(routes["features"]) == 4
    assert {
        feature["properties"]["supplier_country"] for feature in routes["features"]
    } == {"Mexico"}
    assert "Municipal systems interview handoff" in brief
    assert "SKU-1018" in brief
    assert "Needs validation" in brief
    assert "2026-09-20" in brief
    assert "Confirm certification and available capacity." in brief
    assert "Required next checks" in brief
    assert "not a shipment plan" in brief
    assert all(name in assumptions for name in PACK_MEMBERS)
    assert "All business records and coordinates are synthetic" in assumptions


def test_evidence_zip_rejects_an_ungoverned_country(evidence, manifest):
    with pytest.raises(ValueError, match="not present in the governed supplier data"):
        build_pack(evidence, manifest, country="Atlantis")


def test_evidence_zip_rejects_a_selected_sku_outside_the_scenario(evidence, manifest):
    with pytest.raises(ValueError, match="selected SKU is not affected"):
        build_pack(evidence, manifest, selected_sku="SKU-NOT-IN-SCENARIO")
