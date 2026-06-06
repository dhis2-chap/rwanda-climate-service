"""Copernicus DEM GLO-30 (30 m) from AWS Open Data (public, no auth required).

Source: s3://copernicus-dem-30m/ (us-east-1, anonymous read)
Tiles: 1°×1° Cloud-Optimized GeoTIFFs at 1 arc-second (~30 m) resolution
Coverage: global land

Tiles are downloaded once and cached at ~/.cache/chap-gis/copernicus-dem-30m/.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from open_climate_service.streaming.protocol import GridSpec

_BUCKET = "copernicus-dem-30m"
_REGION = "us-east-1"
_RESOLUTION_DEG = 1 / 3600   # 1 arc-second ≈ 30 m (native Copernicus DEM GLO-30 resolution)
_CACHE = Path.home() / ".cache" / "chap-gis" / "copernicus-dem-30m"


def _tile_key(lat_floor: int, lon_floor: int) -> str:
    """Return the S3 key for the 1°×1° COG tile whose SW corner is (lat, lon)."""
    lat_str = f"N{abs(lat_floor):02d}" if lat_floor >= 0 else f"S{abs(lat_floor):02d}"
    lon_str = f"E{abs(lon_floor):03d}" if lon_floor >= 0 else f"W{abs(lon_floor):03d}"
    name = f"Copernicus_DSM_COG_10_{lat_str}_00_{lon_str}_00_DEM"
    return f"{_BUCKET}/{name}/{name}.tif"


def _tiles_for_bbox(xmin: float, ymin: float, xmax: float, ymax: float) -> list[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    lat = math.floor(ymin)
    while lat < math.ceil(ymax):
        lon = math.floor(xmin)
        while lon < math.ceil(xmax):
            tiles.add((lat, lon))
            lon += 1
        lat += 1
    return sorted(tiles)


def _ensure_tile(lat_floor: int, lon_floor: int) -> Path | None:
    """Download and cache a Copernicus DEM tile; return local path or None if tile is ocean-only."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    lat_str = f"N{abs(lat_floor):02d}" if lat_floor >= 0 else f"S{abs(lat_floor):02d}"
    lon_str = f"E{abs(lon_floor):03d}" if lon_floor >= 0 else f"W{abs(lon_floor):03d}"
    name = f"Copernicus_DSM_COG_10_{lat_str}_00_{lon_str}_00_DEM"
    target = _CACHE / f"{name}.tif"
    if target.exists():
        return target
    import s3fs

    fs = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": _REGION})
    key = _tile_key(lat_floor, lon_floor)
    try:
        fs.get(key, str(target))
    except FileNotFoundError:
        # Tile does not exist (ocean-only cell)
        return None
    return target


class ElevationPlugin:
    """Copernicus DEM GLO-30 elevation dataset plugin.

    Downloads 1°×1° COG tiles from the publicly accessible AWS S3 bucket
    on first use and caches them locally.  Returns elevation in metres on a
    WGS-84 grid.
    """

    max_concurrency = 1
    commit_batch_size = 1

    def __init__(self, **_: Any) -> None:
        pass

    async def probe(self, bbox: list[float], **_: Any) -> GridSpec:
        xmin, ymin, xmax, ymax = map(float, bbox)
        nx = max(1, math.ceil((xmax - xmin) / _RESOLUTION_DEG))
        ny = max(1, math.ceil((ymax - ymin) / _RESOLUTION_DEG))
        return GridSpec(
            shape=(ny, nx),
            crs=4326,
            dtype=np.dtype("float32"),
            nodata=np.nan,
            time_dim="t",
            x_dim="x",
            y_dim="y",
        )

    async def periods(self, start: str, end: str, **_: Any) -> list[str]:
        return ["2021"]

    async def fetch_period(self, period_id: str, bbox: list[float], **_: Any) -> xr.Dataset:
        return await asyncio.to_thread(self._fetch_sync, bbox)

    def _fetch_sync(self, bbox: list[float]) -> xr.Dataset:
        import rioxarray  # noqa: F401

        xmin, ymin, xmax, ymax = map(float, bbox)
        tile_coords = _tiles_for_bbox(xmin, ymin, xmax, ymax)

        arrays: list[xr.DataArray] = []
        for lat_f, lon_f in tile_coords:
            path = _ensure_tile(lat_f, lon_f)
            if path is None:
                continue
            da = xr.open_dataarray(path, engine="rasterio").squeeze(drop=True)
            da = da.rename({"x": "x", "y": "y"})
            arrays.append(da.load())

        if not arrays:
            raise RuntimeError(f"No elevation tiles found for bbox {bbox}")

        # Ensure all tiles have consistent name before combining
        named = [a.rename("elevation") for a in arrays]

        if len(named) == 1:
            mosaic = named[0]
        else:
            mosaic = xr.combine_by_coords(named, combine_attrs="drop_conflicts")
            if isinstance(mosaic, xr.Dataset):
                mosaic = mosaic["elevation"]

        # Crop to bbox; y is north-first in the COGs
        da = mosaic.sel(x=slice(xmin, xmax), y=slice(ymax, ymin))
        da = da.astype("float32")
        da.attrs = {"long_name": "elevation above mean sea level", "units": "m"}
        da.name = "elevation"

        ts = np.datetime64("2021-01-01", "D").astype("datetime64[ns]")
        da_out = xr.DataArray(
            da.values[np.newaxis],
            dims=["t", "y", "x"],
            coords={"t": [ts], "y": da.y.values, "x": da.x.values},
            attrs=da.attrs,
        )
        return xr.Dataset({"elevation": da_out})
