# Mosquito Suitability Hotspot Workflow

Identifies high-risk mosquito breeding hotspots in Rwanda by combining temperature-based habitat suitability, landcover-derived breeding sites, rice field locations, and population exposure.

**Pipeline:** CHELSA temperature → suitability score → exposure (landcover + rice fields) → hotspots (population-weighted)

## Prerequisites

### 1. Start the service

```bash
make run
```

### 2. Ingest required datasets

All four datasets must be ingested before running the workflow.

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
```

Each ingestion request is synchronous and returns when complete. First run downloads source data to `~/.cache/chap-gis/`; subsequent runs reuse the cache.

## Run the workflow

Submit as a batch job and poll for completion:

```bash
# Submit
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Mosquito suitability hotspots",
    "process": {
      "process_graph": {
        "load_temp": {
          "process_id": "load_collection",
          "arguments": {"id": "chelsa_temperature_monthly"}
        },
        "suit": {
          "process_id": "suitability",
          "arguments": {"temperature": {"from_node": "load_temp"}}
        },
        "mean_suit": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "suit"},
            "reducer": {"process_graph": {"mean": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "load_lc": {
          "process_id": "load_collection",
          "arguments": {"id": "esa_worldcover_2021"}
        },
        "lc_2d": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "load_lc"},
            "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "load_rice": {
          "process_id": "load_collection",
          "arguments": {"id": "africa_rice_fields_2023"}
        },
        "rice_2d": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "load_rice"},
            "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "load_pop": {
          "process_id": "load_collection",
          "arguments": {
            "id": "worldpop_population_yearly",
            "temporal_extent": ["2018-01-01", "2018-12-31"]
          }
        },
        "pop_2d": {
          "process_id": "reduce_dimension",
          "arguments": {
            "data": {"from_node": "load_pop"},
            "reducer": {"process_graph": {"first": {"process_id": "first", "arguments": {"data": {"from_parameter": "data"}}, "result": true}}},
            "dimension": "t"
          }
        },
        "exp": {
          "process_id": "exposure",
          "arguments": {
            "suitability": {"from_node": "mean_suit"},
            "landcover": {"from_node": "lc_2d"},
            "rice": {"from_node": "rice_2d"}
          }
        },
        "hot": {
          "process_id": "hotspots",
          "arguments": {
            "population": {"from_node": "pop_2d"},
            "exposure": {"from_node": "exp"}
          }
        },
        "save": {
          "process_id": "save_result",
          "arguments": {"data": {"from_node": "hot"}, "format": "GTiff"},
          "result": true
        }
      }
    }
  }')
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Start
curl -s -X POST "http://localhost:8000/jobs/$JOB_ID/results"

# Poll
watch -n 5 "curl -s http://localhost:8000/jobs/$JOB_ID | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['status'])\""
```

## Output

Results are written to `data/openeo_jobs/<job-id>/results/result.tif` — a single-band GeoTIFF in WGS84 where:

- `1` = hotspot (top 10th percentile of population × exposure score)
- `0` = non-hotspot

Also downloadable via the API:

```bash
curl -O "http://localhost:8000/jobs/$JOB_ID/results/result.tif"
```

## Customisation

| Parameter | Where | Default |
|---|---|---|
| Temperature period | `chelsa_temperature_monthly` ingestion `start`/`end` | 2018-01–2018-12 |
| Population year | `worldpop_population_yearly` `temporal_extent` in process graph | 2018 |
| Hotspot threshold | `hotspots` process `percentile` argument | 90th percentile |
| Breeding site decay | `exposure.py` `_LAMBDA_M` | 651 m |

## Processes

| Process | Description |
|---|---|
| `suitability` | Gaussian thermal performance curve (Mordecai/Villena): score ∈ [0,1], peaks at 25°C, zero outside 16–34°C |
| `exposure` | Distance-decay kernel from breeding sites (wetlands, water buffers, rice fields) weighted by suitability |
| `hotspots` | Binary mask: pixels ≥ Nth percentile of population × exposure |
