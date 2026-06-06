"""Identify mosquito breeding sites from landcover and rice field data."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process

# WorldCover class codes
_WETLAND_CLASSES = [90, 95]   # herbaceous wetlands, mangroves
_WATER_CLASS = 80              # permanent water bodies
_WATER_BUFFER_PX = 2           # dilation radius around permanent water


def _to_spatial_only(da: xr.DataArray) -> xr.DataArray:
    for dim in list(da.dims):
        if dim not in ("y", "x") and da.sizes[dim] == 1:
            da = da.isel({dim: 0}, drop=True)
    return da


@process(
    summary="Identify mosquito breeding sites from ESA WorldCover and rice fields",
    description=(
        "Returns a binary breeding-site mask derived from ESA WorldCover landcover "
        "and optional rice field data.\n\n"
        "Breeding sites:\n"
        "- Wetlands (WorldCover classes 90, 95)\n"
        "- 2-pixel buffer around permanent water (class 80)\n"
        "- Rice fields (where provided)\n\n"
        "Output values:\n"
        "- 1 = breeding site\n"
        "- 0 = non-breeding land\n"
        "- NaN = permanent water (class 80) — masked out in downstream exposure computation"
    ),
)
def breeding_site_mask(
    landcover: xr.DataArray,
    rice: xr.DataArray | None = None,
) -> xr.DataArray:
    """Binary breeding-site mask from WorldCover landcover and optional rice fields.

    Parameters
    ----------
    landcover:
        ESA WorldCover classification raster (integer codes, EPSG:4326).
    rice:
        Optional binary rice field raster (1 = rice, 0 = no rice).

    Returns
    -------
    xr.DataArray
        Float32 mask: 1 = breeding site, 0 = non-breeding land, NaN = permanent water.
        Same spatial grid as landcover.
    """
    from scipy.ndimage import binary_dilation

    landcover = _to_spatial_only(landcover)
    if rice is not None:
        rice = _to_spatial_only(rice)
        if rice.shape != landcover.shape:
            rice = rice.interp_like(landcover, method="nearest")

    lc = landcover.values

    mask = np.isin(lc, _WETLAND_CLASSES).astype("float32")

    water = lc == _WATER_CLASS
    buffered_water = binary_dilation(water, iterations=_WATER_BUFFER_PX)
    mask = np.where(buffered_water & ~water, 1.0, mask)

    if rice is not None:
        mask = np.where(rice.values > 0, 1.0, mask)

    # Encode permanent water as NaN so exposure can apply a water mask without
    # needing the original landcover array.
    mask = np.where(water, np.nan, mask)

    result = xr.DataArray(
        mask,
        dims=landcover.dims,
        coords=landcover.coords,
        attrs={
            "long_name": "mosquito breeding site mask",
            "flag_values": [0, 1],
            "flag_meanings": "non_breeding breeding",
            "water_encoded_as": "NaN",
        },
    )
    result.name = "breeding_mask"
    return result
