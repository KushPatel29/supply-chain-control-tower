"""
The page's opening sentence named a warehouse region that does not exist.

`Control Tower Insight` writes the executive overview's verdict line. It ranked
regions with `TOPN(1, VALUES(dim_warehouse[region]), [OTIF %], ASC)` and put the
winner into the sentence. What rendered was:

    OTIF 90.4% against a 95.0% target - 4.6 pts short.  is the weakest lane at ,
    and 22.8% of inventory value sits in the expiry window.

dim_warehouse holds ten rows and five regions, and every order line matches one
of them - so nothing in the data was wrong. The sixth member is the engine's:
the one side of a relationship carries a blank row for keys the many side might
not match, `VALUES()` returns it, its OTIF is BLANK, and BLANK sorts first
ascending. The ranking therefore chose the empty member every time, and the
FORMAT of a blank is an empty string, so the defect rendered as two gaps in a
sentence rather than as an error anywhere.

Nothing in the suite could have caught it. The model binds correctly, the TMDL
parses, every measure reference resolves, and the figures either side of the
gap - 90.4%, 22.8% - are right. It is only visible in the rendered prose, which
is exactly the case the screenshot pass exists to find and exactly the case a
reader would notice first.

So this file holds the mechanism from both ends: no measure may rank a bare
`VALUES()` ascending, and the data may not quietly acquire a region the ranking
would have to skip.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
TABLES = next(ROOT.glob("powerbi/pbip/*.SemanticModel/definition/tables"))
BRONZE = ROOT / "data" / "bronze"

MEASURE_BODY = re.compile(
    r"^\tmeasure ('[^']+'|[^\s=]+).*?(?=^\t(?:measure|column|partition)\s|\Z)",
    re.M | re.S)
BARE_VALUES = re.compile(r"VALUES\s*\(\s*'?[\w ]+'?\[[^\]]+\]\s*\)")


def topn_arguments(body):
    """The top-level arguments of every TOPN call in a measure body.

    Split on brackets rather than with a regex: TOPN's second argument is
    itself a function call, so a comma-separated pattern captures the source
    and the ordering expression together and then matches neither. That is not
    a hypothetical - the first version of this test did exactly that, flagged
    nothing, and passed against the very measure it was written for.
    """
    calls = []
    for start in (m.end() for m in re.finditer(r"\bTOPN\s*\(", body)):
        depth, arg, args = 1, [], []
        for char in body[start:]:
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
                if depth == 0:
                    break
            if char == "," and depth == 1:
                args.append(" ".join("".join(arg).split()))
                arg = []
            else:
                arg.append(char)
        args.append(" ".join("".join(arg).split()))
        calls.append(args)
    return calls


def measures():
    """(name, body) for every measure in the semantic model."""
    for path in sorted(TABLES.glob("*.tmdl")):
        text = path.read_text(encoding="utf-8")
        for match in MEASURE_BODY.finditer(text):
            yield match.group(1).strip("'"), match.group(0)


def test_there_are_measures_to_read():
    """A glob that matches nothing passes every check below."""
    found = list(measures())
    assert len(found) > 20, f"only {len(found)} measures found - is the model there?"


def test_no_measure_ranks_a_bare_values_ascending():
    """The mechanism, stated as a rule.

    Ranking descending is safe: the blank member's BLANK measure sorts last and
    can only win when nothing else has a value. Ascending it wins outright, so
    every ascending rank over a column of a related table has to drop blanks
    before it sorts - `FILTER(ADDCOLUMNS(VALUES(...), ...), NOT ISBLANK(...))`,
    or the same shape spelled differently.
    """
    offenders = []
    for name, body in measures():
        for args in topn_arguments(body):
            ascending = any(arg.upper() == "ASC" for arg in args[2:])
            if ascending and len(args) > 1 and BARE_VALUES.fullmatch(args[1]):
                offenders.append(f"{name}: TOPN(..., {args[1]}, ..., ASC)")
    assert not offenders, (
        "ascending rankings that will select the relationship's blank member "
        f"and name it in prose: {offenders}")


def test_the_verdict_line_drops_blanks_before_it_ranks():
    """The fix itself, pinned where a future edit would undo it."""
    body = dict(measures())["Control Tower Insight"]
    assert "NOT ISBLANK([@otif])" in body, (
        "the region ranking no longer drops blanks, so the blank member is back "
        "in the running for weakest lane")
    assert "ISBLANK(vWorstRegion)" in body, (
        "nothing guards the sentence against an empty region name; a filter that "
        "leaves no region standing will render 'is the weakest lane at ,' again")


def otif_by_region():
    """[OTIF %] per region, from the CSVs and by the rule the model applies.

    `otif_flag` is not a column of the orders file: the fact_orders partition
    derives it in Power Query as shipped on or before the promise AND a fill
    rate of at least 95%. Re-deriving it here rather than reading a gold column
    keeps this test measuring what the report measures.
    """
    orders = pd.read_csv(BRONZE / "fact_orders.csv",
                         parse_dates=["promised_date", "shipped_date"])
    warehouses = pd.read_csv(BRONZE / "dim_warehouse.csv")
    on_time = orders.shipped_date <= orders.promised_date
    in_full = (orders.qty_shipped / orders.qty_ordered).round(4) >= 0.95
    orders = orders.assign(otif_flag=(on_time & in_full).astype(int))
    merged = orders.merge(warehouses[["warehouse_id", "region"]], on="warehouse_id")
    return merged.groupby("region").otif_flag.mean(), warehouses


def test_the_ranking_it_writes_names_a_region_that_exists():
    """The same question asked of the data rather than of the DAX.

    Reproduced from the CSVs the model reads, so it fails if the ranking's
    subject ever stops being derivable - an orders file that lost its warehouse
    key, or a promise date that stopped being comparable.
    """
    otif, warehouses = otif_by_region()
    worst = otif.idxmin()
    assert isinstance(worst, str) and worst.strip(), "the weakest lane has no name"
    assert worst in set(warehouses.region), f"{worst!r} is not a region of the network"
    assert 0 < otif.min() < 1


def test_every_region_of_the_network_can_be_ranked():
    """The cost of dropping blanks, held where it would bite.

    Skipping BLANK regions is right for the engine's phantom member and wrong
    for a real one: a region with distribution centres but no orders would now
    be excluded from the ranking rather than named as the worst lane in the
    network. That is a generator defect rather than a measure defect, so it is
    checked here, against the data, instead of being papered over in DAX.
    """
    orders = pd.read_csv(BRONZE / "fact_orders.csv")
    warehouses = pd.read_csv(BRONZE / "dim_warehouse.csv")
    served = set(warehouses[warehouses.warehouse_id.isin(orders.warehouse_id)].region)
    missing = sorted(set(warehouses.region) - served)
    assert not missing, (
        f"regions with a DC and no order lines: {missing} - the verdict line "
        "cannot rank them, so the worst-served regions in the network are the "
        "ones it will never name")


@pytest.mark.parametrize("column", ["warehouse_id", "promised_date", "shipped_date",
                                   "qty_ordered", "qty_shipped"])
def test_the_orders_file_still_carries_what_the_ranking_needs(column):
    """The inputs the OTIF rule reads. A rename upstream empties the measure
    rather than failing it, which is how this class of defect stays invisible."""
    assert column in pd.read_csv(BRONZE / "fact_orders.csv", nrows=1).columns
