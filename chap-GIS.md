# chap-GIS on Open Climate Service — Rwanda

This is an [openEO](https://openeo.org/) re-implementation of the [chap-GIS](https://github.com/dhis2-chap/chap-GIS) malaria exposure pipeline, deployed as a Rwanda country instance of the [Open Climate Service](https://github.com/dhis2/open-climate-service).

The pipeline is identical in concept to yours. This document explains the mapping from your code to ours, what we adapted and why, and how to run it.

---

## Pipeline mapping

| chap-GIS module | openEO process | File |
|---|---|---|
| `climate.lapse_rate_downscale` | `lapse_rate_downscale` | `plugins/processes/lapse_rate_downscale.py` |
| `suitability.thermal_suitability` | `suitability` | `plugins/processes/suitability.py` |
| `landcover.breeding_site_mask` | `breeding_site_mask` | `plugins/processes/breeding_site_mask.py` |
| `exposure.exposure` | `exposure` | `plugins/processes/exposure.py` |
| `pop_exposure = population × exposure` | `multiply_cubes` + `resample_cube_spatial` | process graph (built-in + thin wrapper) |
| `hotspots.identify_hotspots` | `hotspots` | `plugins/processes/hotspots.py` |
| `aggregate.aggregate_to_admin` | `aggregate_spatial` | framework built-in |

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
Both chap-GIS and this implementation target the Copernicus DEM GLO-30 (~30 m / 1 arc-second) as the reference grid. Temperature (CHELSA, ~1 km) is bilinearly interpolated up to the 30 m grid by `lapse_rate_downscale`. WorldCover (10 m) and rice fields (20 m) are produced at their native resolution by `breeding_site_mask`, then resampled to the 30 m DEM grid with `resample_cube_spatial` before the distance-decay `exposure` step. WorldPop (100 m) is resampled to the 30 m grid before the population × exposure multiplication.

At 30 m, Rwanda is ~7 500 × 6 800 pixels (~51 M pixels). The distance transform dominates compute time; expect a few minutes per run. This matches chap-GIS's processing profile.

### Aggregation method
chap-GIS uses `exactextract` for exact pixel-in-polygon weighting. This implementation uses openEO's `aggregate_spatial`, which uses centroid-based assignment. For the ~1 km pixel size relative to Rwanda district areas (median ~400 km²), the difference is negligible.

### Annual mean temperature
Both chap-GIS and this implementation compute the temporal mean temperature first, then apply the TPC once. In the process graph: `reduce_dimension(correct_temperature, t, mean)` → `suitability(mean_temperature)`. The TPC is not applied per month.

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
      "load_temperature":       {"process_id": "load_collection",      "arguments": {"id": "chelsa_temperature_monthly",  "temporal_extent": ["2018-01-01","2018-04-01"]}},
      "load_elevation":         {"process_id": "load_collection",      "arguments": {"id": "nasadem_elevation"}},
      "load_landcover":         {"process_id": "load_collection",      "arguments": {"id": "esa_worldcover_2021"}},
      "load_rice":              {"process_id": "load_collection",      "arguments": {"id": "africa_rice_fields_2023"}},
      "load_population":        {"process_id": "load_collection",      "arguments": {"id": "worldpop_population_yearly", "temporal_extent": ["2018-01-01","2018-12-31"]}},
      "lc_2d":                  {"process_id": "reduce_dimension",     "arguments": {"data": {"from_node": "load_landcover"}, "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "rice_2d":                {"process_id": "reduce_dimension",     "arguments": {"data": {"from_node": "load_rice"},      "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "pop_2d":                 {"process_id": "reduce_dimension",     "arguments": {"data": {"from_node": "load_population"},"reducer": {"process_graph": {"last":  {"process_id": "last",  "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "lc_30m":                 {"process_id": "resample_cube_spatial","arguments": {"data": {"from_node": "lc_2d"},   "target": {"from_node": "load_elevation"}, "method": "near"}},
      "rice_30m":               {"process_id": "resample_cube_spatial","arguments": {"data": {"from_node": "rice_2d"}, "target": {"from_node": "load_elevation"}, "method": "near"}},
      "correct_temperature":    {"process_id": "lapse_rate_downscale", "arguments": {"temperature": {"from_node": "load_temperature"}, "elevation": {"from_node": "load_elevation"}}},
      "mean_temperature":       {"process_id": "reduce_dimension",     "arguments": {"data": {"from_node": "correct_temperature"}, "reducer": {"process_graph": {"mean": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}}, "dimension": "t"}},
      "compute_suitability":    {"process_id": "suitability",          "arguments": {"temperature": {"from_node": "mean_temperature"}}},
      "compute_breeding_mask":  {"process_id": "breeding_site_mask",   "arguments": {"landcover": {"from_node": "lc_30m"}, "rice": {"from_node": "rice_30m"}}},
      "compute_exposure":       {"process_id": "exposure",             "arguments": {"breeding_mask": {"from_node": "compute_breeding_mask"}, "elevation": {"from_node": "load_elevation"}, "suitability": {"from_node": "compute_suitability"}}},
      "pop_aligned":            {"process_id": "resample_cube_spatial","arguments": {"data": {"from_node": "pop_2d"}, "target": {"from_node": "compute_exposure"}, "method": "near"}},
      "pop_exposure":           {"process_id": "multiply_cubes",       "arguments": {"x": {"from_node": "pop_aligned"}, "y": {"from_node": "compute_exposure"}}},
      "compute_hotspots":       {"process_id": "hotspots",             "arguments": {"pop_exposure": {"from_node": "pop_exposure"}, "percentile": 90.0}},
      "save":                   {"process_id": "save_result",          "arguments": {"data": {"from_node": "compute_hotspots"}, "format": "Zarr", "options": {"dataset_id": "mosquito_hotspots", "variable": "hotspot"}}, "result": true}
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

### `breeding_site_mask`

Equivalent to `landcover.breeding_site_mask`. Returns a float32 DataArray encoding three states:
- **1** = breeding site (WorldCover wetlands 90/95, 2-pixel water-edge buffer, rice fields)
- **0** = non-breeding land
- **NaN** = permanent water (class 80) — propagates through `exposure` as a water mask

Source: [`plugins/processes/breeding_site_mask.py`](plugins/processes/breeding_site_mask.py)

### `exposure`

Takes the pre-computed breeding mask (at 30 m, after resampling WorldCover) plus optional elevation and suitability. Matches chap-GIS exactly: suitability is looked up **at the nearest breeding site**, not at each pixel. This means a pixel far from a thermally suitable breeding site gets lower exposure, which is the correct causal model.

```
exposure(x) = exp(−d(x) / λ) × exp(−max(Δz(x), 0) / γ) × S(T_{nearest breeding site})
```

Source: [`plugins/processes/exposure.py`](plugins/processes/exposure.py)

### `multiply_cubes`

Thin wrapper for element-wise multiplication of two spatially aligned DataArrays. Used once in the process graph: `population × exposure` → `pop_exposure`. Source: [`plugins/processes/multiply_cubes.py`](plugins/processes/multiply_cubes.py)

### `hotspots`

Takes pre-computed `pop_exposure` directly; just thresholds at the Nth percentile of non-zero values. The population × exposure multiplication and the population spatial alignment (`resample_cube_spatial`) are done in the process graph before this node. Source: [`plugins/processes/hotspots.py`](plugins/processes/hotspots.py)

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

---

## What is not yet implemented

| chap-GIS feature | Status | Notes |
|---|---|---|
| 30 m fine-grid reprojection | Not implemented | Working at CHELSA ~1 km; processing chain is resolution-agnostic |
| `exactextract` pixel-exact zonal stats | Not implemented | Using centroid-based `aggregate_spatial`; negligible difference at 1 km vs. district scale |
| CHAP-CSV column naming (`period`, `org_unit_id`) | Not implemented | Columns are `t`, `geometry`, `hotspot`; needs a thin adapter for DHIS2 import |
