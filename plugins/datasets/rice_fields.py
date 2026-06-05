"""Africa rice fields static dataset plugin (Jiang et al. 2023, Zenodo 13729353)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from open_climate_service.streaming.protocol import GridSpec

_ZENODO_RECORD = "13729353"
_ZENODO_URL = f"https://zenodo.org/records/{_ZENODO_RECORD}/files/Africa_rice_paddies_2023_20m.tif"
_RESOLUTION_DEG = 20 / (111_320)  # 20m in degrees (approx)


class RiceFieldsPlugin:
    """Static plugin for Africa rice field raster (Jiang et al. 2023).

    Single-period dataset (2023). Downloads from Zenodo on first fetch
    and caches locally.

    Source: Zenodo record 13729353 (CC-BY-4.0)
    Resolution: 20 m
    Coverage: Africa
    """

    max_concurrency = 1
    commit_batch_size = 1

    def __init__(self, **_: Any) -> None:
        self._cached_path: Path | None = None

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
        # Static 2023 dataset — only one period
        if start[:4] <= "2023" <= end[:4]:
            return ["2023"]
        return []

    async def fetch_period(self, period_id: str, bbox: list[float], **_: Any) -> xr.Dataset:
        return await asyncio.to_thread(self._fetch_sync, period_id, bbox)

    def _fetch_sync(self, period_id: str, bbox: list[float]) -> xr.Dataset:
        import rioxarray  # noqa: F401

        local = self._ensure_downloaded()
        xmin, ymin, xmax, ymax = map(float, bbox)

        da = xr.open_dataarray(local, engine="rasterio").squeeze(drop=True)
        da = da.sel(x=slice(xmin, xmax), y=slice(ymax, ymin)).load()

        ts = np.datetime64("2023-01-01", "D").astype("datetime64[ns]")
        da_out = xr.DataArray(
            da.values.astype("uint8")[np.newaxis],
            dims=["t", "y", "x"],
            coords={"t": [ts], "y": da.y.values, "x": da.x.values},
        )
        da_out.attrs["flag_values"] = [0, 1]
        da_out.attrs["flag_meanings"] = "no_rice rice"
        return xr.Dataset({"rice": da_out})

    def _ensure_downloaded(self) -> Path:
        cache_dir = Path.home() / ".cache" / "chap-gis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / "Africa_rice_paddies_2023_20m.tif"
        if not target.exists():
            import httpx

            with httpx.stream("GET", _ZENODO_URL, follow_redirects=True, timeout=300) as r:
                r.raise_for_status()
                with target.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        return target
