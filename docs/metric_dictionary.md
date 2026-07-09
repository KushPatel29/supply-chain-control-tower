# Metric Dictionary — Supply Chain Control Tower

The governance artifact that turns "we built some dashboards" into "we run
a governed semantic layer." Every measure exposed to report consumers is
defined once, here, with an owner, grain, and refresh expectation — the
Power BI model implements these definitions, it does not invent its own.

| # | Metric | Definition | Formula / source | Grain | Owner (role) | Refresh SLA |
|---|--------|------------|------------------|-------|--------------|-------------|
| 1 | Total Revenue | Value of goods shipped, at order-line price | `SUM(qty_shipped × unit_price)` from `gold.fact_orders` | Order line | Finance | Daily 6am |
| 2 | Gross Margin % | Margin after cost of goods, pre-opex | `(Revenue − COGS) / Revenue` | Order line | Finance | Daily 6am |
| 3 | OTIF % | Orders shipped on/before promised date **and** ≥95% fill | `otif_flag` computed in Silver (`02_silver_transform.py`) | Order | Supply Chain | Daily 6am |
| 4 | Fill Rate | Shipped quantity as share of ordered | `qty_shipped / qty_ordered` | Order line | Supply Chain | Daily 6am |
| 5 | Inventory Turns | Annualized sell-through of inventory | `(COGS / Avg Inventory Value) × (365 / days in period)` | Aggregate | Supply Chain | Weekly |
| 6 | Days on Hand | Days current inventory would last at current COGS run rate | `365 / Inventory Turns` | Aggregate | Supply Chain | Weekly |
| 7 | Expiry Risk Flag | Shelf-life urgency banding per lot snapshot | Critical ≤2 days, Warning ≤5 days, else OK — computed in Silver | Lot × snapshot | Operations | Weekly |
| 8 | % Inventory at Risk | Share of inventory value flagged Critical or Warning | `(Critical $ + Warning $) / Total Inventory $` | Aggregate | Operations | Weekly |
| 9 | Inventory Value | On-hand quantity valued at unit cost | `qty_on_hand × unit_cost` | Lot × snapshot | Finance | Weekly |
| 10 | DQ Pass Rate | Share of automated data-quality checks passing | `passed / total` from `gold.dq_log` | Pipeline run | Data team | Per run |

## Change control

- A metric definition changes only via a PR to this file **and** the
  matching DAX/notebook change in the same commit — definition and
  implementation never drift apart.
- Threshold constants (95% fill for OTIF, 2/5-day expiry bands, 0.5%
  variance tolerance) live in exactly one place each (Silver notebook or
  DAX measure) and are referenced here, not duplicated.

## Known definitional decisions (the "why" a stakeholder will ask about)

- **OTIF uses promised date, not requested date** — measures our
  reliability against what we committed, not what the customer wished for.
  Swap to requested-date OTIF if the business runs customer-scorecard
  negotiations on it.
- **Inventory Turns uses average inventory across snapshots**, not
  point-in-time — a single end-of-period snapshot over/understates turns
  when inventory is seasonal.
- **Revenue uses order-line price** (price at time of sale), not current
  product master price — historical reports must not change when prices do.
