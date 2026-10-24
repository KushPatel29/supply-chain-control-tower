"""Reconcile a synthetic S&OP policy challenge without authorizing execution."""

from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "analytics/output/service_policy_options.csv"


def review(rows: list[dict], min_units=None, min_revenue=None, budget=None) -> dict:
    if not rows or len({row["policy"] for row in rows}) != len(rows):
        raise ValueError("Unique, nonempty policy alternatives are required")
    current = next((row for row in rows if row["policy"] == "flat 95% (in force)"), None)
    if current is None:
        raise ValueError("The current policy is required for a comparable challenge")
    values = [{"policy": row["policy"], **{
        name: Decimal(str(row[name]))
        for name in ("safety_stock_value", "fill_units", "fill_revenue")
    }} for row in rows]
    for row in values:
        if not all(value.is_finite() for key, value in row.items() if key != "policy"):
            raise ValueError("Finite values are required")
        if row["safety_stock_value"] < 0 or not all(0 <= row[k] <= 1 for k in ("fill_units", "fill_revenue")):
            raise ValueError("Invalid stock investment or fill rate")
    baseline = next(row for row in values if row["policy"] == current["policy"])
    floors = {"fill_units": Decimal(str(min_units)) if min_units is not None else baseline["fill_units"],
              "fill_revenue": Decimal(str(min_revenue)) if min_revenue is not None else baseline["fill_revenue"]}
    cap = Decimal(str(budget)) if budget is not None else baseline["safety_stock_value"]
    if not cap.is_finite() or cap < 0 or any(not x.is_finite() or not 0 <= x <= 1 for x in floors.values()):
        raise ValueError("Invalid policy constraints")
    evaluated = []
    for row in values:
        failures = [name + " below agreed floor" for name, floor in floors.items() if row[name] < floor]
        if row["safety_stock_value"] > cap:
            failures.append("stock investment exceeds ceiling")
        evaluated.append({"policy": row["policy"], "eligible": not failures,
                          "reasons": failures, **{k: str(v) for k, v in row.items() if k != "policy"}})
    eligible = [row for row in values if next(x for x in evaluated if x["policy"] == row["policy"])["eligible"]]
    chosen = max(eligible, key=lambda r: (r["fill_revenue"], r["fill_units"], -r["safety_stock_value"], r["policy"])) if eligible else None
    return {
        "schema_version": 1,
        "classification": "synthetic_policy_challenge",
        "constraints": {"minimum_unit_fill": str(floors["fill_units"]),
                        "minimum_revenue_fill": str(floors["fill_revenue"]), "stock_ceiling": str(cap)},
        "alternatives": evaluated, "candidate": chosen["policy"] if chosen else None,
        "decision": "CONDITIONAL CANDIDATE" if chosen else "NO FEASIBLE CANDIDATE",
        "execution_approved": False,
        "required_owners": {"Commercial": "confirm unit/revenue service priorities and lost-sales assumptions",
                            "Supply planning": "validate lead-time, lot-life and capacity assumptions",
                            "Finance": "confirm stock investment ceiling and carrying-cost basis"},
        "unresolved": ["No completed stakeholder meeting or approval", "No ERP transaction or purchase order created",
                       "Modelled fill rates are not observed future service or guaranteed capacity"],
    }


def build() -> dict:
    with SOURCE.open(newline="", encoding="utf-8") as stream:
        result = review(list(csv.DictReader(stream)))
    result["source_sha256"] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    return result


if __name__ == "__main__":
    result = build()
    target = ROOT / "analytics/output/sop_review.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
