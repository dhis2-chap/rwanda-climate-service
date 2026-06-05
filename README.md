# Rwanda Climate Service

An [Open Climate Service](https://dhis2.github.io/open-climate-service/) instance configured for Rwanda.

## Setup

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Configure credentials (see [ERA5-Land datasets](https://dhis2.github.io/open-climate-service/era5_land_datasets/) for EDH and CDS setup).

3. Start the service:
   ```bash
   make run
   ```

The API will be available at http://127.0.0.1:8000.
