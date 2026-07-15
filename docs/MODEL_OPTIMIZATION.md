# Semantic model optimization — measured, then fixed

A VertiPaq-style storage profile of the semantic model, captured live from
Power BI Desktop's engine with the DAX `INFO.STORAGETABLECOLUMNS()` /
`INFO.STORAGETABLECOLUMNSEGMENTS()` functions (the same numbers VertiPaq
Analyzer reports), followed by the fix the profile demanded.

## The finding: auto date/time was 90% of column storage

Power BI's **auto date/time** feature silently creates a hidden calendar
table (`LocalDateTable_*`) plus a date-hierarchy *variation* for **every
date column in the model** — this model has six date columns, so it carried
six hidden calendars plus a template, despite already having a proper,
governed `dim_date`.

Measured before the fix (dictionary + hierarchy bytes per table):

| Object | Bytes | Share |
|---|---:|---:|
| 7 hidden `LocalDateTable_*` / `DateTableTemplate_*` tables | 40,416 | **90.5%** |
| All real tables combined (dims + facts) | 4,232 | 9.5% |

At this demo size that's kilobytes; the *ratio* is the point. Every date
column added to a fact table would spawn another ~7k-row hidden calendar —
at 100M-row scale with wide date-heavy facts, auto date/time routinely adds
hundreds of MB of pure duplication and slows every refresh.

## The fix (applied in this repo, verified in Desktop)

1. `__PBI_TimeIntelligenceEnabled = 0` in `model.tmdl` (disables the feature).
2. Deleted the 7 hidden table definitions; stripped every `variation` block
   and the six auto-generated relationships that referenced them.
3. Time intelligence is provided properly instead: `dim_date` is **marked as
   the date table** (`dataCategory: Time` + key column) and the
   **`Time Intelligence` calculation group** (Current / MTD / QTD / YTD /
   Previous Month / MoM % / Rolling 28D) supplies period logic for *every*
   measure — 7 calculation items instead of 19 measures x 7 variants.

Result: the model reopens and refreshes cleanly, auto date/time storage is
**zero**, and period switching is a slicer instead of a measure explosion.

## Other optimizations this model already carries

- Facts join dims on integer surrogate keys (`date_key`, `product_key`, ...)
  — the highest-cardinality strings never leave the dimensions.
- Foreign-key columns and the `security_mapping` entitlement table are
  hidden from the field list; measures live in a dedicated `_Measures` table.
- No bi-directional relationships; RLS filters flow one direction from
  `dim_warehouse`.

Profile source data: [`vertipaq_profile.csv`](vertipaq_profile.csv).
