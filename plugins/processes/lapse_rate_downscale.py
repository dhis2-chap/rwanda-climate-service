"""Lapse-rate elevation correction for gridded temperature data."""

from __future__ import annotations

import xarray as xr

from open_climate_service.process import process

# Standard environmental lapse rate: 6.5 K per 1000 m
_LAPSE_RATE_K_PER_M = 6.5e-3


@process(
    summary="Correct temperature for elevation using the environmental lapse rate",
    description=(
        "Bilinearly interpolates coarse temperature to the elevation grid, then "
        "applies the standard environmental lapse rate (6.5 K km⁻¹) to correct "
        "for the difference between the pixel's actual elevation and the coarse "
        "grid's reference elevation.  Pass a fine-resolution DEM to downscale "
        "temperature; pass the same-resolution DEM for a plain elevation correction.\n\n"
        "Formula: T_out = T_interp − lapse_rate × (elev − elev_coarse)\n"
        "where elev_coarse is the DEM resampled to the temperature grid."
    ),
)
def lapse_rate_downscale(
    temperature: xr.DataArray,
    elevation: xr.DataArray,
    lapse_rate: float = _LAPSE_RATE_K_PER_M,
) -> xr.DataArray:
    """Apply lapse-rate elevation correction to temperature.

    Parameters
    ----------
    temperature:
        Air temperature in °C, at any grid resolution (typically CHELSA ~1 km).
    elevation:
        Terrain elevation in metres.  The output grid matches the elevation grid.
        Use a coarser DEM for a plain elevation correction or a finer DEM to
        downscale temperature to a higher resolution.
    lapse_rate:
        Environmental lapse rate in K m⁻¹ (default 0.0065, i.e. 6.5 K km⁻¹).

    Returns
    -------
    xr.DataArray
        Temperature in °C on the elevation grid, corrected for actual elevation.
    """
    # Squeeze time-dim from static elevation so interp_like sees only (y, x)
    elev_2d = elevation
    for dim in list(elev_2d.dims):
        if dim not in ("y", "x") and elev_2d.sizes[dim] == 1:
            elev_2d = elev_2d.isel({dim: 0}, drop=True)

    # Reference elevation: DEM resampled to the coarse temperature grid
    elev_coarse = elev_2d.interp_like(
        temperature.isel(t=0, drop=True) if "t" in temperature.dims else temperature,
        method="linear",
    )

    # Interpolate temperature to the elevation grid
    temp_interp = temperature.interp_like(elev_2d, method="linear")

    # Lapse-rate correction: higher than coarse reference → cooler
    elev_fine_broadcast = elev_2d
    if "t" in temp_interp.dims:
        elev_fine_broadcast = elev_2d.expand_dims(t=temp_interp.t)
        elev_coarse = elev_coarse.expand_dims(t=temp_interp.t)

    corrected = (
        temp_interp - lapse_rate * (elev_fine_broadcast - elev_coarse)
    ).astype("float32")

    corrected.attrs = dict(temperature.attrs)
    corrected.attrs["long_name"] = corrected.attrs.get("long_name", "temperature") + " (lapse-rate corrected)"
    corrected.attrs["lapse_rate_K_per_m"] = lapse_rate
    return corrected
