"""
Reference data for the synthetic retail chain the control tower watches.

Everything the generator needs to invent a believable business lives here as plain
data, so the shape of the demo company can be inspected and changed without reading
generator code.

The company is **Northgate Retail Canada** - a mass-retail chain running its own
distribution network. Stores are the demand points, distribution centres and vendors
are the supply, and regional managers own the store book. Money is in CAD.

Why a retail chain rather than a food distributor
-------------------------------------------------
The control tower's questions - expiry risk, on-time-in-full, sourcing
concentration, safety stock, supplier quality - are the same either way. A retail
chain makes them harder in the way that matters: half the catalogue has a clock on
it (produce measured in days, dairy in weeks) and half does not (an air fryer keeps
until someone buys it), so the same network has to run two inventory disciplines at
once. FEFO where there is a shelf life; markdown risk where there is not.

Departments carry the commercial behaviour: what a selling unit costs, how it is
marked up, how much of it survives to full price, when in the year it sells, and
how often a replenishment line cannot be filled complete.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Department:
    """A merchandising department and how it behaves commercially."""

    name: str
    # Typical landed cost per selling unit - a kilogram for weighed departments,
    # an each for the rest - and the spread it is marked up at.
    unit_cost: float
    markup: float
    # Share of items sold by weight rather than by each. Fresh is nearly all scale;
    # electronics is none of it.
    weighed_share: float
    # Share of units bought that are sold at a price that counts. Fresh loses it to
    # shrink, apparel and seasonal lose it to markdown, packaged goods keep nearly
    # all of it.
    sell_through: float
    # Shelf life in days, drawn uniformly. General merchandise gets a long window
    # rather than none, so one FEFO model covers the whole catalogue and the
    # expiry-risk report simply never flags a kettle.
    shelf_life: tuple[int, int]
    # Multiplicative demand factor by calendar month (Jan..Dec).
    seasonality: tuple[float, ...]
    # Share of replenishment lines this department should attract.
    weight: float
    # Probability a line cannot be filled complete, and the share that typically
    # arrives when it is short. Fresh runs short because it is grown rather than
    # manufactured; seasonal runs short because the buy is committed months before
    # the demand is known.
    short_ship_rate: float
    typical_fill_when_short: float
    # Cold chain: which departments a refrigerated DC has to handle.
    temperature: str


# Two stories are planted deliberately, because a dashboard that finds nothing is
# not worth looking at:
#
#   Electronics is a large share of revenue at the thinnest margin in the chain, so
#   it drags blended margin down while looking like a growth engine on a revenue
#   chart.
#
#   Apparel and Toys & Seasonal have the worst sell-through, which is a markdown
#   problem rather than a demand problem: it shows up in margin and in the SKU
#   watchlist, not in the sales line.
DEPARTMENTS: tuple[Department, ...] = (
    Department("Grocery", 3.20, 1.26, 0.02, 0.985, (120, 540),
               (0.97, 0.94, 0.99, 1.00, 1.02, 1.03, 1.04, 1.03, 1.00, 1.01, 1.08, 1.14),
               0.22, 0.018, 0.80, "Ambient"),
    Department("Fresh & Produce", 2.10, 1.38, 0.78, 0.88, (3, 12),
               (0.90, 0.89, 0.95, 1.01, 1.10, 1.18, 1.22, 1.19, 1.06, 0.98, 0.96, 1.02),
               0.15, 0.115, 0.62, "Chilled"),
    Department("Dairy & Frozen", 3.05, 1.27, 0.06, 0.960, (14, 120),
               (0.95, 0.93, 0.97, 1.00, 1.05, 1.12, 1.16, 1.12, 1.01, 0.97, 0.98, 1.06),
               0.13, 0.035, 0.75, "Frozen"),
    Department("Meat & Seafood", 6.40, 1.30, 0.85, 0.910, (4, 16),
               (0.88, 0.87, 0.94, 1.02, 1.14, 1.22, 1.26, 1.18, 1.02, 0.96, 0.96, 1.08),
               0.11, 0.072, 0.68, "Chilled"),
    Department("Health & Wellness", 7.80, 1.42, 0.00, 0.990, (365, 900),
               (1.12, 1.06, 1.00, 0.97, 0.95, 0.94, 0.94, 0.98, 1.02, 1.04, 1.00, 0.98),
               0.09, 0.026, 0.78, "Ambient"),
    Department("Household Essentials", 5.10, 1.31, 0.00, 0.990, (540, 1095),
               (1.02, 0.98, 1.02, 1.03, 1.02, 1.00, 0.99, 1.00, 1.01, 1.00, 0.98, 0.95),
               0.09, 0.022, 0.82, "Ambient"),
    Department("Apparel", 9.50, 1.72, 0.00, 0.820, (900, 1095),
               (0.82, 0.86, 1.06, 1.14, 1.06, 0.96, 0.92, 1.16, 1.12, 0.94, 0.98, 1.10),
               0.06, 0.058, 0.70, "Ambient"),
    Department("Electronics", 84.00, 1.14, 0.00, 0.940, (900, 1095),
               (0.86, 0.82, 0.88, 0.90, 0.92, 0.94, 0.96, 1.02, 1.00, 1.02, 1.46, 1.42),
               0.05, 0.094, 0.55, "Ambient"),
    Department("Home & Kitchen", 14.50, 1.55, 0.00, 0.930, (900, 1095),
               (0.94, 0.90, 0.98, 1.04, 1.10, 1.06, 1.00, 0.98, 1.02, 1.02, 1.06, 1.14),
               0.06, 0.040, 0.74, "Ambient"),
    Department("Toys & Seasonal", 11.00, 1.48, 0.00, 0.790, (540, 1095),
               (0.62, 0.60, 0.72, 0.86, 0.92, 1.06, 1.02, 0.94, 0.90, 1.06, 1.72, 2.10),
               0.04, 0.132, 0.58, "Ambient"),
)

# Item types per department, paired with a brand tier and a pack size to build SKU
# names.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Grocery": ("Breakfast Cereal", "Pasta", "Cooking Oil", "Canned Soup", "Snack Crackers",
                "Coffee", "Bottled Water", "Soda 12pk", "Rice", "Baking Mix", "Condiments",
                "Baby Formula"),
    "Fresh & Produce": ("Bananas", "Apples", "Salad Greens", "Tomatoes", "Berries", "Potatoes",
                        "Citrus", "Avocados", "Onions", "Fresh Herbs"),
    "Dairy & Frozen": ("Whole Milk", "Shredded Cheese", "Greek Yogurt", "Butter", "Ice Cream",
                       "Frozen Pizza", "Frozen Vegetables", "Eggs", "Frozen Entree"),
    "Meat & Seafood": ("Ground Beef", "Chicken Breast", "Pork Chops", "Bacon", "Salmon Fillet",
                       "Shrimp", "Deli Turkey", "Ribeye Steak", "Rotisserie Chicken"),
    "Health & Wellness": ("Pain Relief", "Vitamins", "Shampoo", "Toothpaste", "Cold & Flu",
                          "Skin Care", "Allergy Relief", "First Aid", "Razors"),
    "Household Essentials": ("Laundry Detergent", "Paper Towels", "Bath Tissue", "Dish Soap",
                             "Trash Bags", "Surface Cleaner", "Air Freshener", "Food Storage"),
    "Apparel": ("Mens Tee", "Womens Denim", "Kids Hoodie", "Socks 6pk", "Activewear Legging",
                "Sleepwear Set", "Work Boot", "Baby Onesie", "Winter Jacket"),
    "Electronics": ("4K Smart TV", "Bluetooth Headphones", "Tablet", "Streaming Stick",
                    "Wireless Router", "Game Console", "Smart Watch", "Portable Speaker"),
    "Home & Kitchen": ("Bath Towel Set", "Bed Sheet Set", "Cookware Set", "Air Fryer",
                       "Storage Bin", "Table Lamp", "Area Rug", "Coffee Maker"),
    "Toys & Seasonal": ("Building Blocks", "Action Figure", "Board Game", "Ride-On Toy",
                        "Patio Chair", "String Lights", "Cooler", "Artificial Tree", "Beach Set"),
}

# A private-label ladder is most of how a mass retailer defends margin, so the demo
# has one: "Northgate Value" opens the price, "Northgate Select" tops it.
BRAND_TIERS: tuple[tuple[str, float], ...] = (
    ("Northgate Value", 0.78), ("Everyday Basics", 0.88), ("National Brand", 1.00),
    ("Northgate Select", 1.14), ("Premium Label", 1.28), ("Exclusive Brand", 1.06),
)

PACK_SIZES: tuple[tuple[str, float], ...] = (
    ("Single", 1.0), ("2-Pack", 1.8), ("Family Size", 2.4), ("Club Pack", 4.2),
    ("Travel Size", 0.5), ("Value Bundle", 3.1), ("Multipack", 2.6),
)


@dataclass(frozen=True)
class Region:
    name: str
    # Share of stores in this region.
    weight: float
    # Typical transit days from the serving distribution centre, and how much of the
    # region's volume moves on the third-party lane that runs late.
    transit_days: float
    third_party_share: float
    cities: tuple[str, ...]


# The network is Canadian: the row-level security roles, the GIS layer and the
# regional-manager story are all keyed on these five regions.
REGIONS: tuple[Region, ...] = (
    Region("BC Lower Mainland", 0.26, 1.0, 0.06, ("Vancouver", "Surrey", "Burnaby", "Richmond", "Coquitlam")),
    Region("BC Interior", 0.14, 2.5, 0.34, ("Kelowna", "Kamloops", "Prince George", "Nelson", "Vernon")),
    Region("Alberta", 0.22, 2.0, 0.12, ("Calgary", "Edmonton", "Red Deer", "Lethbridge", "Grande Prairie")),
    Region("Ontario", 0.26, 3.0, 0.18, ("Toronto", "Ottawa", "Hamilton", "London", "Sudbury")),
    Region("Quebec", 0.12, 3.5, 0.28, ("Montreal", "Quebec City", "Laval", "Gatineau", "Sherbrooke")),
)


@dataclass(frozen=True)
class StoreFormat:
    """How a store format behaves: order size, cadence and price position."""

    name: str
    weight: float
    orders_per_month: float
    lines_per_order: float
    # Multiplier on list price - clubs and online run leaner - and on order quantity.
    price_index: float
    size_index: float


STORE_FORMATS: tuple[StoreFormat, ...] = (
    StoreFormat("Supercentre", 0.34, 5.2, 7.0, 1.00, 3.20),
    StoreFormat("Neighbourhood Market", 0.22, 6.0, 5.5, 1.01, 1.30),
    StoreFormat("Discount Store", 0.15, 4.2, 6.5, 0.99, 1.80),
    StoreFormat("Club Warehouse", 0.09, 3.4, 8.0, 0.88, 6.40),
    StoreFormat("Express", 0.09, 6.8, 3.2, 1.04, 0.55),
    StoreFormat("Online Fulfilment Centre", 0.07, 8.5, 8.0, 0.94, 4.10),
    StoreFormat("Pickup & Delivery Hub", 0.04, 7.2, 4.5, 0.98, 0.90),
)

# Store-name vocabulary. Names read as "<locality> <format-ish>", which is how store
# lists actually look once a chain has grown by acquisition.
STORE_FIRST: tuple[str, ...] = (
    "Northgate", "Cedar Park", "Lakeview", "Riverbend", "Highland", "Fairview", "Oakmont",
    "Summit", "Brookfield", "Stonegate", "Westfield", "Ridgeway", "Meadowbrook", "Ironwood",
    "Clearwater", "Fox Run", "Harvest Point", "Silver Lake", "Prairie View", "Kingsport",
    "Bayside", "Granite Falls", "Willow Creek", "Copper Ridge", "Maple Grove", "Redbud",
    "Sunfield", "Trailside", "Union Square", "Vista Park", "Glenmore", "Birchwood",
)
STORE_SECOND: tuple[str, ...] = (
    "Supercentre", "Market", "Crossing", "Commons", "Town Centre", "Plaza", "Marketplace",
    "Village", "Station", "Landing", "Square", "Junction", "Gateway", "Exchange", "Depot",
    "Pointe", "Centre",
)

# Vendor naming. CPG-flavoured, so a vendor scorecard reads like a real one.
SUPPLIER_PREFIXES: tuple[str, ...] = (
    "Crestline", "Harborview", "Kingsford", "Silverbrook", "Ridgemont", "Northwind",
    "Copper Creek", "Stonebridge", "Alderwood", "Blackpine", "Sandhill", "Grayrock",
    "Elkhorn", "Bayfield", "Windrow", "Thornbury", "Larkspur", "Fairmont", "Redstone",
    "Brightwater", "Cascadia", "Maplewood", "Ironvale", "Whitecourt",
)
SUPPLIER_SUFFIXES: tuple[str, ...] = (
    "Brands", "Consumer Products", "Foods", "Home Goods", "Distribution", "Manufacturing",
    "Supply Co", "Industries", "Global", "Partners",
)

# Distribution centres. A retail network runs three kinds, and which one a
# department lands in is what makes cold-chain capacity a constraint rather than a
# detail.
DC_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ambient DC", ("Ambient",)),
    ("Cold Chain DC", ("Chilled", "Frozen")),
    ("Cross-Dock", ("Ambient", "Chilled", "Frozen")),
)
