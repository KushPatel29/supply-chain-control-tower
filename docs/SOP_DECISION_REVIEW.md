# S&OP challenge: preserve both service priorities within the stock ceiling

Run `python analytics/sop_review.py` and inspect the
[reconciled decision packet](../analytics/output/sop_review.json).

The input is the existing service-economics output, not a new invented forecast.
Finance holds the stock-investment ceiling constant; Commercial requires neither
unit fill nor revenue-weighted fill to fall below the current policy. The
challenge compares all four alternatives at the same modelled investment.

This exposes a useful conflict: the policy optimal for units improves unit fill
but reduces revenue-weighted fill. A familiar ABC ladder also fails the unit
floor. The revenue objective meets both default floors and becomes a conditional
candidate. If the requested combination is infeasible, the tool returns no
candidate; it never lowers a target silently.

The packet routes assumptions to Commercial, Supply Planning and Finance, names
the unresolved capacity/lot-life/lead-time checks and retains execution approval
as false. This is a runnable synthetic planning review, not evidence of a real
S&OP meeting, SAP use, vendor negotiation or purchase-order execution.
