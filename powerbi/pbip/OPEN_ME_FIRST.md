# How to open this Power BI Project

The semantic model is fully pre-built in code (TMDL): 9 tables with the
Silver-layer logic implemented in Power Query M, 10 relationships, 18 DAX
measures in a `_Measures` table, and an RLS role. You only build visuals.

## Steps

1. **Enable PBIP support** (one-time): Power BI Desktop → File → Options and
   settings → Options → Preview features → check **"Power BI Project (.pbip)
   save option"** → restart Desktop. (Recent versions have this on by
   default — if you don't see it in the list, it's already enabled.)
2. Double-click **`SupplyChainControlTower.pbip`**.
3. When the report opens (three empty named pages), click **Refresh** to
   load the CSVs into the model.
4. If you moved/cloned this repo somewhere else: Home → Transform data →
   Edit parameters → set **DataPath** to your local
   `...\supply-chain-control-tower\data\bronze` folder, then Refresh.

## Verify the model loaded

- Model view: star schema with fact_orders + fact_inventory in the middle.
- Data pane: `_Measures` table with 18 measures.
- Modeling → Manage roles: "Sales - BC Lower Mainland" role exists.
  Test with Modeling → View as → check that totals shrink to one region.

## Then build visuals per the build guide

Follow section 4 of [`../BUILD_GUIDE.md`](../BUILD_GUIDE.md) — the pages are
already created and named. Suggested first page (Executive Overview):

| Visual | Fields |
|---|---|
| 4 KPI cards | Total Revenue, Gross Margin %, OTIF %, % Inventory at Risk |
| Line chart | dim_date[full_date] on X, Total Revenue on Y |
| Slicers | dim_warehouse[region], dim_customer[channel] |

## If Desktop shows an error opening the project

Note the exact error text and file it mentions — the TMDL was authored by
hand, so a version-specific syntax quirk is possible; it's a quick fix.
