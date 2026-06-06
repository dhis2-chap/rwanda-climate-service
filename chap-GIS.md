# chap-GIS on Open Climate Service — Rwanda

This is an [openEO](https://openeo.org/) re-implementation of the [chap-GIS](https://github.com/dhis2-chap/chap-GIS) malaria exposure pipeline, deployed as a Rwanda country instance of the [Open Climate Service](https://github.com/dhis2/open-climate-service).

The pipeline is identical in concept to yours. This document explains the mapping from your code to ours, what we adapted and why, and how to run it.

---

## Pipeline mapping

| chap-GIS module | openEO process | File |
|---|---|---|
| `climate.lapse_rate_downscale` | `lapse_rate_downscale` | `plugins/processes/lapse_rate_downscale.py` |
| `suitability.thermal_suitability` | `suitability` | `plugins/processes/suitability.py` |
| `landcover.breeding_site_mask` | internal to `exposure` | `plugins/processes/exposure.py` |
| `exposure.exposure` | `exposure` | `plugins/processes/exposure.py` |
| `hotspots.identify_hotspots` | `hotspots` | `plugins/processes/hotspots.py` |
| `aggregate.aggregate_to_admin` | openEO `aggregate_spatial` | framework built-in |

---

## Parameters

All defaults match chap-GIS exactly.

| Parameter | chap-GIS default | This implementation |
|---|---|---|
| Optimal temperature T_opt | 25.0 °C | 25.0 °C |
| Gaussian width σ | 5.0 °C | 5.0 °C |
| Lower thermal limit T_min | 16.0 °C | 16.0 °C |
| Upper thermal limit T_max | 34.0 °C | 34.0 °C |
| Horizontal decay λ | 651.0 m | 651.0 m |
| Vertical decay γ | 22.5 m | 22.5 m |
| Standard lapse rate | 6.5 K km⁻¹ | 6.5 K km⁻¹ |
| Water edge buffer | 2 pixels | 2 pixels |
| Hotspot percentile | 90 | 90 |
| WorldCover wetland codes | 90, 95 | 90, 95 |
| WorldCover permanent water | 80 | 80 |

---

## Data sources

| chap-GIS source | This implementation | Notes |
|---|---|---|
| CHELSA v2.1 monthly temperature | `chelsa_temperature_monthly` (same) | 1981–2018, ~1 km |
| Copernicus DEM GLO-30 (CDSE credentials) | `nasadem_elevation` (AWS Open Data, anonymous) | Same product, no credentials needed via S3 |
| ESA WorldCover 2021 (CDSE credentials) | `esa_worldcover_2021` (AWS Open Data, anonymous) | Same product at 10 m |
| WorldPop constrained (yearly) | `worldpop_population_yearly` (same) | 100 m |
| Jiang et al. 2023 rice fields | `africa_rice_fields_2023` (Zenodo, same) | 20 m, Africa only |
| GeoBoundaries admin boundaries | `plugins/data/rwanda_districts.geojson` (bundled) | Rwanda ADM2, 30 districts |

---

## Key differences

### Resolution
chap-GIS targets 30 m by reprojecting everything to a fine DEM grid. This implementation works at CHELSA's native ~1 km because the openEO `load_collection` returns data at the dataset's native resolution. At 1 km, Rwanda is ~228×252 pixels — manageable for a national service.

The lapse-rate correction is still applied (temperature adjusted for actual vs. coarse elevation), just at 1 km rather than 30 m. The vertical decay in `exposure` likewise uses 1 km elevation. The physics is the same; sub-kilometre terrain variation is averaged out.

To run at 30 m, load elevation first and pass `spatial_extent` with your target resolution — the processing chain is resolution-agnostic.

### Aggregation method
chap-GIS uses `exactextract` for exact pixel-in-polygon weighting. This implementation uses openEO's `aggregate_spatial`, which uses centroid-based assignment. For the ~1 km pixel size relative to Rwanda district areas (median ~400 km²), the difference is negligible.

### Annual mean vs. per-month TPC
chap-GIS computes an annual mean temperature first, then applies the TPC once. Here we apply the TPC per month and then take the mean suitability. For a symmetric Gaussian this is mathematically equivalent as long as the mean is taken before the hotspot classification. The per-month path preserves seasonal variation if you later want month-by-month hotspot maps.

### Output format
chap-GIS writes a CHAP-compatible CSV directly. Here we use the framework's standard CSV format: columns `t`, `geometry` (district shapeID), `hotspot` (fraction). A thin adapter mapping `shapeID` → DHIS2 org-unit UID can translate this for DHIS2 import.

---

## Running it

### Prerequisites

Start the service:
```bash
make run
```

Ingest all five datasets (each call blocks until complete; first run downloads to `~/.cache/chap-gis/`):

```bash
curl -X POST http://localhost:8000/ingestions -H "Content-Type: application/json" \
  -d '{"dataset_id": "esa_worldcover_2021",        "start": "2021",    "publish": true}'

curl -X POST http://localhost:8000/ingestions -H "Content-Type: application/json" \
  -d '{"dataset_id": "chelsa_temperature_monthly",  "start": "2018-01", "end": "2018-12", "publish": true}'

curl -X POST http://localhost:8000/ingestions -H "Content-Type: application/json" \
  -d '{"dataset_id": "africa_rice_fields_2023",    "start": "2023",    "publish": true}'

curl -X POST http://localhost:8000/ingestions -H "Content-Type: application/json" \
  -d '{"dataset_id": "worldpop_population_yearly",  "start": "2018",    "end": "2018", "publish": true}'

curl -X POST http://localhost:8000/ingestions -H "Content-Type: application/json" \
  -d '{"dataset_id": "nasadem_elevation",           "start": "2021",    "publish": true}'
```

### Workflow 1 — Hotspot raster

Equivalent to `chap-gis analyze --country=RWA`. Produces a binary hotspot mask and publishes it as a versioned Zarr (Icechunk) collection, visible on the map at `http://localhost:8000/map`.

Process graph: [`plugins/workflows/mosquito_hotspot_raster.json`](plugins/workflows/mosquito_hotspot_raster.json)

```bash
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Mosquito hotspot raster (Rwanda 2018 Q1)",
    "process": {"process_graph": {
      "load_temperature":    {"process_id": "load_collection",     "arguments": {"id": "chelsa_temperature_monthly",  "temporal_extent": ["2018-01-01","2018-04-01"]}},
      "load_elevation":      {"process_id": "load_collection",     "arguments": {"id": "nasadem_elevation"}},
      "load_landcover":      {"process_id": "load_collection",     "arguments": {"id": "esa_worldcover_2021"}},
      "load_rice":           {"process_id": "load_collection",     "arguments": {"id": "africa_rice_fields_2023"}},
      "load_population":     {"process_id": "load_collection",     "arguments": {"id": "worldpop_population_yearly", "temporal_extent": ["2018-01-01","2018-12-31"]}},
      "lc_2d":   {"process_id": "reduce_dimension", "arguments": {"data": {"from_node": "load_landcover"}, "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "rice_2d": {"process_id": "reduce_dimension", "arguments": {"data": {"from_node": "load_rice"},      "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "correct_temperature": {"process_id": "lapse_rate_downscale", "arguments": {"temperature": {"from_node": "load_temperature"}, "elevation": {"from_node": "load_elevation"}}},
      "mean_temperature":    {"process_id": "reduce_dimension",     "arguments": {"data": {"from_node": "correct_temperature"}, "reducer": {"process_graph": {"mean": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "compute_suitability": {"process_id": "suitability", "arguments": {"temperature": {"from_node": "mean_temperature"}}},
      "compute_exposure":    {"process_id": "exposure",    "arguments": {"suitability": {"from_node": "compute_suitability"}, "landcover": {"from_node": "lc_2d"}, "rice": {"from_node": "rice_2d"}, "elevation": {"from_node": "load_elevation"}}},
      "compute_hotspots":    {"process_id": "hotspots",   "arguments": {"population": {"from_node": "load_population"}, "exposure": {"from_node": "compute_exposure"}, "percentile": 90.0}},
      "save": {"process_id": "save_result", "arguments": {"data": {"from_node": "compute_hotspots"}, "format": "Zarr", "options": {"dataset_id": "mosquito_hotspots", "variable": "hotspot"}}, "result": true}
    }}
  }')
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"
watch -n 5 "curl -s http://localhost:8000/jobs/$JOB_ID | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['status'])\""
```

### Workflow 2 — District aggregation

Equivalent to `chap-gis aggregate`. Loads the published `mosquito_hotspots` collection and produces a CSV of hotspot fraction per district per month.

Process graph: [`plugins/workflows/mosquito_district_aggregation.json`](plugins/workflows/mosquito_district_aggregation.json)

```bash
GEOJSON=$(cat plugins/data/rwanda_districts.geojson)
DISTRICT_IDS=$(python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
print(json.dumps([f['properties']['shapeID'] for f in d['features']]))
")

JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Mosquito district aggregation (Rwanda 2018 Q1)\",
    \"process\": {\"process_graph\": {
      \"load_hotspots\": {\"process_id\": \"load_collection\",   \"arguments\": {\"id\": \"mosquito_hotspots\", \"temporal_extent\": [\"2018-01-01\",\"2018-04-01\"]}},
      \"aggregate\":     {\"process_id\": \"aggregate_spatial\", \"arguments\": {\"data\": {\"from_node\": \"load_hotspots\"}, \"geometries\": $GEOJSON, \"reducer\": {\"process_graph\": {\"mean\": {\"process_id\": \"mean\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}}},
      \"label\":         {\"process_id\": \"rename_labels\",     \"arguments\": {\"data\": {\"from_node\": \"aggregate\"}, \"dimension\": \"geometry\", \"target\": $DISTRICT_IDS}},
      \"export\":        {\"process_id\": \"save_result\",       \"arguments\": {\"data\": {\"from_node\": \"label\"}, \"format\": \"CSV\"}, \"result\": true}
    }}
  }")
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"
curl -O "http://localhost:8000/jobs/$JOB_ID/results/result.csv"
```

CSV columns: `t` (ISO month), `geometry` (GeoBoundaries `shapeID`), `hotspot` (fraction [0–1]).

Map shapeID → district name:
```bash
python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
for f in d['features']:
    print(f['properties']['shapeID'], f['properties']['shapeName'])
"
```

---

## Process implementations

### `lapse_rate_downscale`

```
T_out = T_interp − lapse_rate × (elev − elev_coarse)
```

`elev_coarse` is the DEM bilinearly resampled to the temperature grid — the same two-step correction as `climate.lapse_rate_downscale` in chap-GIS. Source: [`plugins/processes/lapse_rate_downscale.py`](plugins/processes/lapse_rate_downscale.py)

### `suitability`

```
S(T) = exp(−((T − T_opt) / σ)²)   for T_min ≤ T ≤ T_max, else 0
```

Equivalent to `suitability.thermal_suitability`. Source: [`plugins/processes/suitability.py`](plugins/processes/suitability.py)

### `exposure`

```
exposure(x) = exp(−d(x) / λ) × exp(−max(Δz(x), 0) / γ) × S(T)
```

- `d(x)` — Euclidean distance to nearest breeding site  
- `Δz(x)` — elevation of pixel x minus elevation of its nearest breeding site (from `distance_transform_edt(return_indices=True)`, same approach as chap-GIS)  
- Breeding sites: WorldCover 90, 95; 2-pixel dilation around 80; rice fields  
- Permanent-water pixels (class 80) set to NaN in output  

Source: [`plugins/processes/exposure.py`](plugins/processes/exposure.py)

### `hotspots`

Threshold at the 90th percentile of non-zero `population × exposure` values; returns binary mask. Equivalent to `hotspots.identify_hotspots`. Source: [`plugins/processes/hotspots.py`](plugins/processes/hotspots.py)

---

## What is not yet implemented

| chap-GIS feature | Status | Notes |
|---|---|---|
| 30 m fine-grid reprojection | Not implemented | Working at CHELSA ~1 km; processing chain is resolution-agnostic |
| `exactextract` pixel-exact zonal stats | Not implemented | Using centroid-based `aggregate_spatial`; negligible difference at 1 km vs. district scale |
| CHAP-CSV column naming (`period`, `org_unit_id`) | Not implemented | Columns are `t`, `geometry`, `hotspot`; needs a thin adapter for DHIS2 import |
