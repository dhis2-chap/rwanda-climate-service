"""ESA WorldCover 10m landcover from AWS Open Data (public, no auth required).

Source: s3://esa-worldcover/v200/2021/map/
Same product as Copernicus CDSE — 11-class landcover at 10m, EPSG:4326.
Tiles downloaded once and cached at ~/.cache/chap-gis/.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from open_climate_service.streaming.protocol import GridSpec

_S3_BASE = "s3://esa-worldcover/v200/2021/map"
_RESOLUTION_DEG = 10 / 111_320  # 10 m in degrees (approx at equator)
_TILE_SIZE_DEG = 3  # WorldCover tiles are 3°×3°


def _tile_name(lat: float, lon: float) -> str:
    """Return tile name for the 3°×3° cell whose lower-left corner contains (lat, lon)."""
    row = math.floor(lat / _TILE_SIZE_DEG) * _TILE_SIZE_DEG
    col = math.floor(lon / _TILE_SIZE_DEG) * _TILE_SIZE_DEG
    lat_str = f"N{row:02d}" if row >= 0 else f"S{abs(row):02d}"
    lon_str = f"E{col:03d}" if col >= 0 else f"W{abs(col):03d}"
    return f"ESA_WorldCover_10m_2021_v200_{lat_str}{lon_str}_Map.tif"


def _tiles_for_bbox(xmin: float, ymin: float, xmax: float, ymax: float) -> list[str]:
    """Return all tile names that overlap the given bounding box."""
    tiles = set()
    lat = math.floor(ymin / _TILE_SIZE_DEG) * _TILE_SIZE_DEG
    while lat < ymax:
        lon = math.floor(xmin / _TILE_SIZE_DEG) * _TILE_SIZE_DEG
        while lon < xmax:
            tiles.add(_tile_name(lat, lon))
            lon += _TILE_SIZE_DEG
        lat += _TILE_SIZE_DEG
    return sorted(tiles)


def _ensure_tile(tile: str) -> Path:
    cache_dir = Path.home() / ".cache" / "chap-gis"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / tile
    if not target.exists():
        import s3fs

        fs = s3fs.S3FileSystem(anon=True)
        fs.get(f"{_S3_BASE}/{tile}", str(target))
    return target


class WorldCoverPlugin:
    """ESA WorldCover 10m 2021 (v200) landcover plugin.

    Tiles are fetched from the AWS Open Data public S3 bucket on first use
    and cached at ~/.cache/chap-gis/. No credentials required.

    Classes:
      10  Tree cover        20  Shrubland         30  Grassland
      40  Cropland          50  Built-up           60  Bare / sparse veg
      70  Snow and ice      80  Permanent water    90  Herbaceous wetland
      95  Mangroves        100  Moss and lichen
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
            dtype=np.dtype("uint8"),
            nodata=0,
            time_dim="t",
            x_dim="x",
            y_dim="y",
        )

    async def periods(self, start: str, end: str, **_: Any) -> list[str]:
        if start[:4] <= "2021" <= end[:4]:
            return ["2021"]
        return []

    async def fetch_period(self, period_id: str, bbox: list[float], **_: Any) -> xr.Dataset:
        return await asyncio.to_thread(self._fetch_sync, bbox)

    def _fetch_sync(self, bbox: list[float]) -> xr.Dataset:
        import rioxarray  # noqa: F401

        xmin, ymin, xmax, ymax = map(float, bbox)
        tiles = _tiles_for_bbox(xmin, ymin, xmax, ymax)

        arrays = []
        for tile in tiles:
            path = _ensure_tile(tile)
            da = xr.open_dataarray(path, engine="rasterio").squeeze(drop=True)
            arrays.append(da)

        if len(arrays) == 1:
            merged = arrays[0]
        else:
            combined = xr.combine_by_coords(arrays, combine_attrs="drop_conflicts")
            if isinstance(combined, xr.Dataset):
                merged = combined[list(combined.data_vars)[0]]
            else:
                merged = combined
        clipped = merged.sel(x=slice(xmin, xmax), y=slice(ymax, ymin)).load()

        ts = np.datetime64("2021-01-01", "D").astype("datetime64[ns]")
        da_out = xr.DataArray(
            clipped.values.astype("uint8")[np.newaxis],
            dims=["t", "y", "x"],
            coords={"t": [ts], "y": clipped.y.values, "x": clipped.x.values},
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
