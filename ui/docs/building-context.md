# Building and lot context for mission setup

Research done in Mana on 25 October 2026 (chat "Search-and-rescue Drone Address", document "Mayfly: Building & Lot Context"). Findings were checked against live endpoints where noted. This note condenses them and says what they mean for the UI. Treat all of it as planning context, not obstacle-clearance certification or a structural assessment.

## Sources by attribute

| Attribute | Best free source | Caveat |
|---|---|---|
| Footprint polygon | Overture buildings or Microsoft Global ML footprints (bbox query, ingest ahead of time) | Overture is ODbL (attribution, share-alike). Microsoft Global ML is CDLA Permissive 2.0. |
| Height | Overture `height`, OSM `height` / `building:levels`, Microsoft modelled average height, lidar from USGS 3DEP | Different measurements: tagged total height, polygon average, roof percentile. Never merge into one "safe altitude". Missing height can be `-1`, never show 0 m. |
| Floors | OSM `building:levels` (excludes roof levels), Overture `num_floors` | Often absent. Floors × floor-to-floor is only a labelled estimate. |
| Occupancy class | FEMA / ORNL USA Structures (`OCC_CLS`, `PRIM_OCC`, `HEIGHT`, `SQMETERS`) | Inferred, not field verified. Layer queries can time out. |
| Lot polygon, area, PIN, owner, class code | County ArcGIS REST (Sangamon: see below) | Public access is not a redistribution licence. A parcel can hold several buildings. `TOTACRES` can be 0 on a valid polygon, treat as missing. |
| Zoning district | City or county planning GIS | A district label is what is permitted, not what exists. Max height there is a development control, not a roof height or flight ceiling. |
| Year built, construction type | Assessor CAMA records, fire department preplans | Not available through any public REST layer we found for Sangamon. Regrid reports 0% year-built coverage there. |

Paid options: Regrid (nationwide parcels, per-record billing, trial covers only sample counties, Sangamon excluded) and Zoneomics (per-municipality, terms restrict republishing). Neither has a verified permanent free nationwide tier.

## Springfield, IL pilot endpoints

All were live-tested without authentication and cap responses at 2,000 records. Query with `geometry=lon,lat`, `geometryType=esriGeometryPoint`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`, `outFields`, `returnGeometry=true`, plus `outSR=4326` for map output. The city service is in EPSG:3436 (US survey feet).

| Need | Layer |
|---|---|
| Parcel polygons | `TyleratENTParcels/MapServer/0` (PIN, TOTACRES) |
| Parcel attributes | `SangamonCountyEPL/MapServer/1` (Owner, ClassCode, address, Zoning) |
| Assessment view | `SangCadastral/MapServer/3` (AssessedTotal, CurrZoning) |
| City zoning polygons | `PW_Zoning/parcelZonesView/MapServer/0` (SYMBOL) |
| City parcel to zoning join | `PW_Zoning/parcelZonesView/MapServer/2` and table `/7` |

Do not use `Sangamon_Zoning/MapServer/5` for Springfield, it returns null inside the city. Test point lon -89.6512, lat 39.79695 returned PIN 14340156007 and zoning H-2 (Historic). There is no public local footprint layer, so footprints come from the national datasets. `BUILD/BUILD_View` is service requests, not buildings. Full host paths are in the Mana document.

## Typical ranges (plausibility priors only)

| Form | Floors | Floor-to-floor | Footprint | Lot |
|---|---|---|---|---|
| Detached single-family | 1–3 | 9–12 ft | 800–3,000 sq ft | 4,000–20,000 sq ft |
| Low/mid-rise multifamily | 2–6 | 9–12 ft | 3,000–30,000 sq ft | 6,000–100,000 sq ft |
| Small/medium retail | 1–2 | 12–20 ft | 2,000–50,000 sq ft | 5,000–200,000 sq ft |
| Small/mid-rise office | 1–12 | 12–15 ft | 5,000–45,000 sq ft | 10,000–200,000 sq ft |

These are synthesis for sanity checks (flag a "2 floors, 40 m" record), not statistics and not safe defaults for flight.

## What responders need first

1. The right building and its geometry: confirmed address-to-building match, labelled buildings on multi-building sites, entrances, access, exposures.
2. Vertical environment: terrain, roof and obstacle maximum with uncertainty, trees, wires, antennas.
3. Live incident conditions, which override any record.
4. Occupancy, stories above and below grade, roof access.
5. Construction, sprinklers, hydrants, utilities, hazmat. Needs department or owner data.
6. Supporting: year built, footprint area, lot geometry. Year built alone does not predict collapse.

NFPA 1620 was folded into NFPA 1660 (2024). Preplans lead with a site diagram, then a short operational summary, then separate floor and roof plans, with a legend and a reviewer and inspection date.

## Implications for the UI

- Every value gets provenance: value, unit, method, source, date, and a state of `verified`, `record`, `estimated` or `unknown`. The current mock card shows "Built 1962" and "Wood frame" as plain facts. Public Sangamon data has neither, so these need an `unknown` or `assessor request` state.
- Keep four height-like fields apart: measured height, estimated height (floors × floor-to-floor), zoning limit, flight ceiling. Never derive one from another silently.
- Show area three ways when present: footprint, total floor area, lot. Label assessed versus geometric acreage.
- "Parcels" layer on the address map (`missions.new.tsx`) can draw the parcel polygon and a zoning chip (for example `H-2 Historic`). Zoning is secondary to confirmed geometry and live hazards, so keep it small.
- Let the responder pick the building when several candidates match, and show match quality.
- A timed-out lookup must not block setup. Show a stale or offline badge and continue.
- Minimise owner data in the mission UI. Owner is not an occupant or contact.
- Regulatory ceiling (14 CFR 107.51, 400 ft AGL with a structure exception) stays a separate field from obstacle clearance.
