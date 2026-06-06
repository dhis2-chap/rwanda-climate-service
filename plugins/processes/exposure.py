"""Human exposure to mosquito breeding sites via distance-decay kernel."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process

# Distance-decay parameters from chap-GIS (calibrated for Anopheles)
_LAMBDA_M = 651.0   # horizontal decay length (metres)
_GAMMA_M = 22.5     # vertical decay length (metres above breeding site)

# WorldCover permanent-water class used to mask non-land pixels
_WATER_CLASS = 80


def _breeding_mask(landcover: xr.DataArray, rice: xr.DataArray | None = None) -> np.ndarray:
    """Identify breeding sites from WorldCover landcover and optional rice fields.

    Breeding sites:
    - Wetlands (WorldCover codes 90, 95)
    - 2-pixel buffer around permanent water (code 80)
    - Rice fields (if provided)
    """
    lc = landcover.values
    mask = np.isin(lc, [90, 95]).astype("float32")
    from scipy.ndimage import binary_dilation

    water = lc == _WATER_CLASS
    buffered = binary_dilation(water, iterations=2)
    mask = np.where(buffered, 1.0, mask)
    if rice is not None:
        mask = np.where(rice.values > 0, 1.0, mask)
    return mask


def _to_spatial_only(da: xr.DataArray) -> xr.DataArray:
    """Return a 2-D (y, x) slice, dropping any size-1 non-spatial dims.

    Static datasets (WorldCover, rice fields, elevation) carry a nominal
    t-coordinate that typically does not match the suitability time axis.
    Squeeze them to 2-D so that interp_like only needs to align the spatial axes.
    """
    for dim in list(da.dims):
        if dim not in ("y", "x") and da.sizes[dim] == 1:
            da = da.isel({dim: 0}, drop=True)
    return da


@process(
    summary="Human exposure to mosquito breeding sites",
    description=(
        "Computes a [0, 1] exposure score using a two-component distance-decay "
        "kernel from identified breeding sites (wetlands, permanent water buffers, "
        "rice fields):\n\n"
        "  exposure = exp(-d_horiz / λ) × exp(-max(Δz, 0) / γ) × suitability\n\n"
        "where d_horiz is the Euclidean distance to the nearest breeding site "
        "(λ = 651 m), and Δz = elev_pixel − elev_nearest_breeding is the "
        "elevation gain above that site (γ = 22.5 m).  The vertical term is "
        "omitted when no elevation input is provided.\n\n"
        "Pixels classified as permanent water (WorldCover class 80) are masked "
        "to NaN in the output."
    ),
)
def exposure(
    suitability: xr.DataArray,
    landcover: xr.DataArray,
    rice: xr.DataArray | None = None,
    elevation: xr.DataArray | None = None,
    pixel_size_m: float = 1000.0,
) -> xr.DataArray:
    """Exposure = distance-decay kernel convolved with breeding site mask × suitability.

    Parameters
    ----------
    suitability:
        Suitability score from :func:`suitability` process, [0, 1].
    landcover:
        ESA WorldCover classification raster (integer codes).
    rice:
        Optional binary rice field raster (1 = rice, 0 = no rice).
    elevation:
        Optional terrain elevation in metres.  When supplied, the vertical
        distance-decay term exp(-max(Δz, 0) / γ) is applied, where Δz is
        the elevation of the current pixel minus the elevation of its nearest
        breeding site.
    pixel_size_m:
        Pixel size in metres for horizontal distance computation.

    Returns
    -------
    xr.DataArray
        Dimensionless exposure score in [0, 1], same grid as suitability.
        Permanent-water pixels are set to NaN.
    """
    from scipy.ndimage import distance_transform_edt

    # Static layers carry a nominal time coordinate — collapse to (y, x) first.
    landcover = _to_spatial_only(landcover)
    if rice is not None:
        rice = _to_spatial_only(rice)
    if elevation is not None:
        elevation = _to_spatial_only(elevation)

    # Spatially align static layers to the suitability grid using a time-free slice.
    ref = suitability.isel(t=0, drop=True) if "t" in suitability.dims else suitability
    if landcover.shape != ref.shape:
        landcover = landcover.interp_like(ref, method="nearest")
    if rice is not None and rice.shape != ref.shape:
        rice = rice.interp_like(ref, method="nearest")
    if elevation is not None and elevation.shape != ref.shape:
        elevation = elevation.interp_like(ref, method="linear").astype("float32")

    breeding = _breeding_mask(landcover, rice)
    water_mask = landcover.values == _WATER_CLASS

    no_breeding = breeding == 0
    # distance_transform_edt with return_indices gives nearest-breeding-site coords
    if elevation is not None:
        dist_px, nearest_idx = distance_transform_edt(no_breeding, return_indices=True)
        elev_vals = elevation.values.astype("float32")
        elev_nearest = elev_vals[nearest_idx[0], nearest_idx[1]]
        delta_z = np.maximum(elev_vals - elev_nearest, 0.0)
        vertical_decay = np.exp(-delta_z / _GAMMA_M).astype("float32")
    else:
        dist_px = distance_transform_edt(no_breeding)
        vertical_decay = np.ones_like(breeding, dtype="float32")

    dist_m = dist_px * pixel_size_m
    horizontal_decay = np.exp(-dist_m / _LAMBDA_M).astype("float32")
    exp_score = (horizontal_decay * vertical_decay * suitability.values).astype("float32")

    # Mask permanent-water pixels
    exp_score = np.where(water_mask, np.nan, exp_score)

    # Normalise non-NaN values to [0, 1]
    max_val = np.nanmax(exp_score)
    if max_val > 0:
        exp_score = exp_score / max_val

    result = suitability.copy(data=exp_score)
    result.attrs = {
        "long_name": "human exposure to breeding sites",
        "units": "1",
        "valid_range": [0.0, 1.0],
        "horizontal_lambda_m": _LAMBDA_M,
        "vertical_gamma_m": _GAMMA_M,
    }
    return result
