"""Resample a datacube to match the spatial grid of a target cube."""

from __future__ import annotations

import xarray as xr

from open_climate_service.process import process


def _to_spatial_only(da: xr.DataArray) -> xr.DataArray:
    for dim in list(da.dims):
        if dim not in ("y", "x") and da.sizes[dim] == 1:
            da = da.isel({dim: 0}, drop=True)
    return da


@process(
    summary="Resample a datacube to the spatial grid of a target cube",
    description=(
        "Reprojects data onto the x/y grid of target using xarray interp_like. "
        "Does not require CRS metadata — use in place of resample_cube_spatial "
        "when the arrays lack odc-geo geobox information.\n\n"
        "method: 'near' or 'nearest' → nearest-neighbour; 'linear' → bilinear."
    ),
)
def resample_to_target(
    data: xr.DataArray,
    target: xr.DataArray,
    method: str = "linear",
) -> xr.DataArray:
    """Resample data to the spatial grid of target using interp_like.

    Parameters
    ----------
    data:
        DataArray to resample.
    target:
        DataArray whose (y, x) coordinates define the output grid.
    method:
        Interpolation method: 'near'/'nearest' for nearest-neighbour,
        'linear' for bilinear (default).

    Returns
    -------
    xr.DataArray
        data resampled to target's spatial grid.
    """
    data = _to_spatial_only(data)
    target = _to_spatial_only(target)
    interp_method = "nearest" if method in ("near", "nearest") else method
    result = data.interp_like(target, method=interp_method)
    result.attrs = data.attrs
    return result
