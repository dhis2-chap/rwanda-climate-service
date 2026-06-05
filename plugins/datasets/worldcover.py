"""ESA WorldCover 10m landcover via Copernicus CDSE openEO.

Requires a free CDSE account (dataspace.copernicus.eu) and credentials
set via the CDSE_USERNAME / CDSE_PASSWORD environment variables or via
OIDC device-flow authentication.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from open_climate_service.streaming.protocol import GridSpec

_CDSE_URL = "https://openeo.dataspace.copernicus.eu"
_COLLECTION = "ESA_WORLDCOVER_10M_2021_V2"
_RESOLUTION_DEG = 10 / 111_320  # 10 m in degrees


def _connect():
    """Return an authenticated CDSE openEO connection."""
    import openeo

    conn = openeo.connect(_CDSE_URL)
    username = os.environ.get("CDSE_USERNAME")
    password = os.environ.get("CDSE_PASSWORD")
    if username and password:
        conn.authenticate_basic(username, password)
    else:
        # Interactive OIDC device-flow (prints a URL to visit)
        conn.authenticate_oidc()
    return conn


class WorldCoverPlugin:
    """Static plugin for ESA WorldCover 10m landcover via Copernicus CDSE openEO.

    Downloads a single scene for the configured extent via the CDSE openEO
    synchronous execution endpoint.  Results are cached locally so subsequent
    ingestion runs skip the download.

    Available years: 2020 (V1), 2021 (V2 — default).
    """

    max_concurrency = 1
    commit_batch_size = 1

    def __init__(self, year: int = 2021, **_: Any) -> None:
        self.year = year
        self._cache: dict[tuple, Path] = {}

    async def probe(self, bbox: list[float], **_: Any) -> GridSpec:
        import math

        xmin, ymin, xmax, ymax = map(float, bbox)
        nx = max(1, math.ceil((xmax - xmin) / _RESOLUTION_DEG))
        ny = max(1, math.ceil((ymax - ymin) / _RESOLUTION_DEG))
        return GridSpec(
            shape=(ny, nx),
            crs=4326,
            dtype=np.dtype("uint8"),
            nodata=0,
            time_dim="t",
            x_dim="x",
            y_dim="y",
        )

    async def periods(self, start: str, end: str) -> list[str]:
        year_str = str(self.year)
        if start[:4] <= year_str <= end[:4]:
            return [year_str]
        return []

    async def fetch_period(self, period_id: str, bbox: list[float], **_: Any) -> xr.Dataset:
        return await asyncio.to_thread(self._fetch_sync, period_id, bbox)

    def _fetch_sync(self, period_id: str, bbox: list[float]) -> xr.Dataset:
        import rioxarray  # noqa: F401

        xmin, ymin, xmax, ymax = map(float, bbox)
        cache_key = (self.year, round(xmin, 4), round(ymin, 4), round(xmax, 4), round(ymax, 4))

        if cache_key not in self._cache:
            cache_dir = Path.home() / ".cache" / "chap-gis"
            cache_dir.mkdir(parents=True, exist_ok=True)
            target = cache_dir / f"worldcover_{self.year}_{xmin:.4f}_{ymin:.4f}_{xmax:.4f}_{ymax:.4f}.tif"

            if not target.exists():
                conn = _connect()
                cube = conn.load_collection(
                    _COLLECTION,
                    spatial_extent={"west": xmin, "south": ymin, "east": xmax, "north": ymax},
                    temporal_extent=[f"{self.year}-01-01", f"{self.year}-12-31"],
                )
                cube.download(str(target), format="GTiff")

            self._cache[cache_key] = target

        local = self._cache[cache_key]
        da = xr.open_dataarray(local, engine="rasterio").squeeze(drop=True)
        da = da.sel(x=slice(xmin, xmax), y=slice(ymax, ymin)).load()

        ts = np.datetime64(f"{self.year}-01-01", "D").astype("datetime64[ns]")
        da_out = xr.DataArray(
            da.values.astype("uint8")[np.newaxis],
            dims=["t", "y", "x"],
            coords={"t": [ts], "y": da.y.values, "x": da.x.values},
        )
        da_out.attrs.update({
            "long_name": "ESA WorldCover landcover classification",
            "flag_values": [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100],
            "flag_meanings": (
                "tree_cover shrubland grassland cropland built_up "
                "bare_sparse_veg snow_ice permanent_water herbaceous_wetland "
                "mangroves moss_lichen"
            ),
        })
        return xr.Dataset({"landcover": da_out})
