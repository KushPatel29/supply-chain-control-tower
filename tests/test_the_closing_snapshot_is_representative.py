"""The warehouse is stocked to the end of the window, so the as-of figure is fair.

This file used to be called `test_the_seed_drains_the_warehouse.py`, and it
measured a defect rather than an invariant. The old generator drew a lot's
production date from `SNAPSHOT_START + uniform(-30, 150)` while the snapshot window
ran to `SNAPSHOT_START + 180`, so for the final month orders consumed stock that
nothing replenished: SKU coverage fell from 53 to 16 and the closing week landed at
about 14% of a median one.

That mattered because inventory is measured **as of the latest snapshot**. Both
semi-additive measures resolved to that thin final week, so the number a reader saw
was real for its date and unrepresentative of the business - a defect that survives
every correctness test, because nothing about it is incorrect.

The retail rebuild fixed the cause: receipts now run on a cadence set by each SKU's
shelf life across the whole window, cold chain regionally and ambient nationally.
So the file keeps the same subject and flips the assertions. If a future generator
change re-introduces the drain, this fails and names the mechanism.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "lake" / "gold"

#: How thin the closing week may be, as a share of the trailing median, before a
#: reader would be misled by the as-of figure.
MIN_CLOSING_COVERAGE = 0.60


def _gold(name: str) -> pd.DataFrame:
    path = GOLD / f"{name}.parquet"
    if not path.is_file():
        pytest.skip(f"gold {name} not built")
    return pd.read_parquet(path)


def test_lots_are_still_being_received_when_the_orders_stop():
    """The mechanism, pinned from the other side."""
    lots = _gold("dim_lot")
    orders = _gold("fact_orders")

    last_lot = pd.to_datetime(lots["production_date"]).max()
    last_order = pd.to_datetime(orders["date_key"], format="%Y%m%d").max()
    gap_days = (last_order - last_lot).days

    assert gap_days <= 21, (
        f"{gap_days} days between the last receipt and the last order: the "
        "warehouse is draining again, and every as-of inventory figure will "
        "under-report the business"
    )


def test_the_closing_snapshot_covers_the_assortment():
    """The consequence: the closing week carries a normal spread of SKUs."""
    fact = _gold("fact_inventory")
    by_date = fact.groupby("date_key")["product_key"].nunique()
    closing, typical = by_date.iloc[-1], by_date.median()
    assert closing >= MIN_CLOSING_COVERAGE * typical, (
        f"the closing snapshot carries {closing} SKUs against a median week of "
        f"{typical}, so the inventory page is reading a truncated week"
    )


def test_the_closing_snapshot_represents_the_business():
    """The invariant the report actually needs.

    Both `Total Inventory Value` and `Qty On Hand` read the latest snapshot. For
    that to be a fair headline, the closing week has to look like a normal week.
    """
    fact = _gold("fact_inventory")
    weekly = fact.groupby("date_key")["inventory_value"].sum()
    closing, typical = weekly.iloc[-1], weekly.median()
    assert closing >= MIN_CLOSING_COVERAGE * typical, (
        f"the closing snapshot holds ${closing:,.0f} against a median week of "
        f"${typical:,.0f} ({closing / typical:.0%}), so every as-of card on the "
        "inventory page under-reports the business"
    )
