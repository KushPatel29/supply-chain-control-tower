"""Advanced, interface-independent decision support for the GIS studio.

The functions in this module deliberately return ordinary pandas frames or
bytes. They can be tested without Streamlit and reused by another interface.
All location data is synthetic; distance remains great-circle screening. No
function invents shipment lanes, alternate capacity, node throughput, road
routing or commercial feasibility.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pandas as pd

from app.gis_decision_engine import country_disruption
from app.incident_command import (
    controlled_decision_journal,
    event_to_action_timeline,
    incident_action_register,
    incident_playbook_catalogue,
)


DEFAULT_EVIDENCE_FILES = (
    "analytics/output/country_exposure.csv",
    "analytics/output/gis_route_summary.csv",
    "analytics/output/inventory_position.csv",
    "analytics/output/network_locations.geojson",
    "analytics/output/sourcing_concentration.csv",
    "analytics/output/supplier_routes.geojson",
    "analytics/output/supplier_scorecard.csv",
    "data/bronze/dim_product.csv",
    "data/bronze/dim_supplier.csv",
    "data/bronze/dim_warehouse.csv",
    "data/bronze/fact_sourcing.csv",
    "gis/network_locations.csv",
)

EVIDENCE_LIMITATIONS = (
    "All business records and coordinates are synthetic portfolio evidence.",
    "WGS 84 points are reference locations, not verified facilities.",
    "Great-circle proximity is screening, not road, freight or travel-time routing.",
    "Country exposure is award-weighted product COGS, not shipment volume.",
    "Supplier scores are annual and supplier-wide, not SKU- or lane-specific.",
    "Qualification does not prove product certification, available capacity or commercial feasibility.",
    "The model excludes freight, duty, FX, border delay, carbon, service territory and node throughput.",
)

_SKU_EXPORT_COLUMNS = (
    "product_id",
    "sku",
    "category",
    "cogs",
    "country_award_share",
    "decision_status",
    "qualified_alternate",
    "alternate_country",
    "alternate_score",
    "switch_lead_days",
    "within_recovery_window",
    "recommended_next_check",
)


def _require(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {sorted(missing)}")


def warehouse_inventory_risk_summary(
    inventory_position: pd.DataFrame,
    dim_warehouse: pd.DataFrame,
    network_locations: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate measured inventory risk onto governed warehouse points.

    ``inventory_position`` has a warehouse name but no warehouse ID. The name
    is therefore used only to bridge through ``dim_warehouse``; coordinates
    are then joined with the governed ID. Results describe inventory evidence
    at each node. They must not be interpreted as supplier flow or node
    throughput, because neither is present in the source data.
    """

    _require(
        inventory_position,
        {
            "warehouse_name",
            "gap_value",
            "excess_value",
            "on_hand_value",
            "covers_lead_time",
        },
        "inventory position",
    )
    _require(
        dim_warehouse,
        {"warehouse_id", "warehouse_name", "region", "city"},
        "warehouse dimension",
    )
    _require(
        network_locations,
        {
            "entity_type",
            "entity_id",
            "name",
            "country",
            "region",
            "longitude",
            "latitude",
            "location_basis",
        },
        "network locations",
    )

    warehouses = dim_warehouse.copy()
    locations = network_locations[
        network_locations["entity_type"].eq("warehouse")
    ].copy()
    if warehouses["warehouse_id"].duplicated().any():
        raise ValueError("warehouse dimension contains duplicate warehouse IDs")
    if warehouses["warehouse_name"].duplicated().any():
        raise ValueError("warehouse dimension contains duplicate warehouse names")
    if locations["entity_id"].duplicated().any():
        raise ValueError("network locations contain duplicate warehouse entity IDs")

    locations = locations.rename(
        columns={
            "entity_id": "warehouse_id",
            "name": "location_warehouse_name",
            "region": "location_region",
        }
    )
    master = warehouses.merge(
        locations[
            [
                "warehouse_id",
                "location_warehouse_name",
                "country",
                "location_region",
                "longitude",
                "latitude",
                "location_basis",
            ]
        ],
        on="warehouse_id",
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not master["_merge"].eq("both").all():
        raise ValueError("warehouse dimension and network locations do not cover the same IDs")
    if not master["warehouse_name"].eq(master["location_warehouse_name"]).all():
        raise ValueError("warehouse names drift between the dimension and location register")
    if not master["region"].eq(master["location_region"]).all():
        raise ValueError("warehouse regions drift between the dimension and location register")
    if not (
        master["longitude"].between(-180, 180).all()
        and master["latitude"].between(-90, 90).all()
    ):
        raise ValueError("warehouse coordinates fall outside WGS 84 bounds")
    master = master.drop(columns=["_merge", "location_warehouse_name", "location_region"])

    evidence = inventory_position.copy()
    for column in ("gap_value", "excess_value", "on_hand_value", "covers_lead_time"):
        evidence[column] = pd.to_numeric(evidence[column], errors="raise")
    evidence = evidence.merge(
        master[["warehouse_id", "warehouse_name"]],
        on="warehouse_name",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    if not evidence["_merge"].eq("both").all():
        missing_names = sorted(
            evidence.loc[evidence["_merge"].ne("both"), "warehouse_name"]
            .dropna()
            .astype(str)
            .unique()
        )
        raise ValueError(f"inventory rows have no governed warehouse match: {missing_names}")
    evidence = evidence.drop(columns="_merge")

    measured = (
        evidence.groupby("warehouse_id", as_index=False)
        .agg(
            positions=("warehouse_name", "size"),
            gap_positions=("gap_value", lambda values: int(values.gt(0).sum())),
            gap_value=("gap_value", "sum"),
            not_covering_lead=(
                "covers_lead_time",
                lambda values: int(values.eq(0).sum()),
            ),
            excess_positions=(
                "excess_value",
                lambda values: int(values.gt(0).sum()),
            ),
            excess_value=("excess_value", "sum"),
            on_hand_value=("on_hand_value", "sum"),
        )
    )
    summary = master.merge(measured, on="warehouse_id", how="left", validate="one_to_one")
    count_columns = (
        "positions",
        "gap_positions",
        "not_covering_lead",
        "excess_positions",
    )
    value_columns = ("gap_value", "excess_value", "on_hand_value")
    summary["has_inventory_evidence"] = summary["positions"].notna()
    summary[list(count_columns)] = summary[list(count_columns)].fillna(0).astype(int)
    summary[list(value_columns)] = summary[list(value_columns)].fillna(0.0).round(2)
    denominator = summary["positions"].where(summary["positions"].gt(0))
    summary["gap_position_share"] = (summary["gap_positions"] / denominator).round(4)
    summary["lead_cover_failure_share"] = (
        summary["not_covering_lead"] / denominator
    ).round(4)
    summary = summary.sort_values(
        ["gap_value", "warehouse_id"], ascending=[False, True]
    ).reset_index(drop=True)
    summary["gap_value_rank"] = range(1, len(summary) + 1)
    return summary[
        [
            "warehouse_id",
            "warehouse_name",
            "region",
            "city",
            "country",
            "longitude",
            "latitude",
            "location_basis",
            "has_inventory_evidence",
            "positions",
            "gap_positions",
            "gap_position_share",
            "gap_value",
            "not_covering_lead",
            "lead_cover_failure_share",
            "excess_positions",
            "excess_value",
            "on_hand_value",
            "gap_value_rank",
        ]
    ]


def build_country_scenario_portfolio(
    sourcing: pd.DataFrame,
    suppliers: pd.DataFrame,
    products: pd.DataFrame,
    concentration: pd.DataFrame,
    scorecard: pd.DataFrame,
    minimum_alternate_score: float = 0,
    recovery_window_days: int = 30,
) -> pd.DataFrame:
    """Run the existing disruption rule consistently for every origin.

    The portfolio is a sensitivity screen. An eligible alternate is outside
    the selected origin, marked qualified, and at or above the selected annual
    supplier-score floor. No capacity, lane, certification or commercial
    feasibility is inferred.
    """

    _require(
        suppliers,
        {"supplier_id", "supplier_name", "country", "is_qualified_alternate"},
        "supplier dimension",
    )
    _require(products, {"product_id", "sku", "category"}, "product dimension")
    _require(scorecard, {"supplier_id", "composite_score"}, "supplier scorecard")
    _require(concentration, {"product_id", "cogs"}, "sourcing concentration")
    _require(
        sourcing,
        {"product_id", "supplier_id", "allocation_share", "contract_lead_days"},
        "sourcing",
    )
    if float(minimum_alternate_score) < 0:
        raise ValueError("minimum alternate score cannot be negative")
    if int(recovery_window_days) <= 0:
        raise ValueError("recovery window must be positive")
    if concentration["product_id"].duplicated().any():
        raise ValueError("sourcing concentration must contain one row per product")

    cogs = concentration[["product_id", "cogs"]].copy()
    cogs["cogs"] = pd.to_numeric(cogs["cogs"], errors="raise")
    total_cogs = float(cogs["cogs"].sum())
    if total_cogs <= 0:
        raise ValueError("total product COGS must be positive")

    countries = sorted(
        str(country)
        for country in suppliers["country"].dropna().unique()
        if str(country).strip()
    )
    rows: list[dict[str, object]] = []
    for country in countries:
        response = country_disruption(
            country,
            sourcing,
            suppliers,
            products,
            concentration,
            scorecard,
            minimum_alternate_score,
            recovery_window_days,
        )
        if response.empty:
            continue
        response = response.copy()
        response["award_weighted_cogs"] = (
            response["cogs"] * response["country_award_share"]
        )
        stranded = response[response["decision_status"].eq("No qualified alternate")]
        recoverable = response[
            response["decision_status"].ne("No qualified alternate")
        ]
        within = recoverable[recoverable["within_recovery_window"].astype(bool)]
        highest_stranded = (
            "—"
            if stranded.empty
            else str(
                stranded.sort_values(
                    ["award_weighted_cogs", "sku"], ascending=[False, True]
                ).iloc[0]["sku"]
            )
        )
        mean_switch = (
            None
            if recoverable.empty
            else round(float(recoverable["switch_lead_days"].mean()), 1)
        )
        maximum_switch = (
            None
            if recoverable.empty
            else int(recoverable["switch_lead_days"].max())
        )
        exposure = float(response["award_weighted_cogs"].sum())
        rows.append(
            {
                "country": country,
                "suppliers_in_origin": int(
                    suppliers.loc[suppliers["country"].eq(country), "supplier_id"].nunique()
                ),
                "affected_skus": int(len(response)),
                "award_weighted_cogs": round(exposure, 2),
                "network_cogs_share": round(exposure / total_cogs, 4),
                "stranded_skus": int(len(stranded)),
                "stranded_product_cogs": round(float(stranded["cogs"].sum()), 2),
                "stranded_award_weighted_cogs": round(
                    float(stranded["award_weighted_cogs"].sum()), 2
                ),
                "recoverable_skus": int(len(recoverable)),
                "recoverable_within_window": int(len(within)),
                "recoverable_outside_window": int(len(recoverable) - len(within)),
                "mean_best_alternate_lead_days": mean_switch,
                "maximum_best_alternate_lead_days": maximum_switch,
                "highest_exposure_stranded_sku": highest_stranded,
                "minimum_alternate_score": float(minimum_alternate_score),
                "recovery_window_days": int(recovery_window_days),
            }
        )

    portfolio = pd.DataFrame(rows)
    if portfolio.empty:
        return portfolio
    portfolio = portfolio.sort_values(
        ["award_weighted_cogs", "country"], ascending=[False, True]
    ).reset_index(drop=True)
    portfolio["exposure_rank"] = range(1, len(portfolio) + 1)
    return portfolio


def _canonical_text_bytes(path: Path, payload: bytes) -> bytes:
    """Normalize supported text evidence to UTF-8 without BOM and LF lines."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"evidence file is not valid UTF-8 text: {path.name}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _row_count(path: Path, payload: bytes) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = payload.decode("utf-8")
        rows = [row for row in csv.reader(io.StringIO(text)) if row]
        return "csv", max(len(rows) - 1, 0)
    if suffix in {".geojson", ".json"}:
        document = json.loads(payload.decode("utf-8"))
        if isinstance(document, Mapping) and document.get("type") == "FeatureCollection":
            features = document.get("features")
            if not isinstance(features, list):
                raise ValueError(f"{path.name} has no valid GeoJSON feature list")
            return "geojson", len(features)
        if isinstance(document, list):
            return "json", len(document)
        return "json", 1
    raise ValueError(f"unsupported evidence format for row counting: {path.suffix}")


def build_evidence_manifest(
    root: str | Path,
    source_files: Iterable[str | Path] = DEFAULT_EVIDENCE_FILES,
) -> pd.DataFrame:
    """Return a deterministic file inventory with row counts and SHA-256.

    Paths are relative to ``root`` and sorted before hashing. Before row
    counting, byte sizing and hashing, every supported text file is normalized
    to UTF-8 without a BOM and LF line endings. The manifest has no clock time
    or machine-specific absolute paths, so identical text evidence produces
    identical output on Windows and Linux.
    """

    repository_root = Path(root).resolve()
    relative_paths = sorted({Path(item).as_posix() for item in source_files})
    if not relative_paths:
        raise ValueError("at least one evidence file is required")

    rows: list[dict[str, object]] = []
    for relative_text in relative_paths:
        relative = Path(relative_text)
        if relative.is_absolute():
            raise ValueError(f"evidence path must be relative: {relative_text}")
        path = (repository_root / relative).resolve()
        try:
            normalized = path.relative_to(repository_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"evidence path escapes the repository: {relative_text}") from exc
        if not path.is_file():
            raise FileNotFoundError(f"evidence file not found: {normalized}")
        payload = _canonical_text_bytes(path, path.read_bytes())
        file_format, rows_in_file = _row_count(path, payload)
        rows.append(
            {
                "path": normalized,
                "format": file_format,
                "rows_or_features": int(rows_in_file),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return pd.DataFrame(rows).sort_values("path").reset_index(drop=True)


def _selected_route_geojson(
    route_geojson: Mapping[str, object], supplier_ids: Iterable[int]
) -> str:
    selected = {int(item) for item in supplier_ids}
    features = route_geojson.get("features", [])
    if not isinstance(features, list):
        raise ValueError("route GeoJSON has no feature list")
    chosen = [
        feature
        for feature in features
        if int(feature.get("properties", {}).get("supplier_id", -1)) in selected
    ]
    chosen.sort(key=lambda feature: int(feature.get("properties", {}).get("supplier_id", -1)))
    if len(chosen) != len(selected):
        found = {
            int(feature.get("properties", {}).get("supplier_id", -1))
            for feature in chosen
        }
        raise ValueError(f"route GeoJSON is missing selected suppliers: {sorted(selected - found)}")
    return json.dumps(
        {"type": "FeatureCollection", "features": chosen},
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def _handoff_text(value: object | None) -> str:
    """Render optional handoff metadata as one deterministic Markdown line."""

    if value is None:
        return "Not recorded"
    normalized = " ".join(str(value).split())
    return normalized or "Not recorded"


def _decision_brief(
    country: str,
    scenario: Mapping[str, object],
    owner: str,
    status: str | None = None,
    target_review: str | None = None,
    session_note: str | None = None,
    selected_exception: Mapping[str, object] | None = None,
) -> str:
    mean_lead = scenario.get("mean_best_alternate_lead_days")
    mean_lead_text = "not available" if pd.isna(mean_lead) else f"{float(mean_lead):.1f} days"
    selected_block = ""
    if selected_exception is not None:
        score = selected_exception.get("alternate_score")
        lead = selected_exception.get("switch_lead_days")
        score_text = "Not available" if pd.isna(score) else f"{float(score):.1f}"
        lead_text = "Not available" if pd.isna(lead) else f"{int(lead)} days"
        selected_block = f"""

## Selected exception

- **SKU:** {_handoff_text(selected_exception.get('sku'))}
- **Exception:** {_handoff_text(selected_exception.get('decision_status'))}
- **Eligible alternate:** {_handoff_text(selected_exception.get('qualified_alternate'))}
- **Alternate country:** {_handoff_text(selected_exception.get('alternate_country'))}
- **Annual alternate score:** {score_text}
- **Contract lead:** {lead_text}
- **Next validation:** {_handoff_text(selected_exception.get('recommended_next_check'))}

This selection records the analyst's focus for the current handoff. It does
not approve a supplier, route, capacity commitment or commercial change.
"""
    return f"""# Network disruption decision brief

- **Scenario:** Supplier origin unavailable — {country}
- **Decision owner:** {_handoff_text(owner)}
- **Recovery window:** {int(scenario['recovery_window_days'])} days
- **Minimum annual alternate score:** {float(scenario['minimum_alternate_score']):.1f}

## Handoff record

- **Status:** {_handoff_text(status)}
- **Target review:** {_handoff_text(target_review)}
- **Session note:** {_handoff_text(session_note)}
{selected_block}

## Decision evidence

- Award-weighted COGS exposure: ${float(scenario['award_weighted_cogs']):,.2f} ({float(scenario['network_cogs_share']):.2%} of network)
- Suppliers in origin: {int(scenario['suppliers_in_origin'])}
- Affected SKUs: {int(scenario['affected_skus'])}
- SKUs without an eligible external alternate: {int(scenario['stranded_skus'])}
- Eligible alternate lead time fits the selected window: {int(scenario['recoverable_within_window'])} of {int(scenario['recoverable_skus'])}
- Mean best eligible-alternate contract lead: {mean_lead_text}
- Highest award-exposure stranded SKU: {scenario['highest_exposure_stranded_sku']}

## Required next checks

1. Procurement confirms SKU-specific qualification, capacity and commercial terms.
2. Supply planning validates on-hand cover and the recovery window.
3. Logistics replaces proximity screening with operational routing, border and node-capacity evidence.

## Evidence boundary

This pack is generated from committed synthetic portfolio evidence. It supports
screening and stakeholder review; it is not a shipment plan, capacity promise
or authorization to execute a sourcing or distribution change.
"""


def _evidence_readme(
    country: str,
    status: str | None = None,
    target_review: str | None = None,
    session_note: str | None = None,
) -> str:
    files = (
        "decision-brief.md — scenario result, owner and required next checks",
        "decision-journal.csv — recommendation, rejected options, decision basis and next approval gate",
        "sku-response-register.csv — one decision row per affected SKU",
        "incident-action-register.csv — priority, owner, service clock and closure evidence per affected SKU",
        "incident-playbook.csv — selected trigger, service levels, escalation, rollback and closure controls",
        "incident-timeline.csv — event-to-recovery stages, latency, owners and service-clock status",
        "selected-supplier-routes.geojson — screening routes for suppliers in the selected origin",
        "evidence-manifest.csv — row counts, byte counts and SHA-256 hashes",
        "README-assumptions.md — this inventory and the model boundaries",
    )
    inventory = "\n".join(f"- `{item.split(' — ')[0]}` — {item.split(' — ')[1]}" for item in files)
    limits = "\n".join(f"- {limit}" for limit in EVIDENCE_LIMITATIONS)
    return f"""# Evidence pack: {country} supplier-origin disruption

## Contents

{inventory}

## Handoff record

- **Status:** {_handoff_text(status)}
- **Target review:** {_handoff_text(target_review)}
- **Session note:** {_handoff_text(session_note)}

## Assumptions and limitations

{limits}

The selected route layer contains geographic proximity evidence only. A line
does not prove that a shipment used that path or node. The SKU register names
candidate validation work; it does not assert that an alternate can absorb
volume. Review the manifest before relying on the pack so each result can be
traced to the exact source bytes used to generate it.

Manifest byte counts and hashes use canonical UTF-8 text with LF line endings,
so source-control newline conversion does not change the evidence identity.
"""


def _zip_member(name: str, text: str) -> tuple[ZipInfo, bytes]:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.extra = b""
    info.comment = b""
    return info, text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def build_evidence_pack(
    country: str,
    sourcing: pd.DataFrame,
    suppliers: pd.DataFrame,
    products: pd.DataFrame,
    concentration: pd.DataFrame,
    scorecard: pd.DataFrame,
    routes: pd.DataFrame,
    route_geojson: Mapping[str, object],
    manifest: pd.DataFrame,
    minimum_alternate_score: float = 0,
    recovery_window_days: int = 30,
    owner: str = "Cross-functional risk review",
    status: str | None = None,
    target_review: str | None = None,
    session_note: str | None = None,
    selected_sku: str | None = None,
) -> bytes:
    """Build a byte-reproducible, in-memory ZIP for one origin scenario.

    The pack includes a decision brief, decision journal, action register,
    incident playbook, event-to-recovery timeline, SKU register, selected route
    GeoJSON, source manifest and assumptions README. It contains no invented route,
    capacity or throughput data and performs no filesystem writes. Optional
    handoff metadata is embedded in the existing brief and assumptions README.
    ``selected_sku`` may identify one affected exception to foreground in the
    brief; it must exist in the generated scenario register. Omitting these
    fields preserves the previous call signature. ZIP members use canonical
    UTF-8/LF text, fixed metadata and ``ZIP_STORED`` so the same inputs produce
    the same archive bytes.
    """

    _require(routes, {"supplier_id", "supplier_country"}, "route summary")
    _require(
        manifest,
        {"path", "format", "rows_or_features", "bytes", "sha256"},
        "evidence manifest",
    )
    portfolio = build_country_scenario_portfolio(
        sourcing,
        suppliers,
        products,
        concentration,
        scorecard,
        minimum_alternate_score,
        recovery_window_days,
    )
    selected_summary = portfolio[portfolio["country"].eq(country)]
    if selected_summary.empty:
        raise ValueError(f"country is not present in the governed supplier data: {country}")
    scenario = selected_summary.iloc[0].to_dict()
    response = country_disruption(
        country,
        sourcing,
        suppliers,
        products,
        concentration,
        scorecard,
        minimum_alternate_score,
        recovery_window_days,
    )
    selected_exception: Mapping[str, object] | None = None
    if selected_sku is not None:
        selected = response[response["sku"].astype(str).eq(str(selected_sku))]
        if selected.empty:
            raise ValueError(
                f"selected SKU is not affected by the {country} scenario: {selected_sku}"
            )
        selected_exception = selected.iloc[0].to_dict()
    ordered = response.assign(
        _priority=response["decision_status"]
        .eq("No qualified alternate")
        .map({True: 0, False: 1})
    ).sort_values(["_priority", "cogs", "sku"], ascending=[True, False, True])
    sku_csv = ordered[list(_SKU_EXPORT_COLUMNS)].to_csv(index=False, lineterminator="\n")

    incident_type = "Supplier outage"
    scenario_name = f"{country} supplier-origin disruption"
    playbook = incident_playbook_catalogue().query(
        "incident_type == @incident_type"
    )
    timeline = event_to_action_timeline(incident_type, scenario_name)
    action_register = incident_action_register(
        response, incident_type, scenario_name
    )
    decision_journal = controlled_decision_journal(
        action_register, incident_type, scenario_name
    )

    selected_supplier_ids = routes.loc[
        routes["supplier_country"].eq(country), "supplier_id"
    ].astype(int)
    if selected_supplier_ids.empty:
        raise ValueError(f"no published supplier route is available for country: {country}")
    selected_geojson = _selected_route_geojson(route_geojson, selected_supplier_ids)
    manifest_csv = (
        manifest.sort_values("path")
        .reset_index(drop=True)
        .to_csv(index=False, lineterminator="\n")
    )

    entries = {
        "README-assumptions.md": _evidence_readme(
            country, status, target_review, session_note
        ),
        "decision-brief.md": _decision_brief(
            country,
            scenario,
            owner,
            status,
            target_review,
            session_note,
            selected_exception,
        ),
        "decision-journal.csv": decision_journal.to_csv(index=False, lineterminator="\n"),
        "evidence-manifest.csv": manifest_csv,
        "incident-action-register.csv": action_register.to_csv(index=False, lineterminator="\n"),
        "incident-playbook.csv": playbook.to_csv(index=False, lineterminator="\n"),
        "incident-timeline.csv": timeline.to_csv(index=False, lineterminator="\n"),
        "selected-supplier-routes.geojson": selected_geojson,
        "sku-response-register.csv": sku_csv,
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_STORED) as archive:
        archive.comment = b""
        for name in sorted(entries):
            info, payload = _zip_member(name, entries[name])
            archive.writestr(info, payload)
    return buffer.getvalue()
