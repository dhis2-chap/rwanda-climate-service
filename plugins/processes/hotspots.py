"""High-risk area (hotspot) identification from population exposure."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process


def _to_spatial_only(da: xr.DataArray) -> xr.DataArray:
    """Return a 2-D (y, x) slice by dropping any size-1 non-spatial dims.

    Population rasters typically have a yearly time axis that doesn't match
    the monthly exposure grid.  Collapse to (y, x) before spatial alignment.
    """
    for dim in list(da.dims):
        if dim not in ("y", "x") and da.sizes[dim] == 1:
            da = da.isel({dim: 0}, drop=True)
    # If multiple time steps remain, take the last (most recent year).
    for dim in list(da.dims):
        if dim not in ("y", "x"):
            da = da.isel({dim: -1}, drop=True)
    return da


@process(
    summary="Identify high-risk hotspot areas from population exposure",
    description=(
        "Marks pixels at or above the specified percentile of nonzero population "
        "exposure values as hotspots (1), all others as 0. Default threshold is "
        "the 90th percentile, matching the chap-GIS definition."
    ),
)
def hotspots(
    population: xr.DataArray,
    exposure: xr.DataArray,
    percentile: float = 90.0,
) -> xr.DataArray:
    """Binary hotspot mask: pixels ≥ Nth percentile of nonzero population exposure.

    Parameters
    ----------
    population:
        Population count per pixel (WorldPop or similar).
    exposure:
        Dimensionless exposure score from :func:`exposure` process, [0, 1].
    percentile:
        Percentile threshold for hotspot classification (default 90).

    Returns
    -------
    xr.DataArray
        Binary mask: 1 = hotspot, 0 = non-hotspot, same grid as inputs.
    """
    # Population rasters carry a time axis (yearly) that differs from the
    # monthly exposure grid — collapse to (y, x) first.
    population = _to_spatial_only(population)

    # Spatially align to the exposure grid using a time-free reference slice.
    ref = exposure.isel(t=0, drop=True) if "t" in exposure.dims else exposure
    if population.shape != ref.shape:
        population = population.interp_like(ref, method="nearest")

    pop_exp = (population.values * exposure.values).astype("float32")
    nonzero = pop_exp[pop_exp > 0]
    if len(nonzero) == 0:
        threshold = 0.0
    else:
        threshold = float(np.percentile(nonzero, percentile))

    mask = (pop_exp >= threshold).astype("uint8")

    result = exposure.copy(data=mask)
    result.attrs = {
        "long_name": f"hotspot mask (p{percentile:.0f})",
        "units": "1",
        "flag_values": [0, 1],
        "flag_meanings": "non_hotspot hotspot",
        "threshold": threshold,
        "percentile": percentile,
    }
    return result
