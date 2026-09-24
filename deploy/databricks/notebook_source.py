"""Turn the Fabric percent-format notebooks into Databricks notebook source.

Kept apart from run_on_databricks.py so the conversion can be tested without
the Databricks SDK installed.
"""
from __future__ import annotations

import re

NOTEBOOKS = ["01_bronze_ingest", "02_silver_transform", "03_gold_curate", "04_data_quality_checks"]
FABRIC_LANDING = 'LAKEHOUSE_FILES = "Files/bronze"'


def to_databricks_source(text: str, landing: str) -> str:
    """Percent-format script -> Databricks notebook source, with the landing path swapped."""
    assert text.count(FABRIC_LANDING) <= 1
    text = text.replace(FABRIC_LANDING, f'LAKEHOUSE_FILES = "{landing}"')
    out, cells = ["# Databricks notebook source"], re.split(r"^# %%", text, flags=re.M)
    for i, cell in enumerate(cells[1:]):
        if i:
            out.append("# COMMAND ----------")
        if cell.startswith(" [markdown]"):
            lines = [ln[2:] if ln.startswith("# ") else ln.lstrip("#") for ln in cell.splitlines()[1:]]
            out += ["# MAGIC %md"] + [f"# MAGIC {ln}".rstrip() for ln in lines]
        else:
            out.append(cell.strip("\n"))
    return "\n".join(out) + "\n"
