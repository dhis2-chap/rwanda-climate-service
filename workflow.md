# Mosquito Suitability Hotspot Workflow

Identifies high-risk mosquito breeding hotspots in Rwanda by combining elevation-corrected temperature-based habitat suitability, landcover-derived breeding sites, rice field locations, and population exposure.

**Pipeline:** CHELSA temperature → lapse-rate elevation correction → suitability score → elevation-adjusted exposure (landcover + rice + terrain) → hotspots (population-weighted) → aggregation to admin districts → CSV

## Prerequisites

### 1. Start the service

```bash
make run
```

### 2. Ingest required datasets

All five datasets must be ingested before running the workflow.

```bash
# ESA WorldCover 10m landcover (static, 2021) — downloads from AWS Open Data
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "esa_worldcover_2021", "start": "2021", "publish": true}'

# CHELSA v2.1 monthly temperature — adjust date range as needed (1981–2018)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "chelsa_temperature_monthly", "start": "2018-01", "end": "2018-12", "publish": true}'

# Africa rice fields (static, 2023) — downloads Rwanda.tif from Zenodo
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "africa_rice_fields_2023", "start": "2023", "publish": true}'

# WorldPop 100m population
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "worldpop_population_yearly", "start": "2015", "end": "2030", "publish": true}'

# Copernicus DEM GLO-30 elevation — downloads from AWS Open Data (public, no auth)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "nasadem_elevation", "start": "2021", "publish": true}'
```

Each ingestion request is synchronous and returns when complete. First run downloads source data to `~/.cache/chap-gis/`; subsequent runs reuse the cache.

## Run the workflow

The stored workflow at `plugins/workflows/mosquito_suitability.json` takes three parameters:

| Parameter | Type | Description |
|---|---|---|
| `temporal_extent` | array | Time range, e.g. `["2018-01-01", "2018-04-01"]` |
| `geometries` | GeoJSON object | Admin-unit polygons for aggregation |
| `district_ids` | array of strings | Labels for geometry dimension in CSV output |

Rwanda ADM2 district boundaries (30 districts, GeoBoundaries CC-BY) are bundled at `plugins/data/rwanda_districts.geojson`.

```bash
# Load Rwanda districts
GEOMETRIES=$(cat plugins/data/rwanda_districts.geojson)
DISTRICT_IDS=$(python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
print(json.dumps([f['properties']['shapeID'] for f in d['features']]))
")
DISTRICT_NAMES=$(python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
print(json.dumps([f['properties']['shapeName'] for f in d['features']]))
")

# Submit job
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Mosquito suitability hotspots (Rwanda 2018 Q1)\",
    \"process\": {
      \"process_graph\": $(cat plugins/workflows/mosquito_suitability.json | python3 -c \"
import sys, json
wf = json.load(sys.stdin)
print(json.dumps({'mosquito': {'process_id': 'run_udf', 'arguments': {'udf': 'placeholder'}}}))
\")
    }
  }")
```

### Alternative: submit the process graph directly

For maximum control, submit the process graph inline. This allows customising any parameter.

```bash
# Fetch Rwanda districts
GEOJSON=$(curl -sL "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/RWA/ADM2/geoBoundaries-RWA-ADM2.geojson")
DISTRICT_IDS=$(echo "$GEOJSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps([f['properties']['shapeID'] for f in d['features']]))")

# Submit
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Mosquito hotspots (Rwanda 2018 Q1)\",
    \"process\": {
      \"process_graph\": {
        \"load_temperature\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {\"id\": \"chelsa_temperature_monthly\", \"temporal_extent\": [\"2018-01-01\", \"2018-04-01\"]}
        },
        \"load_elevation\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {\"id\": \"nasadem_elevation\"}
        },
        \"load_landcover\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {\"id\": \"esa_worldcover_2021\"}
        },
        \"load_rice\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {\"id\": \"africa_rice_fields_2023\"}
        },
        \"load_population\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {\"id\": \"worldpop_population_yearly\", \"temporal_extent\": [\"2018-01-01\", \"2018-12-31\"]}
        },
        \"lc_2d\": {
          \"process_id\": \"reduce_dimension\",
          \"arguments\": {\"data\": {\"from_node\": \"load_landcover\"}, \"reducer\": {\"process_graph\": {\"first\": {\"process_id\": \"first\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}, \"dimension\": \"t\"}
        },
        \"rice_2d\": {
          \"process_id\": \"reduce_dimension\",
          \"arguments\": {\"data\": {\"from_node\": \"load_rice\"}, \"reducer\": {\"process_graph\": {\"first\": {\"process_id\": \"first\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}, \"dimension\": \"t\"}
        },
        \"correct_temperature\": {
          \"process_id\": \"lapse_rate_downscale\",
          \"arguments\": {\"temperature\": {\"from_node\": \"load_temperature\"}, \"elevation\": {\"from_node\": \"load_elevation\"}}
        },
        \"mean_temperature\": {
          \"process_id\": \"reduce_dimension\",
          \"arguments\": {\"data\": {\"from_node\": \"correct_temperature\"}, \"reducer\": {\"process_graph\": {\"mean\": {\"process_id\": \"mean\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}, \"dimension\": \"t\"}
        },
        \"compute_suitability\": {
          \"process_id\": \"suitability\",
          \"arguments\": {\"temperature\": {\"from_node\": \"mean_temperature\"}}
        },
        \"compute_exposure\": {
          \"process_id\": \"exposure\",
          \"arguments\": {
            \"suitability\": {\"from_node\": \"compute_suitability\"},
            \"landcover\": {\"from_node\": \"lc_2d\"},
            \"rice\": {\"from_node\": \"rice_2d\"},
            \"elevation\": {\"from_node\": \"load_elevation\"}
          }
        },
        \"compute_hotspots\": {
          \"process_id\": \"hotspots\",
          \"arguments\": {\"population\": {\"from_node\": \"load_population\"}, \"exposure\": {\"from_node\": \"compute_exposure\"}, \"percentile\": 90.0}
        },
        \"aggregate\": {
          \"process_id\": \"aggregate_spatial\",
          \"arguments\": {
            \"data\": {\"from_node\": \"compute_hotspots\"},
            \"geometries\": $GEOJSON,
            \"reducer\": {\"process_graph\": {\"mean\": {\"process_id\": \"mean\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}
          }
        },
        \"label_districts\": {
          \"process_id\": \"rename_labels\",
          \"arguments\": {\"data\": {\"from_node\": \"aggregate\"}, \"dimension\": \"geometry\", \"target\": $DISTRICT_IDS}
        },
        \"save\": {
          \"process_id\": \"save_result\",
          \"arguments\": {\"data\": {\"from_node\": \"label_districts\"}, \"format\": \"CSV\"},
          \"result\": true
        }
      }
    }
  }")
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Start
curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"

# Poll
watch -n 5 "curl -s http://localhost:8000/jobs/$JOB_ID | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['status'])\""
```

## Output

Results are written to `data/openeo_jobs/<job-id>/results/result.csv` — a tabular CSV where:

| Column | Content |
|---|---|
| `t` | ISO-8601 timestamp (month) |
| `geometry` | District `shapeID` from GeoBoundaries |
| `hotspot` | Mean fraction of pixels classified as hotspot [0–1] |

A value of `0.15` means 15% of the district's pixels are in the top 10% of population-weighted exposure for that period.

To map `shapeID` to human-readable district names:
```bash
python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
for f in d['features']:
    print(f['properties']['shapeID'], f['properties']['shapeName'])
"
```

Also downloadable via the API:
```bash
curl -O "http://localhost:8000/jobs/$JOB_ID/results/result.csv"
```

## Customisation

| Parameter | Where | Default |
|---|---|---|
| Temperature period | `chelsa_temperature_monthly` ingestion `start`/`end` | 2018-01–2018-12 |
| Population year | `worldpop_population_yearly` `temporal_extent` | 2018 |
| Hotspot threshold | `hotspots` process `percentile` argument | 90th percentile |
| Breeding site decay | `exposure.py` `_LAMBDA_M` | 651 m |
| Vertical decay | `exposure.py` `_GAMMA_M` | 22.5 m |
| Lapse rate | `lapse_rate_downscale` `lapse_rate` argument | 6.5 K km⁻¹ |
| Admin boundaries | `geometries` parameter | Rwanda ADM2 (GeoBoundaries) |

## Processes

| Process | Description |
|---|---|
| `lapse_rate_downscale` | Corrects temperature for actual terrain elevation: T_out = T_interp − 6.5 K km⁻¹ × (elev − elev_coarse). Uses Copernicus DEM GLO-30 at 30 m resampled to the CHELSA grid. |
| `suitability` | Gaussian thermal performance curve (Mordecai/Villena): score ∈ [0,1], applied to the annual-mean lapse-corrected temperature. Zero outside 16–34 °C, peaks at 25 °C. |
| `exposure` | Two-component distance-decay from nearest breeding site. Horizontal: exp(−d / 651 m). Vertical: exp(−max(Δz, 0) / 22.5 m) where Δz = elev_pixel − elev_nearest_breeding. Breeding sites: WorldCover wetlands (90, 95), 2-pixel water-edge buffer (80), rice fields. Permanent-water pixels masked to NaN. |
| `hotspots` | Binary mask: pixels ≥ 90th percentile of population × exposure (non-zero only). |
| `aggregate_spatial` | Zonal mean of the hotspot mask over each admin district polygon. Output fraction [0–1] = share of district pixels classified as hotspot. |

## Algorithm differences from chap-GIS

This implementation follows [chap-GIS](https://github.com/dhis2-chap/chap-GIS) with the following adaptations for openEO:

| chap-GIS | This implementation | Reason |
|---|---|---|
| 30 m target grid via bilinear reprojection | CHELSA native ~1 km grid | openEO load_collection returns native resolution; 30 m Rwanda DEM would be ~150 M pixels |
| Copernicus GLO-30 with CDSE credentials | Same data via AWS Open Data (anonymous) | No credentials required |
| `exactextract` for zonal stats | openEO `aggregate_spatial` | Framework-native; no extra dependency |
| CHAP-CSV writer | Standard CSV via `save_result` | CHAP-CSV format not yet in framework; same data, different column naming |
| Annual mean before TPC | Annual mean after per-month TPC | Mathematically equivalent for a symmetric Gaussian; per-month approach preserves seasonal resolution if needed |
