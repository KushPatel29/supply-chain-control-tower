"""
Data contract enforcement — the boundary between "their system" and ours.

In a multi-team company the data platform doesn't control the source
systems: an ERP upgrade can rename a column on a Tuesday and say nothing.
The contract (contracts/bronze_v1.json) is the version-controlled agreement
about what the sources deliver, checked BEFORE anything is written to
Bronze, with the two semantics that matter:

  * additive change  -> allowed. New columns are logged and flow through;
                        downstream simply doesn't select them yet.
  * breaking change  -> fatal, pre-Bronze. A missing contracted column or a
                        type drift (integer -> string) stops the run with
                        exit code 3 before it can poison the lake.

This is deliberately a different failure class from the DQ gate: the gate
judges the *content* of a structurally valid build; the contract rejects
*structural* drift before a single row lands.
"""

import json
from pathlib import Path

import pandas as pd

CONTRACT_FILE = Path(__file__).resolve().parent.parent / "contracts" / "bronze_v1.json"

# pandas dtype kinds acceptable for each contracted logical type
_ACCEPTABLE_KINDS = {
    "integer": set("iu"),
    "number": set("iuf"),      # widening int -> float is not a break
    "string": set("O"),
    "boolean": set("b"),
}


def load_contract(path: Path = CONTRACT_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_table(df: pd.DataFrame, table_name: str, contract: dict) -> dict:
    """Returns {'breaking': [...], 'additive': [...]} for one landed table."""
    spec = contract["tables"].get(table_name)
    if spec is None:
        return {"breaking": [f"table '{table_name}' has no contract"], "additive": []}

    breaking, additive = [], []
    for col, logical_type in spec.items():
        if col not in df.columns:
            breaking.append(f"{table_name}.{col}: contracted column missing")
            continue
        kind = df[col].dtype.kind
        if kind not in _ACCEPTABLE_KINDS[logical_type]:
            breaking.append(
                f"{table_name}.{col}: type drift — contract says {logical_type}, "
                f"received dtype kind '{kind}'")
    for col in df.columns:
        if col not in spec:
            additive.append(f"{table_name}.{col}: new column (allowed, not yet consumed)")
    return {"breaking": breaking, "additive": additive}


def enforce(tables: dict[str, pd.DataFrame], contract: dict | None = None) -> dict:
    """Validate every landed table. Returns the full violation report;
    caller decides what a breaking violation costs (the batch pipeline
    aborts pre-Bronze; the stream rejects the single file)."""
    contract = contract or load_contract()
    report = {"version": contract["version"], "breaking": [], "additive": []}
    for name, df in tables.items():
        result = check_table(df, name, contract)
        report["breaking"] += result["breaking"]
        report["additive"] += result["additive"]
    return report
