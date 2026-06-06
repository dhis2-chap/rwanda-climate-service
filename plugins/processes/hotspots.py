"""High-risk area (hotspot) identification from population-weighted exposure."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process


@process(
    summary="Binary hotspot mask from population-weighted exposure",
    description=(
        "Marks pixels at or above the Nth percentile of non-zero population-weighted "
        "exposure as hotspots (1); all others are 0.  NaN pixels (e.g. water) remain 0.\n\n"
        "Compute pop_exposure = population × exposure in the process graph before "
        "calling this process — use multiply_cubes after aligning population to "
        "the exposure grid with resample_cube_spatial."
    ),
)
def hotspots(
    pop_exposure: xr.DataArray,
    percentile: float = 90.0,
) -> xr.DataArray:
    """Binary hotspot mask: pixels ≥ Nth percentile of non-zero population exposure.

    Parameters
    ----------
    pop_exposure:
        Population-weighted exposure score (population × exposure), 2-D (y, x).
        Produced by multiplying WorldPop population by the exposure field.
    percentile:
        Percentile threshold for hotspot classification (default 90).

    Returns
    -------
    xr.DataArray
        Binary mask (uint8): 1 = hotspot, 0 = non-hotspot.
    """
    vals = pop_exposure.values.astype("float32")
    nonzero = vals[np.isfinite(vals) & (vals > 0)]
    if len(nonzero) == 0:
        mask = np.zeros_like(vals, dtype="uint8")
        threshold = 0.0
    else:
        threshold = float(np.percentile(nonzero, percentile))
        mask = np.where(np.isfinite(vals) & (vals >= threshold), 1, 0).astype("uint8")

    result = pop_exposure.copy(data=mask)
    result.attrs = {
        "long_name": f"hotspot mask (p{percentile:.0f})",
        "units": "1",
        "flag_values": [0, 1],
        "flag_meanings": "non_hotspot hotspot",
        "threshold": threshold,
        "percentile": percentile,
    }
    return result
