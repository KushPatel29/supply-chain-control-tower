# Network Risk Decision Room: Interview Playbook

Use this guide to demonstrate business-analysis judgement through the app. The
strongest story is not “I built a dashboard.” It is: **I turned an ambiguous
operational question into a governed, testable decision workflow.**

## Before the interview

- Open the app and leave **Country disruption** set to **Mexico**, minimum
  alternate score **0**, and recovery window **30 days**.
- Open **Node outage** in a second browser tab with **Ontario DC 1** selected.
- Confirm the **Evidence trail** publication gate passes before the call.
- Keep the repository, GIS analysis and test suite available as supporting
  evidence. Do not lead with code unless asked.
- Say at the start that the business records and coordinates are synthetic.

## Six-minute talk track

### 0:00–0:40 — Frame the decision

**Show:** the title, evidence boundary and four app tabs.

**Say:** “I started with a decision, not a map: if a sourcing origin or a
distribution node becomes unavailable, which products need attention first,
who owns the next check, and what evidence is safe to use? I translated that
into scenario rules, an exception register, acceptance controls and an export
that a stakeholder can act on.”

### 0:40–1:40 — Run the Mexico disruption

**Show:** Mexico selected with score floor 0 and a 30-day recovery window.

**Say:** “Mexico is the largest modeled origin: four suppliers touch 36 SKUs
and represent **$11,821,992.49**, or **27.24%**, of award-weighted network COGS.
The qualified-alternate rule leaves **13 SKUs without an eligible external
source**. Of the remaining 23, only **7 fit a 30-day recovery window**; their
mean best contract lead is **31.7 days**. This converts a broad country-risk
question into a prioritized SKU register.”

Point out that the map highlights supplier reference locations while the table
contains the decision evidence. The map is context; the register is the action
surface.

### 1:40–2:40 — Make the assumption visible

**Do:** raise the minimum alternate score from 0 to 55, then to 60.

**Say:** “Qualification alone may be too permissive, so I exposed the supplier
performance threshold instead of burying it in code. At 55, stranded SKUs rise
from 13 to 20; at 60, they rise to 25. That is not a forecast. It is a policy
sensitivity that lets procurement challenge the definition of an acceptable
alternate.”

Restore the score floor to 0 before moving on.

### 2:40–3:40 — Test Ontario DC 1

**Show:** **Node outage** with Ontario DC 1 unavailable.

**Say:** “Ontario DC 1 is the nearest screening node for six supplier reference
points. Removing it reroutes those six to their next-nearest available node,
adding **1,155.6 km** across the affected screening connections. The largest
single increase is **342.3 km**, for Galloway-Wyatt moving from Ontario DC 1 to
Ontario DC 3. The affected suppliers represent **$44,455,614.81** of annual
inbound spend.”

Immediately qualify the last number: “That spend belongs to the six suppliers;
it is context, not proof that the money physically flowed through Ontario DC 1.
The model contains no shipment-lane or node-throughput fact.”

### 3:40–4:40 — Close the loop to action

**Show:** the SKU response register and download a decision brief.

**Say:** “A scenario is only useful if it changes work. Each row states whether
a qualified alternate exists, the best available contract lead, whether it
fits the selected window, and the next validation step. The exported brief
retains the owner, thresholds and method boundary so the decision does not lose
its assumptions when it leaves the app.”

Name the hand-offs: procurement confirms qualification, capacity and terms;
supply planning checks cover and timing; logistics validates the actual route
and node capacity.

### 4:40–6:00 — Prove why the evidence is trustworthy

**Show:** **Evidence trail**, then enable the invalid-latitude toggle.

**Say:** “The publication gate reconciles keys, checks WGS 84 bounds, confirms
supplier coverage and recomputes the nearest node. A latitude of 95 degrees
blocks publication in memory without changing the source. This is the BA value
I wanted to show: requirements, acceptance criteria, exception handling and a
traceable decision—not simply a visually appealing map.”

Finish with: “For production I would replace reference points and proximity
lines with authoritative locations, an appropriate projected CRS where needed,
a road or freight network, border time, capacity and approval history.”

## Facts to know without looking at the screen

### Mexico baseline

| Measure | Exact result | Meaning |
|---|---:|---|
| Suppliers in origin | 4 | Governed supplier records whose country is Mexico |
| Affected SKUs | 36 | Products with at least one Mexican award |
| Award-weighted COGS exposure | $11,821,992.49 | Product COGS multiplied by Mexican award share |
| Share of network COGS | 27.24% | Largest modeled origin exposure |
| No qualified external alternate | 13 SKUs | No qualified awarded supplier outside Mexico |
| Qualified external alternate exists | 23 SKUs | Capacity and commercial terms still require validation |
| Recoverable within 30 days | 7 of 23 | Best eligible contract lead is at most 30 days |
| Mean best alternate lead | 31.7 days | Simple mean of each recoverable SKU’s shortest eligible contract lead |

### Ontario DC 1 outage baseline

| Measure | Exact result | Meaning |
|---|---:|---|
| Impacted supplier connections | 6 of 15 | Their nearest screening node is Ontario DC 1 |
| Supplier spend represented | $44,455,614.81 | Annual spend of those suppliers; **not node throughput** |
| Aggregate added distance | 1,155.6 km | Sum of great-circle deltas across six screening connections |
| Largest added distance | 342.3 km | Galloway-Wyatt: Ontario DC 1 to Ontario DC 3 |

Four affected suppliers screen next to Ontario DC 3; Williams and Sons and
Gray-Mayo screen next to Alberta DC 2. None of these destinations is a capacity
or service-territory recommendation.

## Business-analyst and stakeholder framing

| Stakeholder | Decision or evidence owned | App hand-off |
|---|---|---|
| Procurement lead | Qualification, supplier terms and award policy | Validate alternates and open qualification work |
| Supply planning lead | Recovery window, inventory cover and priority | Assess cover for stranded or slow-switch SKUs |
| Logistics/network lead | Actual lane, border, port and node capacity | Replace proximity screening before execution |
| Finance partner | COGS and spend definitions | Confirm financial exposure and scenario materiality |
| GIS/data steward | Business keys, location source, CRS and publication | Correct rejected features and approve governed layers |
| Business analyst | Decision question, requirements, rules, acceptance criteria and exception path | Facilitate agreement and preserve traceability |

Useful requirement framing:

- **Question:** If an origin or node is unavailable, what must be reviewed first?
- **Inputs:** governed supplier/product awards, performance, COGS, WGS 84
  reference points and published screening routes.
- **Business rules:** external supplier, qualified status, optional score floor
  and selected recovery window.
- **Outputs:** exposure measures, exception register, reroute register and
  downloadable decision brief.
- **Acceptance:** stable keys, valid coordinates, complete supplier coverage,
  reproducible nearest-node choice and visible limitations.

## Data lineage

```text
fact_sourcing.csv ─┬─ dim_supplier.csv ─┬─ country disruption rules
                   │                    └─ qualification and origin
                   └─ sourcing_concentration.csv ─ product COGS

supplier_scorecard.csv ─ minimum alternate score + supplier context

network_locations.csv ─ WGS 84 validation ─┬─ network_locations.geojson
                                           └─ Haversine nearest-node rule
                                              └─ supplier_routes.geojson
                                                 + gis_route_summary.csv

tested decision functions ─ Streamlit interface ─ decision brief/register
```

The interface reads committed evidence. It does not silently geocode locations,
call an external routing service or alter source files.

## Method boundaries to state plainly

- All business data and locations are synthetic portfolio evidence.
- WGS 84 points are reference locations, not verified facilities.
- Haversine distance is deterministic proximity screening—not road, ocean,
  rail, port or travel-time routing.
- Country exposure is award-weighted product COGS, not shipment volume.
- Supplier scores are annual and supplier-wide, not SKU- or lane-specific.
- Qualification is supplier-level; product certification and available
  capacity are not modeled.
- Alternate lead time is contractual and the reported mean is unweighted.
- Freight, duty, FX, border delay, carbon, throughput and service territories
  are absent.
- The Ontario outage’s spend figure is supplier context, not warehouse flow.
- The app supports investigation and hand-off; it does not authorize execution.

## Likely interview questions

### Why Streamlit when the repository already has Power BI?

Power BI is the governed monitoring layer. Streamlit makes scenario logic,
assumptions, exception handling and downloadable outputs easy to demonstrate.
They are complementary: one monitors the business; the other facilitates a
specific decision conversation.

### Why did you use great-circle distance?

It is transparent, reproducible and suitable for first-pass geographic
proximity. I would not convert it to transit time. Operational use requires a
routable network, constraints, capacity and validation by logistics.

### How do you know the joins are reliable?

Supplier and warehouse IDs reconcile to the governed dimensions. The gate
checks unique keys, coordinate bounds, complete 15-supplier route coverage,
warehouse referential integrity and a one-to-one supplier performance join.
The nearest destination is independently recomputed.

### Why allow the user to change the supplier-score floor?

It makes a contested policy assumption visible. The score is a supplier-wide
screen, so raising it shows sensitivity; it does not prove that an alternate
has SKU-specific capability or capacity.

### What would you do before putting this into production?

Confirm requirements and definitions with users; obtain authoritative
locations; establish source ownership and refresh SLAs; transform to suitable
CRSs; add routable roads/freight lanes, capacity and commercial constraints;
implement authentication, role-based access, audit history, monitoring and
user-acceptance testing.

### How does this relate to municipal GIS work?

The transferable method is reconciling business-system IDs to spatial
features, governing CRS and provenance, testing publication rules, routing
exceptions and presenting decisions clearly. A municipal implementation would
use authoritative parcels, roads, utilities, facilities, assets and work
orders. This project demonstrates the method; it does not claim municipal
production experience.

### What was your role as a business analyst?

I framed the decision, identified stakeholders, defined measures and
assumptions, translated them into acceptance criteria, designed the exception
and hand-off workflow, and ensured every result could be traced back to a
committed source and tested rule.

## Run locally

Run from the repository root so local and Community Cloud paths behave the same:

```powershell
git clone https://github.com/KushPatel29/supply-chain-control-tower.git
cd supply-chain-control-tower
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. The app needs no API key or secrets. Run the
repository checks with `python -m pytest -q`.

## Deploy to Streamlit Community Cloud

After the app files are committed and pushed, open
[Streamlit Community Cloud](https://share.streamlit.io), choose **Create app**,
then **Yup, I have an app**, and use:

| Field | Value |
|---|---|
| Repository | `KushPatel29/supply-chain-control-tower` |
| Branch | `master` |
| Main file path | `streamlit_app.py` |
| App URL / custom subdomain | `kush-network-risk-studio` if available |
| Advanced settings → Python | `3.12` |
| Secrets | Leave blank |

Click **Deploy**. Dependencies are read from the root `requirements.txt` and
theme settings from `.streamlit/config.toml`. Community Cloud identifies the
deployment by repository, branch and entrypoint; those fields should only be
changed through a deliberate redeployment. See the
[official deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
for the current interface.
