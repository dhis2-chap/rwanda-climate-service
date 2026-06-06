# Mosquito Suitability Hotspot Workflow

Identifies high-risk mosquito breeding hotspots in Rwanda by combining elevation-corrected temperature-based habitat suitability, landcover-derived breeding sites, rice field locations, and population exposure.

Two workflows cover the full pipeline:

| Workflow | File | Output |
|---|---|---|
| **Hotspot raster** | `mosquito_hotspot_raster.json` | Published Zarr collection (map view + STAC) |
| **District aggregation** | `mosquito_district_aggregation.json` | CSV of hotspot fraction per district per month |

Run the raster workflow first. The aggregation workflow reads from the published collection, so the two can be re-run independently — for example, re-aggregate with different boundaries without recomputing the raster.

## Step 1 — Start the service

```bash
make run
```

## Step 2 — Ingest required datasets

All five datasets must be ingested before running the raster workflow. Each call is synchronous.

```bash
# ESA WorldCover 10m landcover (2021)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "esa_worldcover_2021", "start": "2021", "publish": true}'

# CHELSA v2.1 monthly temperature (1981–2018 available)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "chelsa_temperature_monthly", "start": "2018-01", "end": "2018-12", "publish": true}'

# Africa rice fields (2023, Jiang et al., Zenodo)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "africa_rice_fields_2023", "start": "2023", "publish": true}'

# WorldPop 100m population
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "worldpop_population_yearly", "start": "2018", "end": "2018", "publish": true}'

# Copernicus DEM GLO-30 elevation (AWS Open Data, no auth required)
curl -X POST http://localhost:8000/ingestions \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "nasadem_elevation", "start": "2021", "publish": true}'
```

First run downloads source data to `~/.cache/chap-gis/`; subsequent runs reuse the cache.

## Step 3 — Run the hotspot raster workflow

Produces a binary hotspot mask (1 = top-10% population-exposure pixel, 0 = non-hotspot) and publishes it as a STAC collection visible on the map.

```bash
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Mosquito hotspot raster (Rwanda 2018 Q1)",
    "process": {
      "process_graph": {
        "load_temperature": {
          "process_id": "load_collection",
          "arguments": {"id": "chelsa_temperature_monthly", "temporal_extent": ["2018-01-01", "2018-04-01"]}
        },
        "load_elevation": {
          "process_id": "load_collection",
          "arguments": {"id": "nasadem_elevation"}
        },
        "load_landcover": {
          "process_id": "load_collection",
          "arguments": {"id": "esa_worldcover_2021"}
        },
        "load_rice": {
          "process_id": "load_collection",
          "arguments": {"id": "africa_rice_fields_2023"}
        },
        "load_population": {
          "process_id": "load_collection",
          "arguments": {"id": "worldpop_population_yearly", "temporal_extent": ["2018-01-01", "2018-12-31"]}
        },
        "lc_2d": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "load_landcover"},
            "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "rice_2d": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "load_rice"},
            "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "correct_temperature": {
          "process_id": "lapse_rate_downscale",
          "arguments": {
            "temperature": {"from_node": "load_temperature"},
            "elevation": {"from_node": "load_elevation"}
          }
        },
        "mean_temperature": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "correct_temperature"},
            "reducer": {"process_graph": {"mean": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "compute_suitability": {
          "process_id": "suitability",
          "arguments": {"temperature": {"from_node": "mean_temperature"}}
        },
        "compute_exposure": {
          "process_id": "exposure",
          "arguments": {
            "suitability": {"from_node": "compute_suitability"},
            "landcover": {"from_node": "lc_2d"},
            "rice": {"from_node": "rice_2d"},
            "elevation": {"from_node": "load_elevation"}
          }
        },
        "compute_hotspots": {
          "process_id": "hotspots",
          "arguments": {
            "population": {"from_node": "load_population"},
            "exposure": {"from_node": "compute_exposure"},
            "percentile": 90.0
          }
        },
        "save": {
          "process_id": "save_result",
          "arguments": {
            "data": {"from_node": "compute_hotspots"},
            "format": "Zarr",
            "options": {"dataset_id": "mosquito_hotspots", "variable": "hotspot"}
          },
          "result": true
        }
      }
    }
  }')
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Start and poll
curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"
watch -n 5 "curl -s http://localhost:8000/jobs/$JOB_ID | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['status'])\""
```

When the job finishes, the collection `mosquito_hotspots` appears in the map at `http://localhost:8000/map` with `YlOrRd` colormap.

## Step 4 — Run the district aggregation workflow

Loads the published `mosquito_hotspots` raster, computes the mean hotspot fraction per district per month, and exports a CSV.

```bash
# Load Rwanda ADM2 boundaries (bundled)
GEOJSON=$(cat plugins/data/rwanda_districts.geojson)
DISTRICT_IDS=$(python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
print(json.dumps([f['properties']['shapeID'] for f in d['features']]))
")

JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Mosquito hotspot district aggregation (Rwanda 2018 Q1)\",
    \"process\": {
      \"process_graph\": {
        \"load_hotspots\": {
          \"process_id\": \"load_collection\",
          \"arguments\": {
            \"id\": \"mosquito_hotspots\",
            \"temporal_extent\": [\"2018-01-01\", \"2018-04-01\"]
          }
        },
        \"aggregate\": {
          \"process_id\": \"aggregate_spatial\",
          \"arguments\": {
            \"data\": {\"from_node\": \"load_hotspots\"},
            \"geometries\": $GEOJSON,
            \"reducer\": {\"process_graph\": {\"mean\": {\"process_id\": \"mean\", \"arguments\": {\"data\": {\"from_parameter\": \"data\"}}, \"result\": true}}}
          }
        },
        \"label_districts\": {
          \"process_id\": \"rename_labels\",
          \"arguments\": {
            \"data\": {\"from_node\": \"aggregate\"},
            \"dimension\": \"geometry\",
            \"target\": $DISTRICT_IDS
          }
        },
        \"export\": {
          \"process_id\": \"save_result\",
          \"arguments\": {\"data\": {\"from_node\": \"label_districts\"}, \"format\": \"CSV\"},
          \"result\": true
        }
      }
    }
  }")
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"
watch -n 5 "curl -s http://localhost:8000/jobs/$JOB_ID | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['status'])\""

# Download result
curl -O "http://localhost:8000/jobs/$JOB_ID/results/result.csv"
```

## Output

### Hotspot raster (Step 3)

Binary GeoTIFF and Zarr store with:
- `1` = hotspot (top 10th percentile of population × exposure)
- `0` = non-hotspot
- `NaN` = permanent water (WorldCover class 80)

Visible on the map at `http://localhost:8000/map`.

### District CSV (Step 4)

| Column | Content |
|---|---|
| `t` | ISO-8601 timestamp (one row per month) |
| `geometry` | District `shapeID` from GeoBoundaries |
| `hotspot` | Mean hotspot fraction for that district [0–1] |

A value of `0.15` means 15% of the district's pixels were classified as hotspots for that month.

Map `shapeID` to district names:
```bash
python3 -c "
import json
d = json.load(open('plugins/data/rwanda_districts.geojson'))
for f in d['features']:
    print(f['properties']['shapeID'], f['properties']['shapeName'])
"
```

## Customisation

| Parameter | Where | Default |
|---|---|---|
| Temperature period | `chelsa_temperature_monthly` ingestion `start`/`end` | 2018-01–2018-12 |
| Population year | `worldpop_population_yearly` `temporal_extent` | 2018 |
| Hotspot threshold | `hotspots` process `percentile` argument | 90th percentile |
| Lapse rate | `lapse_rate_downscale` `lapse_rate` argument | 6.5 K km⁻¹ |
| Breeding site decay | `exposure.py` `_LAMBDA_M` | 651 m |
| Vertical terrain decay | `exposure.py` `_GAMMA_M` | 22.5 m |
| Admin boundaries | `geometries` in aggregation job | Rwanda ADM2 (GeoBoundaries) |

## Processes

| Process | Description |
|---|---|
| `lapse_rate_downscale` | Corrects CHELSA temperature for actual terrain elevation using the standard lapse rate (6.5 K km⁻¹). Bilinearly interpolates to the elevation grid; correction = −lapse_rate × (elev − elev_coarse). |
| `suitability` | Gaussian thermal performance curve (Mordecai/Villena): S(T) = exp(−((T − 25°C)/5°C)²), zero outside 16–34 °C. Applied to annual-mean lapse-corrected temperature. |
| `exposure` | Two-component distance-decay from nearest breeding site. Horizontal: exp(−d / 651 m). Vertical: exp(−max(Δz, 0) / 22.5 m) where Δz = elev_pixel − elev_nearest_breeding. Breeding sites: WorldCover wetlands (90, 95), 2-pixel water-edge buffer (80), and rice fields. Permanent-water pixels masked to NaN. |
| `hotspots` | Binary mask: 1 where population × exposure ≥ 90th percentile of all non-zero values, 0 elsewhere. |
| `aggregate_spatial` | Zonal mean of the binary hotspot mask per district polygon. Output fraction = share of pixels classified as hotspot. |

## Datasets

| Dataset | ID | Source |
|---|---|---|
| Temperature | `chelsa_temperature_monthly` | CHELSA v2.1 (1981–2018, ~1 km) |
| Elevation | `nasadem_elevation` | Copernicus DEM GLO-30 (AWS Open Data, 30 m) |
| Landcover | `esa_worldcover_2021` | ESA WorldCover 2021 (AWS Open Data, 10 m) |
| Rice fields | `africa_rice_fields_2023` | Jiang et al. 2023 / Zenodo (20 m) |
| Population | `worldpop_population_yearly` | WorldPop Global (100 m) |

## Algorithm notes

This implementation follows [chap-GIS](https://github.com/dhis2-chap/chap-GIS) with these adaptations:

| chap-GIS | This implementation | Notes |
|---|---|---|
| 30 m target grid | CHELSA native ~1 km | 30 m Rwanda DEM = ~150 M pixels; 1 km is sufficient for district aggregation |
| Copernicus GLO-30 via CDSE (credentials) | Same data via AWS Open Data (anonymous) | No credentials required |
| `exactextract` zonal stats | openEO `aggregate_spatial` | Framework-native, no extra dependency |
| CHAP-CSV writer | Standard CSV | Same data; column renaming left to the CHAP adapter |
| Annual mean → TPC | Annual mean → TPC | Same result; both average before or after a symmetric Gaussian |
