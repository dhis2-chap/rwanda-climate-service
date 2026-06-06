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
        "Computes an exposure field using a two-component distance-decay kernel "
        "from breeding sites, optionally weighted by the thermal suitability at "
        "the nearest breeding site (matching chap-GIS exposure.exposure):\n\n"
        "  exposure(x) = exp(−d(x) / λ) × exp(−max(Δz(x), 0) / γ) × S(T_nearest)\n\n"
        "where d(x) is the Euclidean distance to the nearest breeding site "
        "(λ = 651 m), Δz(x) = elev(x) − elev(nearest site) is the elevation "
        "gain (γ = 22.5 m), and S(T_nearest) is the thermal suitability at "
        "the nearest breeding site (1 if not provided).\n\n"
        "Permanent-water pixels (NaN in breeding_mask) are set to NaN in the output."
    ),
)
def exposure(
    breeding_mask: xr.DataArray,
    elevation: xr.DataArray | None = None,
    suitability: xr.DataArray | None = None,
    pixel_size_m: float | None = None,
) -> xr.DataArray:
    """Distance-decay exposure kernel from mosquito breeding sites.

    Matches chap-GIS exposure.exposure: suitability is sampled at the nearest
    breeding site, not at the target pixel.

    Parameters
    ----------
    breeding_mask:
        Float32 mask: 1 = breeding site, 0 = non-breeding land, NaN = water.
        From :func:`breeding_site_mask`.
    elevation:
        Optional terrain elevation in metres for vertical decay.
    suitability:
        Optional thermal suitability raster (same grid as breeding_mask).
        When provided, exposure is weighted by the suitability value at the
        nearest breeding site — identical to chap-GIS's approach.
    pixel_size_m:
        Pixel size in metres.  Inferred from breeding_mask x-coordinates when
        None (WGS-84 equatorial approximation: 1° ≈ 111 320 m).

    Returns
    -------
    xr.DataArray
        Exposure field (no fixed upper bound; ≤ 1 when suitability ≤ 1),
        same grid as breeding_mask.  Permanent-water pixels are NaN.
    """
    from scipy.ndimage import distance_transform_edt

    if pixel_size_m is None:
        if breeding_mask.x.size > 1:
            dx_deg = float(abs(float(breeding_mask.x[1]) - float(breeding_mask.x[0])))
            pixel_size_m = dx_deg * 111_320.0
        else:
            pixel_size_m = 30.0

    if elevation is not None:
        elevation = _to_spatial_only(elevation)
        if elevation.shape != breeding_mask.shape:
            elevation = elevation.interp_like(breeding_mask, method="linear").astype("float32")

    if suitability is not None:
        suitability = _to_spatial_only(suitability)
        if suitability.shape != breeding_mask.shape:
            suitability = suitability.interp_like(breeding_mask, method="linear").astype("float32")

    mask_vals = breeding_mask.values.astype("float32")
    water_mask = np.isnan(mask_vals)
    is_breeding = np.where(water_mask, False, mask_vals > 0)
    no_breeding = ~is_breeding

    # Always compute indices when elevation or suitability needs nearest-site lookup
    need_indices = elevation is not None or suitability is not None
    if need_indices:
        dist_px, nearest_idx = distance_transform_edt(no_breeding, return_indices=True)
    else:
        dist_px = distance_transform_edt(no_breeding)

    dist_m = dist_px * pixel_size_m
    horizontal_decay = np.exp(-dist_m / _LAMBDA_M).astype("float32")

    if elevation is not None:
        elev_vals = elevation.values.astype("float32")
        elev_nearest = elev_vals[nearest_idx[0], nearest_idx[1]]
        delta_z = np.maximum(elev_vals - elev_nearest, 0.0)
        vertical_decay = np.exp(-delta_z / _GAMMA_M).astype("float32")
    else:
        vertical_decay = np.ones(mask_vals.shape, dtype="float32")

    exp_score = (horizontal_decay * vertical_decay).astype("float32")

    if suitability is not None:
        suit_vals = suitability.values.astype("float32")
        # Weight by suitability at the nearest breeding site (chap-GIS convention)
        nearest_suit = suit_vals[nearest_idx[0], nearest_idx[1]]
        nearest_suit = np.where(np.isfinite(nearest_suit), nearest_suit, 0.0)
        exp_score *= nearest_suit
        # At breeding sites: use their own suitability directly
        exp_score[is_breeding] = np.where(
            np.isfinite(suit_vals[is_breeding]), suit_vals[is_breeding], 0.0
        )

    # Apply water mask (NaN propagates through)
    exp_score = np.where(water_mask, np.nan, exp_score)

    result = breeding_mask.copy(data=exp_score)
    result.attrs = {
        "long_name": "distance-decay exposure from breeding sites",
        "units": "1",
        "horizontal_lambda_m": _LAMBDA_M,
        "vertical_gamma_m": _GAMMA_M,
    }
    result.name = "exposure"
    return result
