"""Element-wise multiplication of two spatially aligned datacubes."""

from __future__ import annotations

import numpy as np
import xarray as xr

from open_climate_service.process import process


@process(
    summary="Multiply two spatially aligned datacubes element-wise",
    description=(
        "Multiplies two DataArrays with the same spatial grid element by element. "
        "Use in a process graph to combine pairs of rasters, e.g. "
        "suitability × exposure or population × exposure. "
        "NaN in either input propagates to the output."
    ),
)
def multiply_cubes(x: xr.DataArray, y: xr.DataArray) -> xr.DataArray:
    """Element-wise product of two spatially aligned DataArrays.

    Parameters
    ----------
    x, y:
        DataArrays on the same spatial grid. If they differ only in a
        size-1 time dimension, x is broadcast to match y's time axis.

    Returns
    -------
    xr.DataArray
        Float32 product, same grid as y.
    """
    # Drop size-1 time dim from static inputs (e.g. suitability after reduce_dimension)
    def _squeeze_t(da: xr.DataArray) -> xr.DataArray:
        for dim in list(da.dims):
            if dim not in ("y", "x") and da.sizes[dim] == 1:
                da = da.isel({dim: 0}, drop=True)
        return da

    x = _squeeze_t(x)
    y = _squeeze_t(y)

    result = (x.values * y.values).astype("float32")
    out = y.copy(data=result)
    out.attrs = {}
    return out
