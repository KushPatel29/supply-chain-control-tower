-- =====================================================================
-- Gold layer star schema — Supply Chain Control Tower
-- Target: Microsoft Fabric Warehouse (T-SQL). Run in the Warehouse SQL
-- editor after the Silver->Gold notebook has landed curated Delta tables,
-- or adapt as CREATE TABLE AS SELECT (CTAS) against the Lakehouse.
-- =====================================================================

-- ---------- Dimensions ----------

CREATE TABLE dim_product (
    product_key      INT           NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    product_id       INT           NOT NULL,
    sku              VARCHAR(20)   NOT NULL,
    product_name     VARCHAR(100)  NOT NULL,
    category         VARCHAR(50)   NOT NULL,
    subcategory      VARCHAR(50)   NOT NULL,
    shelf_life_days  INT           NOT NULL,
    unit_of_measure  VARCHAR(10)   NOT NULL,
    unit_cost        DECIMAL(10,2) NOT NULL,
    unit_price       DECIMAL(10,2) NOT NULL
);

CREATE TABLE dim_supplier (
    supplier_key     INT          NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    supplier_id      INT          NOT NULL,
    supplier_name    VARCHAR(100) NOT NULL,
    region           VARCHAR(50)  NOT NULL
);

CREATE TABLE dim_warehouse (
    warehouse_key    INT          NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    warehouse_id     INT          NOT NULL,
    warehouse_name   VARCHAR(100) NOT NULL,
    region           VARCHAR(50)  NOT NULL,
    city             VARCHAR(100) NOT NULL
);

CREATE TABLE dim_customer (
    customer_key     INT          NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    customer_id      INT          NOT NULL,
    customer_name    VARCHAR(100) NOT NULL,
    channel          VARCHAR(20)  NOT NULL,   -- Retail / Foodservice / Wholesale
    region           VARCHAR(50)  NOT NULL
);

CREATE TABLE dim_lot (
    lot_key          INT  NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    lot_id           INT  NOT NULL,
    product_key      INT  NOT NULL,
    supplier_key     INT  NOT NULL,
    warehouse_key    INT  NOT NULL,
    production_date  DATE NOT NULL,
    received_date    DATE NOT NULL,
    expiry_date      DATE NOT NULL
);

CREATE TABLE dim_date (
    date_key         INT  NOT NULL PRIMARY KEY NONCLUSTERED NOT ENFORCED,
    full_date        DATE NOT NULL,
    year             INT  NOT NULL,
    quarter          INT  NOT NULL,
    month            INT  NOT NULL,
    month_name       VARCHAR(10) NOT NULL,
    week_of_year     INT  NOT NULL,
    day_of_week_name VARCHAR(10) NOT NULL
);

-- ---------- Facts ----------

-- Grain: one row per lot per warehouse per snapshot date
CREATE TABLE fact_inventory (
    date_key          INT NOT NULL,
    lot_key           INT NOT NULL,
    product_key       INT NOT NULL,
    warehouse_key     INT NOT NULL,
    qty_on_hand       DECIMAL(12,2) NOT NULL,
    days_until_expiry INT NOT NULL,
    expiry_risk_flag  VARCHAR(10) NOT NULL,   -- 'Critical' <=2d, 'Warning' <=5d, 'OK'
    inventory_value   DECIMAL(14,2) NOT NULL  -- qty_on_hand * unit_cost, resolved at load time
);

-- Grain: one row per order line
CREATE TABLE fact_orders (
    date_key         INT NOT NULL,     -- order date
    order_id         INT NOT NULL,
    customer_key     INT NOT NULL,
    product_key      INT NOT NULL,
    lot_key          INT NOT NULL,
    warehouse_key    INT NOT NULL,
    qty_ordered      DECIMAL(12,2) NOT NULL,
    qty_shipped      DECIMAL(12,2) NOT NULL,
    fill_rate        DECIMAL(6,4)  NOT NULL,  -- qty_shipped / qty_ordered
    promised_date    DATE NOT NULL,
    shipped_date     DATE NOT NULL,
    otif_flag        BIT NOT NULL,            -- 1 = shipped on/before promised date AND fill_rate >= 0.98
    revenue          DECIMAL(14,2) NOT NULL,  -- qty_shipped * unit_price
    cogs             DECIMAL(14,2) NOT NULL,  -- qty_shipped * unit_cost
    gross_margin     DECIMAL(14,2) NOT NULL   -- revenue - cogs
);

-- ---------- Notes ----------
-- * Surrogate keys (*_key) are populated by the Silver->Gold notebook using
--   monotonically_increasing_id() or a hash of the natural key; natural keys
--   (*_id) are retained for traceability/debugging.
-- * NOT ENFORCED constraints are used because Fabric Warehouse does not
--   enforce PK/FK; they exist purely to document intent and let Power BI's
--   auto-detect relationships and query optimizer use them.
