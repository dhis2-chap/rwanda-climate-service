"""Mosquito exposure via distance-decay kernel from breeding sites."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process

_LAMBDA_M = 651.0   # horizontal decay length (metres)
_GAMMA_M = 22.5     # vertical decay length (metres above breeding site)


def _to_spatial_only(da: xr.DataArray) -> xr.DataArray:
    for dim in list(da.dims):
        if dim not in ("y", "x") and da.sizes[dim] == 1:
            da = da.isel({dim: 0}, drop=True)
    return da


@process(
    summary="Distance-decay exposure field from breeding sites",
    description=(
        "Computes a [0, 1] exposure field using a two-component distance-decay "
        "kernel from breeding sites identified by the breeding_site_mask process:\n\n"
        "  exposure(x) = exp(−d(x) / λ) × exp(−max(Δz(x), 0) / γ)\n\n"
        "where d(x) is the Euclidean distance to the nearest breeding site "
        "(λ = 651 m) and Δz(x) = elev(x) − elev(nearest breeding site) is "
        "the elevation gain above that site (γ = 22.5 m, omitted when no "
        "elevation is provided).\n\n"
        "Permanent-water pixels (NaN in breeding_mask) are set to NaN in the output.\n\n"
        "Multiply the result by a suitability raster in the process graph to "
        "produce habitat-weighted exposure."
    ),
)
def exposure(
    breeding_mask: xr.DataArray,
    elevation: xr.DataArray | None = None,
    pixel_size_m: float = 1000.0,
) -> xr.DataArray:
    """Distance-decay exposure kernel from mosquito breeding sites.

    Parameters
    ----------
    breeding_mask:
        Binary breeding-site mask from :func:`breeding_site_mask`:
        1 = breeding site, 0 = non-breeding land, NaN = permanent water.
    elevation:
        Optional terrain elevation in metres.  When supplied, the vertical
        decay term exp(−max(Δz, 0) / γ) is applied using the elevation of
        the nearest breeding site as the reference.
    pixel_size_m:
        Pixel size in metres for horizontal distance computation.

    Returns
    -------
    xr.DataArray
        Dimensionless exposure field in [0, 1], same grid as breeding_mask.
        Permanent-water pixels are NaN.
    """
    from scipy.ndimage import distance_transform_edt

    if elevation is not None:
        elevation = _to_spatial_only(elevation)
        if elevation.shape != breeding_mask.shape:
            elevation = elevation.interp_like(breeding_mask, method="linear").astype("float32")

    mask_vals = breeding_mask.values.astype("float32")
    water_mask = np.isnan(mask_vals)
    # Treat water as non-breeding for the distance transform (mosquitoes don't
    # breed in open water, but adjacent pixels do get exposure from nearby sites).
    is_breeding = np.where(water_mask, False, mask_vals > 0)
    no_breeding = ~is_breeding

    if elevation is not None:
        dist_px, nearest_idx = distance_transform_edt(no_breeding, return_indices=True)
        elev_vals = elevation.values.astype("float32")
        elev_nearest = elev_vals[nearest_idx[0], nearest_idx[1]]
        delta_z = np.maximum(elev_vals - elev_nearest, 0.0)
        vertical_decay = np.exp(-delta_z / _GAMMA_M).astype("float32")
    else:
        dist_px = distance_transform_edt(no_breeding)
        vertical_decay = np.ones(mask_vals.shape, dtype="float32")

    dist_m = dist_px * pixel_size_m
    horizontal_decay = np.exp(-dist_m / _LAMBDA_M).astype("float32")
    exp_score = (horizontal_decay * vertical_decay).astype("float32")

    # Apply water mask
    exp_score = np.where(water_mask, np.nan, exp_score)

    # Normalise non-NaN values to [0, 1]
    max_val = float(np.nanmax(exp_score))
    if max_val > 0:
        exp_score = exp_score / max_val

    result = breeding_mask.copy(data=exp_score)
    result.attrs = {
        "long_name": "distance-decay exposure from breeding sites",
        "units": "1",
        "valid_range": [0.0, 1.0],
        "horizontal_lambda_m": _LAMBDA_M,
        "vertical_gamma_m": _GAMMA_M,
    }
    result.name = "exposure"
    return result
