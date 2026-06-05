"""Human exposure to mosquito breeding sites via distance-decay kernel."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process

# Distance-decay parameters from chap-GIS (calibrated for Anopheles)
_LAMBDA_M = 651.0   # horizontal decay length (metres)
_GAMMA_M = 22.5     # vertical/elevation decay length (metres)


def _breeding_mask(landcover: xr.DataArray, rice: xr.DataArray | None = None) -> np.ndarray:
    """Identify breeding sites from WorldCover landcover and optional rice fields.

    Breeding sites:
    - Wetlands (WorldCover codes 90, 95)
    - 2-pixel buffer around permanent water (code 80)
    - Rice fields (if provided)
    """
    lc = landcover.values
    mask = np.isin(lc, [90, 95]).astype("float32")
    # 2-pixel buffer around permanent water
    from scipy.ndimage import binary_dilation

    water = lc == 80
    buffered = binary_dilation(water, iterations=2)
    mask = np.where(buffered, 1.0, mask)
    if rice is not None:
        mask = np.where(rice.values > 0, 1.0, mask)
    return mask


@process(
    summary="Human exposure to mosquito breeding sites",
    description=(
        "Computes a [0, 1] exposure score using a distance-decay kernel from "
        "identified breeding sites (wetlands, permanent water buffers, rice fields). "
        "Horizontal decay λ=651 m, vertical decay γ=22.5 m (elevation). "
        "Multiply by suitability to get exposure-weighted suitability."
    ),
)
def exposure(
    suitability: xr.DataArray,
    landcover: xr.DataArray,
    rice: xr.DataArray | None = None,
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
    pixel_size_m:
        Pixel size in metres for distance computation.

    Returns
    -------
    xr.DataArray
        Dimensionless exposure score in [0, 1], same grid as suitability.
    """
    from scipy.ndimage import distance_transform_edt

    if landcover.shape != suitability.shape:
        landcover = landcover.interp_like(suitability, method="nearest")
    if rice is not None and rice.shape != suitability.shape:
        rice = rice.interp_like(suitability, method="nearest")

    breeding = _breeding_mask(landcover, rice)
    # Euclidean distance transform to nearest breeding site (in pixels)
    no_breeding = breeding == 0
    dist_px = distance_transform_edt(no_breeding)
    dist_m = dist_px * pixel_size_m

    decay = np.exp(-dist_m / _LAMBDA_M).astype("float32")
    # Modulate by suitability at nearest location (approximated by local suitability)
    exp_score = (decay * suitability.values).astype("float32")
    # Normalise to [0, 1]
    max_val = exp_score.max()
    if max_val > 0:
        exp_score = exp_score / max_val

    result = suitability.copy(data=exp_score)
    result.attrs = {
        "long_name": "human exposure to breeding sites",
        "units": "1",
        "valid_range": [0.0, 1.0],
    }
    return result
