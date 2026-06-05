"""Mosquito habitat suitability from monthly temperature (Mordecai/Villena thermal curve)."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process

_T_OPT = 25.0   # °C optimal for Anopheles
_SIGMA = 5.0    # °C width parameter
_T_MIN = 16.0   # °C lower thermal limit
_T_MAX = 34.0   # °C upper thermal limit


@process(
    summary="Mosquito habitat suitability score from temperature",
    description=(
        "Computes a [0, 1] suitability score using the Mordecai/Villena Gaussian "
        "thermal performance curve. Suitability is zero outside 16–34 °C and peaks "
        "at 25 °C. Input temperature must be in °C."
    ),
)
def suitability(temperature: xr.DataArray) -> xr.DataArray:
    """Gaussian thermal performance curve for Anopheles mosquitoes.

    S(T) = exp(-((T - T_opt) / σ)²)  for T_min ≤ T ≤ T_max, else 0.

    Parameters
    ----------
    temperature:
        Monthly or daily mean air temperature in °C.

    Returns
    -------
    xr.DataArray
        Dimensionless suitability score in [0, 1], same grid as input.
    """
    t = temperature.values.astype("float32")
    s = np.exp(-(((t - _T_OPT) / _SIGMA) ** 2))
    s = np.where((t >= _T_MIN) & (t <= _T_MAX), s, 0.0).astype("float32")

    result = temperature.copy(data=s)
    result.attrs = {
        "long_name": "mosquito habitat suitability",
        "units": "1",
        "valid_range": [0.0, 1.0],
    }
    return result
