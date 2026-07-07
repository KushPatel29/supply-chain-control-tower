# Power BI Build Guide — Supply Chain Control Tower

Two ways to build this depending on where you are in the setup:

- **Path A — Fabric-connected** (do this once your Fabric trial workspace has run notebooks 01-04): connect Power BI Desktop straight to the Gold Lakehouse tables. This is the "real" version and what your portfolio should ultimately show.
- **Path B — Local fallback**: import directly from `data/bronze/*.csv` and replicate the Silver/Gold logic in Power Query, so you can start building the report today without waiting on Fabric provisioning. Swap to Path A later without rebuilding the report — just repoint each table's source.

## 1. Connect to data

**Path A:** Power BI Desktop → Get Data → More → Fabric → Lakehouses → select your workspace → select the `gold` schema tables (`dim_product`, `dim_supplier`, `dim_warehouse`, `dim_customer`, `dim_lot`, `dim_date`, `fact_inventory`, `fact_orders`, `dq_log`) → Import mode (not DirectQuery, so DAX runs fast on a laptop-sized model).

**Path B:** Get Data → Text/CSV → import each file from `data/bronze/`. You'll be missing the surrogate keys and calculated columns (`days_until_expiry`, `otif_flag`, `revenue`, etc.) — recreate them as Power Query calculated columns using the same logic as `notebooks/02_silver_transform.py` and `03_gold_curate.py` (the transformations are simple enough to port 1:1 to M/DAX for this fallback).

## 2. Build the star schema relationships

In Model view, create these relationships (all single-direction, dimension → fact):

| From | To | Cardinality |
|---|---|---|
| dim_product[product_key] | fact_orders[product_key] | 1:* |
| dim_product[product_key] | fact_inventory[product_key] | 1:* |
| dim_customer[customer_key] | fact_orders[customer_key] | 1:* |
| dim_warehouse[warehouse_key] | fact_orders[warehouse_key] | 1:* |
| dim_warehouse[warehouse_key] | fact_inventory[warehouse_key] | 1:* |
| dim_lot[lot_key] | fact_orders[lot_key] | 1:* |
| dim_lot[lot_key] | fact_inventory[lot_key] | 1:* |
| dim_date[date_key] | fact_orders[date_key] | 1:* |
| dim_date[date_key] | fact_inventory[date_key] | 1:* |

Mark `dim_date` as a **Date table** (Model view → right-click dim_date → Mark as date table).

## 3. Add the measure table

Create a blank query with no rows named `_Measures` (Home → Enter Data → 0 columns → name it `_Measures`), hide it from Report view, then paste in every measure from [`dax_measures.dax`](dax_measures.dax). Keeping measures in a dedicated table instead of scattered on fact tables is the standard "governed semantic model" pattern — call this out explicitly in your project README/demo, it's exactly the kind of practice a hiring manager is screening for.

## 4. Build report pages

1. **Executive Overview** — KPI cards: Total Revenue, Gross Margin %, OTIF %, % Inventory at Risk. Trend line of Revenue and Gross Margin % by week. Slicers: region, channel, date range.
2. **Inventory & Expiry Risk** — Matrix of Qty On Hand / Inventory Value by product & warehouse, conditional-formatted by `expiry_risk_flag`. Card for Critical Expiry Value. Table drillthrough to lot-level detail (lot_id, expiry_date, days_until_expiry) — this is the lot-traceability story from your resume made clickable.
3. **Fulfillment (OTIF)** — OTIF % and Avg Fill Rate by customer/channel/warehouse, with a trend line and a "late orders" table filtered to `otif_flag = 0` for root-cause drill-in.
4. **Data Quality** — Simple table/card view of `dq_log`: DQ Pass Rate, and a list of any failed checks with their detail message. This turns notebook 04 into something visual instead of just console output.

## 5. Row-Level Security (RLS)

1. Add a small `security_mapping` table (email, region) — one row per test user, e.g. `you@example.com, BC Lower Mainland`.
2. Modeling → Manage Roles → New role `Sales - Regional`. Add this filter on **dim_customer**:
   ```dax
   [region] = LOOKUPVALUE(security_mapping[region], security_mapping[email], USERPRINCIPALNAME())
   ```
3. This makes Sales users see only their region's orders/margin, while Finance/Ops roles can be left unfiltered — matches the "Sales/Finance/Operations see only authorized margin and inventory data" line from your resume.
4. Test it: Modeling → View As → pick the role → confirm the report filters down correctly.

## 6. Column-level security (bonus, differentiator)

Power BI Desktop's UI doesn't expose column-level/object-level security directly — you need the free **Tabular Editor 2** (external tool, installs alongside Power BI Desktop). Open your model in Tabular Editor → select `fact_orders[cogs]` and `fact_orders[gross_margin]` → set **Object Level Security** so a "Sales - Restricted" role can't see cost/margin columns at all, only revenue. Document this with a screenshot in your README — it's a genuinely advanced skill most BI portfolios skip.

## 7. Publish

Publish to the Power BI Service (free workspace is fine) → get a shareable link (or embed via "Publish to web" **only** if the data is 100% synthetic, which it is here) → put the link in your repo README and resume.
