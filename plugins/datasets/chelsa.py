"""CHELSA v2.1 monthly temperature streaming plugin."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import numpy as np
import xarray as xr

from open_climate_service.streaming.protocol import GridSpec

# CHELSA v2.1 monthly mean temperature (tas) on SwitchDrive
# _CHELSA_URL = (
#     "https://os.zhdk.cloud.switch.ch/chelsav2/"
#     "GLOBAL/monthly/tas/CHELSA_tas_{month:02d}_{year}_V.2.1.tif"
# )

CHELSA_URL_2 = (
    "https://os.unil.cloud.switch.ch/chelsa02/chelsa/global/monthly/{variable}/{year}/"
        "CHELSA_{variable}_{month:02d}_{year}_{version}.tif"
)

# CHELSA resolution: 30 arc-seconds ≈ 0.00833° ≈ 1 km
_CHELSA_RES_DEG = 30 / 3600


class CHELSATemperaturePlugin:
    """Streaming plugin for CHELSA v2.1 monthly mean temperature.

    Downloads individual monthly GeoTIFF files from the CHELSA archive.
    Values are in Kelvin × 10 + offset; converted to °C at fetch time.

    Coverage: 1981–2018 (V2.1 climatology period).
    """

    max_concurrency = 2
    commit_batch_size = 12

    async def probe(self, bbox: list[float], **_: Any) -> GridSpec:
        import math

        xmin, ymin, xmax, ymax = map(float, bbox)
        nx = max(1, math.ceil((xmax - xmin) / _CHELSA_RES_DEG))
        ny = max(1, math.ceil((ymax - ymin) / _CHELSA_RES_DEG))
        return GridSpec(
            shape=(ny, nx),
            crs=4326,
            dtype=np.dtype("float32"),
            nodata=None,
            time_dim="t",
            x_dim="x",
            y_dim="y",
        )

    async def periods(self, start: str, end: str) -> list[str]:
        start_dt = date.fromisoformat(start[:7] + "-01")
        end_dt = date.fromisoformat(end[:7] + "-01")
        # CHELSA V2.1 covers 1981–2018
        end_dt = min(end_dt, date(2021, 12, 1))
        if start_dt > end_dt:
            return []
        result: list[str] = []
        current = start_dt
        while current <= end_dt:
            result.append(f"{current.year:04d}-{current.month:02d}")
            month = current.month % 12 + 1
            year = current.year + (1 if current.month == 12 else 0)
            current = date(year, month, 1)
        return result

    async def fetch_period(self, period_id: str, bbox: list[float], **_: Any) -> xr.Dataset:
        return await asyncio.to_thread(self._fetch_sync, period_id, bbox)

    def _fetch_sync(self, period_id: str, bbox: list[float]) -> xr.Dataset:
        import rioxarray  # noqa: F401

        year, month = int(period_id[:4]), int(period_id[5:7])
        url = CHELSA_URL_2.format(variable="tas", year=year, month=month, version="V.2.1")
        xmin, ymin, xmax, ymax = map(float, bbox)

        da = xr.open_dataarray(url, engine="rasterio", mask_and_scale=False).squeeze(drop=True)
        # Clip to bbox
        da = da.sel(x=slice(xmin, xmax), y=slice(ymax, ymin))
        da = da.load()

        # CHELSA V2.1 tas is stored as Kelvin × 10 (scale_factor 0.1 → K). rioxarray
        # returns the raw integer values (mask_and_scale is off by default), so we
        # apply scale/offset ourselves and convert K → °C.
        scale = da.attrs.get("scale_factor", 0.1)
        offset = da.attrs.get("add_offset", 0.0)
        temp_c = (da.values.astype("float32") * scale + offset) - 273.15

        # Guard against a scale/encoding change silently producing nonsense (e.g. if
        # rioxarray ever starts auto-applying scale_factor and we double-scale).
        finite = temp_c[np.isfinite(temp_c)]
        if finite.size and (finite.min() < -90.0 or finite.max() > 60.0):
            raise ValueError(
                f"CHELSA temperature for {period_id} is outside the physical range "
                f"[{finite.min():.1f}, {finite.max():.1f}] °C — check scale_factor handling."
            )

        ts = np.datetime64(f"{period_id}-01", "D").astype("datetime64[ns]")
        da_c = xr.DataArray(
            temp_c[np.newaxis],
            dims=["t", "y", "x"],
            coords={
                "t": [ts],
                "y": da.y.values,
                "x": da.x.values,
            },
        )
        da_c.attrs["units"] = "degC"
        return xr.Dataset({"temperature": da_c})
